# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
from pathlib import Path

CATALOGUE = Path(__file__).resolve().parent / "data" / "fut_cards.json"

_CARDS: dict | None = None

KIT_CATEGORY_HOME = 2
KIT_CATEGORY_AWAY = 3
KIT_CATEGORY_THIRD = 5

DEFAULT_DISCARD = {"bronze": 8, "silver": 25, "gold": 63}

PLAYER_CARD_TYPE = 1
QUALITY_LEVEL = {"bronze": 1, "silver": 2, "gold": 3}

_DISCARD_TABLE: dict | None = None


def discard_table() -> dict:
    global _DISCARD_TABLE
    if _DISCARD_TABLE is None:
        _DISCARD_TABLE = {
            (int(row["cardType"]), int(row["level"]), int(row["rare"])):
                int(row["price"])
            for row in load_cards().get("discardValues", [])
        }
    return _DISCARD_TABLE


def level_for(rating: int) -> int:
    if rating >= 75:
        return 3
    if rating >= 65:
        return 2
    return 1


def player_discard_value(rating: int, rare_flag: int = 0) -> int:
    table = discard_table()
    rating = int(rating)
    level = level_for(rating)
    price = table.get((PLAYER_CARD_TYPE, level, int(rare_flag)))
    if price is None:
        price = table.get((PLAYER_CARD_TYPE, level, 3 if rare_flag > 1 else 0))
    if not price:
        return 0
    return int(int(price) * rating / 100 + 0.5)


def load_cards(path: Path = CATALOGUE) -> dict:
    global _CARDS
    if _CARDS is None:
        if not path.is_file():
            _CARDS = {"consumables": [], "staff": [], "clubItems": [],
                      "discardValues": []}
        else:
            with path.open(encoding="utf-8") as handle:
                _CARDS = json.load(handle)
    return _CARDS


def family(name: str) -> list:
    return load_cards().get(name, [])


def pack_eligible(name: str = "consumables", quality: str | None = None,
                  rare: bool | None = None) -> list:
    items = [item for item in family(name) if item.get("packEligible", True)]
    if quality is not None:
        items = [item for item in items if item.get("quality") == quality]
    if rare is not None:
        items = [item for item in items
                 if bool(int(item.get("rareflag", 0) or 0)) is rare]
    return items


def discard_value(definition: dict) -> int:
    value = int(definition.get("discardValue", 0) or 0)
    if value:
        return value
    return DEFAULT_DISCARD.get(definition.get("quality", "bronze"), 8)


STAFF_SUBTYPE_FROM_ROLE = True
STAFF_ROLE_SUBTYPE = {"manager": 4, "headCoach": 5, "GKCoach": 6,
                      "physio": 7, "fitnessCoach": 8}


STAFF_START_CONTRACT = 7


def staff_role_subtype(resource_id: int) -> int:
    if not STAFF_SUBTYPE_FROM_ROLE:
        return 0
    role = family_by_resource().get(int(resource_id or 0))
    return STAFF_ROLE_SUBTYPE.get(str(role or ""), 0)


def build_card(definition: dict, item_id: int, timestamp: int) -> dict:
    resource_id = int(definition["resourceId"])
    card = {
        "id": int(item_id),
        "assetId": int(definition.get("assetId", resource_id)),
        "resourceId": resource_id,
        "itemType": str(definition["itemType"]),
        "itemState": "free",
        "rating": int(definition.get("rating", 0)),
        "rareflag": int(definition.get("rareflag", 0)),
        "cardassetid": int(definition.get("cardassetid", 0)),
        "cardsubtypeid": int(definition.get("cardsubtypeid", 0)),
        "amount": int(definition.get("amount", 0)),
        "year": int(definition.get("year", 2017)),
        "discardValue": discard_value(definition),
        "untradeable": True,
        "owners": 1,
        "lastSalePrice": 0,
        "marketDataMinPrice": 0,
        "marketDataMaxPrice": 0,
        "timestamp": int(timestamp),
    }
    for key in ("bronze", "silver", "gold"):
        if key in definition:
            card[key] = int(definition[key] or 0)
    if str(definition.get("itemType", "")) == "staff":
        subtype = (STAFF_ROLE_SUBTYPE.get(str(definition.get("family", "")), 0)
                   if STAFF_SUBTYPE_FROM_ROLE else 0)
        if subtype:
            card["cardsubtypeid"] = subtype
        card["contract"] = STAFF_START_CONTRACT
    category = definition.get("category")
    if isinstance(category, int):
        card["category"] = category
    name = str(definition.get("name", "") or "")
    if name:
        card["name"] = name
    team_id = int(definition.get("teamid", 0) or 0)
    if team_id:
        card["teamid"] = team_id
    nation = int(definition.get("nation", 0) or 0)
    if nation:
        card["nation"] = nation
    league_id = int(definition.get("leagueId", 0) or 0)
    if league_id:
        card["leagueId"] = league_id
    manufacturer = str(definition.get("manufacturer", "") or "")
    if manufacturer:
        card["manufacturer"] = manufacturer

    if str(definition.get("itemType", "")) == "stadium":
        stadium_id = int(definition.get("stadiumid")
                         or definition.get("assetId", resource_id) or 0)
        if stadium_id:
            card["stadiumid"] = stadium_id

    rating = int(definition.get("rating", 0) or 0)
    if rating:
        card["value"] = rating
    return card


_FAMILY_BY_RESOURCE: dict | None = None


_DEFINITIONS_BY_RESOURCE = None


def definitions_by_resource() -> dict:
    global _DEFINITIONS_BY_RESOURCE
    if _DEFINITIONS_BY_RESOURCE is None:
        _DEFINITIONS_BY_RESOURCE = {
            int(item["resourceId"]): item
            for group in ("consumables", "staff", "clubItems")
            for item in family(group) if item.get("resourceId")
        }
    return _DEFINITIONS_BY_RESOURCE


def family_by_resource() -> dict:
    global _FAMILY_BY_RESOURCE
    if _FAMILY_BY_RESOURCE is None:
        _FAMILY_BY_RESOURCE = {
            int(item["resourceId"]): item.get("family")
            for group in ("consumables", "staff")
            for item in family(group) if item.get("family")
        }
    return _FAMILY_BY_RESOURCE
