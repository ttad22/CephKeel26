#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# Force non-interactive backend for headless runs
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


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


def plot_metric(df, metric, ylabel, out_path, title):
    modes = ["baseline", "adaptive"]
    data = df[["scenario", "mode", metric]].dropna()

    scenarios = []
    for s in sorted(data["scenario"].unique()):
        has_all = all(((data["scenario"] == s) & (data["mode"] == m)).any() for m in modes)
        if has_all:
            scenarios.append(s)

    if not scenarios:
        return False

    x = np.arange(len(scenarios))
    width = 0.35
    rng = np.random.default_rng(42)

    fig, ax = plt.subplots(figsize=(10, 4.8))

    for i, mode in enumerate(modes):
        means = []
        err_low = []
        err_high = []
        for s in scenarios:
            vals = data[(data["scenario"] == s) & (data["mode"] == mode)][metric].values
            mean, lo, hi = bootstrap_ci(vals, rng=rng)
            means.append(mean)
            err_low.append(lo)
            err_high.append(hi)

        offset = (-width / 2) if mode == "baseline" else (width / 2)
        ax.bar(
            x + offset,
            means,
            width,
            label=mode,
            yerr=[err_low, err_high],
            capsize=4,
        )

    ax.set_xticks(x)
    ax.set_xticklabels([s.replace("_", "\n") for s in scenarios])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return True


def main():
    parser = argparse.ArgumentParser(description="Plot CephKeel summary charts with 95% CI")
    parser.add_argument("--input", default="summary.csv", help="Path to summary.csv")
    parser.add_argument("--outdir", default="plots", help="Output directory for charts")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df = df[df["mode"].isin(["baseline", "adaptive"])]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    metrics = [
        ("flap_count", "OSD Flap Count", "OSD flaps", outdir / "flap_count.png"),
        ("peering_time_s", "Peering Time", "Seconds", outdir / "peering_time_s.png"),
        ("health_to_ok_s", "Time to HEALTH_OK", "Seconds", outdir / "health_to_ok_s.png"),
        ("client_p99_ms", "Client p99 Latency", "Milliseconds", outdir / "client_p99_ms.png"),
        ("client_p999_ms", "Client p99.9 Latency", "Milliseconds", outdir / "client_p999_ms.png"),
    ]

    made = []
    for metric, title, ylabel, path in metrics:
        ok = plot_metric(df, metric, ylabel, path, title)
        if ok:
            made.append(path)

    if not made:
        raise SystemExit("No charts generated (missing paired baseline/adaptive data).")

    stats_rows = []
    rng = np.random.default_rng(42)
    for metric, _, _, _ in metrics:
        data = df[["scenario", "mode", metric]].dropna()
        for (scenario, mode), sub in data.groupby(["scenario", "mode"]):
            mean, lo, hi = bootstrap_ci(sub[metric].values, rng=rng)
            stats_rows.append({
                "scenario": scenario,
                "mode": mode,
                "metric": metric,
                "mean": round(mean, 6),
                "ci_low": round(mean - lo, 6),
                "ci_high": round(mean + hi, 6),
                "n": int(sub.shape[0]),
            })

    pd.DataFrame(stats_rows).to_csv(outdir / "summary_stats.csv", index=False)


if __name__ == "__main__":
    main()
