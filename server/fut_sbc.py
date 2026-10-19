# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import fut_economy
import fut_squads

STATUS_VOCABULARY_IN_POOL = ("COMPLETED", "IN_PROGRESS", "EXPIRED", "LOCKED",
                             "UNLOCKED", "REPEATABLE")
STATUS_COMPLETED = "COMPLETED"
STATUS_IN_PROGRESS = "IN_PROGRESS"

SBC_REWARD_ITEM_ID_BASE = 900_000

ITEM_AWARD_HAL_ID = 100

PLAYER_TYPE_DEFAULT = "DEFAULT"
PLAYER_TYPE_BRICK = "BRICK"

_NEVER_EXPIRES = 2_145_916_800


SET_IMAGE_GENERIC = 1_001_000
SET_IMAGE_BY_NAME = {
    "premier league":   1_010_000,
    "liga nos":         1_011_000,
    "russian league":   1_012_000,
    "bronze upgrade":   1_002_000,
    "silver upgrade":   1_004_000,
    "gold upgrade":     1_006_000,
    "hybrid leagues":   1_007_000,
    "hybrid nations":   1_008_000,
    "league and nation hybrid": 1_009_000,
}

CHALLENGE_IMAGE_COUNTS = {1_001_000: 3, 1_007_000: 10, 1_008_000: 10,
                          1_009_000: 4, 1_010_000: 20, 1_011_000: 18,
                          1_012_000: 16}


def set_image_id(name: str) -> int:
    return SET_IMAGE_BY_NAME.get(str(name).strip().lower(), SET_IMAGE_GENERIC)


def challenge_image_id(set_name: str, challenge_index: int) -> int | None:
    base = set_image_id(set_name)
    slot = int(challenge_index) + 1
    return base + slot if slot <= CHALLENGE_IMAGE_COUNTS.get(base, 0) else None


CATALOGUE_PATH = Path(__file__).resolve().parent / "data" / "sbc_catalogue.json"


AWARD_COIN = "coin"
AWARD_ITEM = "item"
AWARD_PACK = "pack"
AWARD_BID_TOKEN = "bidToken"
AWARD_TYPES = (AWARD_COIN, AWARD_ITEM, AWARD_PACK, AWARD_BID_TOKEN)

CHALLENGE_COIN_REWARD = 500
SET_COIN_REWARD = 2_500

ELIGIBILITY_KEYS = {
    "team_chemistry": 1,
    "player_count": 2,
    "same_nation_count": 4,
    "same_league_count": 5,
    "same_club_count": 6,
    "unique_nations": 7,
    "unique_leagues": 8,
    "unique_clubs": 9,
    "nation_id": 10,
    "league_id": 11,
    "club_id": 12,
    "player_level": 17,
    "player_rarity": 18,
    "team_rating": 19,
}
ELIGIBILITY_SCOPES = {"min": 0, "max": 1, "exact": 2}
SCOPE_KEY = 13

RULE_KEYS = {
    "unique_nations":    ("unique_nations", None),
    "unique_leagues":    ("unique_leagues", None),
    "unique_clubs":      ("unique_clubs", None),
    "same_nation_count": ("same_nation_count", None),
    "same_league_count": ("same_league_count", None),
    "same_club_count":   ("same_club_count", None),
    "team_rating":       ("team_rating", None),
    "team_chemistry":    ("team_chemistry", None),
    "nation_players":    ("player_count", "nation_id"),
    "league_players":    ("player_count", "league_id"),
    "club_players":      ("player_count", "club_id"),
    "level_players":     ("player_count", "player_level"),
    "rare_players":      ("player_count", "player_rarity"),
}

RARITY_RARE = 1

LEVEL_BRONZE, LEVEL_SILVER, LEVEL_GOLD = 1, 2, 3
LEVEL_BANDS = {LEVEL_BRONZE: (0, 64), LEVEL_SILVER: (65, 74), LEVEL_GOLD: (75, 99)}

CLIENT_EVALUATED = ("team_rating", "team_chemistry")

MAX_WIRE_RULES = 5


def load_catalogue(now: int | None = None) -> dict:
    document = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    if int(document.get("schemaVersion", 0)) != 2:
        raise ValueError("unsupported SBC catalogue schema")
    current = int(time.time()) if now is None else int(now)
    seen_sets, seen_challenges = set(), set()
    categories = []
    for category in document.get("categories") or []:
        active_sets = []
        for sbc_set in category.get("sets") or []:
            set_id = int(sbc_set["id"])
            if set_id in seen_sets:
                raise ValueError(f"duplicate SBC set id: {set_id}")
            seen_sets.add(set_id)
            active_challenges = []
            for challenge in sbc_set.get("challenges") or []:
                challenge_id = int(challenge["id"])
                if challenge_id in seen_challenges:
                    raise ValueError(f"duplicate SBC challenge id: {challenge_id}")
                seen_challenges.add(challenge_id)
                rules = challenge.get("requirements") or []
                if bool(challenge.get("enabled", True)) and len(rules) > MAX_WIRE_RULES:
                    raise ValueError(
                        f"SBC challenge {challenge_id} has {len(rules)} rules;"
                        f" the client shows {MAX_WIRE_RULES}")
                if not 1 <= int(challenge.get("players", STARTING_XI)) <= STARTING_XI:
                    raise ValueError(f"SBC challenge {challenge_id} squad size")
                for rule in rules:
                    if rule.get("type") not in RULE_KEYS:
                        raise ValueError(f"unsupported SBC rule: {rule.get('type')}")
                    if rule.get("scope") not in ELIGIBILITY_SCOPES:
                        raise ValueError(f"unsupported SBC scope: {rule.get('scope')}")
                if bool(challenge.get("enabled", True)):
                    active_challenges.append(challenge)
            if (bool(sbc_set.get("enabled", True)) and
                    int(sbc_set.get("startsAt", 0)) <= current <
                    int(sbc_set.get("endsAt", _NEVER_EXPIRES)) and
                    active_challenges):
                selected_set = dict(sbc_set)
                selected_set["challenges"] = active_challenges
                active_sets.append(selected_set)
        if active_sets:
            selected = dict(category)
            selected["sets"] = active_sets
            categories.append(selected)
    return {"schemaVersion": 2, "categories": categories}


def _all_sets(now: int | None = None) -> list[dict]:
    return [sbc_set for category in load_catalogue(now)["categories"]
            for sbc_set in category["sets"]]


def _wire_requirements(requirements: list[dict]) -> list[dict]:
    rows = []
    for slot, rule in enumerate(requirements[:MAX_WIRE_RULES], 1):
        kind = str(rule["type"])
        key, filter_key = RULE_KEYS[kind]

        def row(name, value):
            rows.append({"eligibilityKey": ELIGIBILITY_KEYS[name],
                         "eligibilitySlot": slot,
                         "eligibilityValue": int(value)})

        row(key, rule["value"])
        if filter_key is not None:
            for filter_id in rule_filter_ids(rule):
                row(filter_key, filter_id)
        row_scope = ELIGIBILITY_SCOPES[str(rule["scope"])]
        rows.append({"eligibilityKey": SCOPE_KEY,
                     "eligibilitySlot": slot,
                     "eligibilityValue": row_scope})
    return rows


def rule_filter_id(rule: dict) -> int:
    if str(rule["type"]) == "rare_players":
        return int(rule.get("filterId", RARITY_RARE))
    return int(rule["filterId"])


def rule_filter_ids(rule: dict) -> tuple[int, ...]:
    if rule.get("filterIds"):
        return tuple(int(value) for value in rule["filterIds"])
    return (rule_filter_id(rule),)


def coin_award(value: int) -> dict:
    return {"type": AWARD_COIN,
            "value": fut_economy.coins(value),
            "count": 1}


def pack_award(pack_id: int, count: int = 1) -> dict:
    import fut_packs
    pack = fut_packs.find_pack(int(pack_id))
    asset = fut_packs.ART_ASSET_BY_TIER.get(
        str((pack or {}).get("category", "gold")), 3)
    return {"type": AWARD_PACK, "value": int(pack_id),
            "count": max(1, int(count)), "assetId": int(asset),
            "halId": int(pack_id)}


_COIN_TEXT = re.compile(r"([\d,]+)\s*coins?", re.I)
_COUNT_TEXT = re.compile(r"^\s*(\d+)\s*x\s*", re.I)
_ITEM_TEXT = re.compile(
    r"(?:\bSBC\b\s+(?:item\s+)?(?P<after>[^,]+?)"
    r"|(?P<before>[^,]+?)\s+\bSBC\b(?:\s+item)?)\s*$", re.I)


def _canonical(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _words(text: str) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", str(text).lower())) - {"pack", "x"}


def _pack_offers():
    import fut_packs
    return (list(fut_packs.PERMANENT_PACK_OFFERS)
            + list(fut_packs.PROMO_PACK_OFFERS)
            + list(fut_packs.REWARD_PACK_OFFERS))


_PLAYER_CARDS: dict = {}


def reward_player(name: str) -> tuple[dict, dict | None] | None:
    import fut
    import fut_items
    player = fut._find_catalogue_player(name)
    if player is None:
        return None
    candidates = [card for card in fut_items.specials_by_asset().get(
        int(player["playerid"]), [])
        if "sbc-reward" in str(card.get("kind", ""))]
    special = max(candidates, key=lambda card: int(card.get("rating", 0)),
                  default=None)
    return player, special


def reward_player_item(name: str, item_id: int = 0,
                       timestamp: int = 0) -> dict | None:
    import fut_items
    resolved = reward_player(name)
    if resolved is None:
        return None
    player, special = resolved
    if special is not None:
        item = fut_items.build_special_item(special, player, item_id, timestamp)
    else:
        base = fut_items.base_cards_by_asset().get(int(player["playerid"]))
        item = (fut_items.build_base_card_item(base, player, item_id, timestamp)
                if base else fut_items.build_item(player, item_id, timestamp,
                                                  rare=True))
    item["untradeable"] = True
    item["discardValue"] = 0
    return item


def player_card(name: str) -> dict | None:
    key = str(name).strip().lower()
    if key not in _PLAYER_CARDS:
        card = reward_player_item(name, 0, 0)
        if card is not None:
            card["id"] = int(card.get("resourceId", 0) or 0)
        _PLAYER_CARDS[key] = card
    return _PLAYER_CARDS[key]


def player_award(name: str, count: int = 1) -> dict:
    award = {"type": AWARD_ITEM, "value": 0, "count": max(1, int(count)),
             "player": str(name)}
    card = player_card(name)
    if card is not None:
        award["assetId"] = int(card.get("assetId", 0) or 0)
        award["ItemType"] = str(card.get("itemType", "player"))
        award["value"] = int(card.get("id", 0) or 0)
        award["halId"] = ITEM_AWARD_HAL_ID
        award["item"] = card
        award["itemData"] = card
    return award


_KIT_CARDS: dict = {}
KIT_QUALITIES = ("bronze", "silver", "gold")


def kit_card(text: str) -> dict | None:
    words = _words(text)
    if "kit" not in words:
        return None
    key = " ".join(sorted(words))
    if key not in _KIT_CARDS:
        import fut_cards
        quality = next((q for q in KIT_QUALITIES if q in words), "gold")
        rare = 1 if "rare" in words else 0
        kits = [item for item in fut_cards.load_cards()["clubItems"]
                if item.get("itemType") == "kit"
                and str(item.get("quality", "")).lower() == quality
                and int(item.get("rareflag", 0) or 0) == rare]
        if not kits:
            _KIT_CARDS[key] = None
        else:
            card = fut_cards.build_card(
                min(kits, key=lambda item: int(item["resourceId"])), 0, 0)
            card["id"] = int(card.get("resourceId", 0) or 0)
            card["untradeable"] = True
            _KIT_CARDS[key] = card
    return _KIT_CARDS[key]


def kit_award(text: str, count: int = 1) -> dict:
    award = {"type": AWARD_ITEM, "value": 0, "count": max(1, int(count)),
             "kit": str(text)}
    card = kit_card(text)
    if card is not None:
        award["value"] = int(card.get("id", 0) or 0)
        award["assetId"] = int(card.get("assetId", 0) or 0)
        award["ItemType"] = str(card.get("itemType", "kit"))
        award["halId"] = ITEM_AWARD_HAL_ID
        award["item"] = card
        award["itemData"] = card
    return award


def reward_item(award: dict, item_id: int = 0, timestamp: int = 0) -> dict | None:
    if award.get("player"):
        return reward_player_item(str(award["player"]), item_id, timestamp)
    if award.get("kit"):
        card = kit_card(str(award["kit"]))
        if card is None:
            return None
        granted = dict(card)
        granted["id"], granted["timestamp"] = int(item_id), int(timestamp)
        return granted
    return None


def parse_rewards(text: str) -> tuple[list[dict], list[str]]:
    awards, unmatched = [], []
    offers = {_canonical(offer["name"]): offer for offer in _pack_offers()}
    aliases = {
        "premiumgoldjumbopack": "jumbopremiumgoldpack",
        "premiumgoldjumbo": "jumbopremiumgoldpack",
        "silverplayerspremiumpack": "premiumsilverplayerspack",
        "silverplayerspremium": "premiumsilverplayerspack",
        "goldplayerspremiumpack": "premiumgoldplayerspack",
        "goldplayerspremium": "premiumgoldplayerspack",
        "primegoldplayers": "primegoldplayerspack",
        "primeelectrumplayers": "primeelectrumplayerspack",
        "jumborareplayerpack": "jumborareplayerspack",
        "jumbosilverpack": "jumbopremiumsilverpack",
        "premiumsilverjumbo": "jumbopremiumsilverpack",
        "premiumsilverjumbopack": "jumbopremiumsilverpack",
        "bronzeplayerspremiumpack": "premiumbronzeplayerspack",
    }
    flat = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", str(text or ""))
    for fragment in re.split(r",", flat):
        fragment = fragment.strip()
        if not fragment:
            continue
        coins = _COIN_TEXT.search(fragment)
        if coins:
            awards.append(coin_award(int(coins.group(1).replace(",", ""))))
            continue
        count_match = _COUNT_TEXT.match(fragment)
        count = int(count_match.group(1)) if count_match else 1
        body = _COUNT_TEXT.sub("", fragment).strip()
        item = _ITEM_TEXT.search(body)
        if item:
            named = (item.group("after") or item.group("before") or "").strip()
            if named:
                awards.append(player_award(named, count))
                continue
        if "kit" in _words(body):
            awards.append(kit_award(body, count))
            continue
        key = _canonical(body)
        offer = offers.get(aliases.get(key, key))
        if offer is None:
            unmatched.append(fragment)
            continue
        awards.append(pack_award(int(offer["id"]), count))
    return awards, unmatched


def wire_awards(awards: list[dict]) -> list[dict]:
    shown = []
    for award in awards:
        kind = award.get("type")
        if kind == AWARD_COIN:
            shown.append({key: award[key] for key in ("type", "value", "count")})
        elif kind == AWARD_PACK:
            shown.append({key: award[key] for key in
                          ("type", "value", "count", "assetId", "halId")})
        elif kind == AWARD_ITEM and award.get("itemData"):
            shown.append({key: award[key] for key in
                          ("type", "value", "count", "assetId", "ItemType",
                           "halId", "item", "itemData")})
    return shown


def challenge_awards(definition: dict) -> list[dict]:
    awards, _ = parse_rewards(definition.get("rewards", ""))
    if awards or "rewardCoins" not in definition:
        return awards
    return [coin_award(int(definition["rewardCoins"]))]


def set_awards(definition: dict) -> list[dict]:
    awards, _ = parse_rewards(definition.get("rewards", ""))
    if awards or "rewardCoins" not in definition:
        return awards
    return [coin_award(int(definition["rewardCoins"]))]


def award_coins(awards: list[dict]) -> int:
    return sum(int(a["value"]) * int(a.get("count", 1))
               for a in awards if a.get("type") == AWARD_COIN)


def award_packs(awards: list[dict]) -> list[int]:
    packs = []
    for award in awards:
        if award.get("type") == AWARD_PACK:
            packs.extend([int(award["value"])] * max(1, int(award.get("count", 1))))
    return packs


def build_player_requirements(players: int) -> list[dict]:
    wanted = max(1, min(STARTING_XI, int(players)))
    return [{"index": index,
             "playerType": PLAYER_TYPE_DEFAULT if index < wanted
             else PLAYER_TYPE_BRICK}
            for index in range(STARTING_XI)]


def challenge_squad_id(challenge_id: int) -> int:
    return SQUAD_ID_BASE + challenge_id


SQUAD_ID_BASE = 800_000


def _challenge(definition: dict, set_id: int, category_id: int, index: int,
               completed: int = 0, in_progress: bool = False,
               set_repeatable: bool = False) -> dict:
    repeatable = bool(definition.get("repeatable", set_repeatable))
    return {
        "challengeId": int(definition["id"]),
        "setId": set_id,
        "categoryId": category_id,
        "name": str(definition["name"]),
        "description": str(definition["description"]),
        "formation": str(definition["formation"]),
        "index": index,
        "squadId": challenge_squad_id(int(definition["id"])),
        **({"status": STATUS_COMPLETED}
           if completed and not repeatable else
           {"status": STATUS_IN_PROGRESS} if in_progress else {}),
        "repeatable": repeatable,
        "timesCompleted": completed,
        "tutorial": 0,
        "endTime": int(definition.get("endsAt", _NEVER_EXPIRES)),
        "elgReq": _wire_requirements(definition.get("requirements") or []),
        "awards": wire_awards(challenge_awards(definition)),
    }


def _set(definition: dict, category_id: int, completed_challenges: int = 0,
         times_completed: int = 0, tagged: bool = False) -> dict:
    return {
        "setId": int(definition["id"]),
        "setImageId": str(set_image_id(definition["name"])),
        "categoryId": category_id,
        "name": str(definition["name"]),
        "description": str(definition["description"]),
        "priority": int(definition["priority"]),
        "challengesCount": len(definition["challenges"]),
        "challengesCompletedCount": completed_challenges,
        "timesCompleted": times_completed,
        "repeatable": bool(definition.get("repeatable", False)),
        "hidden": False,
        "tutorial": False,
        "taggedByUser": bool(tagged),
        "taggedByProduction": False,
        "endTime": int(definition.get("endsAt", _NEVER_EXPIRES)),
        "awards": wire_awards(set_awards(definition)),
    }


def build_sets(completed: dict[int, int] | None = None,
               tagged: set[int] | None = None) -> bytes:
    done = completed or {}
    tagged = tagged or set()
    categories = []
    for category in load_catalogue()["categories"]:
        sets = []
        for definition in category["sets"]:
            ids = challenge_ids(int(definition["id"]))
            counts = [int(done.get(challenge_id, 0)) for challenge_id in ids]
            finished = sum(1 for count in counts if count)
            cycles = min(counts, default=0) if finished == len(ids) else 0
            if ids and finished == len(ids) and                     bool(definition.get("repeatable", False)):
                finished, cycles = 0, 0
            sets.append(_set(
                definition, int(category["id"]), finished, cycles,
                int(definition["id"]) in tagged))
        categories.append({
            "categoryId": int(category["id"]),
            "name": str(category["name"]),
            "priority": int(category.get("priority", 1)),
            "sets": sets,
        })
    document = {"categories": categories}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def challenge_ids(set_id: int) -> list[int]:
    definition = find_set(set_id)
    return ([int(row["id"]) for row in definition["challenges"]]
            if definition else [])


def find_set(set_id: int):
    for entry in _all_sets():
        if int(entry["id"]) == int(set_id):
            return entry
    return None


def build_challenges(set_id: int, completed: dict[int, int] | None = None,
                     in_progress: set | None = None) -> bytes:
    done = completed or {}
    started = in_progress or set()
    entry = find_set(set_id)
    challenges = []
    if entry is not None:
        category_id = next(
            int(category["id"])
            for category in load_catalogue()["categories"]
            if any(int(row["id"]) == int(set_id) for row in category["sets"]))
        set_repeatable = bool(entry.get("repeatable", False))
        for index, definition in enumerate(entry["challenges"]):
            challenge_id = int(definition["id"])
            challenges.append(_challenge(definition, int(set_id), category_id,
                                         index, done.get(challenge_id, 0),
                                         challenge_id in started,
                                         set_repeatable))
    document = {"challenges": challenges}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


SQUAD_TYPE_CHALLENGE = "REGULAR_SQUAD"

SQUAD_SLOTS = 23
STARTING_XI = 11


def build_challenge_start(challenge_id: int, set_id: int, persona_id: int,
                          formation: str = "f442",
                          saved: dict | None = None,
                          items_by_id: dict | None = None) -> bytes:
    squad = fut_squads.build_empty_squad(
        challenge_squad_id(challenge_id), persona_id,
        _challenge_name(set_id, challenge_id),
        (saved or {}).get("formation") or formation,
        SQUAD_TYPE_CHALLENGE)
    slots = (saved or {}).get("slots") or {}
    lookup = items_by_id or {}
    for index, item_id in sorted(slots.items()):
        if not 0 <= index < len(squad["players"]):
            continue
        item = lookup.get(int(item_id))
        if item is None:
            continue
        squad["players"][index]["itemData"] = item
        squad["players"][index]["kitNumber"] = index + 1
    if saved:
        squad["chemistry"] = int(saved.get("chemistry", 0) or 0)
    document = {
        "squad": squad,
        "playerRequirements": build_player_requirements(
            challenge_players(challenge_definition(challenge_id) or {})),
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_challenge_squad(challenge_id: int, set_id: int, persona_id: int,
                          formation: str = "f442") -> bytes:
    return json.dumps(
        fut_squads.build_empty_squad(
            challenge_squad_id(challenge_id), persona_id,
            _challenge_name(set_id, challenge_id), formation,
            SQUAD_TYPE_CHALLENGE),
        separators=(",", ":")).encode("utf-8")


def _challenge_name(set_id: int, challenge_id: int) -> str:
    entry = find_set(set_id)
    if entry is not None:
        for definition in entry["challenges"]:
            if int(definition["id"]) == int(challenge_id):
                return str(definition["name"])
    return "Squad Building Challenge"


def find_challenge(challenge_id: int):
    for sbc_set in _all_sets():
        for index, definition in enumerate(sbc_set["challenges"]):
            if int(definition["id"]) == int(challenge_id):
                return (int(sbc_set["id"]), str(definition["name"]),
                        str(definition["description"]),
                        str(definition["formation"]), index)
    return None


def challenge_definition(challenge_id: int) -> dict | None:
    for sbc_set in _all_sets():
        for definition in sbc_set["challenges"]:
            if int(definition["id"]) == int(challenge_id):
                result = dict(definition)
                result["setId"] = int(sbc_set["id"])
                result["setChallengeIds"] = challenge_ids(int(sbc_set["id"]))
                result["repeatable"] = bool(
                    definition.get("repeatable", sbc_set.get("repeatable", False)))
                result["rewardUntradeable"] = bool(
                    definition.get("rewardUntradeable", False))
                result["setRewardUntradeable"] = bool(
                    sbc_set.get("rewardUntradeable", False))
                awards = challenge_awards(definition)
                group = set_awards(sbc_set)
                if len(sbc_set["challenges"]) == 1 and group == awards:
                    awards = []
                result["challengeAwards"] = awards
                result["setAwards"] = group
                result["rewardCoins"] = award_coins(awards)
                result["setRewardCoins"] = award_coins(group)
                result["challengePacks"] = award_packs(awards)
                result["setPacks"] = award_packs(group)
                return result
    return None


def challenge_players(definition: dict) -> int:
    return max(1, min(STARTING_XI, int(definition.get("players", STARTING_XI))))


def player_level(item: dict) -> int:
    rating = int(item.get("rating", 0) or 0)
    for level, (low, high) in LEVEL_BANDS.items():
        if low <= rating <= high:
            return level
    return LEVEL_GOLD if rating > 0 else 0


def _distinct(items, field):
    return len({int(item.get(field, 0) or 0) for item in items
                if int(item.get(field, 0) or 0)})


def _largest_group(items, field):
    counts = {}
    for item in items:
        value = int(item.get(field, 0) or 0)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return max(counts.values(), default=0)


def _matching(items, rule):
    kind, wanted = str(rule["type"]), set(rule_filter_ids(rule))
    if kind == "nation_players":
        return sum(1 for i in items if int(i.get("nation", 0) or 0) in wanted)
    if kind == "league_players":
        return sum(1 for i in items if int(i.get("leagueId", 0) or 0) in wanted)
    if kind == "club_players":
        return sum(1 for i in items if int(i.get("teamid", 0) or 0) in wanted)
    if kind == "level_players":
        return sum(1 for i in items if player_level(i) in wanted)
    return sum(1 for i in items if int(i.get("rareflag", 0) or 0))


def evaluate_challenge(definition: dict, items_by_slot: dict[int, dict],
                       reported: dict | None = None) -> list[str]:
    wanted_players = challenge_players(definition)
    items = [items_by_slot[index] for index in sorted(items_by_slot)
             if 0 <= int(index) < wanted_players]
    reported = reported or {}
    failures = []
    if len(items) != wanted_players:
        failures.append(f"player_count exact {wanted_players} (actual {len(items)})")
    for rule in definition.get("requirements") or []:
        kind, scope = str(rule["type"]), str(rule["scope"])
        if kind == "unique_nations":
            actual = _distinct(items, "nation")
        elif kind == "unique_leagues":
            actual = _distinct(items, "leagueId")
        elif kind == "unique_clubs":
            actual = _distinct(items, "teamid")
        elif kind == "same_nation_count":
            actual = _largest_group(items, "nation")
        elif kind == "same_league_count":
            actual = _largest_group(items, "leagueId")
        elif kind == "same_club_count":
            actual = _largest_group(items, "teamid")
        elif kind == "team_rating":
            actual = int(reported.get("rating", 0) or 0)
        elif kind == "team_chemistry":
            actual = int(reported.get("chemistry", 0) or 0)
        else:
            actual = _matching(items, rule)
        wanted = int(rule["value"])
        passed = ((scope == "min" and actual >= wanted) or
                  (scope == "max" and actual <= wanted) or
                  (scope == "exact" and actual == wanted))
        if not passed:
            failures.append(f"{kind} {scope} {wanted} (actual {actual})")
    return failures


SQUAD_KEY_PREFIX = "sbcSquad"
PROGRESS_KEY = "sbcProgress"
_SQ_RATING = 100
_SQ_CHEMISTRY = 101
_SQ_FORMATION = 102


def squad_key(challenge_id: int) -> str:
    return f"{SQUAD_KEY_PREFIX}{int(challenge_id)}"


def parse_submitted_squad(body: bytes | None) -> dict | None:
    try:
        document = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(document, dict):
        return None
    slots = {}
    for entry in document.get("players") or []:
        if not isinstance(entry, dict):
            continue
        item = entry.get("itemData")
        if not isinstance(item, dict):
            continue
        try:
            index = int(entry.get("index", -1))
            item_id = int(item.get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if 0 <= index < SQUAD_SLOTS and item_id > 0:
            slots[index] = item_id
    out = {"slots": slots}
    for name, key in (("rating", "rating"), ("chemistry", "chemistry")):
        try:
            out[name] = int(document.get(key, 0) or 0)
        except (TypeError, ValueError):
            out[name] = 0
    formation = document.get("formation")
    out["formation"] = str(formation) if isinstance(formation, str) else ""
    return out


def save_submitted_squad(store, persona_id: int, challenge_id: int,
                         parsed: dict, repeatable: bool = False) -> None:
    if parsed is None:
        raise ValueError("invalid squad document")
    if hasattr(store, "save_sbc_squad"):
        store.save_sbc_squad(int(persona_id), int(challenge_id), parsed,
                             repeatable=repeatable)
        return
    entries = [{"key": index, "value": item_id}
               for index, item_id in sorted(parsed.get("slots", {}).items())]
    entries += [
        {"key": _SQ_RATING, "value": int(parsed.get("rating", 0))},
        {"key": _SQ_CHEMISTRY, "value": int(parsed.get("chemistry", 0))},
        {"key": _SQ_FORMATION,
         "value": _formation_index(parsed.get("formation", ""))},
    ]
    store.save_clientdata(int(persona_id), squad_key(challenge_id), entries)


def load_submitted_squad(store, persona_id: int, challenge_id: int) -> dict:
    if hasattr(store, "load_sbc_squad"):
        return store.load_sbc_squad(int(persona_id), int(challenge_id)) or {
            "slots": {}, "rating": 0, "chemistry": 0, "formation": ""}
    values = {}
    for entry in (store.load_clientdata(int(persona_id),
                                        squad_key(challenge_id)) or []):
        try:
            values[int(entry.get("key", -1))] = int(entry.get("value", 0))
        except (AttributeError, TypeError, ValueError):
            continue
    return {
        "slots": {slot: values[slot] for slot in range(SQUAD_SLOTS)
                  if values.get(slot)},
        "rating": values.get(_SQ_RATING, 0),
        "chemistry": values.get(_SQ_CHEMISTRY, 0),
        "formation": _formation_name(values.get(_SQ_FORMATION, 0)),
    }


def _formation_index(name: str) -> int:
    import fut_squads
    try:
        return fut_squads.FORMATIONS.index(str(name))
    except ValueError:
        return fut_squads.FORMATIONS.index(fut_squads.DEFAULT_FORMATION)


def _formation_name(index: int) -> str:
    import fut_squads
    if 0 <= index < len(fut_squads.FORMATIONS):
        return fut_squads.FORMATIONS[index]
    return fut_squads.DEFAULT_FORMATION


def load_progress(store, persona_id: int) -> dict:
    if hasattr(store, "sbc_progress"):
        return store.sbc_progress(int(persona_id))
    out = {}
    for entry in (store.load_clientdata(int(persona_id), PROGRESS_KEY) or []):
        try:
            out[int(entry.get("key", 0))] = int(entry.get("value", 0))
        except (AttributeError, TypeError, ValueError):
            continue
    return {k: v for k, v in out.items() if k and v}


def load_in_progress(store, persona_id: int) -> set:
    if hasattr(store, "sbc_in_progress"):
        return set(store.sbc_in_progress(int(persona_id)))
    started = set()
    for definition in (challenge for sbc_set in _all_sets()
                       for challenge in sbc_set["challenges"]):
        challenge_id = int(definition["id"])
        if (load_submitted_squad(store, persona_id, challenge_id)
                or {}).get("slots"):
            started.add(challenge_id)
    return started


def record_completion(store, persona_id: int, challenge_id: int) -> dict:
    progress = load_progress(store, persona_id)
    progress[int(challenge_id)] = 1
    store.save_clientdata(int(persona_id), PROGRESS_KEY,
                          [{"key": k, "value": v}
                           for k, v in sorted(progress.items())])
    return progress


def build_submit_receipt(challenge_id: int, set_id: int, credits: int,
                         challenge_awards: list | None = None,
                         set_awards: list | None = None,
                         recovered_packs: int = 0) -> bytes:
    document = {
        "challengeId": int(challenge_id),
        "setId": int(set_id),
        "credits": int(credits),
        "grantedChallengeAwards": list(challenge_awards or []),
        "grantedSetAwards": list(set_awards or []),
        "preOrderPacks": 0,
        "recoveredPacks": max(0, int(recovered_packs)),
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def set_of(challenge_id: int) -> int:
    found = find_challenge(challenge_id)
    return found[0] if found else 0


def set_is_complete(set_id: int, progress: dict) -> bool:
    entry = find_set(set_id)
    if entry is None:
        return False
    ids = challenge_ids(set_id)
    return all(progress.get(cid) for cid in ids)
