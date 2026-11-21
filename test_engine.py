import json
import os
import unittest

from lsm import (CorruptFileError, DatabaseLockedError, InvalidKeyError, InvalidValueError,
                 LSMStore, StoreClosedError)
from tests.helpers import TempDirTestCase


class BasicOperations(TempDirTestCase):
    def test_put_get_overwrite(self):
        s = self.open()
        s.put("a", "1")
        s.put("a", "2")
        self.assertEqual(s.get("a"), "2")

    def test_missing_key_is_none_and_empty_db_is_safe(self):
        s = self.open()
        self.assertIsNone(s.get("nope"))
        s.flush()
        s.compact()
        self.assertEqual(s.scan(), [])

    def test_delete_writes_tombstone(self):
        s = self.open()
        s.put("a", "1")
        s.delete("a")
        self.assertIsNone(s.get("a"))

    def test_delete_nonexistent_key_succeeds(self):
        s = self.open()
        s.delete("ghost")
        self.assertIsNone(s.get("ghost"))

    def test_key_and_value_validation(self):
        s = self.open()
        for bad in ("", None, 5, b"x", "k" * 2000):
            with self.assertRaises(InvalidKeyError):
                s.put(bad, "v")
        with self.assertRaises(InvalidKeyError):
            s.get("")
        with self.assertRaises(InvalidValueError):
            s.put("k", None)
        with self.assertRaises(InvalidValueError):
            s.put("k", "v" * (1024 * 1024 + 1))

    def test_closed_store_rejects_operations(self):
        s = self.open()
        s.close()
        with self.assertRaises(StoreClosedError):
            s.put("a", "1")

    def test_unicode_keys_and_values(self):
        s = self.open()
        s.put("नमस्ते", "ಕನ್ನಡ ✓")
        s.close()
        s2 = self.open()
        self.assertEqual(s2.get("नमस्ते"), "ಕನ್ನಡ ✓")


class FlushAndReadPath(TempDirTestCase):
    def test_flush_triggers_at_memtable_limit(self):
        s = self.open(memtable_limit=3)
        for i in range(3):
            s.put(f"k{i}", "v")
        self.assertEqual(s.stats()["sstables"], 1)
        self.assertEqual(s.stats()["memtable_entries"], 0)
        self.assertEqual(os.path.getsize(self.path("wal.log")), 0)

    def test_sstable_file_is_sorted_json_with_tombstone(self):
        s = self.open(memtable_limit=1000)
        s.put("b", "2")
        s.put("a", "1")
        s.delete("c")
        s.flush()
        with open(self.path("sst_000001.json")) as f:
            doc = json.load(f)
        self.assertEqual(doc["entries"], [["a", "1"], ["b", "2"], ["c", None]])
        self.assertEqual((doc["min_key"], doc["max_key"], doc["entry_count"]), ("a", "c", 3))

    def test_newest_value_wins_across_files(self):
        s = self.open(memtable_limit=2)
        s.put("a", "old"); s.put("x", "1")       # flush -> file 1
        s.put("a", "new"); s.put("y", "2")       # flush -> file 2
        self.assertGreaterEqual(s.stats()["sstables"], 2)
        self.assertEqual(s.get("a"), "new")

    def test_tombstone_hides_key_in_older_sstable(self):
        s = self.open(memtable_limit=2)
        s.put("a", "1"); s.put("b", "2")          # flushed
        s.delete("a")
        self.assertIsNone(s.get("a"))             # tombstone in memtable
        s.put("c", "3")                            # flush tombstone to a newer file
        self.assertIsNone(s.get("a"))             # tombstone in newer SSTable
        self.assertEqual(s.get("b"), "2")

    def test_restart_keeps_flushed_and_unflushed_data(self):
        s = self.open(memtable_limit=3)
        for i in range(7):
            s.put(f"k{i}", str(i))
        s.delete("k1")
        s.close()
        s2 = self.open(memtable_limit=3)
        self.assertEqual([s2.get(f"k{i}") for i in range(7)],
                         ["0", None, "2", "3", "4", "5", "6"])


class Compaction(TempDirTestCase):
    def test_compaction_matches_model_and_drops_tombstones(self):
        s = self.open(memtable_limit=4)
        model = {}
        for i in range(30):
            k = f"k{i % 9}"
            if i % 5 == 4:
                s.delete(k); model.pop(k, None)
            else:
                s.put(k, str(i)); model[k] = str(i)
        s.flush()
        before = s.stats()["sstables"]
        s.compact()
        self.assertEqual(s.stats()["sstables"], 1)
        self.assertGreater(before, 1)
        self.assertEqual(dict(s.scan()), model)
        with open(self.path(s.stats()["live_files"][0])) as f:
            self.assertTrue(all(v is not None for _, v in json.load(f)["entries"]))
        sst_files = [n for n in os.listdir(self.dir) if n.startswith("sst_")]
        self.assertEqual(len(sst_files), 1)         # old files deleted

    def test_compaction_does_not_resurrect_deleted_keys(self):
        s = self.open(memtable_limit=2)
        s.put("a", "1"); s.put("b", "2")
        s.delete("a"); s.put("c", "3")
        s.compact()
        self.assertIsNone(s.get("a"))
        s.close()
        self.assertIsNone(self.open().get("a"))

    def test_compaction_of_everything_deleted_leaves_no_files(self):
        s = self.open(memtable_limit=2)
        s.put("a", "1"); s.put("b", "2")
        s.delete("a"); s.delete("b")
        s.compact()
        self.assertEqual(s.stats()["sstables"], 0)
        self.assertIsNone(s.get("a"))


class RangeScan(TempDirTestCase):
    def test_scan_sorted_deduplicated_across_layers(self):
        s = self.open(memtable_limit=3)
        for k in ["d", "b", "a"]:
            s.put(k, "old-" + k)
        s.put("b", "new-b"); s.put("e", "5"); s.delete("d")
        self.assertEqual(s.scan(), [("a", "old-a"), ("b", "new-b"), ("e", "5")])
        self.assertEqual(s.scan("b", "e"), [("b", "new-b")])


class LockingAndCorruption(TempDirTestCase):
    def test_second_open_is_locked_out(self):
        self.open()
        with self.assertRaises(DatabaseLockedError):
            LSMStore(self.dir)

    def test_lock_released_on_close(self):
        s = self.open()
        s.close()
        self.open()

    def _flushed_store_dir(self):
        s = self.open(memtable_limit=2)
        s.put("a", "1"); s.put("b", "2")
        s.close()

    def test_bad_entry_count_raises_with_file_name(self):
        self._flushed_store_dir()
        p = self.path("sst_000001.json")
        doc = json.load(open(p)); doc["entry_count"] = 99
        json.dump(doc, open(p, "w"))
        with self.assertRaises(CorruptFileError) as cm:
            LSMStore(self.dir)
        self.assertIn("sst_000001.json", str(cm.exception))

    def test_unsorted_sstable_rejected(self):
        self._flushed_store_dir()
        p = self.path("sst_000001.json")
        doc = json.load(open(p)); doc["entries"].reverse()
        json.dump(doc, open(p, "w"))
        with self.assertRaises(CorruptFileError):
            LSMStore(self.dir)

    def test_garbage_sstable_and_missing_sstable_and_bad_manifest(self):
        self._flushed_store_dir()
        open(self.path("sst_000001.json"), "w").write("{not json")
        with self.assertRaises(CorruptFileError):
            LSMStore(self.dir)
        os.remove(self.path("sst_000001.json"))
        with self.assertRaises(CorruptFileError):
            LSMStore(self.dir)
        open(self.path("manifest.json"), "w").write("[]")
        with self.assertRaises(CorruptFileError):
            LSMStore(self.dir)

    def test_failed_open_releases_lock(self):
        self._flushed_store_dir()
        open(self.path("sst_000001.json"), "w").write("garbage")
        with self.assertRaises(CorruptFileError):
            LSMStore(self.dir)
        os.remove(self.path("manifest.json"))
        os.remove(self.path("sst_000001.json"))
        self.open()  # would raise DatabaseLockedError if the lock leaked


if __name__ == "__main__":
    unittest.main()
