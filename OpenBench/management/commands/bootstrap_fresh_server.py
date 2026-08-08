import getpass
import hashlib
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from OpenBench.models import (
    Book, Engine, LogEvent, Machine, Network, PGN, Profile, Result,
    RuleProfile, Test,
)
from OpenBench.rule_profiles import canonical_profile_fields


MAX_CONFIG_BYTES = 65536
MAX_PASSWORD_BYTES = 4096
SHA8 = re.compile(r"^[0-9a-f]{8}$")
SHA40_OR_64 = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class BootstrapRejected(Exception):
    pass


def _exact_object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise BootstrapRejected(f"{label}_shape_invalid")
    return value


def _regular_file(path_value, maximum, label):
    if not isinstance(path_value, str):
        raise BootstrapRejected(f"{label}_path_invalid")
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise BootstrapRejected(f"{label}_path_invalid")
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise BootstrapRejected(f"{label}_size_invalid")
    return path


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Bootstrap an exact-zero fresh canonical ShogiBench server once."

    def add_arguments(self, parser):
        parser.add_argument("--config", required=True)

    def handle(self, *args, **options):
        try:
            config_path = _regular_file(options["config"], MAX_CONFIG_BYTES, "config")
            config = self._load_config(config_path)
            material = self._validate_material(config)
            self._assert_zero_state()
            operator_password = getpass.getpass("New ShogiBench operator password: ")
            worker_password = self._read_password(config["worker_password_file"])
            self._validate_passwords(config, operator_password, worker_password)
            counts = self._bootstrap(config, material, operator_password, worker_password)
        except (BootstrapRejected, ValidationError) as error:
            code = str(error)
            self.stdout.write(json.dumps({
                "schema_version": 1,
                "profile_id": "shogibench-fresh-bootstrap-result-v1",
                "status": "rejected",
                "error": code,
            }, sort_keys=True, separators=(",", ":")))
            raise CommandError("fresh bootstrap rejected") from None

        return json.dumps({
            "schema_version": 1,
            "profile_id": "shogibench-fresh-bootstrap-result-v1",
            "canonical_rule_profile_count": counts["rule_profiles"],
            "login_account_count": 2,
            "autotune_account_count": 1,
            "engine_count": counts["engines"],
            "network_count": counts["networks"],
            "book_count": counts["books"],
            "seed_material_count": counts["seed_material"],
            "secret_values_emitted": False,
            "status": "bootstrapped",
        }, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load_config(path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BootstrapRejected("config_json_invalid") from None
        _exact_object(value, (
            "schema_version", "profile_id", "operator_username",
            "worker_username", "worker_password_file", "autotune_username",
            "engine", "network", "books",
        ), "config")
        if value["schema_version"] != 1 or value["profile_id"] != "shogibench-fresh-bootstrap-v1":
            raise BootstrapRejected("config_identity_invalid")
        usernames = [
            value["operator_username"], value["worker_username"], value["autotune_username"],
        ]
        if any(not isinstance(item, str) or not item or len(item) > 64 for item in usernames):
            raise BootstrapRejected("username_invalid")
        if len(set(usernames)) != 3:
            raise BootstrapRejected("username_not_distinct")
        engine = _exact_object(value["engine"], ("name", "source", "sha", "bench"), "engine")
        if (
            not isinstance(engine["name"], str) or not engine["name"]
            or len(engine["name"]) > 64
            or not isinstance(engine["source"], str) or not engine["source"]
            or len(engine["source"]) > 1024
            or not isinstance(engine["sha"], str) or not SHA40_OR_64.fullmatch(engine["sha"])
            or not isinstance(engine["bench"], int) or isinstance(engine["bench"], bool)
            or engine["bench"] <= 0
        ):
            raise BootstrapRejected("engine_invalid")
        network = _exact_object(
            value["network"], ("sha256", "name", "engine", "source_file"), "network",
        )
        books = value["books"]
        if not isinstance(books, list) or not books:
            raise BootstrapRejected("books_invalid")
        for book in books:
            _exact_object(book, ("sha256", "name", "engine", "source_file"), "book")
        for label, item in [("network", network), *[("book", book) for book in books]]:
            if (
                not isinstance(item["sha256"], str) or not SHA8.fullmatch(item["sha256"])
                or not isinstance(item["name"], str) or not item["name"] or len(item["name"]) > 64
                or item["engine"] != engine["name"]
            ):
                raise BootstrapRejected(f"{label}_invalid")
        if len({network["sha256"], *(book["sha256"] for book in books)}) != len(books) + 1:
            raise BootstrapRejected("seed_hash_not_distinct")
        return value

    @staticmethod
    def _validate_material(config):
        material = []
        for label, item in [("network", config["network"]), *[("book", b) for b in config["books"]]]:
            path = _regular_file(item["source_file"], 16 * 1024 ** 3, f"{label}_source")
            if _sha256_file(path)[:8] != item["sha256"]:
                raise BootstrapRejected(f"{label}_hash_mismatch")
            material.append((item["sha256"], path))
        return material

    @staticmethod
    def _read_password(path_value):
        path = _regular_file(path_value, MAX_PASSWORD_BYTES, "worker_password")
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise BootstrapRejected("worker_password_encoding_invalid") from None
        if "\r" in value or "\n" in value or not value:
            raise BootstrapRejected("worker_password_invalid")
        return value

    @staticmethod
    def _validate_passwords(config, operator_password, worker_password):
        if not operator_password or operator_password == worker_password:
            raise BootstrapRejected("password_invalid")
        validate_password(operator_password, user=User(username=config["operator_username"]))
        validate_password(worker_password, user=User(username=config["worker_username"]))

    @staticmethod
    def _assert_zero_state():
        targets = (
            User, Profile, Test, Result, Machine, Engine, Network, Book,
            PGN, LogEvent, RuleProfile,
        )
        if any(model.objects.exists() for model in targets):
            raise BootstrapRejected("database_not_fresh")
        media = Path(settings.MEDIA_ROOT)
        if media.exists():
            if media.is_symlink() or not media.is_dir():
                raise BootstrapRejected("media_root_invalid")
            if any(path.is_file() or path.is_symlink() for path in media.rglob("*")):
                raise BootstrapRejected("media_not_fresh")

    @staticmethod
    def _bootstrap(config, material, operator_password, worker_password):
        storage = FileSystemStorage()
        saved = []
        try:
            with transaction.atomic():
                operator = User.objects.create_user(
                    username=config["operator_username"], password=operator_password,
                )
                Profile.objects.create(user=operator, enabled=True, approver=True, repos={})
                worker = User.objects.create_user(
                    username=config["worker_username"], password=worker_password,
                )
                Profile.objects.create(user=worker, enabled=True, approver=False, repos={})
                autotune = User.objects.create_user(username=config["autotune_username"])
                autotune.set_unusable_password()
                autotune.save(update_fields=("password",))
                Profile.objects.create(user=autotune, enabled=False, approver=False, repos={})

                RuleProfile.objects.create(**canonical_profile_fields())
                Engine.objects.create(**config["engine"])
                Network.objects.create(
                    default=True,
                    sha256=config["network"]["sha256"],
                    name=config["network"]["name"],
                    engine=config["network"]["engine"],
                    author="bootstrap",
                )
                for book in config["books"]:
                    Book.objects.create(
                        sha256=book["sha256"],
                        name=book["name"],
                        engine=book["engine"],
                        author="bootstrap",
                    )
                for identifier, path in material:
                    with path.open("rb") as stream:
                        saved_name = storage.save(identifier, stream)
                    if saved_name != identifier:
                        raise BootstrapRejected("seed_storage_collision")
                    saved.append(saved_name)
        except Exception:
            for name in saved:
                storage.delete(name)
            raise
        return {
            "rule_profiles": RuleProfile.objects.count(),
            "engines": Engine.objects.count(),
            "networks": Network.objects.count(),
            "books": Book.objects.count(),
            "seed_material": len(saved),
        }
