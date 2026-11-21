# Demo script (about 5 minutes)

1. **Problem (30 s).** Engineers use LevelDB/RocksDB as black boxes. We built an LSM-Tree of roughly 600 lines so every part is readable.
2. **Design (1 min).** Show the diagrams in the README: write path (WAL, then memtable, flush to SSTable) and read path (memtable, then newest to oldest SSTable).
3. **Live demo (2 min).** Run `python demo.py`: put/get/delete, flush and compaction, then a real `SIGKILL` and recovery with 100% of acknowledged writes present.
4. **Durability approach (30 s).** WAL before acknowledgement, temp file + fsync + atomic rename, WAL truncated only after the SSTable and manifest are durable, orphan files removed at startup.
5. **Results (1 min).** Show `results/mixed/latency_vs_dataset_size.png` (read latency grows as SSTables accumulate) and `results/mixed_compacted/` (compaction brings it back down). Show `python -m unittest` output including the SIGKILL test.
6. **Trade-offs (30 s).** `sync=True` is safe but slow, `sync=False` is fast but can lose the last writes on power loss; more SSTables mean cheaper writes but costlier reads; compaction pays CPU and I/O to fix reads.
