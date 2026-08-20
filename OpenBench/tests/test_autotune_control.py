import io
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from OpenBench.models import Engine, LogEvent, Machine, Network, Profile, Result, RuleProfile, Test
from OpenBench.rule_profiles import canonical_profile_fields

POLICY = {
    'alpha': 0.05,
    'beta': 0.10,
    'dev_time_control': '1.0+0.1',
    'base_time_control': '1.0+0.1',
    'elo_lower': 0.0,
    'elo_upper': 4.0,
    'priority': 0,
    'throughput': 1,
    'upload_pgns': True,
    'workload_size': 1,
}
OPENING = {
    'name': 'SHOGI.floodgate32-80.adjust_bishop_exchange.sfen.epd',
    'sha256': 'd' * 64,
    'source': 'https://example.invalid/opening.zip',
}
OPENBENCH_CONFIG = {
    'books': {OPENING['name']: {'sha': OPENING['sha256'], 'source': OPENING['source']}},
}


@override_settings(
    AUTOTUNE_USERNAME='autotune',
    AUTOTUNE_RATING_POLICIES={'acceptance': POLICY},
    AUTOTUNE_RATING_GAME_BUDGETS={'acceptance': 2},
)
class AutotuneControlTests(TestCase):

    def setUp(self):
        user = User.objects.create_user(username='autotune')
        user.set_unusable_password()
        user.save()
        Profile.objects.create(user=user, enabled=False, approver=False, repos={})
        self.other_user = User.objects.create_user(username='other')
        Profile.objects.create(user=self.other_user, enabled=True, approver=True, repos={})
        self.rule = RuleProfile.objects.create(**canonical_profile_fields())
        self.engine = Engine.objects.create(
            name='public-engine', source='https://example.invalid/source', sha='b' * 64, bench=1,
        )
        Network.objects.create(
            default=True,
            sha256='12345678',
            name='network',
            engine=self.engine.name,
            author='operator',
        )

    def _request(self, action, payload, schema_version=1):
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            'schema_version': schema_version,
            'action': action,
            **payload,
        }).encode('utf-8')))
        stdout = io.StringIO()
        with (
            patch('sys.stdin', stdin),
            patch(
                'OpenBench.management.commands.autotune_control.OPENBENCH_CONFIG',
                OPENBENCH_CONFIG,
            ),
        ):
            call_command('autotune_control', action, stdout=stdout)
        return json.loads(stdout.getvalue())

    def _create_payload(self):
        side = {
            'engine': self.engine.name,
            'repo': 'https://example.invalid/repository',
            'options': 'option.EnteringKingRule=CSARule24',
            'network': '12345678',
        }
        return {
            'rule_profile_id': self.rule.profile_id,
            'stage': 'acceptance',
            'policy': POLICY,
            'game_budget': 2,
            'opening': OPENING,
            'dev': side,
            'base': side,
        }

    def _source_v2(self, name, commit, bench):
        repo = 'https://github.com/example/public-engine'
        return {
            'engine': self.engine.name,
            'repo': repo,
            'source': {
                'name': name,
                'commit_sha': commit,
                'bench': bench,
            },
            'options': 'option.EnteringKingRule=CSARule24',
            'network': '12345678',
        }

    def _create_payload_v2(self):
        return {
            'rule_profile_id': self.rule.profile_id,
            'stage': 'acceptance',
            'policy': POLICY,
            'game_budget': 2,
            'opening': OPENING,
            'dev': self._source_v2('dev-source', 'a' * 40, 111),
            'base': self._source_v2('base-source', 'c' * 40, 222),
        }

    def test_create_get_and_budget_stop(self):
        created = self._request('create', self._create_payload())
        self.assertEqual(created['status'], 'created')
        test = Test.objects.get(pk=created['test_id'])
        self.assertEqual(test.author, 'autotune')
        self.assertEqual(test.rule_profile, self.rule)
        self.assertTrue(test.approved)
        self.assertEqual(test.test_mode, 'GAMES')
        self.assertEqual(test.max_games, 2)
        self.assertEqual(test.workload_size, 1)
        self.assertEqual(test.book_name, OPENING['name'])
        self.assertEqual(test.dev_book_sha, '')
        self.assertEqual(test.dev_book_name, '')
        self.assertEqual(test.base_book_sha, '')
        self.assertEqual(test.base_book_name, '')

        observed = self._request('get', {'test_id': test.id})
        self.assertEqual(observed['status'], 'observed')
        self.assertFalse(observed['state']['finished'])
        self.assertEqual(observed['stage'], 'acceptance')
        self.assertEqual(observed['policy'], POLICY)
        self.assertEqual(observed['opening'], OPENING)
        self.assertEqual(observed['dev'], self._create_payload()['dev'])
        self.assertEqual(observed['base'], self._create_payload()['base'])
        self.assertIsNone(observed['terminal_reason'])
        self.assertEqual(observed['startup'], {
            'phase': 'workload_pending',
            'ready': False,
        })
        self.assertEqual(observed['statistics']['games'], 0)
        self.assertEqual(observed['statistics']['penta'], [0, 0, 0, 0, 0])

        stopped = self._request(
            'stop', {'test_id': test.id, 'reason': 'external_game_budget'},
        )
        self.assertEqual(stopped['status'], 'stopped')

    def test_create_v2_binds_distinct_engine_sources_and_round_trips_them(self):
        payload = self._create_payload_v2()
        created = self._request('create', payload, schema_version=2)

        self.assertEqual(created['schema_version'], 2)
        self.assertEqual(created['dev'], payload['dev'])
        self.assertEqual(created['base'], payload['base'])
        test = Test.objects.get(pk=created['test_id'])
        self.assertEqual(test.dev.sha, 'a' * 40)
        self.assertEqual(test.dev.bench, 111)
        self.assertEqual(test.base.sha, 'c' * 40)
        self.assertEqual(test.base.bench, 222)

        observed = self._request('get', {'test_id': test.id}, schema_version=2)
        self.assertEqual(observed['dev'], payload['dev'])
        self.assertEqual(observed['base'], payload['base'])

    def test_get_reports_bounded_bench_validated_startup(self):
        created = self._request('create', self._create_payload())
        test = Test.objects.get(pk=created['test_id'])
        LogEvent.objects.create(
            author='worker',
            summary='AUTOTUNE_BENCH_VALIDATED',
            log_file='',
            machine_id=7,
            test_id=test.id,
        )

        observed = self._request('get', {'test_id': test.id})

        self.assertEqual(observed['startup'], {
            'phase': 'bench_validated',
            'ready': True,
        })

    def test_get_classifies_worker_bench_error_without_returning_raw_summary(self):
        created = self._request('create', self._create_payload())
        test = Test.objects.get(pk=created['test_id'])
        test.finished = True
        test.save(update_fields=('finished', 'updated'))
        raw_summary = '[tanuki] Wrong Bench: 123456'
        LogEvent.objects.create(
            author='worker',
            summary=raw_summary,
            log_file='',
            machine_id=7,
            test_id=test.id,
        )

        observed = self._request('get', {'test_id': test.id})

        self.assertEqual(observed['terminal_reason'], 'worker_wrong_bench')
        self.assertEqual(observed['terminal_diagnostic'], {
            'actual_bench': 123456,
            'expected_dev_bench': 1,
            'expected_base_bench': 1,
            'dev_engine_sha': 'b' * 64,
            'base_engine_sha': 'b' * 64,
        })
        self.assertNotIn(raw_summary, json.dumps(observed))

    def test_get_classifies_bounded_worker_game_error_before_native_result(self):
        created = self._request('create', self._create_payload())
        test = Test.objects.get(pk=created['test_id'])
        test.finished = True
        test.failed = True
        test.error = True
        test.save(update_fields=('finished', 'failed', 'error', 'updated'))
        machine = Machine.objects.create(user=self.other_user, info={})
        Result.objects.create(test=test, machine=machine, crashes=2, timeloss=3)

        observed = self._request('get', {'test_id': test.id})

        self.assertEqual(observed['terminal_reason'], 'worker_game_error')
        self.assertEqual(observed['terminal_diagnostic'], {
            'crashes': 2,
            'timelosses': 3,
            'illegal_or_unclassified': False,
        })

    def test_explicit_operator_abort_is_a_distinct_owned_stop_reason(self):
        created = self._request('create', self._create_payload())
        stopped = self._request(
            'stop',
            {'test_id': created['test_id'], 'reason': 'operator_explicit_abort'},
        )
        self.assertEqual(stopped['status'], 'stopped')
        self.assertEqual(stopped['reason'], 'operator_explicit_abort')
        self.assertTrue(Test.objects.get(pk=created['test_id']).finished)
        self.assertTrue(LogEvent.objects.filter(
            test_id=created['test_id'], summary='AUTOTUNE_OPERATOR_ABORT',
        ).exists())
        self.assertTrue(stopped['state']['finished'])

    def test_rejects_policy_mismatch_without_creating_test(self):
        payload = self._create_payload()
        payload['policy'] = {**POLICY, 'workload_size': 4}
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            'schema_version': 1,
            'action': 'create',
            **payload,
        }).encode('utf-8')))

        with (
            patch('sys.stdin', stdin),
            patch(
                'OpenBench.management.commands.autotune_control.OPENBENCH_CONFIG',
                OPENBENCH_CONFIG,
            ),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_control', 'create', stdout=stdout)

        self.assertEqual(json.loads(stdout.getvalue())['error'], 'rating_policy_mismatch')
        self.assertEqual(Test.objects.count(), 0)

    def test_rejects_game_budget_mismatch_without_creating_test(self):
        payload = self._create_payload()
        payload['game_budget'] = 4
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            'schema_version': 1,
            'action': 'create',
            **payload,
        }).encode('utf-8')))

        with (
            patch('sys.stdin', stdin),
            patch(
                'OpenBench.management.commands.autotune_control.OPENBENCH_CONFIG',
                OPENBENCH_CONFIG,
            ),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_control', 'create', stdout=stdout)

        self.assertEqual(json.loads(stdout.getvalue())['error'], 'rating_budget_mismatch')
        self.assertEqual(Test.objects.count(), 0)

    def test_rejects_engine_rule_mismatch(self):
        payload = self._create_payload()
        payload['dev'] = {**payload['dev'], 'options': 'option.EnteringKingRule=CSARule27'}
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            'schema_version': 1,
            'action': 'create',
            **payload,
        }).encode('utf-8')))

        with (
            patch('sys.stdin', stdin),
            patch(
                'OpenBench.management.commands.autotune_control.OPENBENCH_CONFIG',
                OPENBENCH_CONFIG,
            ),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_control', 'create', stdout=stdout)

        self.assertEqual(json.loads(stdout.getvalue())['error'], 'engine_rule_option_mismatch')
        self.assertEqual(Test.objects.count(), 0)

    def test_v2_rejects_non_github_engine_repository(self):
        payload = self._create_payload_v2()
        payload['dev']['repo'] = 'https://example.invalid/public-engine'
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            'schema_version': 2,
            'action': 'create',
            **payload,
        }).encode('utf-8')))

        with (
            patch('sys.stdin', stdin),
            patch(
                'OpenBench.management.commands.autotune_control.OPENBENCH_CONFIG',
                OPENBENCH_CONFIG,
            ),
            self.assertRaises(CommandError),
        ):
            call_command('autotune_control', 'create', stdout=stdout)

        self.assertEqual(json.loads(stdout.getvalue())['error'], 'engine_source_url_mismatch')
        self.assertEqual(Test.objects.count(), 0)

    def test_rejects_other_users_test(self):
        other = Test.objects.create(
            author='other',
            upload_pgns='FALSE',
            rule_profile=self.rule,
            book_name='book',
            dev=self.engine,
            dev_repo='https://example.invalid/repository',
            dev_engine=self.engine.name,
            dev_time_control='1.0+0.1',
            base=self.engine,
            base_repo='https://example.invalid/repository',
            base_engine=self.engine.name,
            base_time_control='1.0+0.1',
        )
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            'schema_version': 1,
            'action': 'stop',
            'test_id': other.id,
            'reason': 'external_game_budget',
        }).encode('utf-8')))

        with patch('sys.stdin', stdin), self.assertRaises(CommandError):
            call_command('autotune_control', 'stop', stdout=stdout)

        self.assertEqual(json.loads(stdout.getvalue())['error'], 'test_not_owned')
        other.refresh_from_db()
        self.assertFalse(other.finished)
