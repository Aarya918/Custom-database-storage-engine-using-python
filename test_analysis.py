import os
import shutil
import tempfile
import unittest

import pandas as pd

from analysis import metrics
from analysis.workload import load_workload
from lsm import LSMStore, WorkloadFormatError
from run_workload import replay

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "data", "sample_workload.csv")


class WorkloadValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, text):
        p = os.path.join(self.tmp, "w.csv")
        open(p, "w").write(text)
        return p

    def test_sample_loads_cleanly(self):
        df, report = load_workload(SAMPLE)
        self.assertEqual((report["valid_rows"], report["excluded_rows"]), (6, 0))

    def test_invalid_rows_excluded_counted_and_first_reported(self):
        p = self.write("seq,op,key,value,timestamp\n"
                       "1,PUT,a,x,2026-10-01T10:00:00\n"
                       "2,UPDATE,a,x,2026-10-01T10:00:01\n"
                       "3,PUT,,x,2026-10-01T10:00:02\n"
                       "4,PUT,b,,2026-10-01T10:00:03\n"
                       "5,GET,a,,2026-10-01T10:00:04\n"
                       "six,GET,a,,2026-10-01T10:00:05\n"
                       "7,GET,a,,not-a-date\n")
        df, report = load_workload(p)
        self.assertEqual(report["valid_rows"], 2)
        self.assertEqual(report["excluded_rows"], 5)
        self.assertEqual(report["first_invalid"]["csv_line"], 3)
        self.assertEqual(sum(report["reasons"].values()), 5)

    def test_missing_columns_and_missing_file(self):
        with self.assertRaises(WorkloadFormatError):
            load_workload(self.write("seq,op\n1,GET\n"))
        with self.assertRaises(WorkloadFormatError):
            load_workload(os.path.join(self.tmp, "nope.csv"))

    def test_timestamp_column_is_optional(self):
        df, report = load_workload(self.write("seq,op,key,value\n1,PUT,a,x\n2,GET,a,\n"))
        self.assertEqual(report["valid_rows"], 2)


class ReplayAndMetrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_sample_replay_gives_expected_state(self):
        df, _ = load_workload(SAMPLE)
        with LSMStore(os.path.join(self.tmp, "db")) as store:
            result = replay(df, store)
            self.assertEqual(store.get("user:1001"), "alice_v2")
            self.assertIsNone(store.get("user:1002"))
        self.assertEqual(list(result["dataset_size"]), [0, 1, 2, 2, 2, 1])
        self.assertTrue((result["latency_us"] > 0).all())

    def test_distribution_matches_prd_example(self):
        df, _ = load_workload(SAMPLE)
        d = metrics.distribution(df)
        self.assertEqual(d["total_ops"], 6)
        self.assertEqual(d["counts"], {"GET": 2, "PUT": 3, "DELETE": 1})
        self.assertEqual((d["read_pct"], d["write_pct"]), (33.3, 66.7))

    def test_empty_workload_is_na_not_a_crash(self):
        d = metrics.distribution(pd.DataFrame({"op": []}))
        self.assertEqual((d["read_pct"], d["write_pct"], d["read_write_ratio"]), ("N/A", "N/A", "N/A"))

    def test_no_writes_gives_na_ratio(self):
        d = metrics.distribution(pd.DataFrame({"op": ["GET", "GET"]}))
        self.assertEqual(d["read_write_ratio"], "N/A")

    def test_window_distribution_by_time_and_by_ops(self):
        df, _ = load_workload(SAMPLE)
        w = metrics.window_distribution(df, "1min")
        self.assertEqual(int(w["total"].sum()), 6)
        w2 = metrics.window_distribution(df.drop(columns=["timestamp"]), window_ops=4)
        self.assertEqual(list(w2["total"]), [4, 2])

    def test_latency_buckets_and_edge_cases(self):
        df = pd.DataFrame({"op": ["GET"] * 6, "dataset_size": [0, 5, 9, 10, 15, 19],
                           "latency_us": [1, 2, 3, 10, 20, 30]})
        table, width = metrics.latency_by_bucket(df, bucket_width=10)
        self.assertEqual(list(table["bucket_start"]), [0, 10])
        self.assertEqual(list(table["p50_us"]), [2.0, 20.0])
        empty, _ = metrics.latency_by_bucket(pd.DataFrame({"op": ["PUT"], "dataset_size": [1],
                                                           "latency_us": [1.0]}))
        self.assertTrue(empty.empty)

    def test_results_file_validation(self):
        p = os.path.join(self.tmp, "r.csv")
        open(p, "w").write("seq,op,key\n1,GET,a\n")
        with self.assertRaises(WorkloadFormatError):
            metrics.load_results(p)


if __name__ == "__main__":
    unittest.main()
