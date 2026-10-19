# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

STAT_NAMES = {
    "players": 1, "playersBronze": 2, "playersSilver": 3, "playersGold": 4,
    "rarePlayers": 5,
    "staff": 10, "staffManager": 11, "staffHeadCoach": 12, "staffGKCoach": 13,
    "staffPhysio": 14, "staffFitnessCoach": 15,
    "stadia": 20, "balls": 30,
    "kits": 40, "kitsHome": 41, "kitsAway": 42,
    "badges": 45, "badgeDBid": 46, "leagueLogos": 47,
    "consumables": 60, "consumablesHealing": 65,
    "consumablesContractPlayer": 66, "consumablesTrainingPlayer": 67,
    "consumablesFitnessPlayer": 68, "consumablesPosition": 69,
    "consumablesTrainingGk": 70, "consumablesContractManager": 71,
    "consumablesFormationManager": 72, "consumablesTrainingManager": 73,
    "consumablesFitnessTeam": 74, "consumablesTrainingPlayerPlayStyle": 75,
    "consumablesTrainingGkPlayStyle": 76,
    "consumablesTrainingManagerLeagueModifier": 77,
}

ITEM_TYPE_TO_STAT = {
    "player": "players",
    "ball": "balls",
    "kit": "kits",
    "custom": "badges",
    "stadium": "stadia",
    "development": "consumables",
    "training": "consumablesTrainingPlayer",
}

STAFF_ROLE_TO_STAT = {
    "manager": "staffManager",
    "headCoach": "staffHeadCoach",
    "GKCoach": "staffGKCoach",
    "fitnessCoach": "staffFitnessCoach",
    "physio": "staffPhysio",
}

CONSUMABLE_TYPES = frozenset({"development", "training"})

FAMILY_TO_STAT = {
    "contract": "consumablesContractPlayer",
    "healing": "consumablesHealing",
    "fitness": "consumablesFitnessPlayer",
    "trainingPlayer": "consumablesTrainingPlayer",
    "trainingGk": "consumablesTrainingGk",
    "position": "consumablesPosition",
    "playStyle": "consumablesTrainingPlayerPlayStyle",
    "leagueModifier": "consumablesTrainingManagerLeagueModifier",
    "formation": "consumablesFormationManager",
}

QUALITY_STAT = ((0, 64, "playersBronze"),
                (65, 74, "playersSilver"),
                (75, 99, "playersGold"))


def counts_from_items(items: list, families: dict | None = None) -> dict:
    counts: dict[str, int] = {}

    def bump(stat: str) -> None:
        if stat:
            counts[stat] = counts.get(stat, 0) + 1

    consumables = 0
    staff = 0
    for item in items:
        kind = str(item.get("itemType", ""))
        if kind in CONSUMABLE_TYPES:
            consumables += 1
            family = (families or {}).get(int(item.get("resourceId", 0) or 0))
            bump(FAMILY_TO_STAT.get(family))
            continue
        if kind == "staff":
            staff += 1
            role = (families or {}).get(int(item.get("resourceId", 0) or 0))
            bump(STAFF_ROLE_TO_STAT.get(role))
            continue
        bump(ITEM_TYPE_TO_STAT.get(kind))
        if kind == "player":
            rating = int(item.get("rating", 0) or 0)
            for low, high, stat in QUALITY_STAT:
                if low <= rating <= high:
                    bump(stat)
                    break
            if int(item.get("rareflag", 0) or 0) >= 1:
                bump("rarePlayers")
    if consumables:
        counts["consumables"] = consumables
    if staff:
        counts["staff"] = staff
    return counts


def build_club_stats(items: list, families: dict | None = None) -> dict:
    entries = [{"type": name,
                "typeValue": int(value),
                "contextId": 0,
                "contextValue": 0}
               for name, value in sorted(counts_from_items(items, families).items())
               if name in STAT_NAMES]
    return {"stat": entries}


def build_empty() -> dict:
    return {"stat": []}
