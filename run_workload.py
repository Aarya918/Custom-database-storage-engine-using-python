#!/usr/bin/env python3
"""Replay a workload CSV against the engine and record latency per operation.

    python run_workload.py workload.csv --db ./data --out results.csv
"""
import argparse
import os
import shutil
import sys
import time

import pandas as pd

from analysis.workload import load_workload
from lsm import LSMError, LSMStore


def replay(df, store, compact_every=0):
    """Replay rows in seq order. Returns a DataFrame with latency_us and dataset_size added.

    latency_us   = wall-clock time of the single store call (time.perf_counter)
    dataset_size = number of distinct live keys just before the operation runs
    """
    live = set()
    latencies, sizes = [], []
    clock = time.perf_counter
    for n, (op, key, value) in enumerate(zip(df["op"], df["key"], df["value"]), start=1):
        sizes.append(len(live))
        if op == "GET":
            t0 = clock(); store.get(key); t1 = clock()
        elif op == "PUT":
            t0 = clock(); store.put(key, value); t1 = clock()
            live.add(key)
        else:
            t0 = clock(); store.delete(key); t1 = clock()
            live.discard(key)
        latencies.append((t1 - t0) * 1e6)
        if compact_every and n % compact_every == 0:
            store.compact()
    out = df.copy()
    out["latency_us"] = [round(x, 3) for x in latencies]
    out["dataset_size"] = sizes
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Replay a key-value workload against the LSM engine")
    p.add_argument("workload")
    p.add_argument("--db", default="./data", help="database directory (must be empty or missing)")
    p.add_argument("--out", default="results.csv")
    p.add_argument("--memtable-limit", type=int, default=1000)
    p.add_argument("--no-sync", action="store_true", help="skip fsync on every WAL write")
    p.add_argument("--compact-every", type=int, default=0, help="run compact() every N operations")
    p.add_argument("--fresh", action="store_true", help="delete the database directory first")
    args = p.parse_args(argv)

    try:
        df, report = load_workload(args.workload)
    except LSMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"rows: {report['total_rows']}  valid: {report['valid_rows']}  excluded: {report['excluded_rows']}")
    if report["excluded_rows"]:
        fi = report["first_invalid"]
        print(f"  first invalid row: CSV line {fi['csv_line']} ({fi['reason']}); reasons: {report['reasons']}")

    if args.fresh and os.path.isdir(args.db):
        shutil.rmtree(args.db)
    if os.path.isdir(args.db) and os.listdir(args.db):
        print(f"error: {args.db} is not empty (use --fresh to wipe it)", file=sys.stderr)
        return 2
    try:
        with LSMStore(args.db, memtable_limit=args.memtable_limit, sync=not args.no_sync) as store:
            result = replay(df, store, args.compact_every)
            stats = store.stats()
    except LSMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result.to_csv(args.out, index=False)
    print(f"wrote {len(result)} rows to {args.out}; final sstables: {stats['sstables']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
