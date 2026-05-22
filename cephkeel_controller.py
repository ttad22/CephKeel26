#!/usr/bin/env python3
"""
CephKeel - adaptive network-aware failure-detection controller.

The controller runs on any host that can reach the Ceph monitors
(e.g. the MON/MGR node).  It periodically measures RTT and packet loss
to one or more peer OSDs (or any reachable Ceph nodes) and updates four
Ceph runtime knobs:

    * osd_heartbeat_grace          - how long a monitor tolerates missed heartbeats
    * osd_heartbeat_interval       - interval between heartbeat messages
    * osd_max_backfills            - max concurrent back-fill streams
    * osd_recovery_max_active      - max concurrent recovery operations

When the network is degraded the controller relaxes the timers and
throttles recovery; when the network is healthy it restores the
baseline values captured at startup.

Robustness features:
    * Multi-probe  : pings multiple targets; majority vote prevents false
                     positives from a single unreachable host.
    * Hysteresis   : requires N consecutive bad (or good) readings before
                     flipping mode, smoothing transient spikes.
    * Dead-man's   : Ceph command failures are logged but never crash the
                     controller — the loop continues uninterrupted.

No changes to the Ceph source tree are required - everything is done
through the public `ceph config set` API, which is why the approach
works on every environment described in the paper [1].
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from typing import List, Tuple

# ----------------------------------------------------------------------
# USER-CONFIGURABLE THRESHOLDS - tune for your own network if needed
# ----------------------------------------------------------------------
LATENCY_THRESHOLD_MS = 50.0      # RTT above which we consider the link "bad"
LOSS_THRESHOLD_PCT   = 1.0       # % packet loss above which we consider the link "bad"

# Probe targets — comma-separated list of IPs.  Majority vote is used:
# if more than half the targets appear degraded, the network is considered bad.
# Default: TTQHOST02 on VLAN 30 for TTT on-premises; override per deployment.
_PING_TARGETS_ENV = os.environ.get("CEPHKEEL_PING_TARGETS", "")
PING_TARGETS: List[str] = (
    [t.strip() for t in _PING_TARGETS_ENV.split(",") if t.strip()]
    if _PING_TARGETS_ENV
    else [os.environ.get("CEPHKEEL_PING_TARGET", "192.0.2.1")]
)
PING_COUNT = 5

# Hysteresis — how many consecutive bad/good readings before flipping mode.
# Set to 1 to disable (immediate flip, original behaviour).
HYSTERESIS_BAD  = int(os.environ.get("CEPHKEEL_HYSTERESIS_BAD",  "2"))
HYSTERESIS_GOOD = int(os.environ.get("CEPHKEEL_HYSTERESIS_GOOD", "3"))

# Baseline persistence (restored when network is healthy)
BASELINE_PATH = os.environ.get(
    "CEPHKEEL_BASELINE_PATH",
    "/var/lib/cephkeel/baseline.json",
)
REFRESH_BASELINE = os.environ.get("CEPHKEEL_REFRESH_BASELINE", "0") == "1"

# Ceph config entity (osd works on Squid; override if needed)
CFG_ENTITY = os.environ.get("CEPHKEEL_CFG_ENTITY", "osd")

# Desired Ceph keys (filtered by supported keys at runtime)
MANAGED_KEYS: List[str] = []
DESIRED_KEYS = [
    "osd_heartbeat_grace",
    "osd_heartbeat_interval",
    "osd_max_backfills",
    "osd_recovery_max_active",
]

# Defaults used only for computing a degraded policy when baseline is missing
DEFAULT_HEARTBEAT_GRACE    = 20
DEFAULT_HEARTBEAT_INTERVAL = 6

# Degraded policy (relative to baseline)
BAD_GRACE_MULTIPLIER    = 1.5
BAD_GRACE_MIN           = 40
BAD_INTERVAL_MULTIPLIER = 1.5
BAD_INTERVAL_MIN        = 10
BAD_BACKFILLS           = 1
BAD_RECOVERY_MAX_ACTIVE = 1

# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------

def run_cmd(cmd: List[str]) -> str:
    """Run a command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def get_supported_keys() -> set:
    """Return supported config keys from `ceph config ls`."""
    try:
        out = run_cmd(["ceph", "config", "ls"])
        return {line.strip() for line in out.splitlines() if line.strip()}
    except RuntimeError as exc:
        logging.warning(f"Could not read config keys: {exc}")
        return set()


def _ping_one(target: str) -> Tuple[float, float]:
    """Ping a single target. Returns (avg_rtt_ms, loss_pct). Raises on failure."""
    out = run_cmd(["ping", "-c", str(PING_COUNT), "-q", target])
    loss_line = next(l for l in out.splitlines() if "packet loss" in l)
    rtt_line  = next(l for l in out.splitlines() if "rtt min/avg" in l)
    loss_pct = float(loss_line.split(",")[2].strip().split("%")[0])
    avg_rtt  = float(rtt_line.split("=")[1].strip().split("/")[1])
    return avg_rtt, loss_pct


def measure_network() -> Tuple[float, float]:
    """
    Probe all configured targets and return (worst_rtt_ms, worst_loss_pct)
    for the majority-vote degraded set.

    A target is considered degraded if its RTT or loss exceeds thresholds.
    The network is declared bad only when more than half the targets are
    degraded (majority vote), which prevents a single unreachable host
    from triggering an unnecessary policy change.

    Returns the mean RTT and loss across all reachable targets so that
    callers can log meaningful numbers.
    """
    results = []
    bad_count = 0
    for target in PING_TARGETS:
        try:
            rtt, loss = _ping_one(target)
            results.append((rtt, loss))
            if rtt > LATENCY_THRESHOLD_MS or loss > LOSS_THRESHOLD_PCT:
                bad_count += 1
                logging.debug(f"  {target}: RTT={rtt:.1f}ms loss={loss:.1f}% [BAD]")
            else:
                logging.debug(f"  {target}: RTT={rtt:.1f}ms loss={loss:.1f}% [OK]")
        except Exception as exc:
            # Unreachable target counts as bad
            bad_count += 1
            logging.warning(f"  {target}: probe failed ({exc}) [BAD]")

    if not results:
        # All probes failed — treat as degraded but return placeholder values
        return 9999.0, 100.0

    mean_rtt  = sum(r for r, _ in results) / len(results)
    mean_loss = sum(l for _, l in results) / len(results)
    return mean_rtt, mean_loss


def is_network_degraded() -> bool:
    """
    Return True if a majority of probe targets are degraded.
    Isolates the majority-vote logic from the raw measurement values.
    """
    bad_count = 0
    total = len(PING_TARGETS)
    for target in PING_TARGETS:
        try:
            rtt, loss = _ping_one(target)
            if rtt > LATENCY_THRESHOLD_MS or loss > LOSS_THRESHOLD_PCT:
                bad_count += 1
        except Exception:
            bad_count += 1
    return bad_count > total / 2


def get_current_ceph_cfg(key: str) -> str:
    """Read a Ceph configuration value via `ceph config get`."""
    try:
        out = run_cmd(["ceph", "config", "get", CFG_ENTITY, key])
        return out.strip()
    except RuntimeError:
        if CFG_ENTITY != "global":
            try:
                out = run_cmd(["ceph", "config", "get", "global", key])
                return out.strip()
            except RuntimeError:
                return ""
        return ""


def set_ceph_cfg(key: str, value: str):
    """Set a Ceph configuration value via `ceph config set`."""
    try:
        run_cmd(["ceph", "config", "set", CFG_ENTITY, key, value])
        logging.info(f"Set Ceph config {CFG_ENTITY} {key} = {value}")
    except RuntimeError:
        if CFG_ENTITY != "global":
            run_cmd(["ceph", "config", "set", "global", key, value])
            logging.info(f"Set Ceph config global {key} = {value}")


def rm_ceph_cfg(key: str):
    """Remove a Ceph configuration value via `ceph config rm`."""
    try:
        run_cmd(["ceph", "config", "rm", CFG_ENTITY, key])
        logging.info(f"Removed Ceph config {CFG_ENTITY} {key}")
    except RuntimeError:
        if CFG_ENTITY != "global":
            try:
                run_cmd(["ceph", "config", "rm", "global", key])
                logging.info(f"Removed Ceph config global {key}")
            except RuntimeError as exc:
                logging.warning(f"Could not remove {key}: {exc}")
        else:
            logging.warning(f"Could not remove {key}: config rm failed")


def load_baseline(path: str):
    """Load baseline config from disk."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception as exc:
        logging.warning(f"Baseline load failed: {exc}")
        return None


def save_baseline(path: str, data: dict):
    """Persist baseline config to disk (atomic write)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def capture_baseline() -> dict:
    """Capture current Ceph config for managed keys."""
    data = {}
    for key in MANAGED_KEYS:
        val = get_current_ceph_cfg(key)
        data[key] = val if val else None
    save_baseline(BASELINE_PATH, data)
    return data


def ensure_baseline_keys(baseline: dict) -> dict:
    """Fill missing keys in baseline and persist if updated."""
    updated = False
    for key in MANAGED_KEYS:
        if key not in baseline:
            val = get_current_ceph_cfg(key)
            baseline[key] = val if val else None
            updated = True
    if updated:
        save_baseline(BASELINE_PATH, baseline)
    return baseline


def parse_int(value: str, default: int) -> int:
    """Parse int with fallback."""
    try:
        return int(value)
    except Exception:
        return default


def compute_bad_settings(baseline: dict) -> dict:
    """Compute degraded settings based on baseline values."""
    grace_base = parse_int(
        baseline.get("osd_heartbeat_grace"), DEFAULT_HEARTBEAT_GRACE
    )
    interval_base = parse_int(
        baseline.get("osd_heartbeat_interval"), DEFAULT_HEARTBEAT_INTERVAL
    )
    grace = max(int(round(grace_base * BAD_GRACE_MULTIPLIER)), grace_base, BAD_GRACE_MIN)
    interval = max(
        int(round(interval_base * BAD_INTERVAL_MULTIPLIER)),
        interval_base,
        BAD_INTERVAL_MIN,
    )
    settings = {
        "osd_heartbeat_grace": str(grace),
        "osd_heartbeat_interval": str(interval),
        "osd_max_backfills": str(BAD_BACKFILLS),
        "osd_recovery_max_active": str(BAD_RECOVERY_MAX_ACTIVE),
    }
    return {k: v for k, v in settings.items() if k in MANAGED_KEYS}


def restore_baseline(baseline: dict):
    """Restore baseline config values (or remove overrides)."""
    for key in MANAGED_KEYS:
        val = baseline.get(key)
        if val is None or val == "":
            rm_ceph_cfg(key)
        else:
            set_ceph_cfg(key, str(val))


def apply_settings(settings: dict):
    """Apply a dict of Ceph config values."""
    for key, value in settings.items():
        set_ceph_cfg(key, str(value))


def apply_adaptive_policy(bad_network: bool, baseline: dict):
    """Apply Ceph knobs based on the network condition."""
    if bad_network:
        apply_settings(compute_bad_settings(baseline))
        logging.info("Network degraded — applied adaptive (relaxed) limits")
    else:
        restore_baseline(baseline)
        logging.info("Network healthy — restored baseline limits")


def main_loop(check_interval: int, baseline: dict):
    """
    Infinite monitoring loop with hysteresis and dead-man's switch.

    Hysteresis state machine:
        consecutive_bad  — incremented each cycle the network looks bad;
                           reset to 0 on a good reading.
        consecutive_good — incremented each cycle the network looks good;
                           reset to 0 on a bad reading.
    Mode only flips when the respective counter reaches its threshold
    (HYSTERESIS_BAD or HYSTERESIS_GOOD), avoiding rapid oscillation on
    transient spikes.

    Dead-man's switch:
        Ceph config set/get failures are caught and logged; the controller
        keeps running so it can recover once the cluster is reachable again.
    """
    current_mode_bad   = False   # last applied policy: True = degraded
    consecutive_bad    = 0
    consecutive_good   = 0

    targets_str = ", ".join(PING_TARGETS)
    logging.info(
        f"Monitoring {len(PING_TARGETS)} probe target(s): {targets_str} | "
        f"hysteresis bad={HYSTERESIS_BAD} good={HYSTERESIS_GOOD}"
    )

    while True:
        try:
            # ── 1. Probe the network ──────────────────────────────────────
            try:
                rtt, loss = measure_network()
                raw_bad   = is_network_degraded()
                logging.info(
                    f"Network probe: mean RTT={rtt:.1f}ms loss={loss:.1f}% "
                    f"({'BAD' if raw_bad else 'OK'}, "
                    f"bad_streak={consecutive_bad + (1 if raw_bad else 0)} "
                    f"good_streak={consecutive_good + (0 if raw_bad else 1)})"
                )
            except Exception as probe_exc:
                # Probe infrastructure failure — treat as bad network
                logging.error(f"Probe error: {probe_exc} — treating as degraded")
                raw_bad = True

            # ── 2. Update hysteresis counters ────────────────────────────
            if raw_bad:
                consecutive_bad  += 1
                consecutive_good  = 0
            else:
                consecutive_good += 1
                consecutive_bad   = 0

            # ── 3. Decide whether to flip mode ───────────────────────────
            want_bad = current_mode_bad   # default: stay in current mode
            if not current_mode_bad and consecutive_bad >= HYSTERESIS_BAD:
                want_bad = True
                logging.warning(
                    f"Switching to DEGRADED mode after {consecutive_bad} "
                    f"consecutive bad readings"
                )
            elif current_mode_bad and consecutive_good >= HYSTERESIS_GOOD:
                want_bad = False
                logging.info(
                    f"Switching to HEALTHY mode after {consecutive_good} "
                    f"consecutive good readings"
                )

            # ── 4. Apply policy (dead-man's switch: never crash) ─────────
            if want_bad != current_mode_bad:
                try:
                    apply_adaptive_policy(want_bad, baseline)
                    current_mode_bad = want_bad
                except Exception as ceph_exc:
                    # Ceph unreachable — log but keep running; will retry next cycle
                    logging.error(
                        f"Ceph config update failed (cluster unreachable?): {ceph_exc}. "
                        f"Will retry next cycle."
                    )

        except Exception as exc:
            logging.error(f"Unexpected error in control loop: {exc}")

        time.sleep(check_interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CephKeel adaptive controller"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="seconds between network checks (default: 5)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Dead-man's switch at startup: warn but do not exit if Ceph is down.
    # The controller may start before the cluster is fully up.
    try:
        _ = run_cmd(["ceph", "status"])
    except Exception as exc:
        logging.warning(
            f"Cannot contact Ceph cluster at startup: {exc}. "
            f"Controller will start anyway and retry each cycle."
        )

    supported = get_supported_keys()
    if supported:
        MANAGED_KEYS = [k for k in DESIRED_KEYS if k in supported]
        missing = [k for k in DESIRED_KEYS if k not in supported]
        if missing:
            logging.warning(f"Skipping unsupported keys: {', '.join(missing)}")
    else:
        MANAGED_KEYS = DESIRED_KEYS[:]

    baseline = load_baseline(BASELINE_PATH)
    if baseline is None or REFRESH_BASELINE:
        logging.info("Capturing baseline Ceph config")
        try:
            baseline = capture_baseline()
        except Exception as exc:
            logging.warning(f"Could not capture baseline: {exc}. Using empty baseline.")
            baseline = {}
    else:
        try:
            baseline = ensure_baseline_keys(baseline)
        except Exception as exc:
            logging.warning(f"Could not refresh baseline keys: {exc}.")

    logging.info(
        f"Starting CephKeel controller | probes={PING_TARGETS} | "
        f"thresholds: RTT>{LATENCY_THRESHOLD_MS}ms or loss>{LOSS_THRESHOLD_PCT}% | "
        f"hysteresis: bad={HYSTERESIS_BAD} good={HYSTERESIS_GOOD}"
    )
    main_loop(args.interval, baseline)
