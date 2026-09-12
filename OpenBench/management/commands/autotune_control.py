import json
import math
import re
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Engine, LogEvent, Network, Profile, RuleProfile, Test
from OpenBench.rule_profiles import CANONICAL_PROFILE_ID, options_select_canonical_rule
from OpenBench import goal_fixed_move
from Client import goal_local_engine

MAX_REQUEST_BYTES = 65536
OPENING_NAME = 'SHOGI.floodgate32-80.adjust_bishop_exchange.sfen.epd'
WRONG_BENCH = re.compile(r'wrong bench:\s*(\d{1,19})\s*$', re.IGNORECASE)
GIT_SHA = re.compile(r'^[0-9a-f]{40}$')


class ControlError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _exact_object(value, fields, code):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ControlError(code)
    return value


def _state(test):
    return {
        'approved': test.approved,
        'failed': test.failed,
        'finished': test.finished,
        'passed': test.passed,
    }


def _response(schema_version, action, status, **values):
    return {
        'schema_version': schema_version,
        'action': action,
        'status': status,
        **values,
    }


def _terminal_outcome(test):
    if not test.finished:
        return None, None
    if test.error:
        failures = test.test.aggregate(
            crashes=Sum('crashes'),
            timelosses=Sum('timeloss'),
        )
        crashes = failures['crashes'] or 0
        timelosses = failures['timelosses'] or 0
        return 'worker_game_error', {
            'crashes': crashes,
            'timelosses': timelosses,
            'illegal_or_unclassified': crashes == 0,
        }
    if test.passed:
        return 'native_pass', None
    if test.failed:
        return 'native_fail', None
    events = LogEvent.objects.filter(test_id=test.id).order_by('-id')[:16]
    for event in events:
        if event.summary == 'AUTOTUNE_BUDGET_STOP':
            return 'external_game_budget', None
        if event.summary == 'AUTOTUNE_OPERATOR_ABORT':
            return 'operator_explicit_abort', None
        if event.machine_id:
            summary = event.summary.lower()
            if 'wrong bench' in summary:
                match = WRONG_BENCH.search(event.summary)
                actual = int(match.group(1)) if match else None
                diagnostic = None if actual is None or actual > 2**63 - 1 else {
                    'actual_bench': actual,
                    'expected_dev_bench': test.dev.bench,
                    'expected_base_bench': test.base.bench,
                    'dev_engine_sha': test.dev.sha,
                    'base_engine_sha': test.base.sha,
                }
                return 'worker_wrong_bench', diagnostic
            if 'non-deterministic benches' in summary:
                return 'worker_nondeterministic_bench', None
            if 'bench exceeded max duration' in summary:
                return 'worker_bench_timeout', None
            if 'failed to execute benchmark' in summary:
                return 'worker_bench_execution_failed', None
            return 'worker_error', None
    return 'external_or_unknown_terminal', None


def _startup_state(test):
    if test.games > 0:
        return {'phase': 'games_started', 'ready': True}
    validated = LogEvent.objects.filter(
        test_id=test.id,
        machine_id__gt=0,
        summary='AUTOTUNE_BENCH_VALIDATED',
    ).exists()
    if validated:
        return {'phase': 'bench_validated', 'ready': True}
    return {'phase': 'workload_pending', 'ready': False}


def _policy_from_test(test):
    return {
        'alpha': test.alpha,
        'beta': test.beta,
        'dev_time_control': test.dev_time_control,
        'base_time_control': test.base_time_control,
        'elo_lower': test.elolower,
        'elo_upper': test.eloupper,
        'priority': test.priority,
        'throughput': test.throughput,
        'workload_size': test.workload_size,
        'upload_pgns': test.upload_pgns == 'TRUE',
    }


def _side_from_test(test, prefix, schema_version):
    side = {
        'engine': getattr(test, f'{prefix}_engine'),
        'repo': getattr(test, f'{prefix}_repo'),
        'options': getattr(test, f'{prefix}_options'),
        'network': getattr(test, f'{prefix}_network'),
    }
    engine = getattr(test, prefix)
    if engine.source.startswith('goal-local'):
        if schema_version != 3 or side['repo'] != '':
            raise ControlError('test_engine_source_not_reconcilable')
        try:
            artifact_id, binary_sha = goal_local_engine.parse_source(engine.source)
            side['source'] = goal_local_engine.descriptor({
                'kind': 'local_private', 'artifact_id': artifact_id,
                'binary_sha256': binary_sha, 'name': engine.name, 'bench': engine.bench,
            })
            if engine.sha != binary_sha:
                raise goal_local_engine.LocalEngineError()
        except goal_local_engine.LocalEngineError:
            raise ControlError('test_engine_source_not_reconcilable') from None
    elif schema_version in (2, 3):
        engine = getattr(test, prefix)
        expected_url = side['repo'].rstrip('/') + '/archive/' + engine.sha + '.zip'
        if not GIT_SHA.fullmatch(engine.sha) or engine.source != expected_url:
            raise ControlError('test_engine_source_not_reconcilable')
        side['source'] = {
            'name': engine.name,
            'commit_sha': engine.sha,
            'bench': engine.bench,
        }
    return side


def _opening_from_test(test):
    books = OPENBENCH_CONFIG.get('books') if isinstance(OPENBENCH_CONFIG, dict) else None
    opening = books.get(test.book_name) if isinstance(books, dict) else None
    if (
        test.book_name != OPENING_NAME
        or not isinstance(opening, dict)
        or set(opening) != {'sha', 'source'}
        or not all(isinstance(opening[name], str) and opening[name] for name in opening)
    ):
        raise ControlError('test_opening_not_reconcilable')
    return {
        'name': test.book_name,
        'sha256': opening['sha'],
        'source': opening['source'],
    }


def _stage_from_test(test):
    fixed_stage = goal_fixed_move.stage_for_test(test)
    if fixed_stage is not None:
        return fixed_stage
    observed = _policy_from_test(test)
    policies = getattr(settings, 'AUTOTUNE_RATING_POLICIES', {})
    budgets = getattr(settings, 'AUTOTUNE_RATING_GAME_BUDGETS', {})
    matches = [
        name for name, policy in policies.items()
        if policy == observed and budgets.get(name) == test.max_games
    ]
    if len(matches) != 1:
        raise ControlError('test_policy_not_reconcilable')
    return matches[0]


def _observation(test, stage=None, schema_version=1):
    terminal_reason, terminal_diagnostic = _terminal_outcome(test)
    observation = {
        'test_id': test.id,
        'rule_profile_id': test.rule_profile_id,
        'stage': stage or _stage_from_test(test),
        'policy': _policy_from_test(test),
        'opening': _opening_from_test(test),
        'dev': _side_from_test(test, 'dev', schema_version),
        'base': _side_from_test(test, 'base', schema_version),
        'test_mode': test.test_mode,
        'max_games': test.max_games,
        'state': _state(test),
        'startup': _startup_state(test),
        'terminal_reason': terminal_reason,
        'terminal_diagnostic': terminal_diagnostic,
        'statistics': {
            'games': test.games,
            'wins': test.wins,
            'losses': test.losses,
            'draws': test.draws,
            'penta': [test.LL, test.LD, test.DD, test.DW, test.WW],
            'llr': {
                'lower': test.lowerllr,
                'current': test.currentllr,
                'upper': test.upperllr,
            },
        },
        'created_at': test.creation.isoformat(),
        'updated_at': test.updated.isoformat(),
    }
    if goal_fixed_move.stage_for_test(test) is not None:
        observation['timing'] = goal_fixed_move.timing_for_options(test.dev_options)
        errors = test.test.aggregate(
            engine_errors=Sum('crashes'), time_losses=Sum('timeloss'),
            illegal_moves=Sum('illegal_moves'),
        )
        observation['statistics']['errors'] = {name: value or 0 for name, value in errors.items()}
    return observation


class Command(BaseCommand):
    help = 'Perform one policy-bounded autotune create, get, or stop operation.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('create', 'get', 'stop'))

    def handle(self, *args, **options):
        action = options['action']
        schema_version = 1
        try:
            request = self._read_request(action)
            schema_version = request['schema_version']
            if action == 'create':
                result = self._create(request)
            elif action == 'get':
                result = self._get(request)
            else:
                result = self._stop(request)
        except ControlError as error:
            self.stdout.write(json.dumps(
                _response(schema_version, action, 'rejected', error=error.code),
                sort_keys=True,
                separators=(',', ':'),
            ))
            raise CommandError('autotune_control rejected') from None

        return json.dumps(result, sort_keys=True, separators=(',', ':'))

    def _read_request(self, action):
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ControlError('request_too_large')
        try:
            request = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ControlError('invalid_json') from None
        _exact_object(request, self._request_fields(action), 'invalid_request_shape')
        if type(request['schema_version']) is not int or request['schema_version'] not in (1, 2, 3) or request['action'] != action:
            raise ControlError('invalid_request_identity')
        return request

    @staticmethod
    def _request_fields(action):
        if action == 'create':
            return (
                'schema_version', 'action', 'rule_profile_id', 'stage', 'policy',
                'game_budget', 'opening', 'dev', 'base',
            )
        if action == 'get':
            return ('schema_version', 'action', 'test_id')
        return ('schema_version', 'action', 'test_id', 'reason')

    @staticmethod
    def _username():
        username = getattr(settings, 'AUTOTUNE_USERNAME', '')
        if not isinstance(username, str) or not username or len(username) > 64:
            raise ControlError('autotune_identity_unconfigured')
        return username

    @staticmethod
    def _profile():
        try:
            profile = RuleProfile.objects.get(pk=CANONICAL_PROFILE_ID)
        except RuleProfile.DoesNotExist:
            raise ControlError('canonical_profile_missing') from None
        return profile

    @staticmethod
    def _actor(username):
        try:
            actor = Profile.objects.select_related('user').get(user__username=username)
        except Profile.DoesNotExist:
            raise ControlError('autotune_identity_missing') from None
        if actor.approver or actor.user.has_usable_password():
            raise ControlError('autotune_identity_has_excess_capability')
        return actor

    @staticmethod
    def _policy(stage, supplied):
        if stage in goal_fixed_move.policies() and supplied == goal_fixed_move.policies()[stage]:
            return supplied
        policies = getattr(settings, 'AUTOTUNE_RATING_POLICIES', {})
        if not isinstance(policies, dict) or stage not in policies:
            raise ControlError('unknown_stage')
        expected = policies[stage]
        if not isinstance(expected, dict) or supplied != expected:
            raise ControlError('rating_policy_mismatch')
        required = {
            'alpha', 'beta', 'dev_time_control', 'base_time_control',
            'elo_lower', 'elo_upper', 'priority', 'throughput',
            'workload_size', 'upload_pgns',
        }
        if set(expected) != required:
            raise ControlError('configured_policy_invalid')
        return expected

    @staticmethod
    def _game_budget(stage, supplied):
        budgets = getattr(settings, 'AUTOTUNE_RATING_GAME_BUDGETS', {})
        if not isinstance(budgets, dict) or stage not in budgets:
            raise ControlError('configured_policy_invalid')
        expected = budgets[stage]
        if (
            isinstance(expected, bool)
            or not isinstance(expected, int)
            or expected < 2
            or expected > 1000000
            or expected % 2
        ):
            raise ControlError('configured_policy_invalid')
        if supplied != expected:
            raise ControlError('rating_budget_mismatch')
        return expected

    @staticmethod
    def _source(value, repo):
        source = _exact_object(
            value,
            ('name', 'commit_sha', 'bench'),
            'invalid_engine_source_shape',
        )
        if (
            not isinstance(source['name'], str)
            or not source['name']
            or len(source['name']) > 128
            or not isinstance(source['commit_sha'], str)
            or not GIT_SHA.fullmatch(source['commit_sha'])
            or isinstance(source['bench'], bool)
            or not isinstance(source['bench'], int)
            or source['bench'] <= 0
            or source['bench'] > 2**63 - 1
        ):
            raise ControlError('invalid_engine_source_value')
        expected_url = repo.rstrip('/') + '/archive/' + source['commit_sha'] + '.zip'
        if not expected_url.startswith('https://github.com/'):
            raise ControlError('engine_source_url_mismatch')
        same_name = Engine.objects.filter(name=source['name'])
        exact = same_name.filter(
            source=expected_url, sha=source['commit_sha'], bench=source['bench'],
        )
        if exact.count() > 1 or (same_name.exists() and not exact.exists()):
            raise ControlError('engine_source_identity_conflict')
        if exact.exists():
            return exact.get()
        return Engine.objects.create(
            name=source['name'],
            source=expected_url,
            sha=source['commit_sha'],
            bench=source['bench'],
        )

    @staticmethod
    def _local_source(value, repo):
        try:
            source = goal_local_engine.descriptor(value)
        except goal_local_engine.LocalEngineError:
            raise ControlError('invalid_local_engine_source') from None
        if repo != '':
            raise ControlError('invalid_local_engine_repository')
        expected = {
            'source': goal_local_engine.source_uri(source),
            'sha': source['binary_sha256'], 'bench': source['bench'],
        }
        matches = list(Engine.objects.filter(
            Q(name=source['name']) | Q(source__startswith=(
                goal_local_engine.SOURCE_PREFIX + source['artifact_id'] + ':'
            )),
        )[:2])
        if matches:
            if (
                len(matches) != 1 or matches[0].name != source['name']
                or any(getattr(matches[0], key) != value for key, value in expected.items())
            ):
                raise ControlError('engine_source_identity_conflict')
            return matches[0]
        return Engine.objects.create(name=source['name'], **expected)

    @staticmethod
    def _side(value, schema_version):
        fields = ('engine', 'repo', 'options', 'network')
        if schema_version in (2, 3):
            fields = (*fields, 'source')
        side = _exact_object(
            value,
            fields,
            'invalid_engine_shape',
        )
        if not all(
            isinstance(side[name], str)
            for name in ('engine', 'repo', 'options', 'network')
        ):
            raise ControlError('invalid_engine_value')
        if not options_select_canonical_rule(side['options']):
            raise ControlError('engine_rule_option_mismatch')
        try:
            network = Network.objects.get(engine=side['engine'], sha256=side['network'])
            engine = (
                Engine.objects.get(name=side['engine'])
                if schema_version == 1
                else Command._local_source(side['source'], side['repo'])
                if schema_version == 3 and isinstance(side['source'], dict) and side['source'].get('kind') == 'local_private'
                else Command._source(side['source'], side['repo'])
            )
        except (Engine.DoesNotExist, Network.DoesNotExist, Engine.MultipleObjectsReturned):
            raise ControlError('engine_material_missing') from None
        return side, engine, network

    @staticmethod
    def _opening(value):
        opening = _exact_object(
            value,
            ('name', 'sha256', 'source'),
            'invalid_opening_shape',
        )
        if not all(isinstance(opening[name], str) and opening[name] for name in opening):
            raise ControlError('invalid_opening_value')
        books = OPENBENCH_CONFIG.get('books') if isinstance(OPENBENCH_CONFIG, dict) else None
        configured = books.get(opening['name']) if isinstance(books, dict) else None
        if (
            opening['name'] != OPENING_NAME
            or not isinstance(configured, dict)
            or set(configured) != {'sha', 'source'}
            or configured.get('sha') != opening['sha256']
            or configured.get('source') != opening['source']
        ):
            raise ControlError('opening_config_mismatch')
        return opening

    @transaction.atomic
    def _create(self, request):
        if request['rule_profile_id'] != CANONICAL_PROFILE_ID:
            raise ControlError('rule_profile_mismatch')
        rule_profile = self._profile()
        actor = self._actor(self._username())
        policy = self._policy(request['stage'], request['policy'])
        fixed_move = policy == goal_fixed_move.policies().get(request['stage'])
        if fixed_move and (
            request['schema_version'] not in (2, 3)
            or not isinstance(request['dev'], dict)
            or not isinstance(request['base'], dict)
            or goal_fixed_move.timing_for_options(request['dev'].get('options')) is None
            or request['base'].get('options') != request['dev'].get('options')
            or not request['dev'].get('network')
            or request['dev'].get('network') != request['base'].get('network')
        ):
            raise ControlError('fixed_move_comparison_mismatch')
        if request['schema_version'] == 3:
            dev_source = request['dev'].get('source') if isinstance(request['dev'], dict) else None
            base_source = request['base'].get('source') if isinstance(request['base'], dict) else None
            if (
                not fixed_move
                or not isinstance(dev_source, dict) or dev_source.get('kind') != 'local_private'
                or not isinstance(base_source, dict) or set(base_source) != {'name', 'commit_sha', 'bench'}
                or request['dev'].get('engine') != request['base'].get('engine')
                or request['dev'].get('options') == goal_fixed_move.OPTIONS
            ):
                raise ControlError('local_engine_comparison_mismatch')
        game_budget = self._game_budget(request['stage'], request['game_budget'])
        if fixed_move and game_budget != (2 if request['stage'] == 'acceptance' else 131072):
            raise ControlError('fixed_move_comparison_mismatch')
        opening = self._opening(request['opening'])
        schema_version = request['schema_version']
        dev, dev_engine, dev_network = self._side(request['dev'], schema_version)
        base, base_engine, base_network = self._side(request['base'], schema_version)
        acceptance_pair = request['stage'] == 'acceptance'
        if acceptance_pair and (policy['workload_size'] != 1 or game_budget != 2):
            raise ControlError('configured_policy_invalid')

        test = Test.objects.create(
            author=actor.user.username,
            upload_pgns='TRUE' if policy['upload_pgns'] else 'FALSE',
            rule_profile=rule_profile,
            book_name=opening['name'],
            dev=dev_engine,
            dev_repo=dev['repo'],
            dev_engine=dev['engine'],
            dev_options=dev['options'],
            dev_network=dev['network'],
            dev_netname=dev_network.name,
            dev_book_sha='',
            dev_book_name='',
            dev_time_control=policy['dev_time_control'],
            base=base_engine,
            base_repo=base['repo'],
            base_engine=base['engine'],
            base_options=base['options'],
            base_network=base['network'],
            base_netname=base_network.name,
            base_book_sha='',
            base_book_name='',
            base_time_control=policy['base_time_control'],
            workload_size=policy['workload_size'],
            priority=policy['priority'],
            throughput=policy['throughput'],
            test_mode='GAMES' if acceptance_pair else 'SPRT',
            max_games=game_budget,
            elolower=policy['elo_lower'],
            eloupper=policy['elo_upper'],
            alpha=policy['alpha'],
            beta=policy['beta'],
            lowerllr=math.log(policy['beta'] / (1.0 - policy['alpha'])),
            upperllr=math.log((1.0 - policy['beta']) / policy['alpha']),
            awaiting=False,
            approved=True,
        )
        actor.tests += 1
        actor.save(update_fields=('tests',))
        LogEvent.objects.create(
            author=actor.user.username,
            summary='AUTOTUNE_CREATE',
            log_file='',
            test_id=test.id,
        )
        return _response(
            schema_version,
            'create',
            'created',
            **_observation(test, request['stage'], schema_version),
        )

    @transaction.atomic
    def _owned_test(self, test_id):
        if not isinstance(test_id, int) or isinstance(test_id, bool) or test_id <= 0:
            raise ControlError('invalid_test_id')
        try:
            test = Test.objects.select_for_update().select_related('rule_profile').get(pk=test_id)
        except Test.DoesNotExist:
            raise ControlError('test_not_found') from None
        if test.author != self._username():
            raise ControlError('test_not_owned')
        if test.rule_profile_id != CANONICAL_PROFILE_ID:
            raise ControlError('rule_profile_mismatch')
        return test

    @transaction.atomic
    def _get(self, request):
        test = self._owned_test(request['test_id'])
        schema_version = request['schema_version']
        return _response(
            schema_version,
            'get',
            'observed',
            **_observation(test, schema_version=schema_version),
        )

    @transaction.atomic
    def _stop(self, request):
        if request['reason'] not in ('external_game_budget', 'operator_explicit_abort'):
            raise ControlError('invalid_stop_reason')
        test = self._owned_test(request['test_id'])
        if test.finished or test.passed or test.failed:
            raise ControlError('test_already_terminal')
        test.finished = True
        test.save(update_fields=('finished', 'updated'))
        LogEvent.objects.create(
            author=test.author,
            summary=(
                'AUTOTUNE_BUDGET_STOP'
                if request['reason'] == 'external_game_budget'
                else 'AUTOTUNE_OPERATOR_ABORT'
            ),
            log_file='',
            test_id=test.id,
        )
        return _response(
            request['schema_version'],
            'stop',
            'stopped',
            test_id=test.id,
            rule_profile_id=test.rule_profile_id,
            reason=request['reason'],
            state=_state(test),
        )
