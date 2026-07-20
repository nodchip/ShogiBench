import re
from dataclasses import dataclass


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

FINISHED_GAME_RE = re.compile(
    r"^Finished game (?P<game>\d+) "
    r"\((?P<sente>.+?) vs (?P<gote>.+?)\): "
    r"(?P<result>1-0|0-1|1/2-1/2) \{(?P<reason>.*)\}$"
)


@dataclass(frozen=True)
class FinishedGame:
    """shogitest が出力した 1 対局分の完了情報を表す。"""

    game: int
    sente: str
    gote: str
    result: str
    reason: str


def new_side_stats():
    """先後別統計の全カウンタを 0 で初期化する。"""
    return {field: 0 for field in SIDE_STAT_FIELDS}


def parse_finished_game(line):
    """shogitest の完了行を解析し、対象外の行では None を返す。"""
    match = FINISHED_GAME_RE.match(line)
    if match is None:
        return None

    return FinishedGame(
        game=int(match.group("game")),
        sente=match.group("sente"),
        gote=match.group("gote"),
        result=match.group("result"),
        reason=match.group("reason"),
    )


def _engine_role(engine_name):
    """worker が付与した engine 名の末尾から Dev/Base を判定する。"""
    if engine_name.endswith("-dev"):
        return "dev"
    if engine_name.endswith("-base"):
        return "base"
    return None


def add_finished_game(counters, finished_game):
    """解析済み対局を先後別統計へ反映する。"""
    sente_role = _engine_role(finished_game.sente)
    gote_role = _engine_role(finished_game.gote)
    if {sente_role, gote_role} != {"dev", "base"}:
        raise ValueError("Finished game must contain Dev and Base exactly once")

    counters["side_stats_games"] += 1

    if finished_game.result == "1-0":
        counters[f"{sente_role}_sente_wins"] += 1
        if finished_game.reason == "Sente wins by impasse":
            counters[f"{sente_role}_sente_impasse_wins"] += 1
    elif finished_game.result == "0-1":
        counters[f"{gote_role}_gote_wins"] += 1
        if finished_game.reason == "Gote wins by impasse":
            counters[f"{gote_role}_gote_impasse_wins"] += 1
    elif sente_role == "dev":
        counters["dev_sente_draws"] += 1
    else:
        counters["dev_gote_draws"] += 1
