import json
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from AutotuneClient.client import (
    ApiClient,
    ClientConfig,
    ClientConfigurationError,
    FatalClientError,
    ManagedClient,
    TransientClientError,
    load_config,
    run_forever,
)


class FakeApi:
    def __init__(self, poll_response):
        self.config = ClientConfig(
            server_url="http://127.0.0.1:8001",
            client_id="autotune-rating-primary",
            credential_file=Path("unused"),
        )
        self.poll_response = poll_response
        self.calls = []

    def post(self, path, payload):
        self.calls.append((path, payload))
        if path.endswith("poll/"):
            return self.poll_response
        return {
            "schema_version": 1,
            "accepted": True,
            "heartbeat_at": "2026-07-31T00:00:00Z",
        }


class FakeResponse:
    def __init__(self, value):
        self.value = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size):
        return self.value


class AutotuneManagedClientTests(TestCase):
    def test_no_task_only_emits_idle_heartbeat(self):
        api = FakeApi({"schema_version": 1, "operation": "no_task"})
        ManagedClient(api).run_once()

        self.assertEqual([call[0] for call in api.calls], [
            "/api/autotune/v1/poll/",
            "/api/autotune/v1/heartbeat/",
        ])
        self.assertEqual(api.calls[1][1]["state"], "idle")
        self.assertIsNone(api.calls[1][1]["last_error"])

    def test_unknown_workload_is_reported_and_never_executed(self):
        api = FakeApi(
            {"schema_version": 1, "operation": "run", "command": "engine.exe"}
        )
        with self.assertRaises(FatalClientError):
            ManagedClient(api).run_once()

        self.assertEqual(len(api.calls), 2)
        self.assertEqual(api.calls[1][1]["state"], "error")
        self.assertEqual(
            api.calls[1][1]["last_error"]["code"], "unsupported_workload_in_v2"
        )

    def test_config_accepts_https_and_never_accepts_token_value(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            token = directory / "token"
            token.write_text("secret-token\n", encoding="utf-8")
            token.chmod(0o600)
            config = directory / "client.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "server_url": "https://bench.example.test",
                        "client_id": "autotune-rating-primary",
                        "credential_file": str(token),
                    }
                ),
                encoding="utf-8",
            )
            config.chmod(0o600)

            loaded = load_config(config)

        self.assertEqual(loaded.server_url, "https://bench.example.test")
        self.assertFalse(hasattr(loaded, "token"))

    def test_config_rejects_remote_plain_http_and_unknown_fields(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            token = directory / "token"
            token.write_text("secret-token\n", encoding="utf-8")
            token.chmod(0o600)
            config = directory / "client.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "server_url": "http://bench.example.test",
                        "client_id": "autotune-rating-primary",
                        "credential_file": str(token),
                        "token": "must-not-be-accepted",
                    }
                ),
                encoding="utf-8",
            )
            config.chmod(0o600)

            with self.assertRaises(ClientConfigurationError):
                load_config(config)

    def test_api_auth_failure_is_fatal_without_secret_in_message(self):
        with TemporaryDirectory() as temporary:
            token = Path(temporary) / "token"
            token.write_text("sensitive-token\n", encoding="utf-8")
            config = ClientConfig(
                "http://127.0.0.1:8001", "autotune-rating-primary", token
            )

            def rejected(request, timeout):
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

            with self.assertRaises(FatalClientError) as captured:
                ApiClient(config, opener=rejected).post("/poll/", {})

        self.assertNotIn("sensitive-token", str(captured.exception))

    def test_transient_failures_use_bounded_exponential_backoff(self):
        class EventuallyHealthyClient:
            def __init__(self):
                self.calls = 0

            def run_once(self):
                self.calls += 1
                if self.calls <= 7:
                    raise TransientClientError("temporary")

        client = EventuallyHealthyClient()
        delays = []

        def stop_after_success(delay):
            delays.append(delay)
            if client.calls == 8:
                raise RuntimeError("stop")

        with self.assertRaisesRegex(RuntimeError, "stop"):
            run_forever(client, sleep=stop_after_success)

        self.assertEqual(delays, [1, 2, 4, 8, 16, 32, 60, 30])
