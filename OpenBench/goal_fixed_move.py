"""Closed, non-scaling clock contract for a common-network Goal comparison."""

PROFILE_ID = 'goal-fixed-move-2t-v1'
OPTIONS = 'Threads=2 Hash=128 option.EnteringKingRule=CSARule24'
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
        test.dev_options != OPTIONS or test.base_options != OPTIONS
        or not test.dev_network or test.dev_network != test.base_network
        or test.rule_profile_id != 'canonical-yaneuraou-csarule24-v1'
        or test.book_name != OPENING_NAME
        or test.max_games != (2 if stage == 'acceptance' else 131072)
        or test.test_mode != ('GAMES' if stage == 'acceptance' else 'SPRT')
    ):
        return None
    return stage
