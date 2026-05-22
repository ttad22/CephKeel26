# CephKeel — Adaptive Failure-Detection Controller for Ceph

> "Enhancing Ceph Stability on Constrained Networks via Adaptive Failure Detection"

CephKeel is a lightweight external controller that monitors network health and
dynamically adjusts Ceph's OSD heartbeat timers and recovery throttles. It
prevents false OSD-down events on constrained or noisy networks (1 GbE, edge,
cloud) without any changes to the Ceph source tree.

## Key Results

| Scenario | Baseline p99 (OCI) | CephKeel p99 (OCI) | Improvement |
|----------|--------------------|--------------------|-------------|
| bw_200m (200 Mbps cap) | 182 ms | 4.2 ms | **98%** |
| loss_1pct (1% packet loss) | 367 ms | 21 ms | **94%** |
| osd_restart | 217 ms | 20 ms | **91%** |
| jitter_50 (20±50 ms) | 1053 ms | 882 ms | 16% |
| no_fault (ambient OCI noise) | 28 ms | 20 ms | 29% |

OSD flap rate: baseline triggers 1 flap/run on all OCI scenarios (including
`no_fault`); CephKeel reduces this to 0 on all non-link-down scenarios.

## How It Works

```
┌─────────────────┐
│   CephKeel      │  every 5 s:
│   Controller    │──── ping probe target(s) ──→ measure RTT + loss
│                 │
│  if RTT > 50ms  │──── ceph config set osd osd_heartbeat_grace 40
│  or loss > 1%   │──── ceph config set osd osd_heartbeat_interval 10
│                 │──── throttle backfills/recovery
│  else           │──── restore baseline values
└─────────────────┘
```

**v2 improvements** (this release):
- **Multi-probe**: ping multiple targets, majority-vote prevents false positives
- **Hysteresis**: require N consecutive bad/good readings before flipping (configurable)
- **Dead-man's switch**: Ceph command failures are logged but never crash the controller

## Repository Layout

```
CephKeel/
├── cephkeel_controller.py   # Adaptive controller (~470 lines, no dependencies)
├── paper/
│   └── cephkeel_paper.tex   # IEEE-format research paper (LaTeX)
├── plots/
│   ├── flap_count.png       # OSD flap reduction chart
│   ├── client_p99_ms.png    # p99 latency comparison
│   ├── client_p999_ms.png   # p99.9 latency comparison
│   └── peering_time_s.png   # Peering time improvement
├── summary.csv              # Aggregated experiment statistics
├── notebooks/
│   └── process_results.ipynb  # Jupyter notebook for result processing
├── scripts/
│   ├── run_experiment.sh    # Fault-injection harness (tc netem / ip link)
│   ├── run_matrix.sh        # Batch experiment runner
│   └── collect_metrics.sh   # Continuous metric collector
├── systemd/
│   └── cephkeel.service     # Systemd unit file
└── workload/
    └── fio_job.fio          # Standard fio workload (128K 70/30 R/W, 4 jobs)
```

## Quick Start

```bash
# 1. Install dependencies
sudo apt install -y python3 iproute2 sysstat fio

# 2. Deploy controller
sudo cp cephkeel_controller.py /usr/local/bin/cephkeel_controller.py
sudo chmod +x /usr/local/bin/cephkeel_controller.py
sudo cp systemd/cephkeel.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cephkeel.service

# 3. Configure probe targets (optional — defaults to <your-osd-node-ip>)
export CEPHKEEL_PING_TARGETS="10.x.x.osd1,10.x.x.osd2"

# 4. Run a single experiment (adaptive mode)
MODE=adaptive INTERFACE=ens3 ./scripts/run_experiment.sh loss_1pct 300 workload/fio_job.fio

# 5. Run the full matrix (baseline + adaptive, 3 reps each)
MODES=baseline,adaptive INTERFACE=ens3 ./scripts/run_matrix.sh 3 300 workload/fio_job.fio \
  no_fault bw_200m loss_1pct jitter_50 osd_restart link_down
```

## Configuration Reference

All settings are via environment variables — no script edits needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `CEPHKEEL_PING_TARGETS` | `<your-osd-node-ip>` | Comma-separated probe IPs |
| `CEPHKEEL_PING_TARGET` | `<your-osd-node-ip>` | Single probe target (legacy) |
| `CEPHKEEL_HYSTERESIS_BAD` | `2` | Consecutive bad readings before degraded mode |
| `CEPHKEEL_HYSTERESIS_GOOD` | `3` | Consecutive good readings before healthy mode |
| `CEPHKEEL_CFG_ENTITY` | `osd` | Ceph config entity (`osd` or `global`) |
| `CEPHKEEL_BASELINE_PATH` | `/var/lib/cephkeel/baseline.json` | Baseline persistence path |
| `CEPHKEEL_REFRESH_BASELINE` | `0` | Set to `1` to force baseline recapture |
| `INTERFACE` | `vmbr0.30` | NIC for tc fault injection |
| `OSD_ID` | `0` | OSD for `osd_restart` scenario |
| `STATUS_INTERVAL` | `5` | Ceph status polling interval (s) |
| `MODE` | *(empty)* | Run label (`baseline` or `adaptive`) |

## Evaluated Fault-Injection Scenarios

| Scenario | Impairment | Severity |
|----------|-----------|----------|
| `no_fault` | None | Steady-state baseline |
| `bw_200m` | 200 Mbps cap (`tc tbf`) | Low |
| `loss_1pct` | 1% random packet loss (`tc netem`) | Medium |
| `jitter_50` | 20 ± 50 ms delay, normal dist | Medium |
| `osd_restart` | Restart one OSD process | High |
| `link_down` | Bring interface down (`ip link`) | Extreme |

## Testbeds

| Testbed | Hardware | OS | Ceph |
|---------|----------|----|------|
| Proxmox (on-prem) | 3× Xeon E5-2680v4, 128–161 GB RAM | Debian/PVE | MicroCeph Squid 19.2.3 |
| OCI (cloud) | 2× E2.1.Micro (EPYC 7551, 1 GB RAM) | Ubuntu 22.04 | MicroCeph Squid 19.2.3 |

## Paper

The full IEEE-format research paper is in `paper/cephkeel_paper.tex`.
Compile with:
```bash
pdflatex paper/cephkeel_paper.tex && bibtex cephkeel_paper && pdflatex paper/cephkeel_paper.tex
```

## License

MIT — see `LICENSE`.

## References

See `REFERENCES.md` for all cited works.
