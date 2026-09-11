import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker


def workload():
    side = {'time_control': 'MT=1000', 'options': 'Threads=2 Hash=128 option.EnteringKingRule=CSARule24', 'network': '12345678'}
    return {'test': {
        'rule_profile_id': 'canonical-yaneuraou-csarule24-v1',
        'book': {'name': 'SHOGI.floodgate32-80.adjust_bishop_exchange.sfen.epd'},
        'dev': dict(side), 'base': dict(side),
        'goal_timing': {'profile_id': 'goal-fixed-move-2t-v1', 'move_time_ms': 1000, 'time_margin_ms': 250, 'scale_factor': 1.0, 'threads': 2, 'hash_mb': 128},
        'scale_method': 'BASE', 'scale_nps': 999999,
    }}


class FixedMoveTests(unittest.TestCase):
    def test_common_fv_requires_matching_explicit_scale_on_both_sides(self):
        for scale in (16, 24):
            value = workload()
            value['test']['goal_timing']['profile_id'] = 'goal-fixed-move-2t-common-fv%d-v1' % scale
            for side in ('dev', 'base'):
                value['test'][side]['options'] += ' NetworkDelay=0 NetworkDelay2=0 FV_SCALE=%d' % scale
            for side in ('dev', 'base'):
                self.assertEqual(worker.scale_time_control(value, 1.0, side), 'st=1000 timemargin=250')
            for replacement in ('', ' FV_SCALE=32', ' FV_SCALE=%d' % (40 - scale)):
                changed = __import__('copy').deepcopy(value)
                changed['test']['base']['options'] = value['test']['base']['options'].rsplit(' FV_SCALE=', 1)[0] + replacement
                with self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
                    worker.scale_time_control(changed, 1.0, 'dev')

    def test_zero_delay_profile_requires_both_exact_options(self):
        value = workload()
        value['test']['goal_timing']['profile_id'] = 'goal-fixed-move-2t-zero-delay-v1'
        for side in ('dev', 'base'):
            value['test'][side]['options'] += ' NetworkDelay=0 NetworkDelay2=0'
        for side in ('dev', 'base'):
            self.assertEqual(worker.scale_time_control(value, 1.0, side), 'st=1000 timemargin=250')
        for replacement in (
            workload()['test']['base']['options'],
            value['test']['base']['options'].replace('NetworkDelay2=0', 'NetworkDelay2=500'),
            value['test']['base']['options'] + ' MinimumThinkingTime=1000',
        ):
            changed = __import__('copy').deepcopy(value)
            changed['test']['base']['options'] = replacement
            with self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
                worker.scale_time_control(changed, 1.0, 'dev')
        value['test']['goal_timing']['profile_id'] = 'goal-fixed-move-2t-v1'
        with self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
            worker.scale_time_control(value, 1.0, 'dev')

    def test_fixed_clock_keeps_bench_validation_but_does_not_scale_by_nps(self):
        config = types.SimpleNamespace(workload=workload())
        with patch.object(worker, 'safe_run_benchmarks', side_effect=[1234, 9876]) as bench, patch.object(worker.ServerReporter, 'report_nps') as report:
            factor = worker.determine_scale_factor(config, 'dev', 'dn', 'base', 'bn')
        self.assertEqual(bench.call_count, 2)
        report.assert_called_once_with(config, 1234, 9876)
        self.assertEqual(factor, 1.0)
        for side in ('dev', 'base'):
            self.assertEqual(worker.scale_time_control(config.workload, factor, side), 'st=1000 timemargin=250')

    def test_drift_is_rejected_before_generating_runner_options(self):
        changes = [
            lambda x: x['test']['base'].update(network='87654321'),
            lambda x: x['test']['dev'].update(options='Threads=1 Hash=128 option.EnteringKingRule=CSARule24'),
            lambda x: x['test']['base'].update(time_control='MT=999'),
            lambda x: x['test']['goal_timing'].update(move_time_ms=999),
            lambda x: x['test']['goal_timing'].update(extra=True),
            lambda x: x['test']['book'].update(name='chess.epd'),
            lambda x: x['test']['book'].update(name='SHOGI.changed.sfen.epd'),
        ]
        for change in changes:
            value=workload();change(value)
            with self.subTest(change=change), self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
                worker.scale_time_control(value, 1.0, 'dev')
        with self.assertRaises(worker.utils.OpenBenchFatalWorkerException):
            worker.scale_time_control(workload(), 0.5, 'dev')

    def test_other_shogi_movetime_keeps_speed_scaling_with_millisecond_units(self):
        value=workload();del value['test']['goal_timing']
        self.assertEqual(worker.scale_time_control(value, 0.5, 'dev'), 'st=500 timemargin=250')
        value['test']['book']['name']='chess.epd'
        self.assertEqual(worker.scale_time_control(value, 0.5, 'dev'), 'st=0.50 timemargin=250')

    def test_existing_increment_clock_is_unchanged(self):
        value=workload();del value['test']['goal_timing']
        value['test']['dev']['time_control']='8.0+0.08'
        self.assertEqual(worker.scale_time_control(value, 0.5, 'dev'), 'tc=4.00+0.04 timemargin=250')


if __name__ == '__main__':
    unittest.main()
