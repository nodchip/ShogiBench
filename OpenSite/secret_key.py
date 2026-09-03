"""Load Django's signing key without storing it in source control."""

import json
import os


_SECRET_ENV = "SHOGIBENCH_DJANGO_SECRET_KEY"
_SECRET_FILE_ENV = "SHOGIBENCH_DJANGO_SECRET_KEY_FILE"
_LOCAL_CONFIG_ENV = "SHOGIBENCH_LOCAL_CONFIG_PATH"
_LOCAL_CONFIG_KEY = "django_signing_key_path"
_DEFAULT_SECRET_FILE = ".django-secret-key"
_MAX_SECRET_BYTES = 4096
_MIN_SECRET_CHARACTERS = 50


def _read_secret_file(path):
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            raise RuntimeError("Django secret key path is not a regular file")

        if os.path.getsize(path) > _MAX_SECRET_BYTES:
            raise RuntimeError("Django secret key file is unexpectedly large")

        with open(path, "r", encoding="utf-8-sig") as secret_file:
            value = secret_file.read().strip()
    except (OSError, UnicodeError):
        raise RuntimeError("Django secret key file could not be read") from None

    return value


def _secret_file_from_local_config():
    config_path = os.environ.get(_LOCAL_CONFIG_ENV, "").strip()
    if not config_path:
        return None

    try:
        if os.path.islink(config_path) or not os.path.isfile(config_path):
            raise RuntimeError("ShogiBench local config is not a regular file")

        with open(config_path, "r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("ShogiBench local config could not be read") from None

    secret_path = config.get(_LOCAL_CONFIG_KEY)
    if not isinstance(secret_path, str) or not secret_path.strip():
        raise RuntimeError("ShogiBench local config has no Django signing key path")

    return secret_path.strip()


def load_secret_key(base_dir):
    """Return a validated key from an environment variable or protected file."""
    value = os.environ.get(_SECRET_ENV, "").strip()

    if not value:
        secret_path = os.environ.get(_SECRET_FILE_ENV, "").strip()
        if not secret_path:
            secret_path = _secret_file_from_local_config()
        if not secret_path:
            secret_path = os.path.join(base_dir, _DEFAULT_SECRET_FILE)
        value = _read_secret_file(secret_path)

    if len(value) < _MIN_SECRET_CHARACTERS:
        raise RuntimeError("Django secret key must contain at least 50 characters")

    return value
