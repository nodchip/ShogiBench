"""Exception reporting that remains credential-safe in local debug mode."""

import html

from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter


CREDENTIAL_KEY_FRAGMENTS = (
    "authorization",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)


def _is_credential_key(key):
    normalized = str(key).casefold()
    return any(fragment in normalized for fragment in CREDENTIAL_KEY_FRAGMENTS)


class CredentialSafeExceptionReporterFilter(SafeExceptionReporterFilter):
    """Redact credential-like POST fields regardless of Django DEBUG state."""

    def is_active(self, request):
        return True

    def get_post_parameters(self, request):
        if request is None:
            return {}

        cleansed = request.POST.copy()
        for key in cleansed:
            if _is_credential_key(key):
                cleansed[key] = self.cleansed_substitute
        return cleansed

    def get_traceback_frame_variables(self, request, tb_frame):
        variables = super().get_traceback_frame_variables(request, tb_frame)
        return [
            (name, self.cleansed_substitute if _is_credential_key(name) else value)
            for name, value in variables
        ]


class CredentialSafeExceptionReporter(ExceptionReporter):
    """Remove submitted credential values from complete HTML and text reports."""

    def _credential_values(self):
        request = self.request
        if request is None:
            return ()

        values = []
        for key in request.POST:
            if _is_credential_key(key):
                values.extend(value for value in request.POST.getlist(key) if value)
        return tuple(values)

    def _redact(self, report):
        variants = set()
        for value in self._credential_values():
            variants.update(
                {
                    value,
                    html.escape(value),
                    repr(value),
                    html.escape(repr(value)),
                }
            )
        for value in sorted(variants, key=len, reverse=True):
            if value:
                report = report.replace(value, SafeExceptionReporterFilter.cleansed_substitute)
        return report

    def get_traceback_html(self):
        return self._redact(super().get_traceback_html())

    def get_traceback_text(self):
        return self._redact(super().get_traceback_text())
