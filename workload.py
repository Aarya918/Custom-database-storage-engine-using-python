"""Load and validate a key-value workload CSV (Rule 6)."""
import os

import pandas as pd

from lsm.errors import WorkloadFormatError

REQUIRED = ["seq", "op", "key", "value"]
VALID_OPS = {"GET", "PUT", "DELETE"}


def load_workload(path):
    """Return (valid_rows_df, report). Invalid rows are excluded and counted, never hidden.

    report = {"total_rows", "valid_rows", "excluded_rows", "reasons": {reason: n},
              "first_invalid": {"csv_line": int, "reason": str} | None}
    """
    if not os.path.isfile(path):
        raise WorkloadFormatError(f"workload file not found: {path}")
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:  # pandas raises several parser error types
        raise WorkloadFormatError(f"cannot parse {path} as CSV: {exc}") from exc
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise WorkloadFormatError(f"missing required column(s): {', '.join(missing)}")

    df = df.copy()
    df["op"] = df["op"].str.strip().str.upper()
    seq_num = pd.to_numeric(df["seq"], errors="coerce")
    reason = pd.Series("", index=df.index, dtype=object)

    def mark(mask, text):
        mask = mask & (reason == "")
        reason.loc[mask] = text

    mark(seq_num.isna() | (seq_num % 1 != 0), "seq is not an integer")
    mark(~df["op"].isin(VALID_OPS), "operation is not GET, PUT or DELETE")
    mark(df["key"] == "", "key is empty")
    mark((df["op"] == "PUT") & (df["value"] == ""), "PUT row has no value")
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        mark((df["timestamp"] != "") & ts.isna(), "timestamp cannot be parsed")

    bad = reason != ""
    report = {
        "total_rows": int(len(df)),
        "valid_rows": int((~bad).sum()),
        "excluded_rows": int(bad.sum()),
        "reasons": {k: int(v) for k, v in reason[bad].value_counts().items()},
        "first_invalid": None,
    }
    if bad.any():
        first = bad.idxmax()
        report["first_invalid"] = {"csv_line": int(first) + 2, "reason": reason[first]}

    good = df[~bad].copy()
    good["seq"] = seq_num[~bad].astype(int)
    good = good.sort_values("seq", kind="stable").reset_index(drop=True)
    return good, report
