import hashlib
import io
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from OpenBench.models import Book, Engine, LogEvent, Network, Profile


class AutotuneRegisterNetworkTests(TestCase):

    def setUp(self):
        user = User.objects.create_user(username='autotune')
        user.set_unusable_password()
        user.save()
        Profile.objects.create(user=user, enabled=False, approver=False, repos={})
        Engine.objects.create(
            name='tanuki-', source='https://example.invalid/source', sha='b' * 64, bench=1,
        )
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / 'artifacts'
        self.media = self.root / 'Media'
        self.artifacts.mkdir()
        self.media.mkdir()
        self.request_id = str(uuid.uuid4())
        request_directory = self.artifacts / self.request_id
        request_directory.mkdir()
        self.content = b'fixed candidate network\n'
        (request_directory / 'candidate-network.bin').write_bytes(self.content)
        self.digest = hashlib.sha256(self.content).hexdigest()

    def tearDown(self):
        self.temporary.cleanup()

    def _payload(self, action, **changes):
        value = {
            'schema_version': 1,
            'action': action,
            'request_id': self.request_id,
            'logical_id': 'goal-candidate-v3',
            'engine': 'tanuki-',
            'sha256': self.digest,
            'size': len(self.content),
        }
        value.update(changes)
        return value

    def _call(self, action, payload=None):
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(
            payload or self._payload(action),
        ).encode('utf-8')))
        stdout = io.StringIO()
        settings = {
            'AUTOTUNE_USERNAME': 'autotune',
            'AUTOTUNE_TRAINING_ARTIFACT_ROOT': str(self.artifacts.resolve()),
            'MEDIA_ROOT': str(self.media.resolve()),
        }
        with override_settings(**settings), patch('sys.stdin', stdin):
            call_command('autotune_register_network', action, stdout=stdout)
        return json.loads(stdout.getvalue())

    def _reject(self, action, payload):
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode('utf-8')))
        settings = {
            'AUTOTUNE_USERNAME': 'autotune',
            'AUTOTUNE_TRAINING_ARTIFACT_ROOT': str(self.artifacts.resolve()),
            'MEDIA_ROOT': str(self.media.resolve()),
        }
        with (
            override_settings(**settings),
            patch('sys.stdin', stdin),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_register_network', action, stdout=stdout)
        return json.loads(stdout.getvalue())

    def test_register_get_and_idempotent_reconcile(self):
        registered = self._call('register')
        self.assertEqual(registered['status'], 'registered')
        self.assertEqual(registered['network_id'], self.digest[:8].upper())
        network = Network.objects.get()
        self.assertEqual(network.author, 'autotune')
        self.assertFalse(network.default)
        self.assertEqual((self.media / network.sha256).read_bytes(), self.content)
        self.assertEqual(LogEvent.objects.get().summary, 'AUTOTUNE_NETWORK_REGISTER')

        reconciled = self._call('register')
        self.assertEqual(reconciled['status'], 'observed')
        observed = self._call('get')
        self.assertEqual(observed['status'], 'observed')
        self.assertEqual(Network.objects.count(), 1)
        self.assertEqual(LogEvent.objects.count(), 1)

    def test_hash_and_size_mismatch_do_not_mutate(self):
        rejected = self._reject(
            'register', self._payload('register', sha256='0' * 64),
        )
        self.assertEqual(rejected['error'], 'artifact_hash_mismatch')
        rejected = self._reject(
            'register', self._payload('register', size=len(self.content) + 1),
        )
        self.assertEqual(rejected['error'], 'artifact_size_mismatch')
        self.assertFalse(Network.objects.exists())
        self.assertEqual(list(self.media.iterdir()), [])

    def test_rejects_unknown_fields_and_request_paths(self):
        payload = self._payload('register')
        payload['path'] = str(self.artifacts / self.request_id / 'candidate-network.bin')
        rejected = self._reject('register', payload)
        self.assertEqual(rejected['error'], 'invalid_request_shape')
        self.assertFalse(Network.objects.exists())

    def test_rejects_foreign_prefix_name_and_storage_conflicts(self):
        prefix = self.digest[:8].upper()
        Network.objects.create(
            sha256=prefix,
            name='foreign',
            engine='tanuki-',
            author='operator',
        )
        rejected = self._reject('register', self._payload('register'))
        self.assertEqual(rejected['error'], 'network_id_conflict')
        Network.objects.all().delete()

        Network.objects.create(
            sha256='12345678',
            name='goal-candidate-v3',
            engine='tanuki-',
            author='operator',
        )
        rejected = self._reject('register', self._payload('register'))
        self.assertEqual(rejected['error'], 'network_name_conflict')
        Network.objects.all().delete()

        Book.objects.create(
            sha256=prefix,
            name='collision',
            engine='tanuki-',
            author='operator',
        )
        rejected = self._reject('register', self._payload('register'))
        self.assertEqual(rejected['error'], 'network_storage_conflict')
        self.assertFalse(Network.objects.exists())

    def test_get_is_read_only_and_detects_storage_drift(self):
        self._call('register')
        network = Network.objects.get()
        log_count = LogEvent.objects.count()
        (self.media / network.sha256).write_bytes(b'drift')
        rejected = self._reject('get', self._payload('get'))
        self.assertEqual(rejected['error'], 'network_storage_drift')
        self.assertEqual(Network.objects.count(), 1)
        self.assertEqual(LogEvent.objects.count(), log_count)
