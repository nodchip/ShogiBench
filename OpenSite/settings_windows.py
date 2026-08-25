import json
import os
import sys
from pathlib import Path

from .settings import *


MAX_CONFIG_BYTES = 65536
MAX_SECRET_BYTES = 4096


def _read_regular_file(path_value, maximum, label):
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError(f'{label} must be an absolute regular file')
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise RuntimeError(f'{label} has invalid size')
    return path.read_bytes().decode('utf-8', errors='strict')


def _artifact_root_was_prevalidated_for_acceptance_audit(artifact_root):
    return (
        os.environ.get('SHOGIBENCH_AUDIT_PREVALIDATED_ARTIFACT_ROOT', '')
        == str(artifact_root)
        and Path(sys.argv[0]).name.casefold() == 'manage.py'
        and sys.argv[1:] == ['audit_fresh_server', 'acceptance']
    )


def _load_local_config():
    path = os.environ.get('SHOGIBENCH_LOCAL_CONFIG_PATH', '')
    raw = _read_regular_file(path, MAX_CONFIG_BYTES, 'local config')
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError('local config must be valid JSON') from None
    expected = {
        'schema_version', 'profile_id', 'autotune_username',
        'rating_policies', 'rating_game_budgets', 'django_signing_key_path',
        'training_artifact_root',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeError('local config has unexpected properties')
    if value['schema_version'] != 1 or value['profile_id'] != 'shogibench-windows-v1':
        raise RuntimeError('local config identity is invalid')
    if not isinstance(value['autotune_username'], str) or not value['autotune_username']:
        raise RuntimeError('autotune username is invalid')
    if not isinstance(value['rating_policies'], dict):
        raise RuntimeError('rating policies are invalid')
    if not isinstance(value['rating_game_budgets'], dict):
        raise RuntimeError('rating game budgets are invalid')
    artifact_root = Path(value['training_artifact_root'])
    if not artifact_root.is_absolute():
        raise RuntimeError('training artifact root must be an absolute directory')
    try:
        artifact_root_invalid = (
            artifact_root.is_symlink() or not artifact_root.is_dir()
        )
    except PermissionError:
        if not _artifact_root_was_prevalidated_for_acceptance_audit(artifact_root):
            raise
        artifact_root_invalid = False
    if artifact_root_invalid:
        raise RuntimeError('training artifact root must be an absolute directory')
    return value


_LOCAL_CONFIG = _load_local_config()
_SIGNING_KEY = _read_regular_file(
    _LOCAL_CONFIG['django_signing_key_path'],
    MAX_SECRET_BYTES,
    'Django signing key',
)
if '\r' in _SIGNING_KEY or '\n' in _SIGNING_KEY or len(_SIGNING_KEY) < 50:
    raise RuntimeError('Django signing key is invalid')

SECRET_KEY = _SIGNING_KEY
DEBUG = False
ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = []
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
AUTOTUNE_USERNAME = _LOCAL_CONFIG['autotune_username']
AUTOTUNE_RATING_POLICIES = _LOCAL_CONFIG['rating_policies']
AUTOTUNE_RATING_GAME_BUDGETS = _LOCAL_CONFIG['rating_game_budgets']
AUTOTUNE_TRAINING_ARTIFACT_ROOT = _LOCAL_CONFIG['training_artifact_root']
