#!/usr/bin/env python3
"""Write-throughput benchmark (FR-12). Optionally compares with LevelDB via plyvel.

    python benchmark.py --writes 5000 --value-size 100 --out benchmark_report.md
"""
import argparse
import os
import platform
import shutil
import tempfile
import time

from lsm import LSMStore


def bench_engine(n, value_size, sync, memtable_limit):
    d = tempfile.mkdtemp(prefix="lsm_bench_")
    value = "x" * value_size
    try:
        with LSMStore(d, memtable_limit=memtable_limit, sync=sync) as s:
            t0 = time.perf_counter()
            for i in range(n):
                s.put(f"key:{i:09d}", value)
            elapsed = time.perf_counter() - t0
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return n / elapsed


def bench_leveldb(n, value_size, sync):
    try:
        import plyvel
    except ImportError:
        return None
    d = tempfile.mkdtemp(prefix="leveldb_bench_")
    value = b"x" * value_size
    try:
        db = plyvel.DB(d, create_if_missing=True)
        t0 = time.perf_counter()
        for i in range(n):
            db.put(f"key:{i:09d}".encode(), value, sync=sync)
        elapsed = time.perf_counter() - t0
        db.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return n / elapsed


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--writes", type=int, default=5000)
    p.add_argument("--value-size", type=int, default=100)
    p.add_argument("--memtable-limit", type=int, default=1000)
    p.add_argument("--out", default="benchmark_report.md")
    a = p.parse_args(argv)

    rows = []
    for sync in (True, False):
        eng = bench_engine(a.writes, a.value_size, sync, a.memtable_limit)
        ldb = bench_leveldb(a.writes, a.value_size, sync)
        ratio = f"{ldb / eng:.1f}x" if ldb else "n/a"
        rows.append((sync, eng, ldb, ratio))

    lines = [
        "# Write throughput benchmark", "",
        f"- Machine: {platform.platform()} ({os.cpu_count()} logical CPUs)",
        f"- Python: {platform.python_version()}",
        f"- Workload: {a.writes} sequential unique-key PUTs, value size {a.value_size} bytes, "
        f"memtable_limit {a.memtable_limit}",
        "- Metric: completed writes / elapsed seconds (time.perf_counter)",
        "- LevelDB baseline: plyvel, same machine and workload"
        + ("" if any(r[2] for r in rows) else " (NOT MEASURED: plyvel is not installed here)"),
        "", "| sync | this engine (writes/s) | LevelDB (writes/s) | LevelDB / engine |",
        "|---|---|---|---|",
    ]
    for sync, eng, ldb, ratio in rows:
        lines.append(f"| {sync} | {eng:,.0f} | {f'{ldb:,.0f}' if ldb else 'n/a'} | {ratio} |")
    lines += ["", "Target from the PRD: engine within 10x of LevelDB (ratio <= 10x)."]
    text = "\n".join(lines) + "\n"
    with open(a.out, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
