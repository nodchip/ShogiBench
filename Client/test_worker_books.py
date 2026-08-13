import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
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
            blacklist=[],
            workload={
                "test": {
                    "id": 1,
                    "dev": {
                        "name": "dev-engine",
                        "private": False,
                        "bench": "123",
                        "build": {},
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
                        "build": {},
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

    def test_public_external_network_is_forwarded_as_evaldir(self):
        config = types.SimpleNamespace(
            syzygy_max=0,
            workload={"test": {
                "type": "GAMES",
                "syzygy_wdl": "DISABLED",
                "book": {"name": "startpos.epd"},
                "dev": {
                    "options": "Threads=1 Hash=16",
                    "network": "ABCDEF12",
                    "private": False,
                    "engine": "tanuki-",
                    "build": {"network": {
                        "mode": "external_directory",
                        "option": "EvalDir",
                        "filename": "nn.bin",
                    }},
                    "book": "",
                    "book_name": "",
                    "time_control": "8.0+0.08",
                },
            }},
        )

        with patch.object(worker, "scale_time_control", return_value="tc"):
            command = worker.MatchRunner.engine_settings(
                config, "engine.exe", "dev", 1.0, 0,
            )

        self.assertIn(
            "option.EvalDir=../Networks/ABCDEF12.eval",
            command.replace("\\", "/"),
        )

    def test_tanuki_build_command_matches_canonical_external_eval_recipe(self):
        build = {
            "path": "source",
            "command": {
                "jobs": 64,
                "target": "normal",
                "arguments": [
                    "YANEURAOU_EDITION=YANEURAOU_ENGINE_NNUE_SFNNwoP1536",
                    "TARGET_CPU=AVX2",
                    "COMPILER=clang++",
                    "EVAL_EMBEDDING=OFF",
                ],
            },
        }

        command = worker.utils.makefile_command(
            "Networks/ABCDEF12.eval", "source", "engine.exe", "clang++", build,
        )

        self.assertEqual(command, [
            "make", "-j64", "normal",
            "YANEURAOU_EDITION=YANEURAOU_ENGINE_NNUE_SFNNwoP1536",
            "TARGET_CPU=AVX2", "COMPILER=clang++", "EVAL_EMBEDDING=OFF",
            "EXE=engine.exe",
        ])
        self.assertFalse(any(item.startswith("EVALFILE=") for item in command))

    def test_public_binary_cache_identity_includes_recipe_but_not_network_bytes(self):
        build = {
            "path": "source",
            "command": {
                "jobs": 64,
                "target": "normal",
                "arguments": ["TARGET_CPU=AVX2", "EVAL_EMBEDDING=OFF"],
            },
            "network": {
                "mode": "external_directory",
                "option": "EvalDir",
                "filename": "nn.bin",
            },
        }
        canonical = worker.utils.engine_binary_name(
            "tanuki-", "fca519e70db42a0882213dcc279caf962fe85774", None, False, build,
        )
        same_recipe = worker.utils.engine_binary_name(
            "tanuki-", "fca519e70db42a0882213dcc279caf962fe85774", None, False, build,
        )
        changed = {**build, "command": {**build["command"], "jobs": 32}}
        changed_recipe = worker.utils.engine_binary_name(
            "tanuki-", "fca519e70db42a0882213dcc279caf962fe85774", None, False, changed,
        )

        self.assertEqual(canonical, same_recipe)
        self.assertRegex(canonical, r"^tanuki--FCA519E7-B[0-9A-F]{8}$")
        self.assertNotEqual(canonical, changed_recipe)

    def test_public_external_network_is_sent_to_bench_over_stdin(self):
        captured = {}

        class Process:
            def communicate(self, *, input):
                captured["input"] = input
                return b"Nodes searched : 472847\nNodes/second : 1000\n", None

        class Queue:
            def put(self, value):
                captured["value"] = value

        with patch.object(worker.bench.subprocess, "Popen", return_value=Process()):
            worker.bench.single_core_bench(
                "engine.exe", "Networks/ABCDEF12.eval", False, "EvalDir", None, Queue(),
            )

        self.assertEqual(
            captured["input"],
            b"setoption name EvalDir value Networks/ABCDEF12.eval\nbench\nquit\n",
        )
        self.assertEqual(captured["value"], (472847, 1000))

    def test_public_bench_forces_canonical_pv_interval_after_evaldir(self):
        captured = {}

        class Process:
            def communicate(self, *, input):
                captured["input"] = input
                return b"Nodes searched : 472847\nNodes/second : 1000\n", None

        class Queue:
            def put(self, value):
                captured["value"] = value

        with patch.object(worker.bench.subprocess, "Popen", return_value=Process()):
            worker.bench.single_core_bench(
                "engine.exe",
                "Networks/ABCDEF12.eval",
                False,
                "EvalDir",
                {"PvInterval": "100000000"},
                Queue(),
            )

        self.assertEqual(
            captured["input"],
            (
                b"setoption name EvalDir value Networks/ABCDEF12.eval\n"
                b"setoption name PvInterval value 100000000\nbench\nquit\n"
            ),
        )
        self.assertEqual(captured["value"], (472847, 1000))

    def test_public_external_network_is_staged_as_same_file_nn_bin(self):
        config = types.SimpleNamespace(
            server="https://example.com",
            username="tester",
            password="secret",
            workload={"test": {"dev": {
                "engine": "tanuki-",
                "netname": "candidate",
                "network": "ABCDEF12",
                "build": {"network": {
                    "mode": "external_directory",
                    "option": "EvalDir",
                    "filename": "nn.bin",
                }},
            }}},
        )

        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                Path("Networks").mkdir()

                def download(*arguments):
                    Path(arguments[-1]).write_bytes(b"network")

                with patch.object(worker.utils, "download_network", side_effect=download):
                    runtime = worker.safe_download_network_weights(config, "dev")

                source = Path("Networks", "ABCDEF12")
                staged = Path(runtime, "nn.bin")
                self.assertTrue(Path(runtime).is_absolute())
                self.assertTrue(os.path.samefile(source, staged))
            finally:
                os.chdir(previous)

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
            123,
        ))
        self.assertIsNone(run_benchmark.call_args_list[0].kwargs["network_option"])

    def test_safe_run_benchmarks_uses_declared_public_network_option(self):
        config = self.make_benchmark_config()
        config.workload["test"]["dev"]["build"] = {
            "network": {"option": "EvalDir"},
            "benchmark_options": {"PvInterval": "100000000"},
        }

        with patch.object(
            worker.bench, "run_benchmark", side_effect=[(100, 123), (1000, 123)],
        ) as run_benchmark:
            worker.safe_run_benchmarks(
                config, "dev", "engine.exe", "Networks/ABCDEF12.eval",
            )

        self.assertEqual(
            run_benchmark.call_args_list[0].kwargs["network_option"], "EvalDir",
        )
        self.assertEqual(
            run_benchmark.call_args_list[1].kwargs["network_option"], "EvalDir",
        )
        self.assertEqual(
            run_benchmark.call_args_list[0].kwargs["benchmark_options"],
            {"PvInterval": "100000000"},
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

        with patch.object(worker.bench, "run_benchmark", side_effect=[(100, 123), wrong_bench]) as run_benchmark:
            with patch.object(worker.ServerReporter, "report_bad_bench") as report_bad_bench:
                with self.assertRaises(worker.utils.OpenBenchBadBenchException):
                    worker.safe_run_benchmarks(config, "dev", "engine.exe", None)

        self.assertEqual(run_benchmark.call_count, 2)
        report_bad_bench.assert_called_once_with(config, "[engine.exe] Wrong Bench: 456")
        self.assertEqual(config.blacklist, [1])

    def test_safe_run_benchmarks_quarantines_unexpected_output_failure(self):
        config = self.make_benchmark_config()

        with patch.object(
            worker.bench, "run_benchmark", side_effect=ValueError("unparseable output"),
        ):
            with patch.object(worker.ServerReporter, "report_bad_bench") as report_bad_bench:
                with self.assertRaisesRegex(
                    worker.utils.OpenBenchBadBenchException,
                    "Failed to Execute Benchmark",
                ):
                    worker.safe_run_benchmarks(config, "dev", "engine.exe", None)

        report_bad_bench.assert_called_once_with(
            config, "[engine.exe] Failed to Execute Benchmark",
        )
        self.assertEqual(config.blacklist, [1])

    def test_bad_bench_report_failure_keeps_local_quarantine(self):
        config = self.make_benchmark_config()
        wrong_bench = worker.utils.OpenBenchBadBenchException(
            "[engine.exe] Wrong Bench: 456"
        )

        with patch.object(worker.bench, "run_benchmark", side_effect=wrong_bench):
            with patch.object(
                worker.ServerReporter,
                "report_bad_bench",
                side_effect=OSError("server unavailable"),
            ):
                with self.assertRaises(worker.utils.OpenBenchBadBenchException):
                    worker.safe_run_benchmarks(config, "dev", "engine.exe", None)

        self.assertEqual(config.blacklist, [1])

    def test_report_nps_includes_owned_test_id(self):
        config = self.make_benchmark_config()
        with patch.object(worker.ServerReporter, "report") as report:
            worker.ServerReporter.report_nps(config, 100, 200)

        self.assertEqual(report.call_args.args[1], "clientSubmitNPS")
        self.assertEqual(report.call_args.args[2]["test_id"], 1)


if __name__ == "__main__":
    unittest.main()
