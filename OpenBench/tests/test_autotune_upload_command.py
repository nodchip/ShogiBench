import hashlib
import json
from io import StringIO

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from OpenBench.models import AutotuneUploadCapability


class ConfigureAutotuneUploadTests(TestCase):
    @staticmethod
    def receipt():
        return {
            "schema_version": 1,
            "profile_id": "v4-shogibench-upload-enrollment-v1",
            "token_id": "upload-v1",
            "verifier": make_password("upload-capability"),
            "verifier_algorithm": "pbkdf2_sha256",
            "verifier_iterations": 600000,
            "credential_fingerprint": "a" * 64,
            "logical_target_id": "v4-shogibench-upload-capability",
            "worker_account": "autotune-worker",
            "acl_sha256": "b" * 64,
        }

    def write_receipt(self, tmp_path, value=None):
        path = tmp_path / "receipt.json"
        payload = (json.dumps(value or self.receipt(), sort_keys=True) + "\n").encode()
        path.write_bytes(payload)
        return path, hashlib.sha256(payload).hexdigest()

    def test_command_creates_once_and_accepts_exact_replay(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            path, digest = self.write_receipt(Path(directory))
            created_output = StringIO()
            replay_output = StringIO()

            call_command(
                "configure_autotune_upload",
                receipt_file=path,
                expected_sha256=digest,
                stdout=created_output,
            )
            call_command(
                "configure_autotune_upload",
                receipt_file=path,
                expected_sha256=digest,
                stdout=replay_output,
            )

        self.assertTrue(json.loads(created_output.getvalue())["created"])
        self.assertFalse(json.loads(replay_output.getvalue())["created"])
        self.assertEqual(AutotuneUploadCapability.objects.count(), 1)

    def test_command_rejects_hash_or_existing_state_drift(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            path, digest = self.write_receipt(Path(directory))
            with self.assertRaisesRegex(CommandError, "SHA-256 changed"):
                call_command(
                    "configure_autotune_upload",
                    receipt_file=path,
                    expected_sha256="0" * 64,
                )
            AutotuneUploadCapability.objects.create(
                token_id="other",
                verifier=make_password("other"),
            )
            with self.assertRaisesRegex(CommandError, "state conflicts"):
                call_command(
                    "configure_autotune_upload",
                    receipt_file=path,
                    expected_sha256=digest,
                )
