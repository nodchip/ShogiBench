import json
import os
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


def _load_local_config():
    path = os.environ.get('SHOGIBENCH_LOCAL_CONFIG_PATH', '')
    raw = _read_regular_file(path, MAX_CONFIG_BYTES, 'local config')
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError('local config must be valid JSON') from None
    expected = {
        'schema_version', 'profile_id', 'autotune_username',
        'rating_policies', 'django_signing_key_path',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeError('local config has unexpected properties')
    if value['schema_version'] != 1 or value['profile_id'] != 'shogibench-windows-v1':
        raise RuntimeError('local config identity is invalid')
    if not isinstance(value['autotune_username'], str) or not value['autotune_username']:
        raise RuntimeError('autotune username is invalid')
    if not isinstance(value['rating_policies'], dict):
        raise RuntimeError('rating policies are invalid')
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
