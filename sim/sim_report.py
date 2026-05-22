#!/usr/bin/env python3
"""
Analyze sim_results.json — prints per-DC breakdown and aggregated stats.
Usage: python3 sim_report.py results.json [--csv]
"""
import json, sys, statistics, argparse

ap = argparse.ArgumentParser()
ap.add_argument("file", nargs="?", default="sim_results.json")
ap.add_argument("--csv", action="store_true")
args = ap.parse_args()

with open(args.file) as f:
    data = json.load(f)

print(f"\nCephKeel Simulation Report")
print(f"  Scenario : {data['scenario']}")
print(f"  DCs      : {data['n_dcs']}  |  OSDs/DC: {data['n_osds_per_dc']}  |  Total nodes: {data['total_nodes']:,}")
print(f"  Duration : {data['duration_s']}s simulated in {data['elapsed_s']}s real ({data['sim_speedup']}x speedup)")
print(f"  Steps    : {data['scenario_steps']}")

dc_results = data.get("dc_results", [])
switches = [r["mode_switches"] for r in dc_results]
events   = [r["events"] for r in dc_results]

if switches:
    print(f"\nMode switch distribution across {len(dc_results)} DCs:")
    print(f"  Min    : {min(switches)}")
    print(f"  Max    : {max(switches)}")
    print(f"  Mean   : {statistics.mean(switches):.2f}")
    print(f"  Median : {statistics.median(switches):.2f}")
    if len(switches) > 1:
        print(f"  StdDev : {statistics.stdev(switches):.2f}")

print(f"\nTotal ceph config events : {data['total_ceph_events']:,}")
print(f"Total mode switches      : {data['total_mode_switches']:,}")

if args.csv:
    print("\ndc_id,mode_switches,events")
    for r in sorted(dc_results, key=lambda x: x["dc_id"]):
        print(f"{r['dc_id']},{r['mode_switches']},{r['events']}")
