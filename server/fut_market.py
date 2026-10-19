# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import fut_cards
import fut_items

SEARCH_CATEGORIES: dict[tuple[str, str], tuple[str, dict]] = {
    ("player", ""): ("players", {}),

    ("training", ""): ("consumables", {"itemType": "training"}),
    ("training", "playerTraining"): ("consumables", {"family": "trainingPlayer"}),
    ("training", "GKTraining"): ("consumables", {"family": "trainingGk"}),
    ("training", "position"): ("consumables", {"family": "position"}),
    ("training", "playStyle"): ("consumables", {"family": "playStyle"}),
    ("training", "formation"): ("consumables", {"family": "formation"}),
    ("training", "managerLeagueModifier"):
        ("consumables", {"family": "leagueModifier"}),

    ("development", ""): ("consumables", {"itemType": "development"}),
    ("development", "contract"): ("consumables", {"family": "contract"}),
    ("development", "healing"):
        ("consumables", {"family": "healing", "cardassetid": 9}),
    ("development", "fitness"):
        ("consumables", {"family": "healing", "cardassetid": 10}),

    ("clubInfo", ""): ("clubItems", {"itemTypes": ("kit", "custom")}),
    ("clubInfo", "badge"): ("clubItems", {"itemType": "custom"}),
    ("clubInfo", "kit"): ("clubItems", {"itemType": "kit"}),

    ("stadium", ""): ("clubItems", {"itemType": "stadium"}),
    ("ball", ""): ("clubItems", {"itemType": "ball"}),

    ("staff", ""): ("staff", {}),
    ("staff", "manager"): ("staff", {"family": "manager"}),
    ("staff", "headCoach"): ("staff", {"family": "headCoach"}),
    ("staff", "GKCoach"): ("staff", {"family": "GKCoach"}),
    ("staff", "fitnessCoach"): ("staff", {"family": "fitnessCoach"}),
    ("staff", "physio"): ("staff", {"family": "physio"}),
}

HEALING_CARD_ASSET = 9
FITNESS_CARD_ASSET = 10

def round_to_price_step(value: int) -> int:
    value = int(value)
    if value <= 1_000:
        step = 50
    elif value <= 10_000:
        step = 100
    elif value <= 50_000:
        step = 250
    elif value <= 100_000:
        step = 500
    else:
        step = 1_000
    snapped = (value // step) * step
    return max(150, min(15_000_000, snapped))


def base_value(definition: dict, kind: str) -> int:
    if kind == "players":
        rating = int(definition.get("rating", 0) or 0)
        rare = int(definition.get("rareflag", 1) or 1)
        floor = max(1, int(fut_items.discard_value(rating, rare)))
        curve = int(150 * (1.25 ** max(0, rating - 60)))
        return max(floor, curve)
    return max(1, int(fut_cards.discard_value(definition)))


_PLAYERS_BY_ID: dict | None = None


def players_by_id() -> dict:
    global _PLAYERS_BY_ID
    if _PLAYERS_BY_ID is None:
        _PLAYERS_BY_ID = {
            int(p["playerid"]): p for p in fut_items.load_current_catalogue()
        }
    return _PLAYERS_BY_ID


def value_for_resource(resource_id: int) -> tuple[int, str]:
    resource_id = int(resource_id)
    definition = fut_cards.definitions_by_resource().get(resource_id)
    if definition is not None:
        return base_value(definition, "cards"), "cards"
    player = players_by_id().get(resource_id & 0xFFFFFF)
    if player is not None:
        return base_value(player, "players"), "players"
    return 0, ""


def price_limits_for(resource_id: int) -> tuple[int, int]:
    value, kind = value_for_resource(resource_id)
    if not value:
        return 150, 15_000_000
    low = max(150, round_to_price_step(value // 4))
    high = min(15_000_000, round_to_price_step(value * 6))
    if high <= low:
        high = round_to_price_step(min(15_000_000, low * 4))
    return low, high


def _rows_for(kind: str) -> list:
    if kind == "players":
        return fut_items.load_current_catalogue()
    return fut_cards.family(kind)


def _matches(definition: dict, narrow: dict) -> bool:
    if "itemType" in narrow and definition.get("itemType") != narrow["itemType"]:
        return False
    if ("itemTypes" in narrow
            and definition.get("itemType") not in narrow["itemTypes"]):
        return False
    if "family" in narrow and definition.get("family") != narrow["family"]:
        return False
    if ("cardassetid" in narrow
            and int(definition.get("cardassetid", 0) or 0) != narrow["cardassetid"]):
        return False
    return True


def resource_of(definition: dict, kind: str) -> int:
    if kind == "players":
        return int(definition.get("resourceId",
                                  definition.get("playerid", 0)) or 0)
    return int(definition.get("resourceId", 0) or 0)


def narrow_definitions(definitions: list, kind: str, filters: dict) -> list:
    rating_band = filters.get("rating_band")
    position = filters.get("position")
    nation = filters.get("nation")
    league = filters.get("league")
    team = filters.get("team")
    rare_only = bool(filters.get("rare_only"))

    out = []
    for definition in definitions:
        rating = int(definition.get("rating", 0) or 0)
        if rating_band is not None and not rating_band[0] <= rating <= rating_band[1]:
            continue
        if kind == "players":
            if position is not None:
                current_position = definition.get("preferredPosition")
                if current_position is None:
                    slot = int(definition.get("position", -1) or -1)
                    current_position = fut_items.POSITIONS.get(slot)
                if current_position != position:
                    continue
            if nation is not None and int(definition.get("nationid", 0) or 0) != nation:
                continue
            if league is not None and int(definition.get("leagueid", 0) or 0) != league:
                continue
            if team is not None and int(definition.get("teamid", 0) or 0) != team:
                continue
        else:
            if position is not None:
                continue
            if nation is not None and int(definition.get("nation", 0) or 0) != nation:
                continue
            if league is not None and int(definition.get("league", 0) or 0) != league:
                continue
            if team is not None and int(definition.get("teamid", 0) or 0) != team:
                continue
        if rare_only and int(definition.get("rareflag", 0) or 0) < 1:
            continue
        out.append(definition)
    return out


def definitions_for(item_type: str, category: str = "") -> tuple[str, list]:
    item_type = str(item_type or "").strip()
    category = str(category or "").strip()
    entry = SEARCH_CATEGORIES.get((item_type, category))
    if entry is None:
        entry = SEARCH_CATEGORIES.get((item_type, ""))
    if entry is None:
        return "", []
    kind, narrow = entry
    rows = [row for row in _rows_for(kind) if _matches(row, narrow)]
    return kind, rows
