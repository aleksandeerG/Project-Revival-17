# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import fut_cards
import fut_items

FORMATIONS = (
    "f3412", "f3421", "f343", "f352", "f4141", "f4222", "f4231", "f4312",
    "f4321", "f433", "f4411", "f442", "f451", "f5212", "f5221", "f532", "f541",
)
DEFAULT_FORMATION = "f442"

SQUAD_SLOTS = 23
STARTING_XI = 11

SQUAD_TYPE = "REGULAR_SQUAD"


def squad_entry(squad: dict) -> dict:
    return {
        "id": int(squad["id"]),
        "squadName": str(squad["squadName"]),
        "squadType": SQUAD_TYPE,
        "formation": str(squad["formation"]),
        "chemistry": int(squad["chemistry"]),
        "rating": int(squad["rating"]),
    }


def build_squad_list(squads: list) -> dict:
    return {"squad": [squad_entry(s) for s in squads]}


def squad_rating(players: list) -> int:
    starters = [p for p in players[:STARTING_XI] if p]
    if not starters:
        return 0
    return round(sum(p["rating"] for p in starters) / len(starters))


def parse_saved_squad(body: bytes) -> dict | None:
    import json as _json
    try:
        document = _json.loads(body or b"{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(document, dict):
        return None
    slots = {}
    for entry in document.get("players") or []:
        if not isinstance(entry, dict):
            continue
        item = entry.get("itemData")
        item_id = entry.get("itemId")
        if isinstance(item, dict):
            item_id = item.get("id", item_id)
        try:
            index = int(entry["index"])
            item_id = int(item_id)
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= index < SQUAD_SLOTS and item_id > 0:
            slots[index] = item_id
    saved = {}
    if slots:
        saved["slots"] = slots
    for key in ("squadName", "formation"):
        value = document.get(key)
        if isinstance(value, str) and value:
            saved[key] = value
    custom = document.get("custom")
    if isinstance(custom, str) and custom:
        saved["custom"] = custom
    for key in ("chemistry", "rating", "starRating", "captain"):
        value = document.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            saved[key] = value

    for key in ("kicktakers", "manager"):
        value = document.get(key)
        if isinstance(value, list) and all(isinstance(row, dict)
                                           for row in value):
            saved[key] = value

    meaningful = set(saved) - {"squadName"}
    return saved if meaningful else None


NO_MANAGER = {"id": 0, "dream": False}


def is_manager_card(item: dict) -> bool:
    if str(item.get("itemType", "")) != "staff":
        return False
    role = fut_cards.family_by_resource().get(
        int(item.get("resourceId", 0) or 0))
    return role == "manager"


def resolve_manager(entries, items_by_id: dict[int, dict] | None) -> list:
    if not isinstance(entries, list):
        return [dict(NO_MANAGER)]
    resolved = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = int(entry.get("id", 0) or 0)
        if not item_id:
            resolved.append(dict(NO_MANAGER))
            continue
        item = (items_by_id or {}).get(item_id)
        if item is not None and not is_manager_card(item):
            resolved.append(dict(NO_MANAGER))
            continue
        if item is None:
            resolved.append(dict(entry) if "resourceId" in entry
                            else dict(NO_MANAGER))
            continue
        document = dict(item)
        document["dream"] = bool(entry.get("dream", False))
        resolved.append(document)
    return resolved or [dict(NO_MANAGER)]


def build_squad(squad: dict, players: list, persona_id: int,
                timestamp: int = 0, slots_by_index: dict | None = None,
                items_by_id: dict[int, dict] | None = None,
                managers_by_id: dict[int, dict] | None = None) -> dict:
    slots = []
    for index in range(SQUAD_SLOTS):
        if slots_by_index is not None:
            item_id = slots_by_index.get(index)
            item_document = (items_by_id or {}).get(item_id)
            player = (players[item_id - 1]
                      if items_by_id is None and item_id
                      and 0 < item_id <= len(players) else None)
        else:
            item_document = None
            player = players[index] if index < len(players) else None
        slot = {
            "index": index,
            "kitNumber": index + 1 if player else 0,
        }
        if item_document is not None:
            slot["kitNumber"] = index + 1
            slot["itemData"] = dict(item_document)
        elif player:
            item_id = (slots_by_index or {}).get(index, index + 1)
            slot["kitNumber"] = index + 1
            slot["itemData"] = fut_items.build_item(
                player, item_id, timestamp)
        slots.append(slot)

    filled = [s for s in slots if "itemData" in s]
    default_kicktakers = [
        {"index": n, "id": s["itemData"]["id"], "dream": False}
        for n, s in enumerate(filled[:5])]
    kicktakers = squad.get("kicktakers", default_kicktakers)
    if not isinstance(kicktakers, list):
        kicktakers = default_kicktakers

    document = {
        "id": int(squad["id"]),
        "personaId": int(persona_id),
        "squadName": str(squad["squadName"]),
        "squadType": SQUAD_TYPE,
        "formation": str(squad["formation"]),
        "captain": int(squad.get(
            "captain", filled[0]["itemData"]["id"] if filled else 0)),
        "chemistry": int(squad["chemistry"]),
        "changed": 0,
        "starRating": int(squad.get("starRating", 5)),
        "players": slots,
        "kicktakers": kicktakers,
        "actives": [],
        "manager": resolve_manager(
            squad.get("manager"),
            items_by_id if managers_by_id is None else managers_by_id),
    }
    custom = squad.get("custom")
    if isinstance(custom, str) and custom:
        document["custom"] = custom
    return document


SQUAD_TYPE_REGULAR = "REGULAR_SQUAD"
SQUAD_TYPE_DREAM = "DREAM_SQUAD"
SQUAD_TYPE_DRAFT = "DRAFT_SQUAD"


def build_empty_squad(squad_id: int, persona_id: int, name: str,
                      formation: str = "f442",
                      squad_type: str = SQUAD_TYPE_REGULAR) -> dict:
    return {
        "id": int(squad_id),
        "personaId": int(persona_id),
        "squadName": str(name),
        "squadType": str(squad_type),
        "formation": str(formation),
        "captain": 0,
        "chemistry": 0,
        "starRating": 0,
        "changed": 0,
        "players": [{"index": index} for index in range(SQUAD_SLOTS)],
        "manager": [],
    }
