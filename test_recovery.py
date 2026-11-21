import json
import os
import shutil
import unittest

from lsm import CorruptFileError, LSMStore
from tests.helpers import TempDirTestCase


class WalRecovery(TempDirTestCase):
    def test_unflushed_writes_replayed_after_unclean_stop(self):
        s = self.open()
        s.put("a", "1"); s.put("b", "2"); s.delete("a")
        # simulate a crash: do NOT call close(); release the lock by hand
        s._wal.flush()
        s._release_resources(); s._closed = True
        s2 = self.open()
        self.assertIsNone(s2.get("a"))
        self.assertEqual(s2.get("b"), "2")

    def test_partial_final_line_is_ignored_and_repaired(self):
        s = self.open()
        s.put("a", "1"); s.put("b", "2")
        s.close()
        with open(self.path("wal.log"), "ab") as f:
            f.write(b'{"seq":3,"op":"PUT","ke')
        s2 = self.open()
        self.assertEqual((s2.get("a"), s2.get("b")), ("1", "2"))
        s2.put("c", "3")                      # must append on a clean line
        s2.close()
        s3 = self.open()
        self.assertEqual((s3.get("a"), s3.get("b"), s3.get("c")), ("1", "2", "3"))

    def test_complete_last_record_without_newline_is_kept(self):
        s = self.open()
        s.put("a", "1")
        s.close()
        with open(self.path("wal.log"), "ab") as f:
            f.write(json.dumps({"seq": 2, "op": "PUT", "key": "b", "value": "2"}).encode())
        s2 = self.open()
        self.assertEqual(s2.get("b"), "2")
        s2.put("c", "3"); s2.close()
        self.assertEqual(self.open().get("c"), "3")

    def test_corruption_in_the_middle_is_reported(self):
        s = self.open()
        s.put("a", "1"); s.put("b", "2")
        s.close()
        lines = open(self.path("wal.log")).read().splitlines()
        open(self.path("wal.log"), "w").write("\n".join([lines[0], "%%garbage%%", lines[1]]) + "\n")
        with self.assertRaises(CorruptFileError) as cm:
            LSMStore(self.dir)
        self.assertIn("wal.log", str(cm.exception))

    def test_seq_continues_after_recovery(self):
        s = self.open()
        s.put("a", "1"); s.put("b", "2")
        s.close()
        s2 = self.open()
        s2.put("c", "3")
        self.assertEqual(s2.stats()["last_seq"], 3)


class CrashDuringFlushAndCompaction(TempDirTestCase):
    def test_crash_after_manifest_before_wal_truncate_no_duplicates(self):
        s = self.open(memtable_limit=1000)
        s.put("a", "1"); s.put("b", "2"); s.delete("a")
        wal_before = open(self.path("wal.log"), "rb").read()
        s.flush()
        s.close()
        open(self.path("wal.log"), "wb").write(wal_before)   # WAL "was not truncated"
        s2 = self.open()
        self.assertIsNone(s2.get("a"))
        self.assertEqual(s2.get("b"), "2")
        self.assertEqual(s2.stats()["memtable_entries"], 0)   # already-flushed seqs skipped
        self.assertEqual(s2.stats()["sstables"], 1)

    def test_crash_before_manifest_orphan_sstable_and_temp_removed(self):
        s = self.open()
        s.put("a", "1")
        s.close()
        open(self.path("sst_000007.json"), "w").write(
            json.dumps({"file_id": 7, "min_key": "z", "max_key": "z", "entry_count": 1,
                        "entries": [["z", "ghost"]]}))
        open(self.path("sst_000008.json.tmp"), "w").write("half written")
        s2 = self.open()
        self.assertIsNone(s2.get("z"))
        self.assertEqual(s2.get("a"), "1")
        self.assertFalse(os.path.exists(self.path("sst_000007.json")))
        self.assertFalse(os.path.exists(self.path("sst_000008.json.tmp")))

    def test_crash_after_compaction_manifest_old_files_removed(self):
        s = self.open(memtable_limit=2)
        s.put("a", "1"); s.put("b", "2"); s.put("a", "3"); s.put("c", "4")
        old = {n: open(self.path(n)).read() for n in s.stats()["live_files"]}
        s.compact()
        s.close()
        for n, text in old.items():              # old files "were not deleted yet"
            open(self.path(n), "w").write(text)
        s2 = self.open()
        self.assertEqual(dict(s2.scan()), {"a": "3", "b": "2", "c": "4"})
        self.assertEqual(len([n for n in os.listdir(self.dir) if n.startswith("sst_")]), 1)


if __name__ == "__main__":
    unittest.main()
