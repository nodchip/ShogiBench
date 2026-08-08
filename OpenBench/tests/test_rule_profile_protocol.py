from django.contrib.auth.models import User
from django.test import TestCase

from OpenBench.config import OPENBENCH_CONFIG, OPENBENCH_CONFIG_CHECKSUM
from OpenBench.models import Engine, Machine, PGN, Profile, Result, RuleProfile, Test
from OpenBench.rule_profiles import canonical_profile_fields


class RuleProfileProtocolTests(TestCase):

    def setUp(self):
        user = User.objects.create_user(username="worker", password="secret")
        Profile.objects.create(user=user, enabled=True, repos={})
        self.machine = Machine.objects.create(
            user=user,
            secret="machine-secret",
            info={
                "client_ver": OPENBENCH_CONFIG["client_version"],
                "OPENBENCH_CONFIG_CHECKSUM": OPENBENCH_CONFIG_CHECKSUM,
            },
        )
        rule_profile = RuleProfile.objects.create(**canonical_profile_fields())
        engine = Engine.objects.create(
            name="engine",
            source="https://example.invalid/source",
            sha="a" * 40,
            bench=1,
        )
        self.test = Test.objects.create(
            author="operator",
            upload_pgns="FALSE",
            rule_profile=rule_profile,
            book_name="book.epd",
            dev=engine,
            dev_repo="https://example.invalid/dev",
            dev_engine="engine",
            dev_time_control="1.0+0.1",
            base=engine,
            base_repo="https://example.invalid/base",
            base_engine="engine",
            base_time_control="1.0+0.1",
        )
        self.result = Result.objects.create(test=self.test, machine=self.machine)

    def _authentication(self):
        return {
            "machine_id": str(self.machine.id),
            "secret": self.machine.secret,
        }

    def test_heartbeat_rejects_rule_profile_mismatch(self):
        response = self.client.post("/clientHeartbeat/", {
            **self._authentication(),
            "test_id": str(self.test.id),
            "rule_profile_id": "legacy-csarule27-unverified-v1",
            "rule_profile_semantics_sha256": "0" * 64,
        })

        self.assertEqual(response.json(), {"error": "Rule profile mismatch"})

    def test_pgn_rejects_rule_profile_mismatch_before_persistence(self):
        response = self.client.post("/clientSubmitPGN/", {
            **self._authentication(),
            "test_id": str(self.test.id),
            "result_id": str(self.result.id),
            "book_index": "1",
            "rule_profile_id": "legacy-csarule27-unverified-v1",
            "rule_profile_semantics_sha256": "0" * 64,
        })

        self.assertEqual(response.json(), {"error": "Rule profile mismatch"})
        self.assertEqual(PGN.objects.count(), 0)
