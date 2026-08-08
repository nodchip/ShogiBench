import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from OpenBench.models import Book, Engine, Network, Profile, RuleProfile


class FreshBootstrapTests(TestCase):

    def _write_inputs(self, root):
        network = root / "network.bin"
        book = root / "book.epd"
        password = root / "worker-password"
        network.write_bytes(b"network material")
        book.write_bytes(b"book material")
        password.write_text("Worker-bootstrap-password-4321!", encoding="utf-8")
        network_hash = hashlib.sha256(network.read_bytes()).hexdigest()[:8]
        book_hash = hashlib.sha256(book.read_bytes()).hexdigest()[:8]
        config = {
            "schema_version": 1,
            "profile_id": "shogibench-fresh-bootstrap-v1",
            "operator_username": "operator",
            "worker_username": "worker",
            "worker_password_file": str(password),
            "autotune_username": "autotune",
            "engine": {
                "name": "tanuki-",
                "source": "https://example.invalid/engine",
                "sha": "a" * 40,
                "bench": 1,
            },
            "network": {
                "sha256": network_hash,
                "name": "network.bin",
                "engine": "tanuki-",
                "source_file": str(network),
            },
            "books": [{
                "sha256": book_hash,
                "name": "book.epd",
                "engine": "tanuki-",
                "source_file": str(book),
            }],
        }
        config_path = root / "bootstrap.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path, config

    def test_bootstraps_exact_minimal_server_without_emitting_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "Media"
            config_path, config = self._write_inputs(root)
            output = io.StringIO()
            with override_settings(MEDIA_ROOT=media), patch(
                "getpass.getpass", return_value="Operator-bootstrap-password-1234!",
            ):
                call_command("bootstrap_fresh_server", config=str(config_path), stdout=output)

            receipt = json.loads(output.getvalue())
            self.assertEqual(receipt["status"], "bootstrapped")
            self.assertTrue(receipt["secret_values_emitted"] is False)
            self.assertNotIn("Operator-bootstrap", output.getvalue())
            self.assertNotIn("Worker-bootstrap", output.getvalue())
            self.assertEqual(User.objects.count(), 3)
            self.assertEqual(Profile.objects.filter(approver=True).count(), 1)
            self.assertFalse(User.objects.get(username="autotune").has_usable_password())
            self.assertEqual(RuleProfile.objects.count(), 1)
            self.assertEqual(Engine.objects.count(), 1)
            self.assertEqual(Network.objects.count(), 1)
            self.assertEqual(Book.objects.count(), 1)
            self.assertTrue((media / config["network"]["sha256"]).is_file())
            self.assertTrue((media / config["books"][0]["sha256"]).is_file())

    def test_rejects_non_fresh_database_without_additional_mutation(self):
        User.objects.create_user(username="existing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, _ = self._write_inputs(root)
            output = io.StringIO()
            with override_settings(MEDIA_ROOT=root / "Media"), self.assertRaises(CommandError):
                call_command("bootstrap_fresh_server", config=str(config_path), stdout=output)

        self.assertEqual(json.loads(output.getvalue())["error"], "database_not_fresh")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(RuleProfile.objects.count(), 0)

    def test_rejects_non_fresh_media_without_database_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "Media"
            media.mkdir()
            (media / "legacy.bin").write_bytes(b"legacy")
            config_path, _ = self._write_inputs(root)
            output = io.StringIO()
            with override_settings(MEDIA_ROOT=media), self.assertRaises(CommandError):
                call_command("bootstrap_fresh_server", config=str(config_path), stdout=output)

        self.assertEqual(json.loads(output.getvalue())["error"], "media_not_fresh")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(RuleProfile.objects.count(), 0)
