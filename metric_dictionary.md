# Metric dictionary

All figures are computed from the results CSV written by `run_workload.py`
(columns: `seq, op, key, value, timestamp, latency_us, dataset_size`).

| Metric | Definition / formula | Where | Use |
|---|---|---|---|
| Read count | number of `GET` operations | `analysis/metrics.py::distribution` | understand read load |
| Write count | number of `PUT` + `DELETE` operations | same | understand write load |
| Read/write ratio | `read_count / write_count` (`N/A` if there are no writes) | same | characterise the workload |
| Operation distribution | `100 * count(op) / total_ops` for each of GET, PUT, DELETE, overall and per window (`N/A` if the workload is empty) | `distribution`, `window_distribution` | spot bursts and shifts |
| Read % / Write % | `100 * read_count / total_ops`, `100 * write_count / total_ops` | `distribution` | summary line |
| Dataset size | distinct live keys **just before** the operation runs: `PUT` adds a key, `DELETE` removes it | `run_workload.py::replay` | x-axis of the latency plot |
| Query response time | wall-clock time of one engine call, `(t_end - t_start) * 1e6` microseconds, using `time.perf_counter` | `run_workload.py::replay` | latency per operation |
| p50 / p95 read latency | median and 95th percentile of `latency_us` over `GET` rows in a dataset-size bucket | `latency_by_bucket` | show read slowdown as SSTables accumulate |
| Dataset-size bucket | `bucket_start = (dataset_size // width) * width`; width is `--bucket-width` or about `max_size / 10` | same | grouping for the plot |
| Write throughput | `completed_writes / elapsed_seconds` | `benchmark.py` | compare with LevelDB |
| Recovery rate | `acknowledged writes present after restart / acknowledged writes` (target 100%) | `tests/test_crash.py` | durability |

An operation is *acknowledged* only after `put()`/`delete()` has returned, which happens after the WAL
record was appended and (when `sync=True`) fsynced.

## Validation rules (Rule 6)
- `op` must be `GET`, `PUT` or `DELETE` (case-insensitive, trimmed); `seq` must be an integer;
  `key` must be non-empty; a `PUT` row needs a value; a non-empty `timestamp` must parse.
- Invalid rows are excluded, counted, and the first one is reported with its CSV line number.
