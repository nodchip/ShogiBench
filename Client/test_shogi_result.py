import os
import sys
import unittest

CLIENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if CLIENT_DIRECTORY not in sys.path:
    sys.path.insert(0, CLIENT_DIRECTORY)

import shogi_result


class ShogiResultTests(unittest.TestCase):
    """shogitest の完了行から先後別統計を生成できることを確認する。"""

    def assert_counters(self, line, expected):
        """1 対局を反映し、指定外のカウンタが増えていないことを確認する。"""
        finished_game = shogi_result.parse_finished_game(line)
        self.assertIsNotNone(finished_game)

        counters = shogi_result.new_side_stats()
        shogi_result.add_finished_game(counters, finished_game)

        complete_expected = shogi_result.new_side_stats()
        complete_expected.update(expected)
        self.assertEqual(counters, complete_expected)

    def test_counts_each_engine_and_side_result(self):
        """Dev/Base の先後勝ちと引き分けを個別に数える。"""
        cases = [
            (
                "Finished game 1 (A-dev vs B-base): 1-0 "
                "{Sente wins by resignation}",
                {"side_stats_games": 1, "dev_sente_wins": 1},
            ),
            (
                "Finished game 2 (B-base vs A-dev): 0-1 "
                "{Gote wins by impasse}",
                {
                    "side_stats_games": 1,
                    "dev_gote_wins": 1,
                    "dev_gote_impasse_wins": 1,
                },
            ),
            (
                "Finished game 3 (A-dev vs B-base): 1/2-1/2 "
                "{Draw by: repetition}",
                {"side_stats_games": 1, "dev_sente_draws": 1},
            ),
            (
                "Finished game 4 (B-base vs A-dev): 1/2-1/2 {Draw}",
                {"side_stats_games": 1, "dev_gote_draws": 1},
            ),
            (
                "Finished game 5 (B-base vs A-dev): 1-0 "
                "{Sente wins by adjudication}",
                {"side_stats_games": 1, "base_sente_wins": 1},
            ),
            (
                "Finished game 6 (A-dev vs B-base): 0-1 "
                "{Gote wins by resignation}",
                {"side_stats_games": 1, "base_gote_wins": 1},
            ),
            (
                "Finished game 7 (B-base vs A-dev): 1-0 "
                "{Sente wins by impasse}",
                {
                    "side_stats_games": 1,
                    "base_sente_wins": 1,
                    "base_sente_impasse_wins": 1,
                },
            ),
        ]

        for line, expected in cases:
            with self.subTest(line=line):
                self.assert_counters(line, expected)

    def test_adjudication_is_not_an_impasse_declaration(self):
        """adjudication 勝ちは宣言勝ちに含めない。"""
        line = (
            "Finished game 8 (A-dev vs B-base): 1-0 "
            "{Sente wins by adjudication}"
        )
        self.assert_counters(
            line,
            {"side_stats_games": 1, "dev_sente_wins": 1},
        )

    def test_returns_none_for_unrelated_line(self):
        """完了行でない文字列は解析対象外として扱う。"""
        self.assertIsNone(shogi_result.parse_finished_game("Started game 1"))

    def test_rejects_ambiguous_engine_roles(self):
        """Dev と Base を一意に決められない対局を拒否する。"""
        finished_game = shogi_result.parse_finished_game(
            "Finished game 9 (A-dev vs B-dev): 1-0 {Sente wins}"
        )
        counters = shogi_result.new_side_stats()

        with self.assertRaisesRegex(ValueError, "Dev and Base"):
            shogi_result.add_finished_game(counters, finished_game)

        self.assertEqual(counters, shogi_result.new_side_stats())


if __name__ == "__main__":
    unittest.main()
