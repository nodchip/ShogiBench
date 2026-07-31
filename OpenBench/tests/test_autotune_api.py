import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from OpenBench.autotune_api import (
    HEARTBEAT_TIMEOUT_SECONDS,
    MANAGED_CLIENT_ID,
    _is_root_owned_systemd_credential,
)
from OpenBench.models import AutotuneClientStatus


class AutotuneApiTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.client_token = directory / "client-token"
        self.loop_token = directory / "loop-token"
        self.client_token.write_text("client-capability\n", encoding="utf-8")
        self.loop_token.write_text("loop-capability\n", encoding="utf-8")
        self.client_token.chmod(0o600)
        self.loop_token.chmod(0o600)
        self.settings = override_settings(
            AUTOTUNE_CLIENT_TOKEN_FILE=str(self.client_token),
            AUTOTUNE_LOOP_TOKEN_FILE=str(self.loop_token),
        )
        self.settings.enable()

    def tearDown(self):
        self.settings.disable()
        self.temporary.cleanup()

    @staticmethod
    def auth(token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    @staticmethod
    def poll_payload():
        return {"schema_version": 1, "client_id": MANAGED_CLIENT_ID}

    @staticmethod
    def heartbeat_payload(state="idle", last_error=None):
        return {
            "schema_version": 1,
            "client_id": MANAGED_CLIENT_ID,
            "state": state,
            "current_test_id": None,
            "origin": None,
            "last_error": last_error,
        }

    def post_json(self, path, payload, token="client-capability"):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth(token),
        )

    def test_client_capability_can_poll_and_heartbeat(self):
        poll = self.post_json("/api/autotune/v1/poll/", self.poll_payload())
        heartbeat = self.post_json(
            "/api/autotune/v1/heartbeat/", self.heartbeat_payload()
        )

        self.assertEqual(poll.status_code, 200)
        self.assertEqual(poll.json(), {"schema_version": 1, "operation": "no_task"})
        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(heartbeat.json()["accepted"])
        status = AutotuneClientStatus.objects.get(client_id=MANAGED_CLIENT_ID)
        self.assertEqual(status.state, "idle")
        self.assertIsNotNone(status.heartbeat_at)

    def test_capabilities_are_not_interchangeable(self):
        wrong_poll = self.post_json(
            "/api/autotune/v1/poll/", self.poll_payload(), token="loop-capability"
        )
        self.post_json("/api/autotune/v1/heartbeat/", self.heartbeat_payload())
        wrong_status = self.client.get(
            f"/api/autotune/v1/status/{MANAGED_CLIENT_ID}/",
            **self.auth("client-capability"),
        )
        right_status = self.client.get(
            f"/api/autotune/v1/status/{MANAGED_CLIENT_ID}/",
            **self.auth("loop-capability"),
        )

        self.assertEqual(wrong_poll.status_code, 403)
        self.assertEqual(wrong_status.status_code, 403)
        self.assertEqual(right_status.status_code, 200)

    def test_status_uses_server_clock_for_fresh_then_stale(self):
        received_at = timezone.now()
        with patch("OpenBench.autotune_api.timezone.now", return_value=received_at):
            self.post_json("/api/autotune/v1/heartbeat/", self.heartbeat_payload())
        fresh_at = received_at + timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
        with patch("OpenBench.autotune_api.timezone.now", return_value=fresh_at):
            fresh = self.client.get(
                f"/api/autotune/v1/status/{MANAGED_CLIENT_ID}/",
                **self.auth("loop-capability"),
            )
        stale_at = fresh_at + timedelta(microseconds=1)
        with patch("OpenBench.autotune_api.timezone.now", return_value=stale_at):
            stale = self.client.get(
                f"/api/autotune/v1/status/{MANAGED_CLIENT_ID}/",
                **self.auth("loop-capability"),
            )

        self.assertTrue(fresh.json()["fresh"])
        self.assertEqual(fresh.json()["state"], "idle")
        self.assertFalse(stale.json()["fresh"])
        self.assertEqual(stale.json()["state"], "stale")

    def test_late_heartbeat_restores_fresh_status(self):
        old = timezone.now() - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS + 1)
        AutotuneClientStatus.objects.create(
            client_id=MANAGED_CLIENT_ID, state="idle", heartbeat_at=old
        )
        self.post_json("/api/autotune/v1/heartbeat/", self.heartbeat_payload())
        response = self.client.get(
            f"/api/autotune/v1/status/{MANAGED_CLIENT_ID}/",
            **self.auth("loop-capability"),
        )

        self.assertTrue(response.json()["fresh"])
        self.assertEqual(response.json()["state"], "idle")

    def test_heartbeat_timestamp_never_moves_backwards(self):
        future = timezone.now() + timedelta(minutes=5)
        AutotuneClientStatus.objects.create(
            client_id=MANAGED_CLIENT_ID, state="idle", heartbeat_at=future
        )
        self.post_json("/api/autotune/v1/heartbeat/", self.heartbeat_payload())
        status = AutotuneClientStatus.objects.get(client_id=MANAGED_CLIENT_ID)
        self.assertEqual(status.heartbeat_at, future)

    def test_error_is_allowlisted_and_returned_without_secret(self):
        response = self.post_json(
            "/api/autotune/v1/heartbeat/",
            self.heartbeat_payload(
                "error",
                {
                    "code": "unsupported_workload_in_v2",
                    "message": "V2 client accepts no executable workload",
                },
            ),
        )
        status = self.client.get(
            f"/api/autotune/v1/status/{MANAGED_CLIENT_ID}/",
            **self.auth("loop-capability"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(status.json()["last_error"]["code"], "unsupported_workload_in_v2")
        self.assertNotIn("client-capability", status.content.decode())
        self.assertNotIn("loop-capability", status.content.decode())

    def test_invalid_requests_fail_closed(self):
        cases = [
            self.client.get(
                "/api/autotune/v1/poll/", **self.auth("client-capability")
            ),
            self.client.post(
                "/api/autotune/v1/poll/",
                data=json.dumps(self.poll_payload()),
                content_type="text/plain",
                **self.auth("client-capability"),
            ),
            self.post_json(
                "/api/autotune/v1/poll/",
                {**self.poll_payload(), "unknown": True},
            ),
            self.post_json(
                "/api/autotune/v1/poll/",
                {**self.poll_payload(), "schema_version": 2},
            ),
            self.post_json(
                "/api/autotune/v1/poll/",
                {**self.poll_payload(), "client_id": "other"},
            ),
            self.client.post(
                "/api/autotune/v1/poll/",
                data=b" " * 4097,
                content_type="application/json",
                **self.auth("client-capability"),
            ),
        ]

        self.assertEqual(
            [response.status_code for response in cases],
            [405, 415, 400, 400, 404, 413],
        )

    @override_settings(AUTOTUNE_CLIENT_TOKEN_FILE="")
    def test_missing_server_credential_fails_closed(self):
        response = self.post_json("/api/autotune/v1/poll/", self.poll_payload())
        self.assertEqual(response.status_code, 503)

    def test_identical_capabilities_fail_closed(self):
        self.loop_token.write_text("client-capability\n", encoding="utf-8")
        response = self.post_json("/api/autotune/v1/poll/", self.poll_payload())
        self.assertEqual(response.status_code, 503)

    def test_unknown_status_client_is_rejected(self):
        response = self.client.get(
            "/api/autotune/v1/status/other/", **self.auth("loop-capability")
        )
        self.assertEqual(response.status_code, 404)

    def test_only_root_owned_systemd_token_mode_is_accepted(self):
        credential = Path("/run/credentials/openbench.service/token")
        root_owned = SimpleNamespace(st_uid=0, st_gid=0)
        user_owned = SimpleNamespace(st_uid=1000, st_gid=1000)

        self.assertTrue(_is_root_owned_systemd_credential(credential, root_owned, 0o440))
        self.assertFalse(_is_root_owned_systemd_credential(credential, root_owned, 0o640))
        self.assertFalse(_is_root_owned_systemd_credential(credential, user_owned, 0o440))
        self.assertFalse(
            _is_root_owned_systemd_credential(Path("/tmp/token"), root_owned, 0o440)
        )
