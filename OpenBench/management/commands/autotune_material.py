import hashlib
import json
import re
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Engine, Network

MAX_REQUEST_BYTES = 65536
MAX_MATERIAL_BYTES = 16 * 1024 * 1024 * 1024
ENGINE = 'tanuki-'
OPENING_NAME = 'SHOGI.floodgate32-80.adjust_bishop_exchange.sfen.epd'
SHA256 = re.compile(r'^[0-9a-f]{64}$')
GIT_SHA = re.compile(r'^[0-9a-f]{40}$')


class MaterialError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = 'Verify fixed ShogiBench network and opening configuration without mutation.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('get', 'inspect'))

    def handle(self, *args, **options):
        try:
            request = self._read_request(options['action'])
            result = self._get(request) if options['action'] == 'get' else self._inspect(request)
        except MaterialError as error:
            self.stdout.write(json.dumps({
                'schema_version': locals().get('request', {}).get('schema_version', 1),
                'action': options['action'],
                'status': 'rejected',
                'error': error.code,
            }, sort_keys=True, separators=(',', ':')))
            raise CommandError('autotune_material rejected') from None
        return json.dumps(result, sort_keys=True, separators=(',', ':'))

    @staticmethod
    def _read_request(action):
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise MaterialError('request_too_large')
        try:
            request = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MaterialError('invalid_json') from None
        fields = (
            {'schema_version', 'action', 'engine', 'network', 'opening'}
            if action == 'get'
            else {
                'schema_version', 'action', 'engine', 'network_sha256',
                'opening_name', 'opening_sha256',
            }
        )
        if not isinstance(request, dict) or set(request) != fields:
            raise MaterialError('invalid_request_shape')
        allowed_versions = (1, 2) if action == 'inspect' else (1,)
        if request['schema_version'] not in allowed_versions or request['action'] != action:
            raise MaterialError('invalid_request_identity')
        if request['engine'] != ENGINE:
            raise MaterialError('invalid_engine')
        if action == 'inspect':
            for label in ('network_sha256', 'opening_sha256'):
                if not isinstance(request[label], str) or not SHA256.fullmatch(request[label]):
                    raise MaterialError(f'invalid_{label}')
            if request['opening_name'] != OPENING_NAME:
                raise MaterialError('invalid_opening_name')
            return request
        network = request['network']
        if not isinstance(network, dict) or set(network) != {'sha256', 'size'}:
            raise MaterialError('invalid_network_shape')
        if not isinstance(network['sha256'], str) or not SHA256.fullmatch(network['sha256']):
            raise MaterialError('invalid_network_sha256')
        if (
            not isinstance(network['size'], int)
            or isinstance(network['size'], bool)
            or network['size'] <= 0
            or network['size'] > MAX_MATERIAL_BYTES
        ):
            raise MaterialError('invalid_network_size')
        opening = request['opening']
        if not isinstance(opening, dict) or set(opening) != {'name', 'sha256', 'source'}:
            raise MaterialError('invalid_opening_shape')
        if (
            opening['name'] != OPENING_NAME
            or not isinstance(opening['sha256'], str)
            or not SHA256.fullmatch(opening['sha256'])
            or not isinstance(opening['source'], str)
            or not opening['source']
        ):
            raise MaterialError('invalid_opening_value')
        return request

    @staticmethod
    def _media_root():
        value = settings.MEDIA_ROOT
        if not isinstance(value, str):
            raise MaterialError('media_root_invalid')
        root = Path(value)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise MaterialError('media_root_invalid')
        return root.resolve(strict=True)

    @staticmethod
    def _verify_file(root, identifier, expected, label):
        path = root / identifier
        if path.is_symlink() or not path.is_file():
            raise MaterialError(f'{label}_storage_missing')
        try:
            resolved = path.resolve(strict=True)
            size = resolved.stat().st_size
            digest = _sha256_file(resolved)
        except OSError:
            raise MaterialError(f'{label}_storage_unreadable') from None
        if resolved.parent != root:
            raise MaterialError(f'{label}_storage_invalid')
        if size != expected['size'] or digest != expected['sha256']:
            raise MaterialError(f'{label}_storage_mismatch')

    @staticmethod
    def _inspect_file(root, identifier, expected_sha256, label):
        path = root / identifier
        if path.is_symlink() or not path.is_file():
            raise MaterialError(f'{label}_storage_missing')
        try:
            resolved = path.resolve(strict=True)
            size = resolved.stat().st_size
            digest = _sha256_file(resolved)
        except OSError:
            raise MaterialError(f'{label}_storage_unreadable') from None
        if resolved.parent != root:
            raise MaterialError(f'{label}_storage_invalid')
        if digest != expected_sha256:
            raise MaterialError(f'{label}_storage_mismatch')
        return size

    @staticmethod
    def _network(network_sha256, allow_duplicate=False):
        if not Engine.objects.filter(name=ENGINE).exists():
            raise MaterialError('engine_missing')
        networks = list(
            Network.objects.filter(
                engine=ENGINE,
                sha256__iexact=network_sha256[:8],
            ).order_by('id')
        )
        if not networks or (len(networks) != 1 and not allow_duplicate):
            raise MaterialError('network_not_unique')
        return networks[0]

    @staticmethod
    def _engine_source():
        engines = list(Engine.objects.filter(name=ENGINE))
        if len(engines) != 1:
            raise MaterialError('engine_not_unique')
        engine = engines[0]
        if (
            not isinstance(engine.source, str)
            or not engine.source.startswith('https://github.com/')
            or not GIT_SHA.fullmatch(engine.sha)
            or engine.source != engine.source.rsplit('/archive/', 1)[0] + '/archive/' + engine.sha + '.zip'
            or isinstance(engine.bench, bool)
            or not isinstance(engine.bench, int)
            or engine.bench <= 0
            or engine.bench > 2**63 - 1
        ):
            raise MaterialError('engine_source_invalid')
        return {
            'name': engine.name,
            'repository': engine.source.rsplit('/archive/', 1)[0],
            'commit_sha': engine.sha,
            'bench': engine.bench,
        }

    @staticmethod
    def _opening(name, sha256, source=None):
        books = OPENBENCH_CONFIG.get('books') if isinstance(OPENBENCH_CONFIG, dict) else None
        opening = books.get(name) if isinstance(books, dict) else None
        if (
            name != OPENING_NAME
            or not isinstance(opening, dict)
            or set(opening) != {'sha', 'source'}
            or opening.get('sha') != sha256
            or not isinstance(opening.get('source'), str)
            or not opening['source']
            or (source is not None and opening['source'] != source)
        ):
            raise MaterialError('opening_config_mismatch')
        return opening

    def _get(self, request):
        network = self._network(request['network']['sha256'])
        opening = self._opening(
            request['opening']['name'],
            request['opening']['sha256'],
            request['opening']['source'],
        )
        root = self._media_root()
        self._verify_file(root, network.sha256, request['network'], 'network')
        return {
            'schema_version': 1,
            'action': 'get',
            'status': 'observed',
            'engine': ENGINE,
            'network': {
                'id': network.sha256,
                'name': network.name,
                'sha256': request['network']['sha256'],
                'size': request['network']['size'],
                'default': network.default,
            },
            'opening': {
                'name': request['opening']['name'],
                'sha256': request['opening']['sha256'],
                'source': opening['source'],
            },
        }

    def _inspect(self, request):
        network = self._network(
            request['network_sha256'],
            allow_duplicate=request['schema_version'] == 2,
        )
        opening = self._opening(request['opening_name'], request['opening_sha256'])
        root = self._media_root()
        network_size = self._inspect_file(
            root, network.sha256, request['network_sha256'], 'network',
        )
        result = {
            'schema_version': request['schema_version'],
            'action': 'inspect',
            'status': 'observed',
            'engine': ENGINE,
            'network': {
                'id': network.sha256,
                'name': network.name,
                'sha256': request['network_sha256'],
                'size': network_size,
                'default': network.default,
            },
            'opening': {
                'name': request['opening_name'],
                'sha256': request['opening_sha256'],
                'source': opening['source'],
            },
        }
        if request['schema_version'] == 2:
            result['engine_source'] = self._engine_source()
        return result
