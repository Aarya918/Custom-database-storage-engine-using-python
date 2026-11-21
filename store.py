"""LSMStore: a small, readable Log-Structured Merge-Tree key-value store.

Write path : validate -> append to WAL (+fsync) -> update memtable -> flush if full
Read path  : memtable -> SSTables newest to oldest, first match wins
Flush      : sorted temp file -> fsync -> rename -> manifest -> truncate WAL
Compaction : merge all SSTables, keep newest value, drop tombstones
Recovery   : replay WAL records newer than manifest.last_flushed_seq
"""
import bisect
import json
import os

from .errors import (CorruptFileError, DatabaseLockedError, InvalidKeyError,
                     InvalidValueError, StorageIOError, StoreClosedError)
from .sstable import SSTable

try:  # POSIX (Linux, macOS)
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None

MAX_KEY_BYTES = 1024
MAX_VALUE_BYTES = 1024 * 1024
WAL_NAME = "wal.log"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = "LOCK"
TMP_SUFFIX = ".tmp"


def _sst_name(file_id):
    return f"sst_{file_id:06d}.json"


def _sst_id(name):
    """Return the numeric id of 'sst_000012.json', or None if it is not an SSTable name."""
    if name.startswith("sst_") and name.endswith(".json"):
        digits = name[4:-5]
        if digits.isdigit():
            return int(digits)
    return None


def _fsync_dir(path):
    """fsync a directory so a rename survives power loss (best effort on Windows)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class LSMStore:
    def __init__(self, path, memtable_limit=1000, sync=True):
        if not isinstance(memtable_limit, int) or memtable_limit < 1:
            raise ValueError("memtable_limit must be a positive integer")
        self.path = os.fspath(path)
        self.memtable_limit = memtable_limit
        self.sync = bool(sync)
        self._closed = True
        self._lock_fd = None
        self._wal = None
        self.mem = {}          # key -> value, None means tombstone
        self.seq = 0           # last sequence number handed out
        self._tables = []      # oldest -> newest
        try:
            os.makedirs(self.path, exist_ok=True)
        except OSError as exc:
            raise StorageIOError(f"cannot create {self.path}: {exc}") from exc
        self._acquire_lock()
        try:
            self._cleanup_tmp_files()
            self._manifest = self._load_manifest()
            self._remove_orphan_tables()
            self._tables = [self._load_table(n) for n in self._manifest["live_files"]]
            self.seq = self._manifest["last_flushed_seq"]
            self._recover_wal()
            self._wal = open(self._p(WAL_NAME), "a", encoding="utf-8", newline="\n")
            self._closed = False
        except BaseException:
            self._release_resources()
            raise

    # ------------------------------------------------------------------ helpers
    def _p(self, name):
        return os.path.join(self.path, name)

    def _check_open(self):
        if self._closed:
            raise StoreClosedError("the store is closed")

    @staticmethod
    def _check_key(key):
        if not isinstance(key, str) or key == "":
            raise InvalidKeyError("key must be a non-empty string")
        try:
            size = len(key.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise InvalidKeyError("key is not valid text") from exc
        if size > MAX_KEY_BYTES:
            raise InvalidKeyError(f"key is {size} bytes; the limit is {MAX_KEY_BYTES}")

    @staticmethod
    def _check_value(value):
        if not isinstance(value, str):
            raise InvalidValueError("value must be a string")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise InvalidValueError("value is not valid text") from exc
        if size > MAX_VALUE_BYTES:
            raise InvalidValueError(f"value is {size} bytes; the limit is {MAX_VALUE_BYTES}")

    # --------------------------------------------------------------------- lock
    def _acquire_lock(self):
        try:
            fd = os.open(self._p(LOCK_NAME), os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise StorageIOError(f"cannot open lock file: {exc}") from exc
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:  # pragma: no cover
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            raise DatabaseLockedError(f"{self.path} is in use by another process") from None
        self._lock_fd = fd

    def _release_resources(self):
        if self._wal is not None:
            try:
                self._wal.close()
            except OSError:
                pass
            self._wal = None
        if self._lock_fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    # --------------------------------------------------------- atomic file write
    def _write_json_atomic(self, final_path, obj):
        """temp file -> fsync -> atomic rename -> fsync directory (Rules 2 and 4)."""
        tmp = final_path + TMP_SUFFIX
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final_path)
            _fsync_dir(self.path)
        except OSError as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise StorageIOError(f"failed to write {os.path.basename(final_path)}: {exc}") from exc

    # ----------------------------------------------------------- startup helpers
    def _cleanup_tmp_files(self):
        for name in os.listdir(self.path):
            if name.endswith(TMP_SUFFIX):
                try:
                    os.remove(self._p(name))
                except OSError as exc:
                    raise StorageIOError(f"cannot remove stray {name}: {exc}") from exc

    def _load_manifest(self):
        path = self._p(MANIFEST_NAME)
        if not os.path.exists(path):
            return {"live_files": [], "next_file_id": 1, "last_flushed_seq": 0}
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as exc:
            raise CorruptFileError(MANIFEST_NAME, f"cannot be read as JSON ({exc})") from exc
        ok = (isinstance(doc, dict)
              and isinstance(doc.get("live_files"), list)
              and all(isinstance(n, str) and _sst_id(n) is not None for n in doc["live_files"])
              and isinstance(doc.get("next_file_id"), int)
              and isinstance(doc.get("last_flushed_seq"), int))
        if not ok:
            raise CorruptFileError(MANIFEST_NAME, "unexpected structure")
        return doc

    def _remove_orphan_tables(self):
        """SSTables not listed in the manifest come from a crash mid flush/compaction."""
        live = set(self._manifest["live_files"])
        for name in os.listdir(self.path):
            if _sst_id(name) is not None and name not in live:
                try:
                    os.remove(self._p(name))
                except OSError as exc:
                    raise StorageIOError(f"cannot remove orphan {name}: {exc}") from exc

    def _load_table(self, name):
        path = self._p(name)
        if not os.path.exists(path):
            raise CorruptFileError(name, "listed in the manifest but missing on disk")
        return SSTable.load(path, name, expected_file_id=_sst_id(name))

    # ------------------------------------------------------------- WAL: recovery
    def _recover_wal(self):
        """Rule 5: replay records with seq > last_flushed_seq; ignore a torn last line."""
        path = self._p(WAL_NAME)
        if not os.path.exists(path):
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            raise StorageIOError(f"cannot read WAL: {exc}") from exc

        lines = data.split(b"\n")
        last_nonempty = max((i for i, ln in enumerate(lines) if ln.strip()), default=-1)
        last_flushed = self._manifest["last_flushed_seq"]
        offset = good_end = 0
        needs_newline = False
        for idx, raw in enumerate(lines):
            line_end = offset + len(raw) + (1 if idx < len(lines) - 1 else 0)
            if raw.strip():
                try:
                    rec = self._parse_wal_record(raw)
                except ValueError as exc:
                    if idx == last_nonempty:
                        break  # torn final record from a crash: ignore it
                    raise CorruptFileError(WAL_NAME, f"line {idx + 1}: {exc}") from exc
                if rec["seq"] > last_flushed:
                    self.mem[rec["key"]] = rec["value"] if rec["op"] == "PUT" else None
                self.seq = max(self.seq, rec["seq"])
                good_end = line_end
                needs_newline = idx == len(lines) - 1  # valid record without newline
            else:
                good_end = line_end
            offset = line_end

        try:
            if good_end < len(data) or needs_newline:
                with open(path, "r+b") as f:
                    f.truncate(good_end)
                    if needs_newline:
                        f.seek(0, os.SEEK_END)
                        f.write(b"\n")
                    f.flush()
                    os.fsync(f.fileno())
        except OSError as exc:
            raise StorageIOError(f"cannot repair WAL tail: {exc}") from exc

    @staticmethod
    def _parse_wal_record(raw):
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError("not valid JSON") from None
        if not isinstance(rec, dict):
            raise ValueError("record is not an object")
        seq, op, key, value = (rec.get(k) for k in ("seq", "op", "key", "value"))
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise ValueError("bad seq")
        if op not in ("PUT", "DELETE") or not isinstance(key, str) or key == "":
            raise ValueError("bad op or key")
        if (op == "PUT" and not isinstance(value, str)) or (op == "DELETE" and value is not None):
            raise ValueError("bad value")
        return rec

    # ----------------------------------------------------------- WAL: write path
    def _append_wal(self, op, key, value):
        """Rule 1: the record is durable (flushed, fsynced if sync) before we return."""
        seq = self.seq + 1
        line = json.dumps({"seq": seq, "op": op, "key": key, "value": value},
                          separators=(",", ":")) + "\n"
        fd = self._wal.fileno()
        size_before = None
        try:
            size_before = os.fstat(fd).st_size
            self._wal.write(line)
            self._wal.flush()
            if self.sync:
                os.fsync(fd)
        except OSError as exc:
            try:  # keep the log consistent: drop any half-written record
                if size_before is not None:
                    self._wal.truncate(size_before)
            except (OSError, ValueError):
                pass
            raise StorageIOError(f"WAL write failed: {exc}") from exc
        self.seq = seq

    def _truncate_wal(self):
        try:
            self._wal.flush()
            self._wal.truncate(0)
            self._wal.flush()
            os.fsync(self._wal.fileno())
        except OSError as exc:
            raise StorageIOError(f"WAL truncate failed: {exc}") from exc

    # --------------------------------------------------------------- public API
    def put(self, key, value):
        self._check_open()
        self._check_key(key)
        self._check_value(value)
        self._append_wal("PUT", key, value)
        self.mem[key] = value
        if len(self.mem) >= self.memtable_limit:
            self.flush()

    def delete(self, key):
        """Write a tombstone. Deleting a missing key is not an error."""
        self._check_open()
        self._check_key(key)
        self._append_wal("DELETE", key, None)
        self.mem[key] = None
        if len(self.mem) >= self.memtable_limit:
            self.flush()

    def get(self, key):
        """Rule 3: newest value wins; a tombstone or a missing key returns None."""
        self._check_open()
        self._check_key(key)
        if key in self.mem:
            return self.mem[key]
        for table in reversed(self._tables):
            found, value = table.lookup(key)
            if found:
                return value
        return None

    def scan(self, start=None, end=None):
        """Sorted, de-duplicated (key, value) pairs with start <= key < end."""
        self._check_open()
        merged = {}
        for table in self._tables:  # oldest first, so newer files overwrite
            lo = bisect.bisect_left(table.keys, start) if start is not None else 0
            hi = bisect.bisect_left(table.keys, end) if end is not None else len(table.keys)
            for i in range(lo, hi):
                merged[table.keys[i]] = table.values[i]
        for key, value in self.mem.items():
            if (start is None or key >= start) and (end is None or key < end):
                merged[key] = value
        return [(k, merged[k]) for k in sorted(merged) if merged[k] is not None]

    def flush(self):
        """Rule 2: memtable -> new SSTable, then (and only then) truncate the WAL."""
        self._check_open()
        if not self.mem:
            return
        entries = sorted(self.mem.items())
        file_id = self._manifest["next_file_id"]
        name = _sst_name(file_id)
        table = SSTable(file_id, entries)
        self._write_json_atomic(self._p(name), table.to_json())
        new_manifest = {
            "live_files": self._manifest["live_files"] + [name],
            "next_file_id": file_id + 1,
            "last_flushed_seq": self.seq,
        }
        self._write_json_atomic(self._p(MANIFEST_NAME), new_manifest)
        self._manifest = new_manifest
        self._tables.append(table)
        self.mem = {}
        self._truncate_wal()

    def compact(self):
        """Rule 4: merge every SSTable into one, newest value wins, tombstones dropped."""
        self._check_open()
        if not self._tables:
            return
        has_tombstone = any(v is None for t in self._tables for v in t.values)
        if len(self._tables) == 1 and not has_tombstone:
            return
        merged = {}
        for table in self._tables:
            merged.update(zip(table.keys, table.values))
        entries = sorted((k, v) for k, v in merged.items() if v is not None)
        old_files = list(self._manifest["live_files"])
        next_id = self._manifest["next_file_id"]
        new_tables, live = [], []
        if entries:
            new_table = SSTable(next_id, entries)
            name = _sst_name(next_id)
            self._write_json_atomic(self._p(name), new_table.to_json())
            new_tables, live, next_id = [new_table], [name], next_id + 1
        new_manifest = {
            "live_files": live,
            "next_file_id": next_id,
            "last_flushed_seq": self._manifest["last_flushed_seq"],
        }
        self._write_json_atomic(self._p(MANIFEST_NAME), new_manifest)
        self._manifest = new_manifest
        self._tables = new_tables
        for old in old_files:  # only after the new manifest is durable
            try:
                os.remove(self._p(old))
            except OSError:
                pass  # an orphan is cleaned up at next startup
        _fsync_dir(self.path)

    def stats(self):
        self._check_open()
        return {
            "memtable_entries": len(self.mem),
            "sstables": len(self._tables),
            "last_seq": self.seq,
            "live_files": list(self._manifest["live_files"]),
        }

    def close(self):
        """Flush WAL buffers and release the directory lock (idempotent)."""
        if self._closed:
            return
        try:
            if self._wal is not None:
                self._wal.flush()
                os.fsync(self._wal.fileno())
        except OSError as exc:
            self._closed = True
            self._release_resources()
            raise StorageIOError(f"close failed: {exc}") from exc
        self._closed = True
        self._release_resources()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
