import io
from contextlib import redirect_stdout
from types import SimpleNamespace

from django.test import SimpleTestCase

from Scripts.safe_output import bounded_safe_message, report_response


class CreateTestOutputSafetyTests(SimpleTestCase):

    def test_known_credential_is_redacted_and_output_is_bounded(self):
        marker = "never-print-this-password"

        result = bounded_safe_message(
            "prefix %s %s" % (marker, "x" * 5000),
            (marker,),
        )

        self.assertNotIn(marker, result)
        self.assertIn("[REDACTED]", result)
        self.assertEqual(len(result), 4096)

    def test_normal_message_is_preserved(self):
        self.assertEqual(
            bounded_safe_message("Test created", ("unused-password",)),
            "Test created",
        )

    def test_complete_debug_response_body_is_not_printed(self):
        marker = "never-print-this-password"
        response = SimpleNamespace(
            status_code=500,
            text="<html>debug body %s</html>" % marker,
            raise_for_status=lambda: None,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            report_response(response, (marker,))

        self.assertEqual(output.getvalue(), "Code  : 500\n")
        self.assertNotIn(marker, output.getvalue())

    def test_extracted_error_message_is_credential_redacted(self):
        marker = "never-print-this-password"
        response = SimpleNamespace(
            status_code=400,
            text=(
                '<div class="error-message"><pre>bad credential %s</pre></div>'
                % marker
            ),
            raise_for_status=lambda: None,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            report_response(response, (marker,))

        self.assertNotIn(marker, output.getvalue())
        self.assertIn("[REDACTED]", output.getvalue())
