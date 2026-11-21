"""Immutable sorted-string table (SSTable) kept as a human-readable JSON file.

File layout::

    {"file_id": 3, "min_key": "a", "max_key": "z", "entry_count": 2,
     "entries": [["a", "1"], ["z", null]]}      # null value = tombstone
"""
import bisect
import json

from .errors import CorruptFileError


class SSTable:
    """In-memory view of one SSTable file. Keys are sorted, so lookups use bisect."""

    def __init__(self, file_id, entries):
        self.file_id = file_id
        self.keys = [k for k, _ in entries]
        self.values = [v for _, v in entries]
        self.min_key = self.keys[0] if self.keys else None
        self.max_key = self.keys[-1] if self.keys else None

    def __len__(self):
        return len(self.keys)

    def lookup(self, key):
        """Return (found, value). value is None for a tombstone."""
        if not self.keys or key < self.min_key or key > self.max_key:
            return False, None
        i = bisect.bisect_left(self.keys, key)
        if i < len(self.keys) and self.keys[i] == key:
            return True, self.values[i]
        return False, None

    def to_json(self):
        return {
            "file_id": self.file_id,
            "min_key": self.min_key,
            "max_key": self.max_key,
            "entry_count": len(self.keys),
            "entries": [[k, v] for k, v in zip(self.keys, self.values)],
        }

    @classmethod
    def load(cls, path, name, expected_file_id=None):
        """Read and validate a file. Raises CorruptFileError on any problem."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as exc:
            raise CorruptFileError(name, f"cannot be read as JSON ({exc})") from exc

        if not isinstance(doc, dict):
            raise CorruptFileError(name, "top level is not an object")
        for field in ("file_id", "entry_count", "entries", "min_key", "max_key"):
            if field not in doc:
                raise CorruptFileError(name, f"missing field '{field}'")
        file_id, entries = doc["file_id"], doc["entries"]
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            raise CorruptFileError(name, "file_id is not an integer")
        if expected_file_id is not None and file_id != expected_file_id:
            raise CorruptFileError(name, f"file_id {file_id} does not match file name")
        if not isinstance(entries, list):
            raise CorruptFileError(name, "entries is not a list")

        clean, prev = [], None
        for pos, item in enumerate(entries):
            if not (isinstance(item, list) and len(item) == 2):
                raise CorruptFileError(name, f"entry {pos} is not a [key, value] pair")
            key, value = item
            if not isinstance(key, str) or not (value is None or isinstance(value, str)):
                raise CorruptFileError(name, f"entry {pos} has invalid key or value type")
            if prev is not None and key <= prev:
                raise CorruptFileError(name, f"entry {pos} breaks sort order at key {key!r}")
            prev = key
            clean.append((key, value))

        if doc["entry_count"] != len(clean):
            raise CorruptFileError(
                name, f"entry_count {doc['entry_count']} != actual {len(clean)}")
        table = cls(file_id, clean)
        if doc["min_key"] != table.min_key or doc["max_key"] != table.max_key:
            raise CorruptFileError(name, "min_key/max_key do not match entries")
        return table
