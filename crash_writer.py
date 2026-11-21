"""Subprocess used by test_crash.py. Applies a deterministic operation stream and appends
the index of each operation to an ack file *after* the engine call returned.

usage: python tests/crash_writer.py DB_DIR ACK_FILE SEED N_OPS
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lsm import LSMStore  # noqa: E402

KEY_SPACE = 60


def gen_ops(seed, n):
    """Deterministic stream shared by the writer and the verifier."""
    rng = random.Random(seed)
    ops = []
    for i in range(n):
        r = rng.random()
        key = f"k{rng.randrange(KEY_SPACE)}"
        if r < 0.65:
            ops.append(("PUT", key, f"v{i}-{rng.randrange(10**6)}"))
        elif r < 0.92:
            ops.append(("DELETE", key, None))
        else:
            ops.append(("COMPACT", None, None))
    return ops


def main():
    db, ack_path, seed, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    store = LSMStore(db, memtable_limit=10, sync=True)
    ack = os.open(ack_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    for i, (op, key, value) in enumerate(gen_ops(seed, n)):
        if op == "PUT":
            store.put(key, value)
        elif op == "DELETE":
            store.delete(key)
        else:
            store.compact()
        os.write(ack, f"{i}\n".encode())   # reached only after the call returned = acknowledged


if __name__ == "__main__":
    main()
