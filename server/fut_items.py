# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
from pathlib import Path

CATALOGUE = Path(__file__).resolve().parent / "data" / "players.json"

POSITIONS = {
    0: "GK", 1: "CB", 2: "RWB", 3: "RB", 4: "CB", 5: "CB", 6: "CB", 7: "LB",
    8: "LWB", 9: "CDM", 10: "CDM", 11: "CDM", 12: "RM", 13: "CM", 14: "CM",
    15: "CM", 16: "LM", 17: "CAM", 18: "CAM", 19: "CAM", 20: "RF", 21: "CF",
    22: "LF", 23: "RW", 24: "ST", 25: "ST", 26: "ST", 27: "LW",
}

RARE_CARD = 1
COMMON_CARD = 0

OUTFIELD_PLAY_STYLES = range(250, 269)
GK_PLAY_STYLES = range(269, 274)
BASIC_PLAY_STYLE = 250
GK_BASIC_PLAY_STYLE = 273


def default_play_style(position: str) -> int:
    return GK_BASIC_PLAY_STYLE if position == "GK" else BASIC_PLAY_STYLE


def valid_play_style(position: str, play_style) -> int:
    try:
        value = int(play_style or 0)
    except (TypeError, ValueError):
        value = 0
    allowed = GK_PLAY_STYLES if position == "GK" else OUTFIELD_PLAY_STYLES
    return value if value in allowed else default_play_style(position)

OUTFIELD_STATS = (
    (("acceleration", 0.45), ("sprintspeed", 0.55)),
    (("finishing", 0.45), ("longshots", 0.20), ("shotpower", 0.20),
     ("positioning", 0.05), ("volleys", 0.05), ("penalties", 0.05)),
    (("shortpassing", 0.35), ("vision", 0.20), ("crossing", 0.15),
     ("longpassing", 0.15), ("curve", 0.10), ("freekickaccuracy", 0.05)),
    (("dribbling", 0.50), ("ballcontrol", 0.35), ("agility", 0.10),
     ("balance", 0.05)),
    (("marking", 0.30), ("standingtackle", 0.30), ("interceptions", 0.20),
     ("headingaccuracy", 0.10), ("slidingtackle", 0.10)),
    (("strength", 0.50), ("stamina", 0.25), ("aggression", 0.20),
     ("jumping", 0.05)),
)
KEEPER_STATS = (
    (("gkdiving", 1.0),), (("gkhandling", 1.0),), (("gkkicking", 1.0),),
    (("gkreflexes", 1.0),),
    (("acceleration", 0.5), ("sprintspeed", 0.5)),
    (("gkpositioning", 1.0),),
)


def load_catalogue(path: Path = CATALOGUE) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return json.load(handle).get("players", [])


def headline_stats(player: dict) -> list:
    attributes = player.get("attributes", {})
    table = KEEPER_STATS if player.get("position") == 0 else OUTFIELD_STATS
    out = []
    for weights in table:
        total = sum(attributes.get(name, 0) * weight for name, weight in weights)
        out.append(max(0, min(99, int(total + 0.5))))
    return out


def build_item(player: dict, item_id: int, timestamp: int,
               rare: bool = True) -> dict:
    asset_id = player["playerid"]
    item = {
        "id": item_id,
        "marketDataMinPrice": 0,
        "marketDataMaxPrice": 0,
        "assetId": asset_id,
        "resourceId": asset_id,
        "rating": player["rating"],
        "preferredPosition": POSITIONS.get(player["position"], "CM"),
        "itemType": "player",
        "itemState": "free",
        "teamid": player.get("teamid") or 0,
        "leagueId": player.get("leagueid") or 0,
        "nation": player.get("nationid") or 0,
        "rareflag": RARE_CARD if rare else COMMON_CARD,
        "playStyle": BASIC_PLAY_STYLE,
        "contract": 7,
        "fitness": 99,
        "injuryGames": 0,
        "injuryType": "none",
        "suspension": 0,
        "training": 0,
        "owners": 1,
        "untradeable": False,
        "discardValue": discard_value(player["rating"],
                                      RARE_CARD if rare else COMMON_CARD),
        "lastSalePrice": 0,
        "timestamp": timestamp,
        "assists": 0,
        "lifetimeAssists": 0,
        "cardsubtypeid": 0,
        "name": player.get("name", ""),
        "attributeList": [{"index": n, "value": v}
                          for n, v in enumerate(headline_stats(player))],
        "statsList": [],
        "lifetimeStats": [],
    }
    card = player.get("_futBaseCard")
    if card is not None:
        item["rating"] = int(card["rating"])
        item["resourceId"] = int(card["resourceId"])
        item["rareflag"] = int(card["rareflag"])
        item["preferredPosition"] = str(card.get(
            "preferredPosition", item["preferredPosition"]))
        for card_key, item_key in (("teamid", "teamid"),
                                   ("leagueId", "leagueId"),
                                   ("nation", "nation")):
            if card_key in card:
                item[item_key] = int(card[card_key])
        stats = [max(0, min(99, int(value)))
                 for value in card.get("headlineStats", [])]
        if len(stats) != 6:
            raise ValueError(
                "a recovered base card must have six headline stats")
        item["attributeList"] = [
            {"index": index, "value": value}
            for index, value in enumerate(stats)
        ]
        item["discardValue"] = discard_value(item["rating"],
                                              item["rareflag"])
    item["playStyle"] = default_play_style(item["preferredPosition"])
    return item


def discard_value(rating: int, rare_flag: int = RARE_CARD) -> int:
    import fut_cards
    price = fut_cards.player_discard_value(rating, rare_flag)
    if price:
        return price
    return 600 if rating >= 75 else 300 if rating >= 65 else 100


def club_items(players: list, count: int, offset: int = 0,
               timestamp: int = 0) -> list:
    chosen = players[offset:offset + count]
    return [build_item(player, offset + index + 1, timestamp)
            for index, player in enumerate(chosen)]


PILE_CLUB = "club"
PILE_TRADE = "trade"


def build_item_move(body: bytes) -> dict:
    import json as _json
    try:
        document = _json.loads(body or b"{}")
    except (ValueError, TypeError):
        document = {}
    moved = []
    for entry in (document.get("itemData") or []):
        if not isinstance(entry, dict):
            continue
        try:
            item_id = int(entry["id"])
        except (KeyError, TypeError, ValueError):
            continue
        moved.append({
            "id": item_id,
            "pile": str(entry.get("pile", PILE_CLUB)),
            "success": True,
        })
    return {"itemData": moved}


SPECIAL_CATALOGUE = Path(__file__).resolve().parent / "data" / "special_cards.json"
BASE_CARD_CATALOGUE = Path(__file__).resolve().parent / "data" / "base_cards.json"

_SPECIALS: list | None = None
_BASE_CARDS: list | None = None
_CURRENT_CATALOGUE: list | None = None


def load_specials(path: Path = SPECIAL_CATALOGUE) -> list:
    global _SPECIALS
    if _SPECIALS is None:
        if not path.is_file():
            _SPECIALS = []
        else:
            with path.open(encoding="utf-8") as handle:
                _SPECIALS = json.load(handle).get("cards", [])
    return _SPECIALS


def load_base_cards(path: Path = BASE_CARD_CATALOGUE) -> list:
    global _BASE_CARDS
    if _BASE_CARDS is None:
        if not path.is_file():
            _BASE_CARDS = []
        else:
            with path.open(encoding="utf-8") as handle:
                _BASE_CARDS = json.load(handle).get("cards", [])
    return _BASE_CARDS


def base_cards_by_asset(cards: list | None = None) -> dict[int, dict]:
    latest: dict[int, dict] = {}
    for card in (load_base_cards() if cards is None else cards):
        asset_id = int(card["assetId"])
        current = latest.get(asset_id)
        if (current is None or int(card.get("siteId", 0)) >
                int(current.get("siteId", 0))):
            latest[asset_id] = card
    return latest


def load_current_catalogue(players: list | None = None,
                           base_cards: list | None = None) -> list:
    global _CURRENT_CATALOGUE
    cacheable = players is None and base_cards is None
    if cacheable and _CURRENT_CATALOGUE is not None:
        return _CURRENT_CATALOGUE
    source = load_catalogue() if players is None else players
    bases = base_cards_by_asset(base_cards)
    current = []
    for player in source:
        row = dict(player)
        card = bases.get(int(row["playerid"]))
        if card is not None:
            row.update({
                "rating": int(card["rating"]),
                "teamid": int(card["teamid"]),
                "leagueid": int(card["leagueId"]),
                "nationid": int(card["nation"]),
                "preferredPosition": str(card["preferredPosition"]),
                "rareflag": int(card["rareflag"]),
                "resourceId": int(card["resourceId"]),
                "_futBaseCard": card,
            })
        current.append(row)
    if cacheable:
        _CURRENT_CATALOGUE = current
    return current


def specials_by_asset() -> dict:
    out: dict = {}
    for card in load_specials():
        out.setdefault(card["assetId"], []).append(card)
    for cards in out.values():
        cards.sort(key=lambda card: -card["rating"])
    return out


DEFAULT_PACK_VARIANT_POLICY = {"mode": "highestRatedPackable"}


def _pack_variant_order(card: dict) -> tuple[int, int, int]:
    return (int(card.get("rating", 0)),
            int(card.get("siteId", 0)),
            int(card.get("resourceId", card.get("assetId", 0))))


def pack_player_variants(special_cards: list | None = None,
                         base_cards: list | None = None,
                         policy: dict | None = None) -> dict[int, tuple[str, dict]]:
    selected_policy = policy if isinstance(policy, dict) else {}
    mode = str(selected_policy.get(
        "mode", DEFAULT_PACK_VARIANT_POLICY["mode"]))
    if mode != "highestRatedPackable":
        raise ValueError(f"unsupported player variant policy {mode!r}")

    selected: dict[int, tuple[str, dict]] = {
        asset_id: ("base", card)
        for asset_id, card in base_cards_by_asset(base_cards).items()
        if bool(card.get("packable", True))
    }
    for card in (load_specials() if special_cards is None else special_cards):
        if not bool(card.get("packable", False)):
            continue
        asset_id = int(card["assetId"])
        current = selected.get(asset_id)
        if current is None or _pack_variant_order(card) > \
                _pack_variant_order(current[1]):
            selected[asset_id] = ("special", card)
    return selected


def active_specials(cards: list | None = None,
                    base_cards: list | None = None,
                    policy: dict | None = None) -> list:
    variants = pack_player_variants(cards, base_cards, policy)
    specials = [card for kind, card in variants.values() if kind == "special"]
    return sorted(specials, key=lambda card: (-int(card["rating"]),
                                               int(card["assetId"])))


def build_base_card_item(card: dict, player: dict, item_id: int,
                         timestamp: int) -> dict:
    current = dict(player)
    current["_futBaseCard"] = card
    return build_item(current, item_id, timestamp,
                      rare=int(card.get("rareflag", 0)) == RARE_CARD)


def build_special_item(special: dict, player: dict, item_id: int,
                       timestamp: int) -> dict:
    item = build_item(player, item_id, timestamp)
    item["rating"] = int(special["rating"])
    item["resourceId"] = int(special["resourceId"])
    item["rareflag"] = int(special["rareflag"])
    item["preferredPosition"] = str(special.get(
        "preferredPosition", item["preferredPosition"]))
    for key in ("teamid", "leagueId", "nation"):
        if key in special:
            item[key] = int(special[key])
    if special.get("headlineStats") is not None:
        stats = [max(0, min(99, int(value)))
                 for value in special["headlineStats"]]
        if len(stats) != 6:
            raise ValueError("a special card must have six headline stats")
        item["attributeList"] = [
            {"index": index, "value": value}
            for index, value in enumerate(stats)
        ]
    item["discardValue"] = discard_value(item["rating"],
                                         int(special["rareflag"]))
    item["playStyle"] = default_play_style(item["preferredPosition"])
    return item
