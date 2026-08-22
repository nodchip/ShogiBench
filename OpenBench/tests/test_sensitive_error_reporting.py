import sys

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.views.debug import technical_500_response

from OpenSite.exception_filter import (
    CredentialSafeExceptionReporter,
    CredentialSafeExceptionReporterFilter,
)


POSTED_PASSWORD_FIXTURE = "never-render-this-password"


def raise_with_password_local():
    password = POSTED_PASSWORD_FIXTURE
    raise RuntimeError("bounded fixture failure")


class SensitiveErrorReportingTests(SimpleTestCase):

    def test_filter_redacts_credential_keys_but_preserves_normal_fields(self):
        marker = "never-render-this-password"
        request = RequestFactory().post(
            "/scripts/",
            {
                "username": "bounded-user",
                "password": marker,
                "api_token": "never-render-this-token",
                "action": "CREATE_TEST",
            },
        )

        filtered = CredentialSafeExceptionReporterFilter().get_post_parameters(request)

        self.assertEqual(filtered["username"], "bounded-user")
        self.assertEqual(filtered["action"], "CREATE_TEST")
        self.assertNotEqual(filtered["password"], marker)
        self.assertNotIn("never-render-this-token", filtered["api_token"])

    @override_settings(DEBUG=True)
    def test_debug_500_page_never_contains_posted_password(self):
        request = RequestFactory().post(
            "/scripts/",
            {"username": "bounded-user", "password": POSTED_PASSWORD_FIXTURE},
        )
        request.exception_reporter_filter = CredentialSafeExceptionReporterFilter()
        request.exception_reporter_class = CredentialSafeExceptionReporter

        try:
            raise_with_password_local()
        except RuntimeError:
            response = technical_500_response(request, *sys.exc_info())

        body = response.content.decode("utf-8")
        self.assertNotIn(POSTED_PASSWORD_FIXTURE, body)
        self.assertIn("bounded-user", body)
