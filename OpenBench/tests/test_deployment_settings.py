import importlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

import OpenSite.settings as project_settings


class DeploymentSettingsTests(SimpleTestCase):
    """本番起動に必要な Django 設定を確認する。"""

    def test_whitenoise_middleware_follows_security_middleware(self):
        """WhiteNoise は SecurityMiddleware の直後で有効化する。"""
        middleware = list(settings.MIDDLEWARE)

        self.assertIn("django.middleware.security.SecurityMiddleware", middleware)
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", middleware)

        security_index = middleware.index("django.middleware.security.SecurityMiddleware")
        whitenoise_index = middleware.index("whitenoise.middleware.WhiteNoiseMiddleware")

        self.assertEqual(security_index + 1, whitenoise_index)

    def test_static_root_is_configured(self):
        """collectstatic の出力先が設定されている。"""
        self.assertTrue(settings.STATIC_ROOT)

    def test_gmail_smtp_is_configured_from_environment(self):
        """移行中は従来の環境変数をfallbackとして利用できる。"""
        with patch.dict(
            os.environ,
            {
                "GMAIL_USER": "sender@example.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ):
            reloaded_settings = importlib.reload(project_settings)

        self.assertEqual(reloaded_settings.EMAIL_BACKEND, "django.core.mail.backends.smtp.EmailBackend")
        self.assertEqual(reloaded_settings.EMAIL_HOST, "smtp.gmail.com")
        self.assertEqual(reloaded_settings.EMAIL_PORT, 587)
        self.assertTrue(reloaded_settings.EMAIL_USE_TLS)
        self.assertEqual(reloaded_settings.EMAIL_HOST_USER, "sender@example.com")
        self.assertEqual(reloaded_settings.EMAIL_HOST_PASSWORD, "app-password")
        self.assertEqual(reloaded_settings.DEFAULT_FROM_EMAIL, "sender@example.com")

        importlib.reload(project_settings)

    def test_gmail_smtp_prefers_systemd_credential(self):
        """systemd credentialがある場合は環境変数より優先する。"""
        with tempfile.TemporaryDirectory() as credential_directory:
            Path(credential_directory, "gmail-app-password").write_text(
                "file-app-password\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "CREDENTIALS_DIRECTORY": credential_directory,
                    "GMAIL_USER": "sender@example.com",
                    "GMAIL_APP_PASSWORD": "environment-app-password",
                },
            ):
                reloaded_settings = importlib.reload(project_settings)

            self.assertEqual(
                reloaded_settings.EMAIL_HOST_PASSWORD,
                "file-app-password",
            )

        importlib.reload(project_settings)
