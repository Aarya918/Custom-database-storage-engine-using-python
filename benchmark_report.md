# Write throughput benchmark

- Machine: Linux-6.18.44-fc-v726-x86_64-with-glibc2.39 (1 logical CPUs)
- Python: 3.12.3
- Workload: 3000 sequential unique-key PUTs, value size 100 bytes, memtable_limit 1000
- Metric: completed writes / elapsed seconds (time.perf_counter)
- LevelDB baseline: plyvel, same machine and workload (NOT MEASURED: plyvel is not installed here)

| sync | this engine (writes/s) | LevelDB (writes/s) | LevelDB / engine |
|---|---|---|---|
| True | 6,862 | n/a | n/a |
| False | 89,544 | n/a | n/a |

Target from the PRD: engine within 10x of LevelDB (ratio <= 10x).
