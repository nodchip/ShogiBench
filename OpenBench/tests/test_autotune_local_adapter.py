import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings


class AutotuneLocalAdapterTests(SimpleTestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manage = self.root / 'manage.py'
        self.manage.write_text('raise SystemExit(0)\n', encoding='utf-8')
        self.config = self.root / 'local.json'
        self.config.write_text('{}\n', encoding='utf-8')

    def tearDown(self):
        self.temporary.cleanup()

    def _environment(self):
        return patch.dict(os.environ, {
            'DJANGO_SETTINGS_MODULE': 'OpenSite.settings_windows',
            'SHOGIBENCH_LOCAL_CONFIG_PATH': str(self.config.resolve()),
        })

    @staticmethod
    def _completed(action, status, schema_version=1):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({
                'schema_version': schema_version,
                'action': action,
                'status': status,
            }).encode('utf-8'),
            stderr=b'',
        )

    def test_loopback_network_registration_uses_only_fixed_command_and_environment(self):
        calls = []
        body = json.dumps({'schema_version': 1, 'action': 'register'}).encode('utf-8')

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return self._completed('register', 'registered')

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/network/register/',
                data=body,
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'registered')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], (
            sys.executable,
            str(self.manage),
            'autotune_register_network',
            'register',
            '--settings',
            'OpenSite.settings_windows',
        ))
        self.assertEqual(calls[0][1]['input'], body)
        self.assertNotIn('PATH', calls[0][1]['env'])
        self.assertEqual(set(calls[0][1]['env']) - {
            'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP',
        }, {'DJANGO_SETTINGS_MODULE', 'SHOGIBENCH_LOCAL_CONFIG_PATH'})
        self.assertNotIn('shell', calls[0][1])

    def test_rating_actions_map_to_fixed_control_command(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            return self._completed('get', 'observed')

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='::1').post(
                '/api/autotune-local/v1/rating/get/',
                data=b'{"schema_version":1,"action":"get"}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0][2:4], ('autotune_control', 'get'))

    def test_rating_schema_v2_is_forwarded_and_requires_v2_response(self):
        calls = []
        body = b'{"schema_version":2,"action":"get","test_id":7}'

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return self._completed('get', 'observed', schema_version=2)

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/rating/get/',
                data=body,
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['schema_version'], 2)
        self.assertEqual(calls[0][1]['input'], body)

    def test_non_rating_target_rejects_schema_v2_without_spawn(self):
        with patch('OpenBench.autotune_local_adapter.subprocess.run') as runner:
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/network/get/',
                data=b'{"schema_version":2,"action":"get"}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'request_identity_invalid')
        runner.assert_not_called()

    def test_rating_schema_v3_reconciles_without_protocol_downgrade(self):
        body = b'{"schema_version":3,"action":"get","test_id":7}'
        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', return_value=self._completed(
                'get', 'observed', schema_version=3,
            )) as runner,
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/rating/get/', data=body, content_type='application/json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['schema_version'], 3)
        self.assertEqual(runner.call_args.kwargs['input'], body)

    def test_private_protocol_cannot_expand_material_or_network_contracts(self):
        for target in ('material', 'network'):
            with self.subTest(target=target), patch('OpenBench.autotune_local_adapter.subprocess.run') as runner:
                response = Client(REMOTE_ADDR='127.0.0.1').post(
                    '/api/autotune-local/v1/%s/get/' % target,
                    data=b'{"schema_version":3,"action":"get"}', content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)
                runner.assert_not_called()

    def test_material_get_maps_to_fixed_read_only_command(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            return self._completed('get', 'observed')

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/material/get/',
                data=b'{"schema_version":1,"action":"get"}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0][2:4], ('autotune_material', 'get'))

    def test_material_inspect_maps_to_fixed_read_only_command(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            return self._completed('inspect', 'observed')

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/material/inspect/',
                data=b'{"schema_version":1,"action":"inspect"}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0][2:4], ('autotune_material', 'inspect'))

    def test_material_inspect_schema_v2_is_forwarded(self):
        calls = []
        body = b'{"schema_version":2,"action":"inspect"}'

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return self._completed('inspect', 'observed', schema_version=2)

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/material/inspect/',
                data=body,
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['schema_version'], 2)
        self.assertEqual(calls[0][1]['input'], body)

    def test_lan_unknown_action_and_wrong_method_never_spawn(self):
        with patch('OpenBench.autotune_local_adapter.subprocess.run') as runner:
            lan = Client(REMOTE_ADDR='192.0.2.10').post(
                '/api/autotune-local/v1/network/register/',
                data=b'{}',
                content_type='application/json',
            )
            unknown = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/network/delete/',
                data=b'{}',
                content_type='application/json',
            )
            method = Client(REMOTE_ADDR='127.0.0.1').get(
                '/api/autotune-local/v1/rating/get/',
            )

        self.assertEqual(lan.status_code, 403)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(method.status_code, 405)
        runner.assert_not_called()

    def test_timeout_is_unknown_and_not_retried(self):
        calls = 0

        def runner(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])

        with (
            override_settings(BASE_DIR=self.root.resolve()),
            self._environment(),
            patch('OpenBench.autotune_local_adapter.subprocess.run', runner),
        ):
            response = Client(REMOTE_ADDR='127.0.0.1').post(
                '/api/autotune-local/v1/rating/create/',
                data=b'{"schema_version":1,"action":"create"}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'operation_outcome_unknown')
        self.assertEqual(calls, 1)
