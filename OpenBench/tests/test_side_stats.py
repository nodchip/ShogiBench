from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from OpenBench.models import Engine, Machine, Profile, Result, Test
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
