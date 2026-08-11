import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


class WindowsSettingsTests(SimpleTestCase):

    def test_source_default_signing_key_is_explicitly_non_secret(self):
        from OpenSite import settings

        self.assertEqual(
            settings.SECRET_KEY,
            'insecure-development-only-not-a-deployment-secret',
        )

    def test_windows_settings_are_non_debug_http_and_file_backed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / 'signing-key'
            secret.write_text('s' * 64, encoding='utf-8')
            config = root / 'local.json'
            artifacts = root / 'artifacts'
            artifacts.mkdir()
            config.write_text(json.dumps({
                'schema_version': 1,
                'profile_id': 'shogibench-windows-v1',
                'autotune_username': 'autotune',
                'rating_policies': {'acceptance': {'workload_size': 2}},
                'django_signing_key_path': str(secret.resolve()),
                'training_artifact_root': str(artifacts.resolve()),
            }), encoding='utf-8')

            with patch.dict(os.environ, {'SHOGIBENCH_LOCAL_CONFIG_PATH': str(config.resolve())}):
                sys.modules.pop('OpenSite.settings_windows', None)
                windows = importlib.import_module('OpenSite.settings_windows')

        self.assertFalse(windows.DEBUG)
        self.assertEqual(windows.ALLOWED_HOSTS, ['*'])
        self.assertEqual(windows.CSRF_TRUSTED_ORIGINS, [])
        self.assertEqual(windows.EMAIL_BACKEND, 'django.core.mail.backends.dummy.EmailBackend')
        self.assertEqual(windows.SECRET_KEY, 's' * 64)
        self.assertEqual(windows.AUTOTUNE_USERNAME, 'autotune')
        self.assertEqual(windows.AUTOTUNE_TRAINING_ARTIFACT_ROOT, str(artifacts.resolve()))

    def test_windows_settings_reject_unknown_local_property(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / 'signing-key'
            secret.write_text('s' * 64, encoding='utf-8')
            config = root / 'local.json'
            artifacts = root / 'artifacts'
            artifacts.mkdir()
            config.write_text(json.dumps({
                'schema_version': 1,
                'profile_id': 'shogibench-windows-v1',
                'autotune_username': 'autotune',
                'rating_policies': {},
                'django_signing_key_path': str(secret.resolve()),
                'training_artifact_root': str(artifacts.resolve()),
                'unexpected': True,
            }), encoding='utf-8')

            with patch.dict(os.environ, {'SHOGIBENCH_LOCAL_CONFIG_PATH': str(config.resolve())}):
                sys.modules.pop('OpenSite.settings_windows', None)
                with self.assertRaisesMessage(RuntimeError, 'unexpected properties'):
                    importlib.import_module('OpenSite.settings_windows')
