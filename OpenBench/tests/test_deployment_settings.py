from django.conf import settings
from django.test import SimpleTestCase


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
