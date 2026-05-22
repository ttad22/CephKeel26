#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def bootstrap_ci(values, n_resamples=2000, alpha=0.05, rng=None):
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return np.nan, np.nan, np.nan
    mean = float(arr.mean())
    if arr.size == 1:
        return mean, 0.0, 0.0
    rng = rng or np.random.default_rng(42)
    samples = rng.choice(arr, size=(n_resamples, arr.size), replace=True)
    means = samples.mean(axis=1)
    low, high = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return mean, mean - low, high - mean


def main():
    parser = argparse.ArgumentParser(description="Generate balanced-only stats CSV (equal N per mode).")
    parser.add_argument("--input", default="summary.csv", help="Path to summary.csv")
    parser.add_argument("--output", default="plots/summary_stats_balanced.csv", help="Output CSV path")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df = df[df["mode"].isin(["baseline", "adaptive"])]

    metrics = [
        "flap_count",
        "peering_time_s",
        "health_to_ok_s",
        "client_p99_ms",
        "client_p999_ms",
    ]

    rows = []
    rng = np.random.default_rng(42)
    for scenario in sorted(df["scenario"].unique()):
        base = df[(df["scenario"] == scenario) & (df["mode"] == "baseline")].copy()
        adap = df[(df["scenario"] == scenario) & (df["mode"] == "adaptive")].copy()
        if base.empty or adap.empty:
            continue
        n = min(len(base), len(adap))

        # Deterministic selection: sort by run_id and take first n
        base = base.sort_values("run_id").head(n)
        adap = adap.sort_values("run_id").head(n)

        for metric in metrics:
            for mode, subset in [("baseline", base), ("adaptive", adap)]:
                vals = subset[metric].dropna().values
                if vals.size == 0:
                    continue
                mean, lo, hi = bootstrap_ci(vals, rng=rng)
                rows.append({
                    "scenario": scenario,
                    "mode": mode,
                    "metric": metric,
                    "mean": round(mean, 6),
                    "ci_low": round(mean - lo, 6),
                    "ci_high": round(mean + hi, 6),
                    "n": int(vals.size),
                })

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)


if __name__ == "__main__":
    main()
