#!/usr/bin/env python3
"""Generate a synthetic key-value workload CSV (no real personal data).

    python generate_workload.py --shape mixed --ops 10000 --seed 1 --out data/mixed.csv
"""
import argparse
import csv
import datetime
import random

SHAPES = {                      # (GET, PUT, DELETE) probabilities
    "read-heavy": (0.90, 0.09, 0.01),
    "write-heavy": (0.10, 0.85, 0.05),
    "mixed": (0.50, 0.45, 0.05),
}


def generate(shape, ops, seed, new_key_prob=0.7):
    rng = random.Random(seed)
    p_get, p_put, _ = SHAPES[shape]
    live, next_id = [], 1
    t0 = datetime.datetime(2026, 10, 1, 10, 0, 0)
    for seq in range(1, ops + 1):
        r = rng.random()
        ts = (t0 + datetime.timedelta(seconds=seq - 1)).isoformat()
        if r < p_get:
            key = rng.choice(live) if live and rng.random() < 0.9 else f"user:{rng.randrange(1, next_id + 50)}"
            yield seq, "GET", key, "", ts
        elif r < p_get + p_put or not live:
            if not live or rng.random() < new_key_prob:
                key = f"user:{next_id}"; next_id += 1; live.append(key)
            else:
                key = rng.choice(live)
            yield seq, "PUT", key, f"value_{seq}", ts
        else:
            i = rng.randrange(len(live))
            live[i], live[-1] = live[-1], live[i]
            yield seq, "DELETE", live.pop(), "", ts


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--shape", choices=sorted(SHAPES), default="mixed")
    p.add_argument("--ops", type=int, default=10000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "op", "key", "value", "timestamp"])
        w.writerows(generate(a.shape, a.ops, a.seed))
    print(f"wrote {a.ops} {a.shape} operations to {a.out}")


if __name__ == "__main__":
    main()
