SIDE_STAT_FIELDS = (
    "side_stats_games",
    "dev_sente_wins",
    "dev_gote_wins",
    "base_sente_wins",
    "base_gote_wins",
    "dev_sente_draws",
    "dev_gote_draws",
    "dev_sente_impasse_wins",
    "dev_gote_impasse_wins",
    "base_sente_impasse_wins",
    "base_gote_impasse_wins",
)

WIN_FIELDS = (
    "dev_sente_wins",
    "dev_gote_wins",
    "base_sente_wins",
    "base_gote_wins",
)

DRAW_FIELDS = (
    "dev_sente_draws",
    "dev_gote_draws",
)

IMPASSE_WIN_FIELDS = (
    ("dev_sente_impasse_wins", "dev_sente_wins"),
    ("dev_gote_impasse_wins", "dev_gote_wins"),
    ("base_sente_impasse_wins", "base_sente_wins"),
    ("base_gote_impasse_wins", "base_gote_wins"),
)


def parse_side_stats_payload(post, batch_games):
    """worker の先後別統計を検証し、旧 payload では None を返す。"""
    present_fields = [field for field in SIDE_STAT_FIELDS if field in post]
    if not present_fields:
        return None
    if len(present_fields) != len(SIDE_STAT_FIELDS):
        raise ValueError("Side statistics payload is incomplete")

    try:
        side_stats = {field: int(post[field]) for field in SIDE_STAT_FIELDS}
    except (TypeError, ValueError) as error:
        raise ValueError("Side statistics must be integers") from error

    if any(value < 0 for value in side_stats.values()):
        raise ValueError("Side statistics must be non-negative")

    coverage = side_stats["side_stats_games"]
    if coverage > batch_games:
        raise ValueError("Side statistics coverage exceeds batch games")

    outcome_games = sum(side_stats[field] for field in WIN_FIELDS + DRAW_FIELDS)
    if outcome_games != coverage:
        raise ValueError("Side statistics outcomes do not match coverage")

    for impasse_field, win_field in IMPASSE_WIN_FIELDS:
        if side_stats[impasse_field] > side_stats[win_field]:
            raise ValueError("Impasse wins exceed corresponding wins")

    return side_stats
