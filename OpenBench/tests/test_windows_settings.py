import importlib
import json
import os
import sys
import tempfile
from contextlib import ExitStack
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
                'rating_game_budgets': {'acceptance': 2},
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
        self.assertEqual(windows.AUTOTUNE_RATING_GAME_BUDGETS, {'acceptance': 2})
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
                'rating_game_budgets': {},
                'django_signing_key_path': str(secret.resolve()),
                'training_artifact_root': str(artifacts.resolve()),
                'unexpected': True,
            }), encoding='utf-8')

            with patch.dict(os.environ, {'SHOGIBENCH_LOCAL_CONFIG_PATH': str(config.resolve())}):
                sys.modules.pop('OpenSite.settings_windows', None)
                with self.assertRaisesMessage(RuntimeError, 'unexpected properties'):
                    importlib.import_module('OpenSite.settings_windows')

    def _import_with_artifact_probe_denied(self, argv, prevalidated=None):
        stack = ExitStack()
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
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
            'rating_game_budgets': {'acceptance': 2},
            'django_signing_key_path': str(secret.resolve()),
            'training_artifact_root': str(artifacts.resolve()),
        }), encoding='utf-8')
        real_is_symlink = Path.is_symlink

        def is_symlink(path):
            if path == artifacts.resolve():
                raise PermissionError('fixture protected artifact root')
            return real_is_symlink(path)

        stack.enter_context(patch.dict(os.environ, {
            'SHOGIBENCH_LOCAL_CONFIG_PATH': str(config.resolve()),
            'SHOGIBENCH_AUDIT_PREVALIDATED_ARTIFACT_ROOT': (
                str(artifacts.resolve()) if prevalidated is None else prevalidated
            ),
        }, clear=True))
        stack.enter_context(patch.object(sys, 'argv', argv))
        stack.enter_context(
            patch.object(Path, 'is_symlink', autospec=True, side_effect=is_symlink)
        )
        self.addCleanup(stack.close)
        sys.modules.pop('OpenSite.settings_windows', None)
        return importlib.import_module('OpenSite.settings_windows'), artifacts.resolve()

    def test_acceptance_audit_can_use_exact_prevalidated_artifact_root(self):
        windows, artifacts = self._import_with_artifact_probe_denied([
            'D:/service/deployment/manage.py',
            'audit_fresh_server',
            'acceptance',
        ])

        self.assertEqual(windows.AUTOTUNE_TRAINING_ARTIFACT_ROOT, str(artifacts))

    def test_prevalidated_artifact_root_does_not_bypass_service_probe(self):
        with self.assertRaises(PermissionError):
            self._import_with_artifact_probe_denied([
                'D:/service/deployment/manage.py',
                'runserver',
            ])

    def test_prevalidated_artifact_root_must_match_config_exactly(self):
        with self.assertRaises(PermissionError):
            self._import_with_artifact_probe_denied([
                'D:/service/deployment/manage.py',
                'audit_fresh_server',
                'acceptance',
            ], prevalidated='D:/different')
