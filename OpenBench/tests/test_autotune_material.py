import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from OpenBench.models import Book, Engine, Network


class AutotuneMaterialTests(TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.media = Path(self.temporary.name)
        self.network_bytes = b'champion network\n'
        self.book_bytes = b'opening book\n'
        self.network_hash = hashlib.sha256(self.network_bytes).hexdigest()
        self.book_hash = hashlib.sha256(self.book_bytes).hexdigest()
        Engine.objects.create(
            name='tanuki-', source='https://example.invalid/source', sha='b' * 64, bench=1,
        )
        self.network = Network.objects.create(
            default=True,
            sha256=self.network_hash[:8].lower(),
            name='champion',
            engine='tanuki-',
            author='bootstrap',
        )
        self.book = Book.objects.create(
            sha256=self.book_hash[:8].upper(),
            name='SHOGI.floodgate32-80.adjust_bishop_exchange.sfen.epd',
            engine='tanuki-',
            author='bootstrap',
        )
        (self.media / self.network.sha256).write_bytes(self.network_bytes)
        (self.media / self.book.sha256).write_bytes(self.book_bytes)

    def tearDown(self):
        self.temporary.cleanup()

    def _payload(self, **changes):
        value = {
            'schema_version': 1,
            'action': 'get',
            'engine': 'tanuki-',
            'network': {'sha256': self.network_hash, 'size': len(self.network_bytes)},
            'book': {'sha256': self.book_hash, 'size': len(self.book_bytes)},
        }
        value.update(changes)
        return value

    def _call(self, payload, action='get'):
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode('utf-8')))
        stdout = io.StringIO()
        with override_settings(MEDIA_ROOT=str(self.media.resolve())), patch('sys.stdin', stdin):
            call_command('autotune_material', action, stdout=stdout)
        return json.loads(stdout.getvalue())

    def test_get_verifies_full_material_and_returns_actual_ids(self):
        result = self._call(self._payload())
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['network']['id'], self.network.sha256)
        self.assertEqual(result['book']['id'], self.book.sha256)
        self.assertEqual(result['network']['sha256'], self.network_hash)
        self.assertEqual(result['book']['sha256'], self.book_hash)

    def test_get_rejects_storage_mismatch_and_unknown_shape_without_mutation(self):
        (self.media / self.network.sha256).write_bytes(b'drift')
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(self._payload()).encode('utf-8')))
        with (
            override_settings(MEDIA_ROOT=str(self.media.resolve())),
            patch('sys.stdin', stdin),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_material', 'get', stdout=stdout)
        self.assertEqual(json.loads(stdout.getvalue())['error'], 'network_storage_mismatch')
        self.assertEqual(Network.objects.count(), 1)
        self.assertEqual(Book.objects.count(), 1)

    def test_inspect_requires_full_hashes_and_returns_verified_sizes(self):
        result = self._call({
            'schema_version': 1,
            'action': 'inspect',
            'engine': 'tanuki-',
            'network_sha256': self.network_hash,
            'book_sha256': self.book_hash,
        }, action='inspect')
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['network']['id'], self.network.sha256)
        self.assertEqual(result['network']['size'], len(self.network_bytes))
        self.assertEqual(result['book']['id'], self.book.sha256)
        self.assertEqual(result['book']['size'], len(self.book_bytes))

    def test_inspect_rejects_hash_mismatch_without_listing_or_mutation(self):
        stdout = io.StringIO()
        payload = {
            'schema_version': 1,
            'action': 'inspect',
            'engine': 'tanuki-',
            'network_sha256': self.network_hash,
            'book_sha256': '0' * 64,
        }
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode('utf-8')))
        with (
            override_settings(MEDIA_ROOT=str(self.media.resolve())),
            patch('sys.stdin', stdin),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_material', 'inspect', stdout=stdout)
        self.assertEqual(json.loads(stdout.getvalue())['error'], 'book_storage_mismatch')
        self.assertEqual(Network.objects.count(), 1)
        self.assertEqual(Book.objects.count(), 1)
