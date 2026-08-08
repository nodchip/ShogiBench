import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


class FreshAuditTests(TestCase):

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
