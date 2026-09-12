import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import goal_local_engine as local


class LocalEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Engines').mkdir()
        (self.root / 'PrivateEngines').mkdir()
        self.data = b'synthetic executable fixture; never executed'
        self.identity = {
            'kind': 'local_private',
            'artifact_id': '11111111-1111-4111-8111-111111111111',
            'binary_sha256': hashlib.sha256(self.data).hexdigest(),
            'name': 'goal-local-11111111-1111-4111-8111-111111111111', 'bench': 321,
        }
        self.side = {
            **self.identity, 'source': local.source_uri(self.identity),
            'sha': self.identity['binary_sha256'], 'private': False,
        }
        self.binary = self.root / 'Engines' / (
            self.identity['name'] + '-' + self.identity['binary_sha256'] + '.exe'
        )
        self.binary.write_bytes(self.data)
        self.metadata = self.root / 'PrivateEngines' / (self.identity['artifact_id'] + '.json')
        self.record = {'schema_version': 1, 'descriptor': self.identity, 'binary_size': len(self.data)}
        self.metadata.write_text(json.dumps(self.record), encoding='utf-8')

    def test_installed_binary_is_rehashed_instead_of_cache_trust(self):
        self.assertEqual(local.load_installed(self.side, self.root), self.binary.name)
        self.binary.write_bytes(b'x' * len(self.data))
        with self.assertRaises(local.LocalEngineError):
            local.load_installed(self.side, self.root)

    def test_source_descriptor_round_trip(self):
        self.assertEqual(local.descriptor(self.identity), self.identity)
        self.assertEqual(local.parse_source(self.side['source']), (
            self.identity['artifact_id'], self.identity['binary_sha256'],
        ))

    def test_untrusted_fields_cannot_supply_paths_build_commands_or_fallback(self):
        for key, value in (
            ('artifact_id', '../escape'), ('name', 'private-path-or-source-name'),
            ('binary_sha256', 'a' * 40), ('bench', True), ('bench', 0),
            ('kind', 'github'), ('recipe', 'compile'),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(local.LocalEngineError):
                local.descriptor({**self.identity, key: value})
        for uri in ('file:///private', 'https://example.invalid/source', self.side['source'] + '/extra'):
            with self.subTest(uri=uri), self.assertRaises(local.LocalEngineError):
                local.parse_source(uri)

    def test_missing_and_mismatched_install_fail_with_fixed_diagnostic(self):
        for override in ({'bench': 999}, {'sha': '0' * 64}, {'private': True}):
            with self.subTest(override=override), self.assertRaises(local.LocalEngineError) as error:
                local.load_installed({**self.side, **override}, self.root)
            self.assertNotIn(str(self.root), str(error.exception))
        self.metadata.write_text('{invalid private text', encoding='utf-8')
        with self.assertRaises(local.LocalEngineError):
            local.load_installed(self.side, self.root)
        self.metadata.unlink()
        with self.assertRaises(local.LocalEngineError):
            local.load_installed(self.side, self.root)

    def test_metadata_is_closed_and_version_is_not_boolean(self):
        for value in ({**self.record, 'build': 'private'}, {**self.record, 'schema_version': True}):
            self.metadata.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(local.LocalEngineError):
                local.load_installed(self.side, self.root)

    def test_hardlinked_binary_is_rejected(self):
        os.link(self.binary, self.root / 'another-link')
        with self.assertRaises(local.LocalEngineError):
            local.load_installed(self.side, self.root)

    def test_worker_local_route_never_downloads_or_compiles(self):
        import worker
        config = types.SimpleNamespace(workload={'test': {'dev': {**self.side, 'engine': 'fixture'}}})
        with patch.object(worker, 'validate_goal_fixed_move') as clock, patch.object(
            worker.goal_local_engine, 'load_installed', return_value=self.binary.name,
        ) as load, patch.object(worker.utils, 'download_public_engine') as public, patch.object(
            worker.utils, 'download_private_engine',
        ) as private:
            self.assertEqual(worker.safe_download_engine(config, 'dev', 'unused'), self.binary.name)
            clock.assert_called_once_with(config.workload)
            load.assert_called_once_with(config.workload['test']['dev'])
            public.assert_not_called()
            private.assert_not_called()


if __name__ == '__main__':
    unittest.main()
