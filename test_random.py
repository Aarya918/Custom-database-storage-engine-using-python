"""Randomized comparison against a plain dict model (Evaluation: engine correctness)."""
import random
import shutil
import tempfile
import unittest

from tests.helpers import TempDirTestCase

KEYS = [f"key{i:02d}" for i in range(40)]


class RandomAgainstDict(TempDirTestCase):
    def run_seed(self, seed, steps=1500):
        rng = random.Random(seed)
        self.dir = tempfile.mkdtemp(prefix="lsm_rand_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        store = self.open(memtable_limit=rng.choice([2, 5, 8, 25]), sync=False)
        model = {}
        for step in range(steps):
            r = rng.random()
            key = rng.choice(KEYS)
            if r < 0.40:
                value = f"v{step}"
                store.put(key, value); model[key] = value
            elif r < 0.55:
                store.delete(key); model.pop(key, None)
            elif r < 0.88:
                self.assertEqual(store.get(key), model.get(key),
                                 f"seed={seed} step={step} key={key}")
            elif r < 0.92:
                store.flush()
            elif r < 0.96:
                store.compact()
            else:   # reopen (clean restart)
                limit = store.memtable_limit
                store.close()
                store = self.open(memtable_limit=limit, sync=False)
        self.assertEqual(dict(store.scan()), model, f"seed={seed}")
        for key in KEYS:
            self.assertEqual(store.get(key), model.get(key), f"seed={seed} final key={key}")
        store.close()

    def test_many_seeds(self):
        for seed in range(12):
            with self.subTest(seed=seed):
                self.run_seed(seed)


if __name__ == "__main__":
    unittest.main()
