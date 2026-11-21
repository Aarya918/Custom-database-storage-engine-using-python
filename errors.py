"""Exception types raised by the storage engine and the analysis tools."""


class LSMError(Exception):
    """Base class for every error raised by this project."""


class InvalidKeyError(LSMError, ValueError):
    """Key is empty, not a string, or larger than the documented limit."""


class InvalidValueError(LSMError, ValueError):
    """Value is not a string or is larger than the documented limit."""


class CorruptFileError(LSMError):
    """An SSTable, the manifest or a WAL record failed validation."""

    def __init__(self, filename, reason):
        self.filename = filename
        self.reason = reason
        super().__init__(f"{filename}: {reason}")


class DatabaseLockedError(LSMError):
    """Another process already holds the database directory."""


class StorageIOError(LSMError):
    """A disk write, rename or fsync failed."""


class StoreClosedError(LSMError):
    """An operation was attempted on a closed store."""


class WorkloadFormatError(LSMError):
    """The workload CSV is missing, malformed or lacks required columns."""
