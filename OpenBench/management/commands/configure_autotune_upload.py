from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from django.contrib.auth.hashers import identify_hasher
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from OpenBench.models import AutotuneUploadCapability

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TOKEN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RECEIPT_KEYS = {
    "schema_version",
    "profile_id",
    "token_id",
    "verifier",
    "verifier_algorithm",
    "verifier_iterations",
    "credential_fingerprint",
    "logical_target_id",
    "worker_account",
    "acl_sha256",
}


def _load_receipt(path: Path, expected_sha256: str):
    if not HASH_PATTERN.fullmatch(expected_sha256):
        raise CommandError("expected receipt SHA-256 is invalid")
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            raise CommandError("enrollment receipt is unsafe")
        payload = path.read_bytes()
    except OSError as error:
        raise CommandError("enrollment receipt is unavailable") from error
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise CommandError("enrollment receipt SHA-256 changed")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CommandError("enrollment receipt is invalid JSON") from error
    if not isinstance(value, dict) or set(value) != RECEIPT_KEYS:
        raise CommandError("enrollment receipt contract changed")
    if (
        value.get("schema_version") != 1
        or value.get("profile_id") != "v4-shogibench-upload-enrollment-v1"
        or value.get("logical_target_id") != "v4-shogibench-upload-capability"
        or value.get("worker_account") != "autotune-worker"
        or value.get("verifier_algorithm") != "pbkdf2_sha256"
        or value.get("verifier_iterations") != 600000
        or not TOKEN_ID_PATTERN.fullmatch(str(value.get("token_id", "")))
        or not HASH_PATTERN.fullmatch(str(value.get("credential_fingerprint", "")))
        or not HASH_PATTERN.fullmatch(str(value.get("acl_sha256", "")))
    ):
        raise CommandError("enrollment receipt values changed")
    try:
        hasher = identify_hasher(value.get("verifier", ""))
    except ValueError as error:
        raise CommandError("enrollment verifier is invalid") from error
    if hasher.algorithm != "pbkdf2_sha256" or hasher.iterations != 600000:
        raise CommandError("enrollment verifier contract changed")
    return value


class Command(BaseCommand):
    help = "Create the single V4 upload capability from a hash-pinned enrollment receipt"

    def add_arguments(self, parser):
        parser.add_argument("--receipt-file", type=Path, required=True)
        parser.add_argument("--expected-sha256", required=True)

    def handle(self, *args, **options):
        receipt = _load_receipt(options["receipt_file"], options["expected_sha256"])
        expected = {
            "token_id": receipt["token_id"],
            "verifier": receipt["verifier"],
            "enabled": True,
            "scope": "network_upload",
            "engine": "tanuki-",
        }
        with transaction.atomic():
            capabilities = list(AutotuneUploadCapability.objects.select_for_update())
            if not capabilities:
                capability = AutotuneUploadCapability.objects.create(**expected)
                created = True
            elif len(capabilities) == 1 and all(
                getattr(capabilities[0], key) == value for key, value in expected.items()
            ):
                capability = capabilities[0]
                created = False
            else:
                raise CommandError("upload capability state conflicts with enrollment")
        self.stdout.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "token_id": capability.token_id,
                    "credential_fingerprint": receipt["credential_fingerprint"],
                    "created": created,
                },
                sort_keys=True,
            )
        )
