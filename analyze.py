#!/usr/bin/env python3
"""Produce distributions and plots from a results CSV written by run_workload.py.

    python analyze.py results.csv --out ./plots
"""
import argparse
import json
import os
import sys

from analysis import metrics, plots
from lsm import LSMError


def main(argv=None):
    p = argparse.ArgumentParser(description="Analyse workload results")
    p.add_argument("results")
    p.add_argument("--out", default="./plots")
    p.add_argument("--bucket-width", type=int, default=None, help="dataset-size bucket width (default: auto)")
    p.add_argument("--window", default="1min", help="time window for the per-window table (e.g. 1min, 5min)")
    p.add_argument("--window-ops", type=int, default=1000, help="block size when no timestamp column exists")
    args = p.parse_args(argv)

    try:
        df = metrics.load_results(args.results)
    except LSMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    os.makedirs(args.out, exist_ok=True)

    summary = metrics.distribution(df)
    windows = metrics.window_distribution(df, args.window, args.window_ops)
    latency, width = metrics.latency_by_bucket(df, args.bucket_width)

    with open(os.path.join(args.out, "distribution.json"), "w") as f:
        json.dump(summary, f, indent=2)
    windows.to_csv(os.path.join(args.out, "window_distribution.csv"), index=False)
    latency.to_csv(os.path.join(args.out, "latency_by_bucket.csv"), index=False)
    plots.plot_distribution(summary, os.path.join(args.out, "distribution.png"))
    plots.plot_windows(windows, os.path.join(args.out, "window_distribution.png"))
    plots.plot_latency(latency, os.path.join(args.out, "latency_vs_dataset_size.png"), width)

    print(json.dumps(summary, indent=2))
    if latency.empty:
        print("No read operations: latency table is N/A.")
    print(f"wrote tables and PNG plots to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
