"""Narrow, additive API for the managed autotune client."""

from __future__ import annotations

import hmac
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from OpenBench.models import AutotuneClientStatus, AutotuneUploadCapability

SCHEMA_VERSION = 1
MANAGED_CLIENT_ID = "autotune-rating-primary"
HEARTBEAT_TIMEOUT_SECONDS = 90
MAX_REQUEST_BYTES = 4096
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ApiRequestError(ValueError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _is_root_owned_systemd_credential(path: Path, metadata: os.stat_result, mode: int) -> bool:
    return (
        path.as_posix().startswith("/run/credentials/")
        and metadata.st_uid == 0
        and metadata.st_gid == 0
        and mode == 0o440
    )


def _error(code: str, status_code: int) -> JsonResponse:
    return JsonResponse(
        {"schema_version": SCHEMA_VERSION, "error": {"code": code}},
        status=status_code,
    )


def _token_from_file(setting_name: str) -> str | None:
    configured = getattr(settings, setting_name, "")
    if not isinstance(configured, str) or not configured:
        return None
    path = Path(configured)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if os.name != "nt":
            metadata = path.stat()
            mode = stat.S_IMODE(metadata.st_mode)
            if mode & 0o077 and not _is_root_owned_systemd_credential(path, metadata, mode):
                return None
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if not token or len(token) > 256 or any(character.isspace() for character in token):
        return None
    return token


def _configured_upload_capability(
    client_token: str | None = None,
    loop_token: str | None = None,
) -> tuple[AutotuneUploadCapability, str, str]:
    if client_token is None:
        client_token = _token_from_file("AUTOTUNE_CLIENT_TOKEN_FILE")
    if loop_token is None:
        loop_token = _token_from_file("AUTOTUNE_LOOP_TOKEN_FILE")
    capabilities = list(AutotuneUploadCapability.objects.filter(enabled=True)[:2])
    try:
        hasher = identify_hasher(capabilities[0].verifier) if len(capabilities) == 1 else None
    except ValueError:
        hasher = None
    if (
        client_token is None
        or loop_token is None
        or hmac.compare_digest(client_token, loop_token)
        or len(capabilities) != 1
        or capabilities[0].scope != "network_upload"
        or capabilities[0].engine != "tanuki-"
        or hasher is None
        or hasher.algorithm != "pbkdf2_sha256"
        or hasher.iterations != 600000
        or check_password(client_token, capabilities[0].verifier)
        or check_password(loop_token, capabilities[0].verifier)
    ):
        raise ApiRequestError("service_unavailable", 503)
    return capabilities[0], client_token, loop_token


def _authorize(request: HttpRequest, setting_name: str) -> None:
    expected = _token_from_file(setting_name)
    other_setting = (
        "AUTOTUNE_LOOP_TOKEN_FILE"
        if setting_name == "AUTOTUNE_CLIENT_TOKEN_FILE"
        else "AUTOTUNE_CLIENT_TOKEN_FILE"
    )
    other = _token_from_file(other_setting)
    _configured_upload_capability(expected, other)
    supplied = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not supplied.startswith(prefix) or not hmac.compare_digest(supplied[len(prefix) :], expected):
        raise ApiRequestError("forbidden", 403)


def _require_method(request: HttpRequest, method: str) -> None:
    if request.method != method:
        raise ApiRequestError("method_not_allowed", 405)


def _json_object(request: HttpRequest, expected_keys: set[str]) -> dict[str, Any]:
    if request.content_type != "application/json":
        raise ApiRequestError("unsupported_media_type", 415)
    try:
        content_length = int(request.headers.get("Content-Length", "0"))
    except ValueError as error:
        raise ApiRequestError("invalid_content_length", 400) from error
    if content_length > MAX_REQUEST_BYTES or len(request.body) > MAX_REQUEST_BYTES:
        raise ApiRequestError("payload_too_large", 413)
    try:
        value = json.loads(request.body)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ApiRequestError("invalid_json", 400) from error
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ApiRequestError("invalid_fields", 400)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ApiRequestError("unsupported_schema", 400)
    if value.get("client_id") != MANAGED_CLIENT_ID:
        raise ApiRequestError("unknown_client", 404)
    return value


def _iso_utc(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


@csrf_exempt
def poll(request: HttpRequest) -> JsonResponse:
    try:
        _require_method(request, "POST")
        _authorize(request, "AUTOTUNE_CLIENT_TOKEN_FILE")
        _json_object(request, {"schema_version", "client_id"})
    except ApiRequestError as error:
        return _error(error.code, error.status_code)
    return JsonResponse({"schema_version": SCHEMA_VERSION, "operation": "no_task"})


@csrf_exempt
def heartbeat(request: HttpRequest) -> JsonResponse:
    keys = {
        "schema_version",
        "client_id",
        "state",
        "current_test_id",
        "origin",
        "last_error",
    }
    try:
        _require_method(request, "POST")
        _authorize(request, "AUTOTUNE_CLIENT_TOKEN_FILE")
        value = _json_object(request, keys)
        if value["state"] not in {
            AutotuneClientStatus.State.IDLE,
            AutotuneClientStatus.State.RUNNING,
            AutotuneClientStatus.State.ERROR,
        }:
            raise ApiRequestError("invalid_state", 400)
        if value["current_test_id"] is not None or value["origin"] is not None:
            raise ApiRequestError("unsupported_workload_state", 400)
        last_error = value["last_error"]
        if last_error is None:
            error_code = ""
            error_message = ""
        elif (
            isinstance(last_error, dict)
            and set(last_error) == {"code", "message"}
            and isinstance(last_error["code"], str)
            and ERROR_CODE_PATTERN.fullmatch(last_error["code"])
            and isinstance(last_error["message"], str)
            and len(last_error["message"]) <= 256
            and "\n" not in last_error["message"]
            and "\r" not in last_error["message"]
        ):
            error_code = last_error["code"]
            error_message = last_error["message"]
        else:
            raise ApiRequestError("invalid_error", 400)
        if value["state"] == AutotuneClientStatus.State.ERROR and not error_code:
            raise ApiRequestError("missing_error", 400)
        if value["state"] != AutotuneClientStatus.State.ERROR and error_code:
            raise ApiRequestError("unexpected_error", 400)
    except ApiRequestError as error:
        return _error(error.code, error.status_code)

    received_at = timezone.now()
    with transaction.atomic():
        client, _ = AutotuneClientStatus.objects.select_for_update().get_or_create(
            client_id=MANAGED_CLIENT_ID
        )
        if client.heartbeat_at is not None and client.heartbeat_at > received_at:
            received_at = client.heartbeat_at
        client.state = value["state"]
        client.heartbeat_at = received_at
        client.current_test_id = None
        client.origin = None
        client.last_error_code = error_code
        client.last_error_message = error_message
        client.save()
    return JsonResponse(
        {
            "schema_version": SCHEMA_VERSION,
            "accepted": True,
            "heartbeat_at": _iso_utc(received_at),
        }
    )


@csrf_exempt
def status(request: HttpRequest, client_id: str) -> JsonResponse:
    try:
        _require_method(request, "GET")
        _authorize(request, "AUTOTUNE_LOOP_TOKEN_FILE")
        if request.body:
            raise ApiRequestError("unexpected_body", 400)
        if client_id != MANAGED_CLIENT_ID:
            raise ApiRequestError("unknown_client", 404)
    except ApiRequestError as error:
        return _error(error.code, error.status_code)

    try:
        client = AutotuneClientStatus.objects.get(client_id=client_id)
    except AutotuneClientStatus.DoesNotExist:
        return _error("unknown_client", 404)
    fresh = bool(
        client.heartbeat_at
        and (timezone.now() - client.heartbeat_at).total_seconds() <= HEARTBEAT_TIMEOUT_SECONDS
    )
    state = client.state if fresh else "stale"
    last_error = None
    if client.last_error_code:
        last_error = {
            "code": client.last_error_code,
            "message": client.last_error_message,
        }
    return JsonResponse(
        {
            "schema_version": SCHEMA_VERSION,
            "client_id": client.client_id,
            "state": state,
            "heartbeat_at": _iso_utc(client.heartbeat_at),
            "fresh": fresh,
            "current_test_id": client.current_test_id,
            "origin": client.origin,
            "last_error": last_error,
        }
    )
