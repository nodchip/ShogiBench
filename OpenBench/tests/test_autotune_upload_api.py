import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from OpenBench.autotune_upload_api import ENGINE, ORIGIN
from OpenBench.models import (
    AutotuneNetworkRegistration,
    AutotuneUploadCapability,
    Network,
)
from OpenBench.workloads.verify_workload import verify_network


class AutotuneUploadApiTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.media_root = directory / "Media"
        self.media_root.mkdir()
        self.client_token = directory / "client-token"
        self.loop_token = directory / "loop-token"
        self.client_token.write_text("client-capability\n", encoding="utf-8")
        self.loop_token.write_text("loop-capability\n", encoding="utf-8")
        self.client_token.chmod(0o600)
        self.loop_token.chmod(0o600)
        self.settings = override_settings(
            AUTOTUNE_CLIENT_TOKEN_FILE=str(self.client_token),
            AUTOTUNE_LOOP_TOKEN_FILE=str(self.loop_token),
            MEDIA_ROOT=str(self.media_root),
        )
        self.settings.enable()
        self.capability = AutotuneUploadCapability.objects.create(
            token_id="upload-v1",
            verifier=make_password("upload-capability"),
        )

    def tearDown(self):
        self.settings.disable()
        self.temporary.cleanup()

    @staticmethod
    def auth(token="upload-v1.upload-capability"):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    @staticmethod
    def metadata(payload, *, name="acceptance.nnue", key="1" * 64):
        return {
            "schema_version": "1",
            "engine": ENGINE,
            "name": name,
            "origin": ORIGIN,
            "full_sha256": hashlib.sha256(payload).hexdigest(),
            "size": str(len(payload)),
            "idempotency_key": key,
        }

    def upload(self, payload, *, token="upload-v1.upload-capability", **overrides):
        metadata = self.metadata(payload)
        metadata.update(overrides)
        return self.client.post(
            "/api/autotune/v1/networks/",
            data={
                **metadata,
                "network": SimpleUploadedFile("candidate.nnue", payload),
            },
            **self.auth(token),
        )

    def test_upload_creates_additive_registration_and_replays_exact_key(self):
        payload = b"bounded acceptance network"

        created = self.upload(payload)
        replayed = self.upload(payload)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(replayed.status_code, 200)
        self.assertFalse(created.json()["registration"]["replayed"])
        self.assertTrue(replayed.json()["registration"]["replayed"])
        self.assertEqual(created.json()["registration"]["network_id"], "5420B68A")
        self.assertEqual(
            created.json()["registration"]["full_sha256"],
            hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(Network.objects.count(), 1)
        self.assertEqual(AutotuneNetworkRegistration.objects.count(), 1)
        self.assertEqual((self.media_root / "5420B68A").read_bytes(), payload)

    def test_exact_receipt_lookup_is_the_only_upload_capability_read(self):
        payload = b"lookup network"
        created = self.upload(payload)
        key = created.json()["registration"]["idempotency_key"]

        found = self.client.get(
            f"/api/autotune/v1/networks/receipts/{key}/",
            **self.auth(),
        )
        missing = self.client.get(
            f"/api/autotune/v1/networks/receipts/{'2' * 64}/",
            **self.auth(),
        )
        list_attempt = self.client.get("/api/autotune/v1/networks/", **self.auth())

        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.json()["registration"]["replayed"])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(list_attempt.status_code, 405)

    def test_wrong_or_other_capability_cannot_upload_or_lookup(self):
        payload = b"separated capability"
        results = [
            self.upload(payload, token="wrong"),
            self.upload(payload, token="client-capability"),
            self.upload(payload, token="loop-capability"),
            self.client.post(
                "/api/autotune/v1/networks/",
                data={
                    **self.metadata(payload),
                    "network": SimpleUploadedFile("candidate.nnue", payload),
                },
            ),
        ]

        self.assertEqual([response.status_code for response in results], [403] * 4)
        self.assertFalse(Network.objects.exists())

    def test_missing_or_duplicate_upload_configuration_fails_closed(self):
        payload = b"configuration boundary"
        self.capability.delete()
        missing = self.upload(payload)
        self.capability = AutotuneUploadCapability.objects.create(
            token_id="upload-v1",
            verifier=make_password("upload-capability"),
        )
        AutotuneUploadCapability.objects.create(
            token_id="upload-v2",
            verifier=make_password("other-capability"),
        )
        duplicate = self.upload(payload)

        self.assertEqual(missing.status_code, 503)
        self.assertEqual(duplicate.status_code, 503)

    def test_payload_identity_and_idempotency_conflicts_do_not_write(self):
        payload = b"first network"
        wrong_hash = self.upload(payload, full_sha256="0" * 64)
        wrong_size = self.upload(payload, size=str(len(payload) + 1))
        created = self.upload(payload)
        conflict = self.upload(
            b"different network",
            idempotency_key="1" * 64,
        )

        self.assertEqual(wrong_hash.status_code, 422)
        self.assertEqual(wrong_size.status_code, 422)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(Network.objects.count(), 1)
        self.assertEqual(AutotuneNetworkRegistration.objects.count(), 1)

    def test_existing_different_prefix_payload_is_preserved_as_collision(self):
        payload = b"new network"
        legacy_id = hashlib.sha256(payload).hexdigest()[:8].upper()
        existing = b"different existing bytes"
        (self.media_root / legacy_id).write_bytes(existing)

        response = self.upload(payload)

        self.assertEqual(response.status_code, 409)
        self.assertEqual((self.media_root / legacy_id).read_bytes(), existing)
        self.assertFalse(Network.objects.exists())

    def test_existing_legacy_row_cannot_be_claimed_as_acceptance_registration(self):
        payload = b"existing legacy network"
        legacy_id = hashlib.sha256(payload).hexdigest()[:8].upper()
        (self.media_root / legacy_id).write_bytes(payload)
        Network.objects.create(
            sha256=legacy_id,
            name="acceptance.nnue",
            engine=ENGINE,
            author="legacy",
        )

        response = self.upload(payload)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(AutotuneNetworkRegistration.objects.exists())
        self.assertEqual((self.media_root / legacy_id).read_bytes(), payload)

    def test_storage_drift_blocks_replay_and_exact_receipt_lookup(self):
        payload = b"sealed registration"
        created = self.upload(payload)
        registration = created.json()["registration"]
        (self.media_root / registration["network_id"]).write_bytes(b"changed")

        replay = self.upload(payload)
        lookup = self.client.get(
            f"/api/autotune/v1/networks/receipts/{registration['idempotency_key']}/",
            **self.auth(),
        )

        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["error"]["code"], "storage_drift")
        self.assertEqual(lookup.status_code, 409)
        self.assertEqual(lookup.json()["error"]["code"], "storage_drift")

    def test_acceptance_registration_is_not_rating_eligible(self):
        payload = b"acceptance only"
        created = self.upload(payload)
        network_id = created.json()["registration"]["network_id"]
        request = type(
            "Request",
            (),
            {"POST": {"dev_engine": ENGINE, "dev_network": network_id}},
        )()
        errors = []

        verify_network(errors, request, "dev_network", "Dev Network", "dev_engine")

        self.assertEqual(errors, ['Unknown Network Provided for Dev Network'])

    def test_legacy_network_remains_rating_eligible(self):
        Network.objects.create(
            sha256="ABCDEF12",
            name="legacy.nnue",
            engine=ENGINE,
            author="legacy",
        )
        request = type(
            "Request",
            (),
            {"POST": {"dev_engine": ENGINE, "dev_network": "ABCDEF12"}},
        )()
        errors = []

        verify_network(errors, request, "dev_network", "Dev Network", "dev_engine")

        self.assertEqual(errors, [])
