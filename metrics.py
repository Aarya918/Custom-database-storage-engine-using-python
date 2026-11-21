"""Read/write distributions and latency-vs-dataset-size aggregation (see docs/metric_dictionary.md)."""
import math

import pandas as pd

NA = "N/A"
OPS = ["GET", "PUT", "DELETE"]


def distribution(df):
    """Overall operation counts and percentages. Zero denominators give 'N/A'."""
    counts = {op: int((df["op"] == op).sum()) for op in OPS}
    total = sum(counts.values())
    reads = counts["GET"]
    writes = counts["PUT"] + counts["DELETE"]
    return {
        "total_ops": total,
        "counts": counts,
        "read_count": reads,
        "write_count": writes,
        "read_pct": round(100.0 * reads / total, 1) if total else NA,
        "write_pct": round(100.0 * writes / total, 1) if total else NA,
        "op_pct": {op: (round(100.0 * n / total, 1) if total else NA) for op, n in counts.items()},
        "read_write_ratio": round(reads / writes, 3) if writes else NA,
    }


def window_distribution(df, window="1min", window_ops=1000):
    """Per time-window counts when a timestamp column exists, else per block of N operations."""
    if df.empty:
        return pd.DataFrame(columns=["window"] + OPS + ["total"] + [f"{o.lower()}_pct" for o in OPS])
    work = df[["op"]].copy()
    ts = pd.to_datetime(df["timestamp"], errors="coerce") if "timestamp" in df.columns else None
    if ts is not None and ts.notna().all():
        work["window"] = ts.dt.floor(window).astype(str)
    else:
        work["window"] = [f"ops {(i // window_ops) * window_ops + 1}-{(i // window_ops + 1) * window_ops}"
                          for i in range(len(work))]
    table = (work.groupby(["window", "op"], sort=False).size().unstack(fill_value=0)
             .reindex(columns=OPS, fill_value=0))
    table["total"] = table.sum(axis=1)
    for op in OPS:
        table[f"{op.lower()}_pct"] = (100.0 * table[op] / table["total"]).round(1)
    return table.reset_index()


def auto_bucket_width(max_size, target_buckets=10):
    if max_size <= 0:
        return 1
    raw = max_size / target_buckets
    if raw <= 10:
        return max(1, math.ceil(raw))
    return int(math.ceil(raw / 10.0) * 10)


def latency_by_bucket(df, bucket_width=None):
    """p50 / p95 GET latency per fixed-width dataset_size bucket."""
    cols = ["bucket_start", "bucket_end", "reads", "p50_us", "p95_us"]
    reads = df[df["op"] == "GET"]
    if reads.empty:
        return pd.DataFrame(columns=cols), bucket_width or 1
    width = bucket_width or auto_bucket_width(int(reads["dataset_size"].max()))
    work = reads.assign(bucket_start=(reads["dataset_size"] // width) * width)
    grouped = work.groupby("bucket_start")["latency_us"]
    out = pd.DataFrame({
        "reads": grouped.size(),
        "p50_us": grouped.quantile(0.50),
        "p95_us": grouped.quantile(0.95),
    }).reset_index()
    out["bucket_end"] = out["bucket_start"] + width
    return out[cols].round(2), width


def load_results(path):
    """Read a results CSV written by run_workload.py and check the measured columns."""
    from lsm.errors import WorkloadFormatError
    import os
    if not os.path.isfile(path):
        raise WorkloadFormatError(f"results file not found: {path}")
    try:
        df = pd.read_csv(path, dtype={"key": str, "value": str}, keep_default_na=False)
    except Exception as exc:
        raise WorkloadFormatError(f"cannot parse {path}: {exc}") from exc
    missing = [c for c in ("op", "latency_us", "dataset_size") if c not in df.columns]
    if missing:
        raise WorkloadFormatError(
            f"results file lacks column(s) {', '.join(missing)}; produce it with run_workload.py")
    df["op"] = df["op"].astype(str).str.upper()
    df["latency_us"] = pd.to_numeric(df["latency_us"], errors="coerce")
    df["dataset_size"] = pd.to_numeric(df["dataset_size"], errors="coerce")
    bad = df["latency_us"].isna() | df["dataset_size"].isna()
    if bad.any():
        first = int(bad.idxmax()) + 2
        raise WorkloadFormatError(f"non-numeric latency_us or dataset_size (first at CSV line {first})")
    return df
