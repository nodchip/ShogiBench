import hashlib
import json
import re
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from OpenBench.models import Book, Engine, Network


MAX_REQUEST_BYTES = 65536
MAX_MATERIAL_BYTES = 16 * 1024 * 1024 * 1024
ENGINE = 'tanuki-'
SHA256 = re.compile(r'^[0-9a-f]{64}$')


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
    help = 'Verify fixed ShogiBench network and book material without listing or mutation.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('get',))

    def handle(self, *args, **options):
        try:
            request = self._read_request(options['action'])
            result = self._get(request)
        except MaterialError as error:
            self.stdout.write(json.dumps({
                'schema_version': 1,
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
        if not isinstance(request, dict) or set(request) != {
            'schema_version', 'action', 'engine', 'network', 'book',
        }:
            raise MaterialError('invalid_request_shape')
        if request['schema_version'] != 1 or request['action'] != action:
            raise MaterialError('invalid_request_identity')
        if request['engine'] != ENGINE:
            raise MaterialError('invalid_engine')
        for label in ('network', 'book'):
            value = request[label]
            if not isinstance(value, dict) or set(value) != {'sha256', 'size'}:
                raise MaterialError(f'invalid_{label}_shape')
            if not isinstance(value['sha256'], str) or not SHA256.fullmatch(value['sha256']):
                raise MaterialError(f'invalid_{label}_sha256')
            if (
                not isinstance(value['size'], int)
                or isinstance(value['size'], bool)
                or value['size'] <= 0
                or value['size'] > MAX_MATERIAL_BYTES
            ):
                raise MaterialError(f'invalid_{label}_size')
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

    def _get(self, request):
        if not Engine.objects.filter(name=ENGINE).exists():
            raise MaterialError('engine_missing')
        network_prefix = request['network']['sha256'][:8]
        book_prefix = request['book']['sha256'][:8]
        networks = list(Network.objects.filter(engine=ENGINE, sha256__iexact=network_prefix))
        books = list(Book.objects.filter(engine=ENGINE, sha256__iexact=book_prefix))
        if len(networks) != 1:
            raise MaterialError('network_not_unique')
        if len(books) != 1:
            raise MaterialError('book_not_unique')
        network = networks[0]
        book = books[0]
        root = self._media_root()
        self._verify_file(root, network.sha256, request['network'], 'network')
        self._verify_file(root, book.sha256, request['book'], 'book')
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
            'book': {
                'id': book.sha256,
                'name': book.name,
                'sha256': request['book']['sha256'],
                'size': request['book']['size'],
            },
        }
