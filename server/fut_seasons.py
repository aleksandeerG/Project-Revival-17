# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import fut_economy


TYPE_OFFLINE = "OFFLINE"
TYPE_ONLINE = "ONLINE"
ELIGIBILITY_AND = "AND"

PRIZE_RELEGATION = "RELEGATION"
PRIZE_MAINTENANCE = "MAINTENANCE"
PRIZE_PROMOTION = "PROMOTION"
PRIZE_CHAMPIONSHIP = "CHAMPIONSHIP"

AWARD_COIN = "coin"

_OPENED_AT = 1_451_606_400
_CLOSES_AT = 2_145_916_800

_TEAM_IDS = (241, 243, 21, 69, 10, 11, 9, 22, 5, 73)

CATALOGUE = (
    (1, 9, 12, 0, 1_900),
    (2, 11, 14, 6, 2_100),
    (3, 13, 16, 8, 2_900),
    (4, 14, 17, 9, 3_300),
    (5, 16, 19, 11, 3_800),
    (6, 16, 19, 11, 4_400),
    (7, 18, 21, 13, 5_000),
    (8, 19, 22, 14, 6_000),
    (9, 21, 24, 16, 7_500),
    (10, 23, 26, 18, 10_000),
)

FIRST_DIVISION_ID = 10
LAST_DIVISION_ID = 1
MATCHES_PER_CAMPAIGN = 10

RESULT_WIN = "WIN"
RESULT_DRAW = "DRAW"
RESULT_LOSS = "LOSS"


def _difficulty(division: int) -> int:
    return max(1, min(5, 1 + (int(division) - 1) // 2))


def _trophy(division: int) -> int:
    if division <= 1:
        return 7_100_001
    if division <= 4:
        return 7_100_002
    if division <= 7:
        return 7_100_003
    if division <= 9:
        return 7_100_004
    return 7_100_005


def _matches(division: int) -> list[dict]:
    difficulty = _difficulty(division)
    offset = (int(division) - 1) % len(_TEAM_IDS)
    teams = _TEAM_IDS[offset:] + _TEAM_IDS[:offset]
    return [
        {
            "teamId": int(team_id),
            "difficulty": int(difficulty),
            "rewardMult": 1,
            "roundId": int(round_id),
            "coins": 300 + (round_id - 1) * 25
                     + (int(division) - 1) * 50,
        }
        for round_id, team_id in enumerate(teams, start=1)
    ]


def _coin_award(coins: int, mode: str) -> dict:
    return {
        "type": AWARD_COIN,
        "value": fut_economy.competition_coins(coins, mode),
        "count": 1,
        "assetId": 0,
        "halId": 0,
        "teamId": 0,
    }


def _prize(level: str, threshold: int, coins: int = 0,
           mode: str = TYPE_OFFLINE) -> dict:
    awards = [_coin_award(coins, mode)] if int(coins) > 0 else []
    return {
        "prizeLevel": str(level),
        "thresholdPoint": int(threshold),
        "awardMappings": [{"awards": awards}],
    }


def build_row(entry: tuple[int, int, int, int, int], now: int,
              mode: str = TYPE_OFFLINE) -> dict:
    division, promotion, title, maintenance, title_coins = entry
    ends_in = max(0, _CLOSES_AT - int(now))
    promotion_coins = max(500, int(title_coins) - 400)
    maintenance_coins = max(300, int(title_coins) // 5)
    return {
        "id": int(division),
        "divisionId": int(division),
        "type": str(mode),
        "numMatches": 10,
        "matchLengthMin": 6,
        "matches": _matches(division),
        "prizeSet": [
            _prize(PRIZE_RELEGATION, 0, mode=mode),
            _prize(PRIZE_MAINTENANCE, maintenance,
                   maintenance_coins, mode),
            _prize(PRIZE_PROMOTION, promotion, promotion_coins, mode),
            _prize(PRIZE_CHAMPIONSHIP, title, title_coins, mode),
        ],
        "elgOperation": ELIGIBILITY_AND,
        "elgReq": [],
        "trophyResourceId": _trophy(division),
        "trophyUseCount": 0,
        "visStartDays": 3_650,
        "visEndDays": 3_650,
        "startDateTime": _OPENED_AT,
        "endDateTime": _CLOSES_AT,
        "untilStartSeconds": 0,
        "untilEndSeconds": int(ends_in),
    }


def build_rows(now: int, mode: str = TYPE_OFFLINE) -> list[dict]:
    if mode not in (TYPE_OFFLINE, TYPE_ONLINE):
        raise ValueError("unknown season mode: %s" % mode)
    return [build_row(entry, now, mode) for entry in CATALOGUE]


def visible_division(division_id: int) -> int:
    value = int(division_id)
    if not LAST_DIVISION_ID <= value <= FIRST_DIVISION_ID:
        raise ValueError("division id is outside 1..10: %s" % division_id)
    return 11 - value


def _definition(division_id: int) -> tuple[int, int, int, int, int]:
    value = int(division_id)
    try:
        return next(entry for entry in CATALOGUE if entry[0] == value)
    except StopIteration as error:
        raise ValueError("division id is outside 1..10: %s" % division_id) \
            from error


def prize_base_coins(division_id: int, outcome: str) -> int:
    _wire_id, _promotion, _title, _maintenance, title_coins = \
        _definition(division_id)
    result = str(outcome or "").upper()
    if result == PRIZE_CHAMPIONSHIP:
        return int(title_coins)
    if result == PRIZE_PROMOTION:
        return max(500, int(title_coins) - 400)
    if result == PRIZE_MAINTENANCE:
        return max(300, int(title_coins) // 5)
    if result == PRIZE_RELEGATION:
        return 0
    raise ValueError("unknown season outcome: %s" % outcome)


def campaign_outcome(division_id: int, points: int) -> str:
    wire_id, promotion, title, maintenance, _coins = _definition(division_id)
    score = max(0, int(points))
    if score >= title:
        return PRIZE_CHAMPIONSHIP
    if wire_id < FIRST_DIVISION_ID and score >= promotion:
        return PRIZE_PROMOTION
    if score >= maintenance or wire_id == LAST_DIVISION_ID:
        return PRIZE_MAINTENANCE
    return PRIZE_RELEGATION


def next_division_id(division_id: int, outcome: str) -> int:
    wire_id = _definition(division_id)[0]
    result = str(outcome or "").upper()
    if result in (PRIZE_CHAMPIONSHIP, PRIZE_PROMOTION):
        return min(FIRST_DIVISION_ID, wire_id + 1)
    if result == PRIZE_RELEGATION:
        return max(LAST_DIVISION_ID, wire_id - 1)
    if result == PRIZE_MAINTENANCE:
        return wire_id
    raise ValueError("unknown season outcome: %s" % outcome)


def canonical_match_result(result: str) -> str | None:
    value = str(result or "").strip().upper()
    if value in ("WIN", "DNF_WIN", "DNF_DRAW"):
        return RESULT_WIN
    if value == "DRAW":
        return RESULT_DRAW
    if value in ("LOSS", "DNF_LOSS", "QUIT"):
        return RESULT_LOSS
    return None


def advance_campaign(division_id: int, campaign: int, played: int, won: int,
                     drawn: int, lost: int, points: int, result: str,
                     mode: str) -> dict:
    wire_id = _definition(division_id)[0]
    canonical = canonical_match_result(result)
    if canonical is None:
        raise ValueError("result cannot advance a season: %s" % result)
    counts = [int(played), int(won), int(drawn), int(lost), int(points)]
    if any(value < 0 for value in counts) or counts[0] >= MATCHES_PER_CAMPAIGN:
        raise ValueError("invalid season counters")

    new_played = counts[0] + 1
    new_won = counts[1] + (canonical == RESULT_WIN)
    new_drawn = counts[2] + (canonical == RESULT_DRAW)
    new_lost = counts[3] + (canonical == RESULT_LOSS)
    new_points = counts[4] + (3 if canonical == RESULT_WIN
                              else 1 if canonical == RESULT_DRAW else 0)
    complete = new_played == MATCHES_PER_CAMPAIGN
    outcome = campaign_outcome(wire_id, new_points) if complete else ""
    reward = (fut_economy.competition_coins(
        prize_base_coins(wire_id, outcome), mode) if complete else 0)
    next_wire_id = next_division_id(wire_id, outcome) if complete else wire_id

    return {
        "division_id": int(next_wire_id),
        "campaign": int(campaign) + (1 if complete else 0),
        "played": 0 if complete else int(new_played),
        "won": 0 if complete else int(new_won),
        "drawn": 0 if complete else int(new_drawn),
        "lost": 0 if complete else int(new_lost),
        "points": 0 if complete else int(new_points),
        "last_result": canonical,
        "campaign_complete": bool(complete),
        "season_end_result": outcome,
        "season_coins": int(reward),
        "completed_division_id": int(wire_id) if complete else 0,
        "completed_played": int(new_played) if complete else 0,
        "completed_won": int(new_won) if complete else 0,
        "completed_drawn": int(new_drawn) if complete else 0,
        "completed_lost": int(new_lost) if complete else 0,
        "completed_points": int(new_points) if complete else 0,
    }
