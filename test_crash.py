"""Hard-kill recovery test: start a writer process, SIGKILL it mid-write, reopen, verify.

Environment variables:  CRASH_ITERS (default 25)   CRASH_SEED (default 1000)
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from lsm import LSMStore
from tests.crash_writer import KEY_SPACE, gen_ops

WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_writer.py")
N_OPS = 20000


def acked_count(ack_path):
    try:
        data = open(ack_path, "rb").read()
    except FileNotFoundError:
        return 0
    return data.count(b"\n")


@unittest.skipIf(os.name == "nt", "SIGKILL tests run on Linux/macOS only (documented limitation)")
class SigkillRecovery(unittest.TestCase):
    def test_every_acknowledged_write_survives_sigkill(self):
        iters = int(os.environ.get("CRASH_ITERS", "25"))
        base_seed = int(os.environ.get("CRASH_SEED", "1000"))
        total_acked = 0
        for it in range(iters):
            seed = base_seed + it
            tmp = tempfile.mkdtemp(prefix="lsm_crash_")
            try:
                db, ack_path = os.path.join(tmp, "db"), os.path.join(tmp, "ack.log")
                rng = random.Random(seed * 31 + 7)
                target = rng.randrange(3, 300)
                proc = subprocess.Popen([sys.executable, WRITER, db, ack_path, str(seed), str(N_OPS)])
                deadline = time.time() + 30
                while acked_count(ack_path) < target:
                    self.assertIsNone(proc.poll(), f"writer exited early (seed={seed})")
                    self.assertLess(time.time(), deadline, f"writer too slow (seed={seed})")
                    time.sleep(0.0005)
                time.sleep(rng.random() * 0.01)          # land the kill at a random point
                proc.kill()                               # SIGKILL
                proc.wait()

                acked = acked_count(ack_path)
                ops = gen_ops(seed, N_OPS)
                expected = {}
                for op, key, value in ops[:acked]:
                    if op == "PUT":
                        expected[key] = value
                    elif op == "DELETE":
                        expected.pop(key, None)
                # the single in-flight operation may or may not have reached the WAL
                pend_op, pend_key, pend_val = ops[acked]
                allowed_alt = {}
                if pend_op == "PUT":
                    allowed_alt[pend_key] = pend_val
                elif pend_op == "DELETE":
                    allowed_alt[pend_key] = None

                with LSMStore(db, memtable_limit=10, sync=True) as store:
                    for i in range(KEY_SPACE):
                        key = f"k{i}"
                        actual, want = store.get(key), expected.get(key)
                        if key in allowed_alt:
                            self.assertIn(actual, (want, allowed_alt[key]),
                                          f"seed={seed} acked={acked} key={key}")
                        else:
                            self.assertEqual(actual, want, f"seed={seed} acked={acked} key={key}")
                    store.put("after_recovery", "ok")      # store must stay writable
                    self.assertEqual(store.get("after_recovery"), "ok")
                total_acked += acked
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        print(f"\ncrash test: {iters} SIGKILLs, {total_acked} acknowledged operations, "
              f"recovery rate 100%")


if __name__ == "__main__":
    unittest.main()
