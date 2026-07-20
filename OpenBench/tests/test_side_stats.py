from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from OpenBench import side_stats
from OpenBench.models import Engine, Machine, Profile, Result, Test
from OpenBench.templatetags.mytags import longStatBlock, shortStatBlock
from OpenBench.utils import update_test


SIDE_STAT_FIELDS = (
    "side_stats_games",
    "dev_sente_wins",
    "dev_gote_wins",
    "base_sente_wins",
    "base_gote_wins",
    "dev_sente_draws",
    "dev_gote_draws",
    "dev_sente_impasse_wins",
    "dev_gote_impasse_wins",
    "base_sente_impasse_wins",
    "base_gote_impasse_wins",
)


class SideStatsIngestionTests(TestCase):
    """先後別統計の protocol 検証と永続化を確認する。"""

    def setUp(self):
        """update_test() を実行する最小の workload を作成する。"""
        self.factory = RequestFactory()
        self.worker = User.objects.create_user(username="worker", password="secret")
        Profile.objects.create(user=self.worker, enabled=True, repos={})
        self.dev = Engine.objects.create(
            name="dev",
            source="https://example.com/dev.zip",
            sha="a" * 40,
            bench=111,
        )
        self.base = Engine.objects.create(
            name="base",
            source="https://example.com/base.zip",
            sha="b" * 40,
            bench=222,
        )
        self.machine = Machine.objects.create(
            user=self.worker,
            info={"concurrency": 1, "physical_cores": 1, "sockets": 1},
        )
        self.test = Test.objects.create(
            author="author",
            book_name="sample-shogi.epd",
            upload_pgns="FALSE",
            dev=self.dev,
            dev_repo="https://example.com/dev",
            dev_engine="tanuki-",
            dev_options="Threads=1 Hash=16",
            dev_network="",
            dev_time_control="8.0+0.08",
            base=self.base,
            base_repo="https://example.com/base",
            base_engine="tanuki-",
            base_options="Threads=1 Hash=16",
            base_network="",
            base_time_control="8.0+0.08",
            test_mode="GAMES",
            max_games=100,
        )
        self.result = Result.objects.create(test=self.test, machine=self.machine)

    def valid_side_payload(self):
        """2 対局で Dev が先後それぞれ勝った妥当な payload を返す。"""
        payload = {field: "0" for field in SIDE_STAT_FIELDS}
        payload.update(
            side_stats_games="2",
            dev_sente_wins="1",
            dev_gote_wins="1",
        )
        return payload

    def post_update(self, side_payload=None, trinomial="0 0 2"):
        """指定した先後別統計を既存の結果報告に付加して送る。"""
        payload = {
            "crashes": "0",
            "timelosses": "0",
            "illegals": "0",
            "machine_id": str(self.machine.id),
            "result_id": str(self.result.id),
            "test_id": str(self.test.id),
            "trinomial": trinomial,
            "pentanomial": "0 0 0 0 1",
        }
        if side_payload is not None:
            payload.update(side_payload)
        request = self.factory.post("/clientSubmitResults/", payload)
        return update_test(request, self.machine)

    def assert_database_unchanged(self):
        """validation error 後に集計値が更新されていないことを確認する。"""
        self.test.refresh_from_db()
        self.result.refresh_from_db()
        self.assertEqual(self.test.games, 0)
        self.assertEqual(self.result.games, 0)
        for field in SIDE_STAT_FIELDS:
            self.assertEqual(getattr(self.test, field), 0)
            self.assertEqual(getattr(self.result, field), 0)

    def test_persists_valid_side_stats_on_test_and_result(self):
        """妥当なカウンタを Test と Result の両方へ累積する。"""
        response = self.post_update(self.valid_side_payload())

        self.assertEqual(response, {})
        self.test.refresh_from_db()
        self.result.refresh_from_db()
        for target in (self.test, self.result):
            self.assertEqual(target.side_stats_games, 2)
            self.assertEqual(target.dev_sente_wins, 1)
            self.assertEqual(target.dev_gote_wins, 1)
            self.assertEqual(target.base_sente_wins, 0)

    def test_accepts_legacy_worker_without_side_fields(self):
        """旧 worker の payload を受理し、詳細カウンタを 0 のまま保つ。"""
        response = self.post_update()

        self.assertEqual(response, {})
        self.test.refresh_from_db()
        self.result.refresh_from_db()
        self.assertEqual(self.test.games, 2)
        self.assertEqual(self.result.games, 2)
        for field in SIDE_STAT_FIELDS:
            self.assertEqual(getattr(self.test, field), 0)
            self.assertEqual(getattr(self.result, field), 0)

    def test_rejects_partial_side_payload_without_updates(self):
        """一部の field しかない新 protocol payload を拒否する。"""
        response = self.post_update({"side_stats_games": "2"})

        self.assertIn("error", response)
        self.assert_database_unchanged()

    def test_rejects_invalid_side_values_without_updates(self):
        """負数・非整数・内訳不整合・過剰 coverage を拒否する。"""
        invalid_payloads = []

        negative = self.valid_side_payload()
        negative["dev_sente_wins"] = "-1"
        invalid_payloads.append(negative)

        non_integer = self.valid_side_payload()
        non_integer["dev_sente_wins"] = "one"
        invalid_payloads.append(non_integer)

        mismatch = self.valid_side_payload()
        mismatch["dev_gote_wins"] = "0"
        invalid_payloads.append(mismatch)

        excessive_coverage = self.valid_side_payload()
        excessive_coverage.update(
            side_stats_games="3",
            base_sente_wins="1",
        )
        invalid_payloads.append(excessive_coverage)

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.post_update(payload)
                self.assertIn("error", response)
                self.assert_database_unchanged()

    def test_rejects_impasse_count_above_corresponding_wins(self):
        """対応する勝ち数を超える宣言勝ち数を拒否する。"""
        payload = self.valid_side_payload()
        payload["dev_sente_impasse_wins"] = "2"

        response = self.post_update(payload)

        self.assertIn("error", response)
        self.assert_database_unchanged()


class SideStatsFormattingTests(TestCase):
    """Long Stat Block 用の先後別統計表示を確認する。"""

    def make_test(self):
        """承認済み表示例と同じ完全な将棋統計を生成する。"""
        test = Test(
            author="author",
            book_name="sample-shogi.epd",
            test_mode="GAMES",
            dev_options="Threads=1 Hash=16",
            dev_time_control="8.0+0.08",
            max_games=1000,
            use_penta=True,
            games=1000,
            wins=510,
            losses=440,
            draws=50,
            LL=50,
            LD=90,
            DD=125,
            DW=135,
            WW=100,
            side_stats_games=1000,
            dev_sente_wins=270,
            dev_gote_wins=240,
            base_sente_wins=235,
            base_gote_wins=205,
            dev_sente_draws=25,
            dev_gote_draws=25,
            dev_sente_impasse_wins=2,
            dev_gote_impasse_wins=1,
            base_sente_impasse_wins=1,
            base_gote_impasse_wins=0,
        )
        return test

    def clear_side_stats(self, test):
        """表示境界ケース用に全カウンタを 0 へ戻す。"""
        for field in SIDE_STAT_FIELDS:
            setattr(test, field, 0)

    def test_formats_complete_side_statistics(self):
        """承認済みの Long Stat Block 追加部分を固定幅で生成する。"""
        expected = "\n".join([
            "Side results",
            "Sente  | W: 505/1000 (50.5%)",
            "Gote   | W: 445/1000 (44.5%)",
            "Draw   | D:  50/1000 ( 5.0%)",
            "",
            "Engine results",
            "Engine | Overall W        | Sente W         | Gote W          | Draw S/G",
            "Dev    | 510/1000 (51.0%) | 270/500 (54.0%) | 240/500 (48.0%) | 25 / 25",
            "Base   | 440/1000 (44.0%) | 235/500 (47.0%) | 205/500 (41.0%) | 25 / 25",
            "",
            "Impasse declarations",
            "Total  | 4  (Sente: 3, Gote: 1)",
            "Dev    | 3  (Sente: 2, Gote: 1)",
            "Base   | 1  (Sente: 1, Gote: 0)",
        ])

        self.assertEqual(side_stats.format_side_stats(self.make_test()), expected)

    def test_partial_coverage_uses_detailed_game_denominator(self):
        """一部取得時は coverage を示し、割合の分母を詳細対局数にする。"""
        test = self.make_test()
        self.clear_side_stats(test)
        test.side_stats_games = 800
        test.dev_sente_wins = 200
        test.dev_gote_wins = 200
        test.base_sente_wins = 180
        test.base_gote_wins = 170
        test.dev_sente_draws = 25
        test.dev_gote_draws = 25

        output = side_stats.format_side_stats(test)

        self.assertTrue(output.startswith("Side stats coverage | N: 800/1000 (partial)\n"))
        self.assertIn("Sente  | W: 380/800 (47.5%)", output)

    def test_legacy_worker_data_is_marked_unavailable(self):
        """対局済みで coverage 0 の将棋 workload は旧データと表示する。"""
        test = self.make_test()
        self.clear_side_stats(test)

        self.assertEqual(
            side_stats.format_side_stats(test),
            "Side stats | unavailable (legacy worker data)",
        )

    def test_zero_engine_side_denominator_is_na(self):
        """エンジンが一度も持っていない側の割合を N/A とする。"""
        test = self.make_test()
        self.clear_side_stats(test)
        test.games = 1
        test.side_stats_games = 1
        test.dev_sente_wins = 1

        output = side_stats.format_side_stats(test)

        self.assertIn("0/0 (N/A)", output)

    def test_omits_side_stats_for_non_shogi_and_empty_workloads(self):
        """非将棋または対局数 0 の workload には追加表示しない。"""
        non_shogi = self.make_test()
        non_shogi.book_name = "startpos.epd"
        empty_shogi = self.make_test()
        empty_shogi.games = 0
        empty_shogi.side_stats_games = 0

        self.assertEqual(side_stats.format_side_stats(non_shogi), "")
        self.assertEqual(side_stats.format_side_stats(empty_shogi), "")

    def test_only_long_stat_block_contains_side_statistics(self):
        """Long Stat Block だけへ追加し、Short Stat Block を変えない。"""
        test = self.make_test()

        self.assertIn("Side results", longStatBlock(test))
        self.assertNotIn("Side results", shortStatBlock(test))
