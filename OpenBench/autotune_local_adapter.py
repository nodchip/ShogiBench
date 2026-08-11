import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 65536
LOCAL_ADDRESSES = frozenset({'127.0.0.1', '::1'})
TARGETS = {
    'material': {
        'command': 'autotune_material',
        'actions': frozenset({'get', 'inspect'}),
        'timeout': 120,
        'statuses': frozenset({'observed'}),
    },
    'network': {
        'command': 'autotune_register_network',
        'actions': frozenset({'register', 'get'}),
        'timeout': 120,
        'statuses': frozenset({'registered', 'observed'}),
    },
    'rating': {
        'command': 'autotune_control',
        'actions': frozenset({'create', 'get', 'stop'}),
        'timeout': 30,
        'statuses': frozenset({'created', 'observed', 'stopped'}),
    },
}


def _error(code, status):
    return JsonResponse({
        'schema_version': 1,
        'profile_id': 'autotune-local-adapter-v1',
        'status': 'rejected',
        'error': code,
    }, status=status)


def _environment():
    environment = {
        name: os.environ[name]
        for name in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')
        if name in os.environ
    }
    settings_module = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    local_config = os.environ.get('SHOGIBENCH_LOCAL_CONFIG_PATH', '')
    if settings_module != 'OpenSite.settings_windows':
        raise RuntimeError('settings identity differs')
    config_path = Path(local_config)
    if not config_path.is_absolute() or config_path.is_symlink() or not config_path.is_file():
        raise RuntimeError('local config identity differs')
    environment.update({
        'DJANGO_SETTINGS_MODULE': settings_module,
        'SHOGIBENCH_LOCAL_CONFIG_PATH': str(config_path),
    })
    return environment


def _decode(completed, action, contract):
    if len(completed.stdout) > MAX_RESPONSE_BYTES:
        raise RuntimeError('response too large')
    try:
        value = json.loads(completed.stdout.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError('response invalid') from None
    if (
        not isinstance(value, dict)
        or value.get('schema_version') != 1
        or value.get('action') != action
    ):
        raise RuntimeError('response identity differs')
    if completed.returncode == 0:
        if value.get('status') not in contract['statuses']:
            raise RuntimeError('response status differs')
        return value, 200
    if value.get('status') == 'rejected' and isinstance(value.get('error'), str):
        return value, 409
    raise RuntimeError('rejection response invalid')


@csrf_exempt
def autotune_local_adapter(request, target, action):
    if request.META.get('REMOTE_ADDR') not in LOCAL_ADDRESSES:
        return _error('loopback_required', 403)
    if request.method != 'POST':
        return _error('post_required', 405)
    contract = TARGETS.get(target)
    if contract is None or action not in contract['actions']:
        return _error('operation_not_allowed', 404)
    content_type = request.META.get('CONTENT_TYPE', '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json':
        return _error('json_required', 415)
    try:
        content_length = int(request.META.get('CONTENT_LENGTH', ''))
    except ValueError:
        return _error('content_length_invalid', 400)
    if content_length < 1 or content_length > MAX_REQUEST_BYTES:
        return _error('request_size_invalid', 413)
    body = request.body
    if len(body) != content_length or len(body) > MAX_REQUEST_BYTES:
        return _error('request_size_invalid', 413)
    deployment = Path(settings.BASE_DIR)
    manage = deployment / 'manage.py'
    if (
        not deployment.is_absolute()
        or deployment.is_symlink()
        or not manage.is_file()
        or Path(sys.executable).is_symlink()
    ):
        return _error('deployment_identity_invalid', 503)
    arguments = (
        sys.executable,
        str(manage),
        contract['command'],
        action,
        '--settings',
        'OpenSite.settings_windows',
    )
    try:
        completed = subprocess.run(
            arguments,
            input=body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=deployment,
            env=_environment(),
            timeout=contract['timeout'],
            check=False,
        )
        value, status = _decode(completed, action, contract)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return _error('operation_outcome_unknown', 503)
    return JsonResponse(value, status=status)
