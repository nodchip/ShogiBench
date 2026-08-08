import os
import sys
import types
import unittest
from unittest.mock import patch

CLIENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if CLIENT_DIRECTORY not in sys.path:
    sys.path.insert(0, CLIENT_DIRECTORY)

import worker


class WorkerBookTests(unittest.TestCase):

    def test_shogi_runner_requires_and_forwards_canonical_rule_profile(self):
        config = types.SimpleNamespace(
            workload={
                "test": {
                    "book": {"name": "SHOGI.startpos.sfen.epd"},
                    "rule_profile_id": "canonical-yaneuraou-csarule24-v1",
                    "rule_profile_semantics_sha256": (
                        "be4a1cff6b5bf416f89f9ed17bc70676f9272bf32fd27dd373b8fb4d8d997a93"
                    ),
                }
            }
        )

        self.assertEqual(
            worker.MatchRunner.rule_profile_settings(config),
            "-ruleprofile canonical-yaneuraou-csarule24-v1",
        )
        config.workload["test"]["rule_profile_id"] = "legacy-csarule27-unverified-v1"
        with self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
            worker.MatchRunner.rule_profile_settings(config)
        config.workload["test"]["rule_profile_id"] = "canonical-yaneuraou-csarule24-v1"
        config.workload["test"]["rule_profile_semantics_sha256"] = "0" * 64
        with self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
            worker.MatchRunner.rule_profile_settings(config)
    def make_benchmark_config(self):
        return types.SimpleNamespace(
            threads=64,
            workload={
                "test": {
                    "id": 1,
                    "dev": {
                        "name": "dev-engine",
                        "private": False,
                        "bench": "123",
                    }
                }
            },
        )

    def test_engine_settings_adds_bookfile_and_bookonthefly(self):
        config = types.SimpleNamespace(
            syzygy_max=0,
            workload={
                "test": {
                    "type": "GAMES",
                    "syzygy_wdl": "DISABLED",
                    "book": {"name": "startpos.epd"},
                    "dev": {
                        "options": "Threads=1 Hash=16",
                        "network": "",
                        "private": False,
                        "engine": "tanuki-",
                        "book": "ABCDEF12",
                        "book_name": "dev-book.db",
                        "time_control": "8.0+0.08",
                    },
                }
            },
        )

        with patch.object(worker, "scale_time_control", return_value="tc"):
            command = worker.MatchRunner.engine_settings(config, "engine.exe", "dev", 1.0, 0)

        normalized = command.replace("\\", "/")
        self.assertIn(
            "option.BookFile=ABCDEF12",
            normalized,
        )
        self.assertIn("option.BookDir=../Books", normalized)
        self.assertNotIn("option.BookOnTheFly=", normalized)

    def test_safe_download_engine_book_uses_books_api(self):
        config = types.SimpleNamespace(
            server="https://example.com",
            username="tester",
            password="secret",
            workload={
                "test": {
                    "dev": {
                        "engine": "tanuki-",
                        "book": "ABCDEF12",
                        "book_name": "dev-book.db",
                    }
                }
            },
        )

        with patch.object(worker.utils, "download_book") as download_book:
            book_path = worker.safe_download_engine_book(config, "dev")

        self.assertEqual(book_path, os.path.join("Books", "ABCDEF12"))
        download_book.assert_called_once_with(
            "https://example.com",
            "tester",
            "secret",
            "tanuki-",
            "dev-book.db",
            "ABCDEF12",
            os.path.join("Books", "ABCDEF12"),
        )

    def test_safe_run_benchmarks_warms_up_before_full_benchmark(self):
        config = self.make_benchmark_config()

        with patch.object(worker.bench, "run_benchmark", side_effect=[(100, 123), (1000, 123)]) as run_benchmark:
            speed = worker.safe_run_benchmarks(config, "dev", "engine.exe", None)

        self.assertEqual(speed, 1000)
        self.assertEqual(run_benchmark.call_args_list[0].args, (
            os.path.join("Engines", "engine.exe"),
            None,
            False,
            1,
            1,
            123,
        ))
        self.assertEqual(run_benchmark.call_args_list[1].args, (
            os.path.join("Engines", "engine.exe"),
            None,
            False,
            64,
            1,
        ))
        self.assertEqual(
            run_benchmark.call_args_list[1].kwargs,
            {"enforce_node_consistency": False},
        )

    def test_full_capacity_benchmark_allows_divergent_nodes_after_serial_validation(self):
        with patch.object(
            worker.bench,
            "multi_core_bench",
            return_value=[(472847, 1000), (472848, 900)],
        ):
            with self.assertRaises(worker.utils.OpenBenchBadBenchException):
                worker.bench.run_benchmark(
                    "engine.exe", None, False, 2, 1, 472847,
                )

            speed, nodes = worker.bench.run_benchmark(
                "engine.exe", None, False, 2, 1,
                enforce_node_consistency=False,
            )

        self.assertEqual(speed, 950)
        self.assertEqual(nodes, 472847)

    def test_full_capacity_benchmark_still_rejects_missing_output(self):
        with patch.object(
            worker.bench,
            "multi_core_bench",
            return_value=[(None, 1000), (472847, 900)],
        ):
            with self.assertRaises(worker.utils.OpenBenchBadBenchException):
                worker.bench.run_benchmark(
                    "engine.exe", None, False, 2, 1,
                    enforce_node_consistency=False,
                )

    def test_safe_run_benchmarks_retries_timeout_once_with_warmup(self):
        config = self.make_benchmark_config()
        timeout = worker.utils.OpenBenchBadBenchException(
            "[Engines\\engine.exe] Bench Exceeded Max Duration"
        )

        with patch.object(worker.bench, "run_benchmark", side_effect=[
            (100, 123),
            timeout,
            (110, 123),
            (1000, 123),
        ]) as run_benchmark:
            with patch.object(worker.ServerReporter, "report_bad_bench") as report_bad_bench:
                speed = worker.safe_run_benchmarks(config, "dev", "engine.exe", None)

        self.assertEqual(speed, 1000)
        self.assertEqual(run_benchmark.call_args_list[0].args[3], 1)
        self.assertEqual(run_benchmark.call_args_list[1].args[3], 64)
        self.assertEqual(run_benchmark.call_args_list[2].args[3], 1)
        self.assertEqual(run_benchmark.call_args_list[3].args[3], 64)
        report_bad_bench.assert_not_called()

    def test_safe_run_benchmarks_does_not_retry_non_timeout_error(self):
        config = self.make_benchmark_config()
        wrong_bench = worker.utils.OpenBenchBadBenchException(
            "[engine.exe] Wrong Bench: 456"
        )

        with patch.object(worker.bench, "run_benchmark", side_effect=[wrong_bench]) as run_benchmark:
            with patch.object(worker.ServerReporter, "report_bad_bench") as report_bad_bench:
                with self.assertRaises(worker.utils.OpenBenchBadBenchException):
                    worker.safe_run_benchmarks(config, "dev", "engine.exe", None)

        self.assertEqual(run_benchmark.call_count, 1)
        report_bad_bench.assert_called_once_with(config, "[engine.exe] Wrong Bench: 456")


if __name__ == "__main__":
    unittest.main()
