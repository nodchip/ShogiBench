"""Closed, non-scaling clock contract for a common-network Goal comparison."""

PROFILE_ID = 'goal-fixed-move-2t-v1'
OPTIONS = 'Threads=2 Hash=128 option.EnteringKingRule=CSARule24'
ZERO_DELAY_OPTIONS = OPTIONS + ' NetworkDelay=0 NetworkDelay2=0'
TIME_CONTROL = 'MT=1000'
OPENING_NAME = 'SHOGI.floodgate32-80.adjust_bishop_exchange.sfen.epd'
TIMING = {
    'profile_id': PROFILE_ID,
    'move_time_ms': 1000,
    'time_margin_ms': 250,
    'scale_factor': 1.0,
    'threads': 2,
    'hash_mb': 128,
}
ZERO_DELAY_TIMING = {**TIMING, 'profile_id': 'goal-fixed-move-2t-zero-delay-v1'}


def timing_for_options(options):
    if options == OPTIONS:
        return dict(TIMING)
    if options == ZERO_DELAY_OPTIONS:
        return dict(ZERO_DELAY_TIMING)
    return None


def policies():
    common = {
        'alpha': 0.05, 'beta': 0.1,
        'dev_time_control': TIME_CONTROL, 'base_time_control': TIME_CONTROL,
        'elo_lower': 0.0, 'elo_upper': 4.0,
        'priority': 0, 'throughput': 1,
    }
    return {
        'acceptance': {**common, 'upload_pgns': True, 'workload_size': 1},
        'stc': {**common, 'upload_pgns': False, 'workload_size': 8},
    }


def stage_for_test(test):
    """Return a stage only when all persisted comparison conditions match."""
    observed = {
        'alpha': test.alpha, 'beta': test.beta,
        'dev_time_control': test.dev_time_control,
        'base_time_control': test.base_time_control,
        'elo_lower': test.elolower, 'elo_upper': test.eloupper,
        'priority': test.priority, 'throughput': test.throughput,
        'upload_pgns': test.upload_pgns == 'TRUE',
        'workload_size': test.workload_size,
    }
    matches = [stage for stage, policy in policies().items() if policy == observed]
    if len(matches) != 1:
        return None
    stage = matches[0]
    if (
        timing_for_options(test.dev_options) is None or test.base_options != test.dev_options
        or not test.dev_network or test.dev_network != test.base_network
        or test.rule_profile_id != 'canonical-yaneuraou-csarule24-v1'
        or test.book_name != OPENING_NAME
        or test.max_games != (2 if stage == 'acceptance' else 131072)
        or test.test_mode != ('GAMES' if stage == 'acceptance' else 'SPRT')
    ):
        return None
    return stage
