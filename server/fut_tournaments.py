# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import fut_economy

TYPE_OFFLINE = "offline"
TYPE_ONLINE = "online"
TYPE_LIVE_OFFLINE = "live_offline"
TYPE_LIVE_ONLINE = "live_online"

LOCK_UNLOCKED = "UNLOCKED"
LOCK_TROPHIES = "LOCKED_TROPHIES"
LOCK_ATTEMPTS_PERM = "LOCKED_ATTEMPTS_PERM"
LOCK_ATTEMPTS_TEMP = "LOCKED_ATTEMPTS_TEMP"

TREE_KNOCKOUT = "knockout"
TREE_GROUP = "group"
TREE_KNOCKOUT_GROUP = "knockout_group"

ELIGIBILITY_AND = "AND"

_OPENED_AT = 1_451_606_400
_CLOSES_AT = 2_145_916_800


def _rounds(rounds: list[tuple[int, int]]) -> list[dict]:
    return [{"id": index,
             "difficulty": int(difficulty),
             "coins": fut_economy.coins(coins),
             "rewardMultiplier": 1}
            for index, (difficulty, coins) in enumerate(rounds, start=1)]


CATALOGUE = [
    {"id": 1, "name": "Bronze Cup", "trophy": 7_100_001, "ai": 1, "minutes": 6,
     "rounds": [(1, 150), (1, 200), (2, 300), (2, 500)]},
    {"id": 2, "name": "Silver Cup", "trophy": 7_100_002, "ai": 2, "minutes": 6,
     "rounds": [(1, 175), (2, 250), (2, 375), (3, 650)]},
    {"id": 3, "name": "Gold Cup", "trophy": 7_100_003, "ai": 3, "minutes": 6,
     "rounds": [(2, 225), (2, 325), (3, 500), (3, 850)]},
    {"id": 4, "name": "Domestic Cup", "trophy": 7_100_004, "ai": 4, "minutes": 8,
     "rounds": [(3, 300), (3, 450), (4, 700), (4, 1_200)]},
    {"id": 5, "name": "International Cup", "trophy": 7_100_005, "ai": 5,
     "minutes": 8,
     "rounds": [(4, 400), (4, 600), (5, 900), (5, 1_600)]},
]
TEAMS_PER_CUP = 16


AWARD_COINS = 1


def _award_set(coins: int) -> dict:
    return {"awards": [{"awardType": AWARD_COINS,
                        "value": int(coins),
                        "halid": 0}]}


def build_row(entry: dict, now: int) -> dict:
    ends_in = _CLOSES_AT - int(now)
    rounds = _rounds(entry["rounds"])
    prize = sum(int(r["coins"]) for r in rounds)
    return {
        "id": int(entry["id"]),
        "type": TYPE_OFFLINE,
        "localizedName": str(entry["name"]),
        "assetName": str(entry["name"]),
        "silhouetteName": str(entry["name"]),
        "imageFormat": "png",

        "eligibilityOperation": ELIGIBILITY_AND,
        "elgReq": [],

        "awardSet": _award_set(prize),

        "numTeams": TEAMS_PER_CUP,
        "numRounds": len(rounds),
        "rounds": rounds,
        "treeType": TREE_KNOCKOUT,

        "lock": LOCK_UNLOCKED,
        "unlockreq": 0,
        "trophyResourceId": int(entry["trophy"]),
        "trophyUserCount": 0,

        "matchlength": int(entry["minutes"]),
        "aigroup": int(entry["ai"]),
        "maxWins": len(rounds),
        "winsRemaining": len(rounds),

        "triesMax": 0,
        "triesPeriod": 0,
        "triesRemaining": 0,

        "starttime": _OPENED_AT,
        "endtime": _CLOSES_AT,
        "visStart": _OPENED_AT,
        "visEnd": _CLOSES_AT,
        "timeUntilStart": 0,
        "timeUntilEnd": int(ends_in),
        "nextReset": int(ends_in),
    }


def build_rows(now: int) -> list[dict]:
    return [build_row(entry, now) for entry in CATALOGUE]


_TEAM_POOL: list[int] | None = None
MAX_OPPONENTS = 128

DEFAULT_TEAM_IDS = (241, 243, 21, 69, 10, 11, 9, 22, 5, 73, 1, 13, 18, 2, 7)


def _team_pool() -> list[int]:
    global _TEAM_POOL
    if _TEAM_POOL is None:
        try:
            import fut_items
            catalogue = fut_items.load_current_catalogue() or []
        except Exception:
            catalogue = []
        rows = catalogue if isinstance(catalogue, list) else catalogue.values()
        known = {int(row.get("teamid") or 0) for row in rows
                 if isinstance(row, dict)}
        head = [t for t in DEFAULT_TEAM_IDS if not known or t in known]
        tail = sorted(t for t in known if t > 0 and t not in set(head))
        _TEAM_POOL = head + tail
    return _TEAM_POOL


def opponent_team_ids(group_id: int, count: int) -> list[int]:
    pool = _team_pool()
    wanted = max(0, min(int(count), MAX_OPPONENTS))
    if not pool or not wanted:
        return []
    window = pool[:len(DEFAULT_TEAM_IDS)] if wanted <= len(DEFAULT_TEAM_IDS) else pool
    offset = (int(group_id) * 7) % len(window)
    rotated = window[offset:] + window[:offset]
    return rotated[:wanted]
