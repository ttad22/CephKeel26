#!/usr/bin/env python3
"""
CephKeel Large-Scale Simulator
================================
Simulates N datacenters × M OSD nodes with real CephKeel controllers.
Each DC runs an actual cephkeel_controller.py against mocked ping/ceph binaries.

Usage:
    python3 sim_engine.py --dcs 100 --osds 16 --duration 120 --scenario mixed
    python3 sim_engine.py --dcs 10  --osds 8  --scenario loss_sweep --output results.json
"""

import argparse, json, logging, math, multiprocessing, os, random
import shutil, signal, subprocess, sys, tempfile, time, statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO DEFINITIONS
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScenarioStep:
    at_second:  float
    dc_id:      Optional[int]   # None = all DCs
    node_id:    Optional[str]   # None = all nodes in DC
    rtt_ms:     Optional[float] = None
    loss_pct:   Optional[float] = None
    jitter_ms:  Optional[float] = None
    link_down:  Optional[bool]  = None


def scenario_no_fault(n, m, d):    return []

def scenario_loss_sweep(n, m, d):
    steps = []
    for dc in range(n):
        t = (d / n) * dc
        loss = 0.5 + (dc / max(n-1,1)) * 4.5
        steps += [ScenarioStep(t, dc, None, loss_pct=loss),
                  ScenarioStep(t + d/n*0.7, dc, None, loss_pct=0.0)]
    return steps

def scenario_latency_spike(n, m, d):
    steps = []
    for _ in range(n * 2):
        dc = random.randint(0, n-1)
        t  = random.uniform(5, d-15)
        steps += [ScenarioStep(t,    dc, None, rtt_ms=random.uniform(60,300)),
                  ScenarioStep(t+10, dc, None, rtt_ms=5.0)]
    return sorted(steps, key=lambda s: s.at_second)

def scenario_cascading(n, m, d):
    steps, wave = [], max(1, n//5)
    for w in range(5):
        for i in range(wave):
            dc = w*wave + i
            if dc >= n: break
            t = (d/5)*w + i*2.0
            steps += [ScenarioStep(t,       dc, None, loss_pct=2.0, rtt_ms=120.0),
                      ScenarioStep(t+d/10,  dc, None, loss_pct=0.0, rtt_ms=5.0)]
    return sorted(steps, key=lambda s: s.at_second)

def scenario_link_down(n, m, d):
    steps = []
    for dc in range(n):
        t = random.uniform(5, d*0.4)
        node = f"10.{dc//256}.{dc%256}.10"
        steps += [ScenarioStep(t,    dc, node, link_down=True),
                  ScenarioStep(t+15, dc, node, link_down=False)]
    return sorted(steps, key=lambda s: s.at_second)

def scenario_mixed(n, m, d):
    return sorted(scenario_loss_sweep(n,m,d) + scenario_latency_spike(n,m,d) +
                  scenario_link_down(n,m,d), key=lambda s: s.at_second)

SCENARIOS = {
    "no_fault": scenario_no_fault, "loss_sweep": scenario_loss_sweep,
    "latency_spike": scenario_latency_spike, "cascading": scenario_cascading,
    "link_down": scenario_link_down, "mixed": scenario_mixed,
}

# ──────────────────────────────────────────────────────────────────────────────
# MOCK BINARY WRITERS
# ──────────────────────────────────────────────────────────────────────────────

def write_mock_ping(bin_dir: Path, state_file: Path):
    (bin_dir / "ping").write_text(f"""#!/usr/bin/env python3
import sys,json,random,time
state_file="{state_file}"; target=sys.argv[-1]
try:
    node=json.load(open(state_file)).get(target,{{}})
except: node={{}}
if node.get("link_down"):
    time.sleep(2)
    print(f"--- {{target}} ping statistics ---")
    print("5 packets transmitted, 0 received, 100.0% packet loss"); sys.exit(1)
rtt=max(0.1, node.get("rtt_ms",5.0)+random.gauss(0,node.get("jitter_ms",0)+0.5))
loss=min(100,max(0,node.get("loss_pct",0)+random.gauss(0,0.1)))
recv=5-round(loss/100*5)
print(f"--- {{target}} ping statistics ---")
if recv==0: print(f"5 packets transmitted, 0 received, 100.0% packet loss"); sys.exit(1)
dev=rtt*0.05
print(f"5 packets transmitted, {{recv}} received, {{loss:.1f}}% packet loss")
print(f"round-trip min/avg/max/stddev = {{rtt-dev:.3f}}/{{rtt:.3f}}/{{rtt+dev:.3f}}/{{dev:.3f}} ms")
""")
    (bin_dir / "ping").chmod(0o755)


def write_mock_ceph(bin_dir: Path, config_file: Path, metrics_file: Path, dc_id: int):
    (bin_dir / "ceph").write_text(f"""#!/usr/bin/env python3
import sys,json,time
cfg_f="{config_file}"; met_f="{metrics_file}"; dc={dc_id}
KEYS=["osd_heartbeat_grace","osd_heartbeat_interval","osd_max_backfills","osd_recovery_max_active"]
def ld():
    try: return json.load(open(cfg_f))
    except: return {{"osd_heartbeat_grace":"20","osd_heartbeat_interval":"6","osd_max_backfills":"1","osd_recovery_max_active":"3"}}
def sv(c): json.dump(c,open(cfg_f,"w"))
def log(a,k="",v=""): open(met_f,"a").write(json.dumps({{"ts":time.time(),"dc":dc,"action":a,"key":k,"value":v}})+"\\n")
cmd=sys.argv[1:]
if not cmd: sys.exit(0)
if cmd[0]=="status": print(json.dumps({{"health":{{"status":"HEALTH_OK"}}}})); sys.exit(0)
if cmd[0]=="config":
    s=cmd[1] if len(cmd)>1 else ""
    if s=="ls": print("\\n".join(KEYS)); sys.exit(0)
    if s=="get":
        k=cmd[3] if len(cmd)>3 else cmd[2] if len(cmd)>2 else ""
        print(ld().get(k,"")); sys.exit(0)
    if s=="set":
        k=cmd[3] if len(cmd)>3 else ""; v=cmd[4] if len(cmd)>4 else ""
        c=ld(); c[k]=v; sv(c); log("set",k,v); sys.exit(0)
    if s=="rm":
        k=cmd[3] if len(cmd)>3 else ""; c=ld(); c.pop(k,None); sv(c); log("rm",k); sys.exit(0)
sys.exit(0)
""")
    (bin_dir / "ceph").chmod(0o755)

# ──────────────────────────────────────────────────────────────────────────────
# DC WORKER — runs one real CephKeel controller
# ──────────────────────────────────────────────────────────────────────────────

def run_dc(dc_id, work_dir, controller_path, n_osds, duration, interval):
    """Run one DC's controller. Write result to dc{N}/result.json when done."""
    dc_dir      = Path(work_dir) / f"dc{dc_id}"
    bin_dir     = dc_dir / "bin"
    state_file  = dc_dir / "state.json"
    config_file = dc_dir / "config.json"
    metrics_file= dc_dir / "metrics.jsonl"

    dc_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    metrics_file.write_text("")
    config_file.write_text(json.dumps({
        "osd_heartbeat_grace":"20","osd_heartbeat_interval":"6",
        "osd_max_backfills":"1","osd_recovery_max_active":"3"}))

    # Build node IPs
    nodes = {f"10.{dc_id//256}.{dc_id%256}.{i+10}":
             {"rtt_ms":5.0+random.gauss(0,0.3),"loss_pct":0.0,"jitter_ms":1.0,"link_down":False}
             for i in range(n_osds)}
    state_file.write_text(json.dumps(nodes))

    write_mock_ping(bin_dir, state_file)
    write_mock_ceph(bin_dir, config_file, metrics_file, dc_id)

    probe_targets = ",".join(list(nodes.keys())[:min(3,n_osds)])
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + ":" + env.get("PATH","")
    env["CEPHKEEL_PING_TARGETS"]    = probe_targets
    env["CEPHKEEL_HYSTERESIS_BAD"]  = "2"
    env["CEPHKEEL_HYSTERESIS_GOOD"] = "3"
    env["CEPHKEEL_BASELINE_PATH"]   = str(dc_dir / "baseline.json")

    with open(dc_dir / "controller.log", "w") as log_fh:
        proc = subprocess.Popen(
            ["python3", controller_path, "--interval", str(interval)],
            env=env, stdout=log_fh, stderr=log_fh)

    # Wait for duration then kill
    time.sleep(duration)
    proc.terminate()
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: proc.kill()

    # Parse metrics and write result file
    events = []
    for line in metrics_file.read_text().splitlines():
        try: events.append(json.loads(line))
        except: pass

    mode_sw = sum(1 for e in events if e.get("action")=="set" and e.get("key")=="osd_heartbeat_grace")
    config_sets = [e for e in events if e.get("action")=="set"]

    result = {"dc_id":dc_id,"n_osds":n_osds,"events":len(events),
              "mode_switches":mode_sw,"config_sets":config_sets}
    (dc_dir / "result.json").write_text(json.dumps(result))


def apply_step(work_dir, states, step):
    dcs = [step.dc_id] if step.dc_id is not None else list(states.keys())
    for dc_id in dcs:
        dc_state = states[dc_id]
        targets  = [step.node_id] if step.node_id else list(dc_state.keys())
        for nip in targets:
            if nip not in dc_state: continue
            n = dc_state[nip]
            if step.rtt_ms    is not None: n["rtt_ms"]    = step.rtt_ms
            if step.loss_pct  is not None: n["loss_pct"]  = step.loss_pct
            if step.jitter_ms is not None: n["jitter_ms"] = step.jitter_ms
            if step.link_down is not None: n["link_down"] = step.link_down
        sf = Path(work_dir) / f"dc{dc_id}" / "state.json"
        if sf.parent.exists(): sf.write_text(json.dumps(dc_state))

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="CephKeel large-scale simulator")
    ap.add_argument("--dcs",        type=int,   default=10)
    ap.add_argument("--osds",       type=int,   default=8)
    ap.add_argument("--duration",   type=int,   default=60)
    ap.add_argument("--interval",   type=int,   default=5)
    ap.add_argument("--scenario",   default="mixed")
    ap.add_argument("--output",     default="sim_results.json")
    ap.add_argument("--workers",    type=int,   default=0)
    ap.add_argument("--controller", default=None)
    ap.add_argument("--work-dir",   default=None)
    ap.add_argument("--keep-work",  action="store_true")
    args = ap.parse_args()

    ctrl = args.controller or str(Path(__file__).parent.parent / "cephkeel_controller.py")
    if not Path(ctrl).exists():
        print(f"ERROR: controller not found: {ctrl}"); return 1

    n_workers = args.workers or min(args.dcs, multiprocessing.cpu_count())
    work_dir  = args.work_dir or tempfile.mkdtemp(prefix="cksim_")

    print(f"CephKeel Simulator")
    print(f"  DCs:{args.dcs}  OSDs/DC:{args.osds}  Total:{args.dcs*args.osds:,}  Duration:{args.duration}s  Scenario:{args.scenario}")
    print(f"  Workers:{n_workers}  WorkDir:{work_dir}")

    # Build node states
    all_states = {}
    for dc_id in range(args.dcs):
        dc_nodes = {f"10.{dc_id//256}.{dc_id%256}.{i+10}":
                    {"rtt_ms":5.0+random.gauss(0,0.3),"loss_pct":0.0,"jitter_ms":1.0,"link_down":False}
                    for i in range(args.osds)}
        all_states[dc_id] = dc_nodes
        dc_dir = Path(work_dir) / f"dc{dc_id}"
        dc_dir.mkdir(parents=True, exist_ok=True)
        (dc_dir / "state.json").write_text(json.dumps(dc_nodes))

    steps = SCENARIOS.get(args.scenario, scenario_mixed)(args.dcs, args.osds, args.duration)
    print(f"  Scenario steps: {len(steps)}")

    # Launch workers in batches
    t_start  = time.time()
    procs    = []
    launched = 0
    pool_args = [(dc_id, work_dir, ctrl, args.osds, args.duration, args.interval)
                 for dc_id in range(args.dcs)]

    print(f"\nLaunching {args.dcs} controller processes...")
    for i in range(0, args.dcs, n_workers):
        batch = pool_args[i:i+n_workers]
        for a in batch:
            p = multiprocessing.Process(target=run_dc, args=a)
            p.start(); procs.append(p)
        launched += len(batch)
        print(f"  {launched}/{args.dcs} launched", end="\r", flush=True)
        if launched < args.dcs: time.sleep(0.3)

    print(f"\n  All {args.dcs} controllers running. Injecting scenario...")

    # Inject faults
    t0 = time.time()
    pending = sorted(steps, key=lambda s: s.at_second)
    idx = 0
    while time.time() - t0 < args.duration:
        elapsed = time.time() - t0
        while idx < len(pending) and pending[idx].at_second <= elapsed:
            apply_step(work_dir, all_states, pending[idx]); idx += 1
        time.sleep(0.2)

    # Wait for all workers (they self-terminate after duration)
    print(f"  Waiting for workers to finish...")
    for p in procs:
        p.join(timeout=args.duration + 15)
        if p.is_alive(): p.kill()

    elapsed_total = time.time() - t_start

    # Collect results from files
    results = []
    for dc_id in range(args.dcs):
        rf = Path(work_dir) / f"dc{dc_id}" / "result.json"
        if rf.exists():
            try: results.append(json.loads(rf.read_text()))
            except: pass

    # Stats
    switches = [r["mode_switches"] for r in results]
    events   = [r["events"]        for r in results]
    total_sw = sum(switches)
    total_ev = sum(events)
    mean_sw  = statistics.mean(switches) if switches else 0
    stdev_sw = statistics.stdev(switches) if len(switches) > 1 else 0

    summary = {
        "scenario": args.scenario, "n_dcs": args.dcs,
        "n_osds_per_dc": args.osds, "total_nodes": args.dcs*args.osds,
        "duration_s": args.duration, "elapsed_s": round(elapsed_total,2),
        "sim_speedup": round(args.duration/elapsed_total,2),
        "dcs_reported": len(results),
        "total_ceph_events": total_ev, "total_mode_switches": total_sw,
        "mean_switches_per_dc": round(mean_sw,2),
        "stdev_switches": round(stdev_sw,2),
        "scenario_steps": len(steps),
        "dc_results": results,
    }
    Path(args.output).write_text(json.dumps(summary, indent=2))

    if not args.keep_work:
        shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"Done in {elapsed_total:.1f}s  (speedup {summary['sim_speedup']}x)")
    print(f"  Nodes simulated   : {args.dcs*args.osds:,}")
    print(f"  DCs reported      : {len(results)}/{args.dcs}")
    print(f"  Ceph config events: {total_ev:,}")
    print(f"  Mode switches     : {total_sw:,}  (mean/DC: {mean_sw:.2f} ± {stdev_sw:.2f})")
    print(f"  Results → {args.output}")
    print(f"{'='*60}")
    return 0

if __name__ == "__main__": exit(main())
