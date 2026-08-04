"""Additive, capability-scoped network registration for V4 acceptance."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

from django.contrib.auth.hashers import check_password
from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from OpenBench.autotune_api import (
    SCHEMA_VERSION,
    ApiRequestError,
    _configured_upload_capability,
    _error,
    _iso_utc,
    _require_method,
)
from OpenBench.models import AutotuneNetworkRegistration, Network

ENGINE = "tanuki-"
ORIGIN = "autotune_acceptance"
SCOPE = "network_upload"
AUTHOR = "autotune-acceptance"
UPLOAD_FIELDS = {
    "schema_version",
    "engine",
    "name",
    "origin",
    "full_sha256",
    "size",
    "idempotency_key",
}
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TOKEN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _authorize_upload(request: HttpRequest):
    capability, client_token, loop_token = _configured_upload_capability()
    supplied = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not supplied.startswith(prefix):
        raise ApiRequestError("forbidden", 403)
    token = supplied[len(prefix) :]
    if hmac.compare_digest(token, client_token) or hmac.compare_digest(token, loop_token):
        raise ApiRequestError("forbidden", 403)
    token_id, separator, secret = token.partition(".")
    if (
        separator != "."
        or not TOKEN_ID_PATTERN.fullmatch(token_id)
        or not secret
        or len(secret) > 128
        or any(character.isspace() for character in secret)
        or not hmac.compare_digest(token_id, capability.token_id)
        or not check_password(secret, capability.verifier)
    ):
        raise ApiRequestError("forbidden", 403)
    return capability


def _parse_upload(request: HttpRequest) -> tuple[dict[str, Any], Any]:
    if not request.content_type or not request.content_type.startswith("multipart/form-data"):
        raise ApiRequestError("unsupported_media_type", 415)
    if set(request.POST) != UPLOAD_FIELDS or set(request.FILES) != {"network"}:
        raise ApiRequestError("invalid_fields", 400)
    values = request.POST
    if values.get("schema_version") != str(SCHEMA_VERSION):
        raise ApiRequestError("unsupported_schema", 400)
    if values.get("engine") != ENGINE or values.get("origin") != ORIGIN:
        raise ApiRequestError("scope_mismatch", 403)
    name = values.get("name", "")
    full_sha256 = values.get("full_sha256", "")
    idempotency_key = values.get("idempotency_key", "")
    size_text = values.get("size", "")
    if not NAME_PATTERN.fullmatch(name):
        raise ApiRequestError("invalid_name", 400)
    if not HASH_PATTERN.fullmatch(full_sha256) or not HASH_PATTERN.fullmatch(idempotency_key):
        raise ApiRequestError("invalid_hash", 400)
    try:
        byte_size = int(size_text)
    except ValueError as error:
        raise ApiRequestError("invalid_size", 400) from error
    if byte_size <= 0 or str(byte_size) != size_text:
        raise ApiRequestError("invalid_size", 400)
    return {
        "engine": ENGINE,
        "name": name,
        "origin": ORIGIN,
        "full_sha256": full_sha256,
        "byte_size": byte_size,
        "idempotency_key": idempotency_key,
    }, request.FILES["network"]


def _uploaded_identity(uploaded: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    for chunk in uploaded.chunks():
        digest.update(chunk)
        byte_size += len(chunk)
    uploaded.seek(0)
    return digest.hexdigest(), byte_size


def _stored_identity(storage: FileSystemStorage, name: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with storage.open(name, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _registration_payload(
    registration: AutotuneNetworkRegistration,
    *,
    replayed: bool,
) -> dict[str, Any]:
    network = registration.network
    return {
        "schema_version": SCHEMA_VERSION,
        "registration": {
            "registration_id": registration.pk,
            "idempotency_key": registration.idempotency_key,
            "engine": network.engine,
            "name": network.name,
            "network_id": network.sha256,
            "full_sha256": registration.full_sha256,
            "size": registration.byte_size,
            "origin": registration.origin,
            "created_at": _iso_utc(registration.created_at),
            "replayed": replayed,
        },
    }


def _same_registration(registration: AutotuneNetworkRegistration, values: dict[str, Any]):
    return (
        registration.network.engine == values["engine"]
        and registration.network.name == values["name"]
        and registration.full_sha256 == values["full_sha256"]
        and registration.byte_size == values["byte_size"]
        and registration.origin == values["origin"]
    )


@csrf_exempt
def upload_network(request: HttpRequest) -> JsonResponse:
    try:
        _require_method(request, "POST")
        capability = _authorize_upload(request)
        values, uploaded = _parse_upload(request)
        actual_hash, actual_size = _uploaded_identity(uploaded)
        if actual_hash != values["full_sha256"] or actual_size != values["byte_size"]:
            raise ApiRequestError("payload_identity_mismatch", 422)
    except ApiRequestError as error:
        return _error(error.code, error.status_code)

    storage = FileSystemStorage()
    legacy_id = actual_hash[:8].upper()
    try:
        with transaction.atomic():
            existing = (
                AutotuneNetworkRegistration.objects.select_for_update()
                .filter(idempotency_key=values["idempotency_key"])
                .first()
            )
            if existing is not None:
                if not _same_registration(existing, values):
                    raise ApiRequestError("idempotency_conflict", 409)
                if not storage.exists(existing.network.sha256) or _stored_identity(
                    storage, existing.network.sha256
                ) != (existing.full_sha256, existing.byte_size):
                    raise ApiRequestError("storage_drift", 409)
                return JsonResponse(_registration_payload(existing, replayed=True), status=200)
            if AutotuneNetworkRegistration.objects.filter(full_sha256=actual_hash).exists():
                raise ApiRequestError("network_already_registered", 409)
            if Network.objects.filter(engine=ENGINE, name=values["name"]).exclude(
                sha256=legacy_id
            ).exists():
                raise ApiRequestError("name_conflict", 409)

            media_exists = storage.exists(legacy_id)
            if media_exists and _stored_identity(storage, legacy_id) != (
                actual_hash,
                actual_size,
            ):
                raise ApiRequestError("network_id_collision", 409)
            network = Network.objects.select_for_update().filter(
                engine=ENGINE,
                sha256=legacy_id,
            ).first()
            if network is not None:
                raise ApiRequestError("network_identity_conflict", 409)
            if not media_exists:
                stored_name = storage.save(legacy_id, uploaded)
                if stored_name != legacy_id:
                    raise ApiRequestError("network_id_collision", 409)
            if network is None:
                network = Network.objects.create(
                    sha256=legacy_id,
                    name=values["name"],
                    engine=ENGINE,
                    author=AUTHOR,
                )
            registration = AutotuneNetworkRegistration.objects.create(
                network=network,
                full_sha256=actual_hash,
                byte_size=actual_size,
                origin=ORIGIN,
                idempotency_key=values["idempotency_key"],
                token_id=capability.token_id,
            )
    except ApiRequestError as error:
        return _error(error.code, error.status_code)
    except IntegrityError:
        return _error("registration_conflict", 409)
    return JsonResponse(_registration_payload(registration, replayed=False), status=201)


@csrf_exempt
def registration_receipt(request: HttpRequest, idempotency_key: str) -> JsonResponse:
    try:
        _require_method(request, "GET")
        _authorize_upload(request)
        if request.body or request.GET:
            raise ApiRequestError("unexpected_input", 400)
        if not HASH_PATTERN.fullmatch(idempotency_key):
            raise ApiRequestError("invalid_hash", 400)
    except ApiRequestError as error:
        return _error(error.code, error.status_code)
    try:
        registration = AutotuneNetworkRegistration.objects.select_related("network").get(
            idempotency_key=idempotency_key
        )
    except AutotuneNetworkRegistration.DoesNotExist:
        return _error("unknown_registration", 404)
    storage = FileSystemStorage()
    if not storage.exists(registration.network.sha256) or _stored_identity(
        storage, registration.network.sha256
    ) != (registration.full_sha256, registration.byte_size):
        return _error("storage_drift", 409)
    return JsonResponse(_registration_payload(registration, replayed=True))
