"""Minimal polling client for the versioned autotune API."""

from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
MANAGED_CLIENT_ID = "autotune-rating-primary"
HEARTBEAT_INTERVAL_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 65536
MAX_BACKOFF_SECONDS = 60


class ClientConfigurationError(ValueError):
    """Static client configuration is unsafe or unsupported."""


class FatalClientError(RuntimeError):
    """The client must stop instead of retrying a policy or contract failure."""


class TransientClientError(RuntimeError):
    """A bounded retry may recover this network or server failure."""


@dataclass(frozen=True)
class ClientConfig:
    server_url: str
    client_id: str
    credential_file: Path


def _validate_server_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ClientConfigurationError(
            "server_url must not contain credentials, path, query, or fragment"
        )
    if parsed.scheme == "https" and parsed.netloc:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return value.rstrip("/")
    raise ClientConfigurationError("server_url must use HTTPS, except for a loopback endpoint")


def _validate_secret_file(path: Path) -> Path:
    value = path.resolve(strict=True)
    candidate = path.absolute()
    while candidate != candidate.parent:
        if candidate.is_symlink():
            raise ClientConfigurationError("credential_file path must not traverse a symlink")
        candidate = candidate.parent
    if not value.is_file():
        raise ClientConfigurationError("credential_file must be a regular non-symlink file")
    if os.name != "nt" and stat.S_IMODE(value.stat().st_mode) & 0o077:
        raise ClientConfigurationError("credential_file must not be accessible by group or others")
    return value


def _validate_config_file(path: Path) -> Path:
    value = path.resolve(strict=True)
    candidate = path.absolute()
    while candidate != candidate.parent:
        if candidate.is_symlink():
            raise ClientConfigurationError("configuration path must not traverse a symlink")
        candidate = candidate.parent
    if not value.is_file():
        raise ClientConfigurationError("configuration must be a regular file")
    if os.name != "nt" and stat.S_IMODE(value.stat().st_mode) & 0o077:
        raise ClientConfigurationError("configuration must not be accessible by group or others")
    return value


def load_config(path: Path) -> ClientConfig:
    try:
        config_path = _validate_config_file(path)
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClientConfigurationError("unable to read client configuration") from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "server_url",
        "client_id",
        "credential_file",
    }:
        raise ClientConfigurationError("client configuration fields do not match schema v1")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ClientConfigurationError("unsupported client configuration schema")
    if value["client_id"] != MANAGED_CLIENT_ID:
        raise ClientConfigurationError("unsupported managed client ID")
    if not isinstance(value["server_url"], str) or not isinstance(value["credential_file"], str):
        raise ClientConfigurationError("server_url and credential_file must be strings")
    credential = _validate_secret_file(Path(value["credential_file"]))
    return ClientConfig(
        server_url=_validate_server_url(value["server_url"]),
        client_id=value["client_id"],
        credential_file=credential,
    )


def _read_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise FatalClientError("credential file is unreadable") from error
    if not token or len(token) > 256 or any(character.isspace() for character in token):
        raise FatalClientError("credential file contains an invalid token")
    return token


class ApiClient:
    def __init__(
        self,
        config: ClientConfig,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.config = config
        self.opener = opener

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.server_url}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {_read_token(self.config.credential_file)}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise FatalClientError("server rejected the client capability") from error
            if 400 <= error.code < 500:
                raise FatalClientError(f"server rejected API request with status {error.code}") from error
            raise TransientClientError(f"server returned status {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransientClientError("managed API request failed") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise FatalClientError("managed API response exceeded the size limit")
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise FatalClientError("managed API returned invalid JSON") from error
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            raise FatalClientError("managed API returned an unsupported schema")
        return value


class ManagedClient:
    def __init__(self, api: ApiClient) -> None:
        self.api = api

    def _heartbeat(self, state: str, last_error: dict[str, str] | None) -> None:
        response = self.api.post(
            "/api/autotune/v1/heartbeat/",
            {
                "schema_version": SCHEMA_VERSION,
                "client_id": self.api.config.client_id,
                "state": state,
                "current_test_id": None,
                "origin": None,
                "last_error": last_error,
            },
        )
        if set(response) != {"schema_version", "accepted", "heartbeat_at"} or not response.get(
            "accepted"
        ):
            raise FatalClientError("heartbeat acknowledgement did not match schema v1")

    def run_once(self) -> None:
        response = self.api.post(
            "/api/autotune/v1/poll/",
            {"schema_version": SCHEMA_VERSION, "client_id": self.api.config.client_id},
        )
        if set(response) == {"schema_version", "operation"} and response.get(
            "operation"
        ) == "no_task":
            self._heartbeat("idle", None)
            return
        self._heartbeat(
            "error",
            {
                "code": "unsupported_workload_in_v2",
                "message": "V2 client accepts no executable workload",
            },
        )
        raise FatalClientError("server returned an executable or unknown workload")


def run_forever(client: ManagedClient, *, sleep: Callable[[float], None] = time.sleep) -> None:
    backoff = 1
    while True:
        try:
            client.run_once()
        except TransientClientError:
            sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue
        backoff = 1
        sleep(HEARTBEAT_INTERVAL_SECONDS)
