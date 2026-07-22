import io
import os
import queue
import sys
import threading
import types
import unittest
from unittest.mock import patch

CLIENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if CLIENT_DIRECTORY not in sys.path:
    sys.path.insert(0, CLIENT_DIRECTORY)

import shogi_result
import worker


class WorkerSideStatsTests(unittest.TestCase):
    """worker が先後別統計を収集・送信できることを確認する。"""

    def make_results(self, include_side_stats=True):
        """MatchRunner が更新する最小の結果辞書を生成する。"""
        results = {
            "trinomial": [0, 0, 0],
            "pentanomial": [0, 0, 0, 0, 0],
            "games": {},
            "crashes": 0,
            "timelosses": 0,
            "illegals": 0,
        }
        if include_side_stats:
            results.update(shogi_result.new_side_stats())
        return results

    def make_batch(self, **side_stats):
        """ServerReporter に渡す 1 pair 分の結果を生成する。"""
        batch = {
            "trinomial": [0, 1, 1],
            "pentanomial": [0, 0, 0, 1, 0],
            "crashes": 0,
            "timelosses": 0,
            "illegals": 0,
            "runner_idx": 0,
        }
        if side_stats:
            batch.update(shogi_result.new_side_stats())
            batch.update(side_stats)
        return batch

    def make_config(self, test_type="GAMES"):
        """report_results に必要な workload 設定を生成する。"""
        return types.SimpleNamespace(
            workload={
                "test": {"id": 10, "type": test_type},
                "result": {"id": 20},
            }
        )

    def test_update_results_counts_pair_and_side_statistics(self):
        """従来の pair 統計と先後別統計を同時に更新する。"""
        results = self.make_results()

        worker.MatchRunner.update_results(
            results,
            "Finished game 1 (A-dev vs B-base): 1-0 "
            "{Sente wins by resignation}",
            is_shogi=True,
        )
        worker.MatchRunner.update_results(
            results,
            "Finished game 2 (B-base vs A-dev): 1/2-1/2 "
            "{Draw by: repetition}",
            is_shogi=True,
        )

        self.assertEqual(results["trinomial"], [0, 1, 1])
        self.assertEqual(results["pentanomial"], [0, 0, 0, 1, 0])
        self.assertEqual(results["side_stats_games"], 2)
        self.assertEqual(results["dev_sente_wins"], 1)
        self.assertEqual(results["dev_gote_draws"], 1)

    def test_side_parse_failure_keeps_legacy_result(self):
        """role 解析失敗時も従来の結果とエラー数を失わない。"""
        results = self.make_results()

        with patch("builtins.print") as output:
            worker.MatchRunner.update_results(
                results,
                "Finished game 1 (A-dev vs B-dev): 1-0 "
                "{Sente wins by disconnect}",
                is_shogi=True,
            )

        self.assertEqual(results["games"], {1: "1-0"})
        self.assertEqual(results["crashes"], 1)
        self.assertEqual(results["side_stats_games"], 0)
        self.assertTrue(any("side statistics" in str(call) for call in output.call_args_list))

    def test_side_parse_failure_for_pair_keeps_legacy_pair_result(self):
        """pair の両局で role 解析に失敗しても従来の pair 結果を残す。"""
        results = self.make_results()

        with patch("builtins.print"):
            worker.MatchRunner.update_results(
                results,
                "Finished game 1 (A-dev vs B-dev): 1-0 {Sente wins}",
                is_shogi=True,
            )
            worker.MatchRunner.update_results(
                results,
                "Finished game 2 (B-dev vs A-dev): 0-1 {Gote wins}",
                is_shogi=True,
            )

        self.assertEqual(sum(results["trinomial"]), 2)
        self.assertEqual(sum(results["pentanomial"]), 1)
        self.assertEqual(results["side_stats_games"], 0)

    def test_runner_enqueues_side_stats_only_for_shogi(self):
        """SHOGI の pair だけ追加カウンタを queue へ含める。"""
        output = (
            b"Finished game 1 (A-dev vs B-base): 1-0 {Sente wins}\n"
            b"Finished game 2 (B-base vs A-dev): 0-1 {Gote wins}\n"
        )

        for book_name, expected_side_stats in (
            ("sample-shogi.epd", True),
            ("sample-chess.epd", False),
        ):
            with self.subTest(book_name=book_name):
                config = types.SimpleNamespace(
                    workload={"test": {"book": {"name": book_name}}}
                )
                result_queue = queue.Queue()
                process = types.SimpleNamespace(stdout=io.BytesIO(output))

                with patch.object(worker, "Popen", return_value=process):
                    worker.run_and_parse_runner(
                        config,
                        "runner --games 2",
                        0,
                        result_queue,
                        threading.Event(),
                    )

                batch = result_queue.get_nowait()
                self.assertEqual("side_stats_games" in batch, expected_side_stats)
                if expected_side_stats:
                    self.assertEqual(batch["side_stats_games"], 2)
                    self.assertEqual(batch["dev_sente_wins"], 1)
                    self.assertEqual(batch["dev_gote_wins"], 1)

    def test_runner_batches_side_stats_by_completed_pair(self):
        """並行対局の完了順が前後しても完成 pair だけを batch に含める。"""
        output = (
            b"Finished game 1 (A-dev vs B-base): 1-0 {Sente wins}\n"
            b"Finished game 3 (A-dev vs B-base): 1-0 {Sente wins}\n"
            b"Finished game 2 (B-base vs A-dev): 0-1 {Gote wins}\n"
            b"Finished game 4 (B-base vs A-dev): 0-1 {Gote wins}\n"
        )
        config = types.SimpleNamespace(
            workload={"test": {"book": {"name": "sample-shogi.epd"}}}
        )
        result_queue = queue.Queue()
        process = types.SimpleNamespace(stdout=io.BytesIO(output))

        with patch.object(worker, "Popen", return_value=process):
            worker.run_and_parse_runner(
                config,
                "runner --games 4",
                0,
                result_queue,
                threading.Event(),
            )

        batches = [result_queue.get_nowait(), result_queue.get_nowait()]
        self.assertTrue(result_queue.empty())
        for batch in batches:
            self.assertEqual(sum(batch["trinomial"]), 2)
            self.assertEqual(batch["side_stats_games"], 2)

    def test_duplicate_finished_game_does_not_duplicate_side_statistics(self):
        """同じ対局の完了行が再出力されても先後統計を二重計上しない。"""
        output = (
            b"Finished game 1 (A-dev vs B-base): 1-0 {Sente wins}\n"
            b"Finished game 1 (A-dev vs B-base): 1-0 {Sente wins}\n"
            b"Finished game 2 (B-base vs A-dev): 0-1 {Gote wins}\n"
        )
        config = types.SimpleNamespace(
            workload={"test": {"book": {"name": "sample-shogi.epd"}}}
        )
        result_queue = queue.Queue()
        process = types.SimpleNamespace(stdout=io.BytesIO(output))

        with patch.object(worker, "Popen", return_value=process):
            worker.run_and_parse_runner(
                config,
                "runner --games 2",
                0,
                result_queue,
                threading.Event(),
            )

        batch = result_queue.get_nowait()
        self.assertTrue(result_queue.empty())
        self.assertEqual(sum(batch["trinomial"]), 2)
        self.assertEqual(batch["side_stats_games"], 2)

    def test_report_results_sums_side_statistics(self):
        """複数 pair の先後別カウンタを整数のまま合算して送る。"""
        batches = [
            self.make_batch(side_stats_games=2, dev_sente_wins=1, dev_gote_draws=1),
            self.make_batch(side_stats_games=2, base_sente_wins=1, dev_sente_draws=1),
        ]

        with patch.object(worker.ServerReporter, "report") as report:
            worker.ServerReporter.report_results(self.make_config(), batches)

        payload = report.call_args.args[2]
        self.assertEqual(payload["side_stats_games"], 4)
        self.assertEqual(payload["dev_sente_wins"], 1)
        self.assertEqual(payload["base_sente_wins"], 1)
        self.assertEqual(payload["dev_sente_draws"], 1)
        self.assertEqual(payload["dev_gote_draws"], 1)
        self.assertIsInstance(payload["side_stats_games"], int)

    def test_report_results_omits_side_statistics_for_chess(self):
        """追加カウンタを持たない CHESS batch では protocol を変えない。"""
        with patch.object(worker.ServerReporter, "report") as report:
            worker.ServerReporter.report_results(
                self.make_config(),
                [self.make_batch()],
            )

        payload = report.call_args.args[2]
        for field in shogi_result.SIDE_STAT_FIELDS:
            self.assertNotIn(field, payload)


if __name__ == "__main__":
    unittest.main()
