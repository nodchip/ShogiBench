import importlib
import os
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
        """Gmail SMTP は環境変数がそろった場合だけ有効化する。"""
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
