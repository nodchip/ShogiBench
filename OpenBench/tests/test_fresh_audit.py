import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from OpenBench.management.commands.audit_fresh_server import Command


class FreshAuditTests(TestCase):

    @staticmethod
    def _seed_counts(**overrides):
        counts = {
            "users": 3,
            "profiles": 3,
            "tests": 0,
            "results": 0,
            "machines": 0,
            "engines": 1,
            "networks": 1,
            "books": 1,
            "pgn_records": 0,
            "log_events": 0,
            "rule_profiles": 1,
        }
        counts.update(overrides)
        return counts

    def test_zero_phase_passes_on_empty_database_and_media(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            output = io.StringIO()
            call_command("audit_fresh_server", "zero", stdout=output)

        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(sum(receipt["counts"].values()), 0)
        self.assertEqual(receipt["media_file_count"], 0)

    def test_zero_phase_rejects_media_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "legacy").write_bytes(b"legacy")
            output = io.StringIO()
            with override_settings(MEDIA_ROOT=directory), self.assertRaises(CommandError):
                call_command("audit_fresh_server", "zero", stdout=output)

        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["error"], "legacy_or_existing_state_present")
        self.assertFalse(receipt["confidential_values_emitted"])

    def test_acceptance_allows_registered_candidate_networks(self):
        command = Command()
        command._canonical_exact = lambda: True
        command._autotune_bounded = lambda: True
        counts = self._seed_counts(networks=2, tests=1, machines=1, log_events=1)

        self.assertIsNone(command._validate("acceptance", counts, media_file_count=3))

    def test_acceptance_allows_registered_candidate_engines(self):
        command = Command()
        command._canonical_exact = lambda: True
        command._autotune_bounded = lambda: True
        counts = self._seed_counts(engines=2)

        self.assertIsNone(command._validate("acceptance", counts, media_file_count=2))

    def test_bootstrap_still_requires_exactly_one_seed_network(self):
        command = Command()
        command._canonical_exact = lambda: True
        command._autotune_bounded = lambda: True
        counts = self._seed_counts(networks=2)

        self.assertEqual(
            command._validate("bootstrap", counts, media_file_count=3),
            "minimal_seed_count_mismatch",
        )

    def test_bootstrap_still_requires_exactly_one_seed_engine(self):
        command = Command()
        command._canonical_exact = lambda: True
        command._autotune_bounded = lambda: True
        counts = self._seed_counts(engines=2)

        self.assertEqual(
            command._validate("bootstrap", counts, media_file_count=2),
            "minimal_seed_count_mismatch",
        )

    def test_acceptance_still_requires_a_seed_network(self):
        command = Command()
        command._canonical_exact = lambda: True
        command._autotune_bounded = lambda: True
        counts = self._seed_counts(networks=0)

        self.assertEqual(
            command._validate("acceptance", counts, media_file_count=1),
            "minimal_seed_count_mismatch",
        )
