"""Bounded response reporting for credential-bearing ShogiBench scripts."""

import html
import re


def bounded_safe_message(message, credential_values, maximum_length=4096):
    """Return one bounded response message with known credentials removed."""

    safe = html.unescape(message)
    for value in credential_values:
        if value:
            safe = safe.replace(value, "[REDACTED]")
    return safe.strip()[:maximum_length]


def report_response(response, credential_values):
    """Print only bounded status/error messages, never the complete body."""

    print("Code  : %s" % (response.status_code))

    pattern = r'<div class="error-message">\s*<pre>(.*?)</pre>\s*</div>'
    if matches := re.findall(pattern, response.text, re.DOTALL):
        print("Error : %s" % bounded_safe_message(matches[0], credential_values))

    pattern = r'<div class="status-message">\s*<pre>(.*?)</pre>\s*</div>'
    if matches := re.findall(pattern, response.text, re.DOTALL):
        print("Status: %s" % bounded_safe_message(matches[0], credential_values))

    response.raise_for_status()
