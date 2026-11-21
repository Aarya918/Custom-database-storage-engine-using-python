#!/usr/bin/env python3
"""Short live demo: basic operations, then a real SIGKILL and recovery.   python demo.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

from lsm import LSMStore
from tests.crash_writer import gen_ops


def section(title):
    print(f"\n=== {title} ===")


def main():
    tmp = tempfile.mkdtemp(prefix="lsm_demo_")
    try:
        section("1. put / get / overwrite / delete")
        with LSMStore(os.path.join(tmp, "db1"), memtable_limit=3) as s:
            s.put("user:1", "alice"); s.put("user:2", "bob")
            s.put("user:1", "alice_v2")
            print("get user:1 ->", s.get("user:1"))
            s.delete("user:2")
            print("get user:2 ->", s.get("user:2"), "(tombstone)")
            print("stats after 4 writes ->", s.stats())

        section("2. flush and compaction (memtable_limit=3)")
        with LSMStore(os.path.join(tmp, "db1"), memtable_limit=3) as s:
            for i in range(8):
                s.put(f"k{i}", str(i))
            print("SSTables before compact:", s.stats()["sstables"])
            s.compact()
            print("SSTables after  compact:", s.stats()["sstables"], "| scan:", s.scan("k0", "k3"))

        section("3. hard kill (SIGKILL) in the middle of writing, then recover")
        db, ack = os.path.join(tmp, "db2"), os.path.join(tmp, "ack.log")
        writer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "crash_writer.py")
        proc = subprocess.Popen([sys.executable, writer, db, ack, "42", "20000"])
        while not os.path.exists(ack) or open(ack, "rb").read().count(b"\n") < 150:
            time.sleep(0.001)
        proc.kill(); proc.wait()
        acked = open(ack, "rb").read().count(b"\n")
        print(f"writer killed with SIGKILL after {acked} acknowledged operations")
        expected = {}
        ops = gen_ops(42, 20000)
        for op, k, v in ops[:acked]:
            if op == "PUT": expected[k] = v
            elif op == "DELETE": expected.pop(k, None)
        with LSMStore(db, memtable_limit=10) as s:
            alt = {ops[acked][1]} if ops[acked][0] != "COMPACT" else set()
            bad = [k for k in {f"k{i}" for i in range(60)}
                   if k not in alt and s.get(k) != expected.get(k)]
            print(f"reopened: WAL replayed, {len(expected)} live keys expected, mismatches: {len(bad)}")
            print("recovery rate:", "100%" if not bad else "FAILED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
