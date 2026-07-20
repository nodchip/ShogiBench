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


def _ratio(numerator, denominator, numerator_width=0):
    """勝ち数と分母を割合付き文字列へ整形する。"""
    if denominator == 0:
        return "0/0 (N/A)"

    numerator_text = str(numerator).rjust(numerator_width)
    percentage = 100.0 * numerator / denominator
    return f"{numerator_text}/{denominator} ({percentage:4.1f}%)"


def _table_row(label, cells, widths):
    """最終列以外を指定幅で左寄せした表の1行を返す。"""
    padded = [cell.ljust(width) for cell, width in zip(cells[:-1], widths[:-1])]
    return f"{label:<6} | " + " | ".join(padded + [cells[-1]])


def format_side_stats(test):
    """将棋 workload の Long Stat Block 用先後別統計を生成する。"""
    if test.games == 0 or "SHOGI" not in test.book_name.upper():
        return ""

    coverage = test.side_stats_games
    if coverage == 0:
        return "Side stats | unavailable (legacy worker data)"

    sente_wins = test.dev_sente_wins + test.base_sente_wins
    gote_wins = test.dev_gote_wins + test.base_gote_wins
    draws = test.dev_sente_draws + test.dev_gote_draws

    dev_sente_games = (
        test.dev_sente_wins
        + test.base_gote_wins
        + test.dev_sente_draws
    )
    dev_gote_games = (
        test.dev_gote_wins
        + test.base_sente_wins
        + test.dev_gote_draws
    )
    base_sente_games = dev_gote_games
    base_gote_games = dev_sente_games

    dev_wins = test.dev_sente_wins + test.dev_gote_wins
    base_wins = test.base_sente_wins + test.base_gote_wins

    lines = []
    if coverage < test.games:
        lines.append(
            f"Side stats coverage | N: {coverage}/{test.games} (partial)"
        )

    numerator_width = max(len(str(sente_wins)), len(str(gote_wins)), len(str(draws)))
    lines.extend([
        "Side results",
        f"Sente  | W: {_ratio(sente_wins, coverage, numerator_width)}",
        f"Gote   | W: {_ratio(gote_wins, coverage, numerator_width)}",
        f"Draw   | D: {_ratio(draws, coverage, numerator_width)}",
        "",
        "Engine results",
    ])

    headers = ["Overall W", "Sente W", "Gote W", "Draw S/G"]
    dev_cells = [
        _ratio(dev_wins, coverage),
        _ratio(test.dev_sente_wins, dev_sente_games),
        _ratio(test.dev_gote_wins, dev_gote_games),
        f"{test.dev_sente_draws} / {test.dev_gote_draws}",
    ]
    base_cells = [
        _ratio(base_wins, coverage),
        _ratio(test.base_sente_wins, base_sente_games),
        _ratio(test.base_gote_wins, base_gote_games),
        f"{test.dev_gote_draws} / {test.dev_sente_draws}",
    ]
    widths = [
        max(len(headers[index]), len(dev_cells[index]), len(base_cells[index]))
        for index in range(len(headers))
    ]
    lines.extend([
        _table_row("Engine", headers, widths),
        _table_row("Dev", dev_cells, widths),
        _table_row("Base", base_cells, widths),
        "",
        "Impasse declarations",
    ])

    dev_sente_impasse = test.dev_sente_impasse_wins
    dev_gote_impasse = test.dev_gote_impasse_wins
    base_sente_impasse = test.base_sente_impasse_wins
    base_gote_impasse = test.base_gote_impasse_wins
    dev_impasse = dev_sente_impasse + dev_gote_impasse
    base_impasse = base_sente_impasse + base_gote_impasse
    sente_impasse = dev_sente_impasse + base_sente_impasse
    gote_impasse = dev_gote_impasse + base_gote_impasse

    lines.extend([
        f"Total  | {dev_impasse + base_impasse}  "
        f"(Sente: {sente_impasse}, Gote: {gote_impasse})",
        f"Dev    | {dev_impasse}  "
        f"(Sente: {dev_sente_impasse}, Gote: {dev_gote_impasse})",
        f"Base   | {base_impasse}  "
        f"(Sente: {base_sente_impasse}, Gote: {base_gote_impasse})",
    ])

    return "\n".join(lines)
