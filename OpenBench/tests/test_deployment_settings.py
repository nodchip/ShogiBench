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

    def test_debug_is_disabled_by_default(self):
        """明示的なlocal debug opt-inがなければdebug pageを返さない。"""
        with patch.dict(os.environ, {"SHOGIBENCH_DEBUG": ""}):
            reloaded_settings = importlib.reload(project_settings)

        self.assertFalse(reloaded_settings.DEBUG)
        importlib.reload(project_settings)

    def test_exception_reporting_uses_credential_safe_components(self):
        self.assertEqual(
            settings.DEFAULT_EXCEPTION_REPORTER_FILTER,
            "OpenSite.exception_filter.CredentialSafeExceptionReporterFilter",
        )
        self.assertEqual(
            settings.DEFAULT_EXCEPTION_REPORTER,
            "OpenSite.exception_filter.CredentialSafeExceptionReporter",
        )

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

    def test_gmail_password_environment_is_rejected(self):
        """旧password環境変数へfallbackせずfail closedにする。"""
        with patch.dict(
            os.environ,
            {
                "CREDENTIALS_DIRECTORY": "",
                "GMAIL_USER": "sender@example.com",
                "GMAIL_APP_PASSWORD": "environment-app-password",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "Gmail credential is unavailable"):
                importlib.reload(project_settings)

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
            self.assertEqual(reloaded_settings.EMAIL_HOST, "smtp.gmail.com")
            self.assertEqual(reloaded_settings.EMAIL_PORT, 587)
            self.assertTrue(reloaded_settings.EMAIL_USE_TLS)
            self.assertEqual(reloaded_settings.EMAIL_HOST_USER, "sender@example.com")
            self.assertEqual(reloaded_settings.DEFAULT_FROM_EMAIL, "sender@example.com")

        importlib.reload(project_settings)
