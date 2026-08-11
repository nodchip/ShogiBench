import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from OpenBench.models import Book, Engine, LogEvent, Network, Profile


MAX_REQUEST_BYTES = 65536
MAX_NETWORK_BYTES = 128 * 1024 * 1024
ENGINE = 'tanuki-'
SHA256 = re.compile(r'^[0-9a-f]{64}$')
LOGICAL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
REQUEST_FIELDS = (
    'schema_version', 'action', 'request_id', 'logical_id', 'engine', 'sha256', 'size',
)


class RegistrationError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _response(action, status, **values):
    return {'schema_version': 1, 'action': action, 'status': status, **values}


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = 'Register or reconcile one fixed-root autotune training network.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('register', 'get'))

    def handle(self, *args, **options):
        action = options['action']
        try:
            request = self._read_request(action)
            source = self._source(request)
            if action == 'register':
                result = self._register(request, source)
            else:
                result = self._get(request, source)
        except RegistrationError as error:
            self.stdout.write(json.dumps(
                _response(action, 'rejected', error=error.code),
                sort_keys=True,
                separators=(',', ':'),
            ))
            raise CommandError('autotune_register_network rejected') from None
        return json.dumps(result, sort_keys=True, separators=(',', ':'))

    @staticmethod
    def _read_request(action):
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise RegistrationError('request_too_large')
        try:
            request = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RegistrationError('invalid_json') from None
        if not isinstance(request, dict) or set(request) != set(REQUEST_FIELDS):
            raise RegistrationError('invalid_request_shape')
        if request['schema_version'] != 1 or request['action'] != action:
            raise RegistrationError('invalid_request_identity')
        try:
            parsed_request_id = uuid.UUID(request['request_id'])
        except (AttributeError, TypeError, ValueError):
            raise RegistrationError('invalid_request_id') from None
        if str(parsed_request_id) != request['request_id']:
            raise RegistrationError('invalid_request_id')
        if not isinstance(request['logical_id'], str) or not LOGICAL_ID.fullmatch(request['logical_id']):
            raise RegistrationError('invalid_logical_id')
        if request['engine'] != ENGINE:
            raise RegistrationError('invalid_engine')
        if not isinstance(request['sha256'], str) or not SHA256.fullmatch(request['sha256']):
            raise RegistrationError('invalid_sha256')
        if (
            not isinstance(request['size'], int)
            or isinstance(request['size'], bool)
            or request['size'] <= 0
            or request['size'] > MAX_NETWORK_BYTES
        ):
            raise RegistrationError('invalid_size')
        return request

    @staticmethod
    def _root(setting_name, code):
        value = getattr(settings, setting_name, '')
        if not isinstance(value, str):
            raise RegistrationError(code)
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise RegistrationError(code)
        return path.resolve(strict=True)

    def _source(self, request):
        root = self._root('AUTOTUNE_TRAINING_ARTIFACT_ROOT', 'artifact_root_invalid')
        request_directory = root / request['request_id']
        source = request_directory / 'candidate-network.bin'
        if (
            request_directory.is_symlink()
            or source.is_symlink()
            or not source.is_file()
        ):
            raise RegistrationError('artifact_missing')
        try:
            resolved_directory = request_directory.resolve(strict=True)
            resolved_source = source.resolve(strict=True)
        except OSError:
            raise RegistrationError('artifact_missing') from None
        if resolved_directory.parent != root or resolved_source.parent != resolved_directory:
            raise RegistrationError('artifact_path_invalid')
        try:
            size = resolved_source.stat().st_size
        except OSError:
            raise RegistrationError('artifact_unreadable') from None
        if size != request['size']:
            raise RegistrationError('artifact_size_mismatch')
        try:
            digest = _sha256_file(resolved_source)
        except OSError:
            raise RegistrationError('artifact_unreadable') from None
        if digest != request['sha256']:
            raise RegistrationError('artifact_hash_mismatch')
        return resolved_source

    @staticmethod
    def _username():
        username = getattr(settings, 'AUTOTUNE_USERNAME', '')
        if not isinstance(username, str) or not username or len(username) > 64:
            raise RegistrationError('autotune_identity_unconfigured')
        try:
            actor = Profile.objects.select_related('user').get(user__username=username)
        except Profile.DoesNotExist:
            raise RegistrationError('autotune_identity_missing') from None
        if actor.approver or actor.user.has_usable_password():
            raise RegistrationError('autotune_identity_has_excess_capability')
        return username

    @staticmethod
    def _receipt(action, status, request, network_id):
        return _response(
            action,
            status,
            request_id=request['request_id'],
            logical_id=request['logical_id'],
            engine=request['engine'],
            sha256=request['sha256'],
            size=request['size'],
            network_id=network_id,
        )

    def _target(self, request):
        media_root = self._root('MEDIA_ROOT', 'media_root_invalid')
        return media_root / request['sha256'][:8].upper()

    @staticmethod
    def _network(request, username, lock=False):
        network_id = request['sha256'][:8].upper()
        query = Network.objects
        if lock:
            query = query.select_for_update()
        same_hash = list(query.filter(sha256=network_id))
        exact = [item for item in same_hash if (
            item.engine == request['engine']
            and item.name == request['logical_id']
            and item.author == username
            and not item.default
            and not item.was_default
        )]
        if same_hash and len(exact) != 1:
            raise RegistrationError('network_id_conflict')
        name_conflict = query.filter(
            engine=request['engine'], name=request['logical_id'],
        ).exclude(sha256=network_id).exists()
        if name_conflict:
            raise RegistrationError('network_name_conflict')
        if Book.objects.filter(sha256=network_id).exists():
            raise RegistrationError('network_storage_conflict')
        return exact[0] if exact else None

    @staticmethod
    def _verify_target(target, request):
        if target.is_symlink() or not target.is_file():
            raise RegistrationError('network_storage_drift')
        try:
            size = target.stat().st_size
            digest = _sha256_file(target)
        except OSError:
            raise RegistrationError('network_storage_drift') from None
        if size != request['size'] or digest != request['sha256']:
            raise RegistrationError('network_storage_drift')

    @staticmethod
    def _copy_exclusive(source, target):
        created = False
        try:
            with source.open('rb') as input_stream:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                with os.fdopen(descriptor, 'wb') as output_stream:
                    for chunk in iter(lambda: input_stream.read(1024 * 1024), b''):
                        output_stream.write(chunk)
            return created
        except FileExistsError:
            return False
        except OSError:
            if created:
                try:
                    target.unlink()
                except OSError:
                    pass
            raise RegistrationError('network_storage_write_failed') from None

    def _register(self, request, source):
        username = self._username()
        if not Engine.objects.filter(name=ENGINE).exists():
            raise RegistrationError('engine_missing')
        target = self._target(request)
        created_file = False
        try:
            with transaction.atomic():
                network = self._network(request, username, lock=True)
                if target.exists() or target.is_symlink():
                    self._verify_target(target, request)
                else:
                    created_file = self._copy_exclusive(source, target)
                    self._verify_target(target, request)
                if network is None:
                    network = Network.objects.create(
                        default=False,
                        was_default=False,
                        sha256=request['sha256'][:8].upper(),
                        name=request['logical_id'],
                        engine=request['engine'],
                        author=username,
                    )
                    LogEvent.objects.create(
                        author=username,
                        summary='AUTOTUNE_NETWORK_REGISTER',
                        log_file='',
                        test_id=0,
                    )
                    status = 'registered'
                else:
                    status = 'observed'
        except Exception:
            if created_file:
                try:
                    target.unlink()
                except OSError:
                    pass
            raise
        return self._receipt('register', status, request, network.sha256)

    def _get(self, request, source):
        del source
        username = self._username()
        network = self._network(request, username)
        if network is None:
            raise RegistrationError('network_not_found')
        self._verify_target(self._target(request), request)
        return self._receipt('get', 'observed', request, network.sha256)
