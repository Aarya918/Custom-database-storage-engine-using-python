import os
import shutil
import tempfile
import unittest

from lsm import LSMStore


class TempDirTestCase(unittest.TestCase):
    """Each test gets a fresh temporary database directory that is removed afterwards."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lsm_test_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._open = []

    def open(self, **kw):
        kw.setdefault("memtable_limit", 1000)
        store = LSMStore(self.dir, **kw)
        self._open.append(store)
        self.addCleanup(store.close)
        return store

    def path(self, name):
        return os.path.join(self.dir, name)
