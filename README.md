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
| no_fault (baseline) | 28 ms | 20 ms | 29% |

OSD flap rate: baseline triggers ≥1 flap/run on stochastic impairment scenarios; CephKeel reduces this to 0 on all non-link-down scenarios.

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

Hysteresis: requires 2 consecutive bad readings to enter degraded mode,
3 consecutive good readings to exit. Prevents oscillation near thresholds.

## Repository Layout

```
CephKeel26/
├── cephkeel_controller.py   # Controller (~470 lines, stdlib only)
├── scripts/
│   ├── run_experiment.sh    # Single fault-injection run (tc netem / ip link)
│   ├── run_matrix.sh        # Full baseline × adaptive matrix runner
│   ├── collect_metrics.sh   # Continuous Ceph status collector
│   └── balanced_stats.py    # Bootstrap CI computation
├── sim/
│   ├── sim_engine.py        # Large-scale simulator (100 DC, no hardware needed)
│   ├── sim_report.py        # Print summary from results JSON
│   └── results_100dc_parallel.json  # Pre-computed results from the paper
├── workload/
│   └── fio_job.fio          # fio workload (128 KB, 70/30 R/W, 4 jobs, 300 s)
├── systemd/
│   └── cephkeel.service     # Systemd unit
├── paper/
│   ├── main.tex             # LaTeX source (IEEE IEEEtran conference)
│   ├── References.bib       # BibTeX database
│   └── fig/
│       └── fig_architecture.pdf  # Pre-compiled architecture figure
└── summary.csv              # Aggregated experiment statistics
```

## Quick Start

**Requirements:** Linux, Python 3.8+, MicroCeph or full Ceph (Squid/Reef), `fio`, `iproute2`

```bash
# 1. Deploy the controller
sudo cp cephkeel_controller.py /usr/local/bin/cephkeel_controller.py
sudo cp systemd/cephkeel.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cephkeel.service

# 2. Set probe targets (IPs of your OSD nodes)
export CEPHKEEL_PING_TARGETS="10.0.0.1,10.0.0.2,10.0.0.3"

# 3. Run a single experiment
MODE=adaptive INTERFACE=eth0 ./scripts/run_experiment.sh loss_1pct 300 workload/fio_job.fio

# 4. Run the full matrix (baseline + adaptive, 5 reps each)
MODES=baseline,adaptive INTERFACE=eth0 ./scripts/run_matrix.sh 5 300 workload/fio_job.fio \
  no_fault bw_200m loss_1pct jitter_50 osd_restart link_down
```

## Reproduce Without Hardware (Simulation)

The simulator runs the unmodified controller against mocked ping/ceph binaries —
no Ceph cluster needed.

```bash
# Run 10 DCs × 6 scenarios (~2 min)
python3 sim/sim_engine.py --dcs 10 --osds 8 --scenario mixed --output results.json

# Print summary
python3 sim/sim_report.py results.json

# Reproduce the paper's 100-DC run (pre-computed results also in repo)
python3 sim/sim_engine.py --dcs 100 --osds 8 --duration 600 --scenario mixed \
  --workers 8 --output results_100dc.json
```

## Configuration

All settings via environment variables — no edits to the script needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `CEPHKEEL_PING_TARGETS` | `192.0.2.1` | Comma-separated probe IPs |
| `CEPHKEEL_HYSTERESIS_BAD` | `2` | Consecutive bad readings → degraded |
| `CEPHKEEL_HYSTERESIS_GOOD` | `3` | Consecutive good readings → healthy |
| `CEPHKEEL_CFG_ENTITY` | `osd` | Ceph config entity (`osd` or `global`) |
| `CEPHKEEL_BASELINE_PATH` | `/var/lib/cephkeel/baseline.json` | Baseline save path |
| `INTERFACE` | `eth0` | NIC for tc fault injection |
| `OSD_ID` | `0` | OSD index for `osd_restart` scenario |

## Fault-Injection Scenarios

| Scenario | Impairment | Tool |
|----------|-----------|------|
| `no_fault` | None | — |
| `bw_200m` | 200 Mbps cap | `tc tbf` |
| `loss_1pct` | 1% random packet loss | `tc netem` |
| `jitter_50` | 20 ± 50 ms delay (normal) | `tc netem` |
| `osd_restart` | Restart one OSD process | `systemctl` |
| `link_down` | Interface down for full run | `ip link` |

## Testbeds Used in the Paper

| Testbed | Nodes | OS | Ceph |
|---------|-------|----|------|
| On-premises (Proxmox) | 3× heterogeneous x86 (1 GbE) | Debian/PVE 8 | MicroCeph Squid 19.2.3 |
| Oracle Cloud (OCI) | 3× VM.Standard.E2.1 (8 GB) | Ubuntu 22.04 | MicroCeph Squid 19.2.3 |

## Compile the Paper

```bash
cd paper
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

## License

MIT
