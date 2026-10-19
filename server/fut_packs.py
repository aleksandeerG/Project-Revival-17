# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
from pathlib import Path

import fut_cards
import fut_items
import fut_player_weights

ROTATION_CONFIG = Path(__file__).resolve().parent / "data" / "pack_rotation.json"

PERMANENT_PACK_OFFERS = (
    {"id": 100, "packType": "BRONZE", "category": "bronze", "priority": 1,
     "name": "Bronze Pack", "coins": 400, "points": 0,
     "bio": "Great value for increasing club depth. A mix of 12 items, "
            "including players, club items and consumables, at least 10 Bronze "
            "with 1 Rare.",
     "itemQuantity": 12, "rareQuantity": 1,
     "bronzeQuantity": 10, "silverQuantity": 2, "goldQuantity": 0},
    {"id": 103, "packType": "BRONZE", "category": "bronze", "priority": 2,
     "name": "Premium Bronze Pack", "coins": 750, "points": 0,
     "bio": "Triple the Rares of a standard Bronze Pack. A mix of 12 items, "
            "including players, club items and consumables, at least 10 Bronze "
            "with 3 Rares.",
     "itemQuantity": 12, "rareQuantity": 3,
     "bronzeQuantity": 10, "silverQuantity": 2, "goldQuantity": 0},
    {"id": 200, "packType": "SILVER", "category": "silver", "priority": 3,
     "name": "Silver Pack", "coins": 2500, "points": 50,
     "bio": "Great value for building mid-tiered squads. A mix of 12 items, "
            "including players and consumables, at least 11 Silver with 1 "
            "Rare.",
     "itemQuantity": 12, "rareQuantity": 1,
     "bronzeQuantity": 1, "silverQuantity": 11, "goldQuantity": 0},
    {"id": 203, "packType": "SILVER", "category": "silver", "priority": 4,
     "name": "Premium Silver Pack", "coins": 3750, "points": 75,
     "bio": "Triple the Rares of a standard Silver Pack! A mix of 12 items, "
            "including players and consumables, at least 11 Silver with 3 "
            "Rares.",
     "itemQuantity": 12, "rareQuantity": 3,
     "bronzeQuantity": 1, "silverQuantity": 11, "goldQuantity": 0},
    {"id": 300, "packType": "GOLD", "category": "gold", "priority": 5,
     "name": "Gold Pack", "coins": 5000, "points": 100,
     "bio": "Great value for finding top-rated players. A mix of 12 items, "
            "including players and consumables, at least 10 Gold with 1 Rare.",
     "itemQuantity": 12, "rareQuantity": 1,
     "bronzeQuantity": 0, "silverQuantity": 2, "goldQuantity": 10},
    {"id": 304, "packType": "PREMIUM_GOLD", "category": "gold", "priority": 6,
     "name": "Premium Gold Pack", "coins": 7500, "points": 150,
     "bio": "Triple the Rares of a standard Gold Pack! A mix of 12 items, "
            "including players and consumables, at least 10 Gold with 3 Rares.",
     "itemQuantity": 12, "rareQuantity": 3,
     "bronzeQuantity": 0, "silverQuantity": 2, "goldQuantity": 10},
)

REWARD_PACK_OFFERS = (
    {"id": 620, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "happy birthday pack", "coins": 0, "points": 0,
     "bio": "La multi ani unchioooo!!! Esti scula noastra mare si te iubim mult. This pack contains 25 90+ rated players",
     "itemQuantity": 25, "rareQuantity": 25, "playersOnly": True,
     "minimumPlayerRating": 90,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 25},
    {"id": 600, "packType": "BRONZE", "category": "bronze", "priority": 0,
     "name": "Bronze Players Pack", "coins": 0, "points": 0,
     "bio": "12 Bronze players.",
     "itemQuantity": 12, "rareQuantity": 0, "playersOnly": True,
     "bronzeQuantity": 12, "silverQuantity": 0, "goldQuantity": 0},
    {"id": 601, "packType": "BRONZE", "category": "bronze", "priority": 0,
     "name": "Premium Bronze Players Pack", "coins": 0, "points": 0,
     "bio": "12 Bronze players, 3 Rare.",
     "itemQuantity": 12, "rareQuantity": 3, "playersOnly": True,
     "bronzeQuantity": 12, "silverQuantity": 0, "goldQuantity": 0},
    {"id": 602, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Silver Players Pack", "coins": 0, "points": 0,
     "bio": "12 Silver players.",
     "itemQuantity": 12, "rareQuantity": 0, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 12, "goldQuantity": 0},
    {"id": 603, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Premium Silver Players Pack", "coins": 0, "points": 0,
     "bio": "12 Silver players, 3 Rare.",
     "itemQuantity": 12, "rareQuantity": 3, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 12, "goldQuantity": 0},
    {"id": 604, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Jumbo Premium Silver Pack", "coins": 0, "points": 0,
     "bio": "24 Silver items, 6 Rare.",
     "itemQuantity": 24, "rareQuantity": 6,
     "bronzeQuantity": 0, "silverQuantity": 24, "goldQuantity": 0},
    {"id": 605, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Electrum Players Pack", "coins": 0, "points": 0,
     "bio": "6 Bronze and 6 Silver players.",
     "itemQuantity": 12, "rareQuantity": 0, "playersOnly": True,
     "bronzeQuantity": 6, "silverQuantity": 6, "goldQuantity": 0},
    {"id": 606, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Premium Electrum Players Pack", "coins": 0, "points": 0,
     "bio": "6 Bronze and 6 Silver players, 3 Rare.",
     "itemQuantity": 12, "rareQuantity": 3, "playersOnly": True,
     "bronzeQuantity": 6, "silverQuantity": 6, "goldQuantity": 0},
    {"id": 607, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Rare Electrum Players Pack", "coins": 0, "points": 0,
     "bio": "6 Silver and 6 Gold players, all Rare.",
     "itemQuantity": 12, "rareQuantity": 12, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 6, "goldQuantity": 6},
    {"id": 608, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "All Players Pack", "coins": 0, "points": 0,
     "bio": "12 players of any quality.",
     "itemQuantity": 12, "rareQuantity": 1, "playersOnly": True,
     "bronzeQuantity": 4, "silverQuantity": 4, "goldQuantity": 4},
    {"id": 609, "packType": "BRONZE", "category": "bronze", "priority": 0,
     "name": "Bronze Gift Pack", "coins": 0, "points": 0,
     "bio": "A small Bronze gift.",
     "itemQuantity": 5, "rareQuantity": 1,
     "bronzeQuantity": 5, "silverQuantity": 0, "goldQuantity": 0},
    {"id": 610, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Rare Player Pack", "coins": 0, "points": 0,
     "bio": "12 Rare players.",
     "itemQuantity": 12, "rareQuantity": 12, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 12},
    {"id": 611, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Two Rare Gold Players Pack", "coins": 0, "points": 0,
     "bio": "2 Gold players, both Rare.",
     "itemQuantity": 2, "rareQuantity": 2, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 2},
    {"id": 612, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Three Common Gold Players Pack", "coins": 0, "points": 0,
     "bio": "3 Gold players, all Common.",
     "itemQuantity": 3, "rareQuantity": 0, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 3},
    {"id": 613, "packType": "SILVER", "category": "silver", "priority": 0,
     "name": "Two Silver Players Pack", "coins": 0, "points": 0,
     "bio": "2 Silver players.",
     "itemQuantity": 2, "rareQuantity": 0, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 2, "goldQuantity": 0},
    {"id": 614, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Two Players Pack", "coins": 0, "points": 0,
     "bio": "2 Gold players, 1 Rare.",
     "itemQuantity": 2, "rareQuantity": 1, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 2},
    {"id": 615, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Rare Consumable Pack", "coins": 0, "points": 0,
     "bio": "12 Gold consumables, all Rare.",
     "itemQuantity": 12, "rareQuantity": 12,
     "families": ["consumables"] * 12,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 12},
    {"id": 616, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Prime Electrum Players Pack", "coins": 0, "points": 0,
     "bio": "6 Silver and 6 Gold players, 6 Rare.",
     "itemQuantity": 12, "rareQuantity": 6, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 6, "goldQuantity": 6},
    {"id": 617, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Premium Loan Player Reward Pack", "coins": 0, "points": 0,
     "bio": "1 Rare Gold loan player.",
     "itemQuantity": 1, "rareQuantity": 1, "playersOnly": True,
     "loanGames": 7,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 1},
    {"id": 619, "packType": "GOLD", "category": "gold", "priority": 0,
     "name": "Jumbo Gold Pack", "coins": 0, "points": 0,
     "bio": "24 Gold items with 3 Rares.",
     "itemQuantity": 24, "rareQuantity": 3,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 24},
)


def find_pack(pack_id: int, timestamp: int | None = None) -> dict | None:
    offer = next((pack for pack in PACK_OFFERS
                  if int(pack["id"]) == int(pack_id)), None)
    if offer is not None:
        return offer
    return next((pack for pack in REWARD_PACK_OFFERS
                 if int(pack["id"]) == int(pack_id)), None)


PROMO_PACK_OFFERS = (
    {"id": 500, "packType": "GOLD", "category": "promo", "priority": 20,
     "name": "Gold Players Pack", "coins": 12500, "points": 250,
     "bio": "Nothing but players to build out your ultimate squads! Includes "
            "12 players, at least 10 Gold with 1 Rare.",
     "itemQuantity": 12, "rareQuantity": 1, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 2, "goldQuantity": 10},
    {"id": 306, "packType": "GOLD", "category": "promo", "priority": 21,
     "name": "Jumbo Premium Gold Pack", "coins": 15000, "points": 300,
     "bio": "Double the size of a Premium Gold Pack with an extra Rare! A "
            "mix of 24 items, including players and consumables, at least 20 "
            "Gold with 7 Rares.",
     "itemQuantity": 24, "rareQuantity": 7,
     "bronzeQuantity": 0, "silverQuantity": 4, "goldQuantity": 20},
    {"id": 502, "packType": "GOLD", "category": "promo", "priority": 22,
     "name": "Premium Gold Players Pack", "coins": 25000, "points": 350,
     "bio": "Nothing but players to build out your ultimate squads! Includes "
            "12 players, at least 10 Gold with 3 Rares.",
     "itemQuantity": 12, "rareQuantity": 3, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 2, "goldQuantity": 10},
    {"id": 403, "packType": "GOLD", "category": "promo", "priority": 23,
     "name": "Rare Gold Pack", "coins": 25000, "points": 500,
     "bio": "The most unique Gold items, all in a single pack. A mix of 12 "
            "items, including players and consumables, all Gold, all Rare.",
     "itemQuantity": 12, "rareQuantity": 12,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 12},
    {"id": 404, "packType": "GOLD", "category": "promo", "priority": 24,
     "name": "Mega Pack", "coins": 35000, "points": 700,
     "bio": "The biggest pack yet with a whopping 30 items! A mix of players "
            "and consumables, at least 26 Gold with 18 Rares.",
     "itemQuantity": 30, "rareQuantity": 18,
     "bronzeQuantity": 0, "silverQuantity": 4, "goldQuantity": 26},
    {"id": 513, "packType": "GOLD", "category": "promo", "priority": 25,
     "name": "Prime Gold Players Pack", "coins": 45000, "points": 600,
     "bio": "Nothing but players to build out your ultimate squads! Includes "
            "12 players, at least 10 Gold with 6 Rares.",
     "itemQuantity": 12, "rareQuantity": 6, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 2, "goldQuantity": 10},
    {"id": 405, "packType": "GOLD", "category": "promo", "priority": 26,
     "name": "Rare Players Pack", "coins": 50000, "points": 1000,
     "bio": "The most unique top-rated players, all in a single pack. "
            "Includes 12 items, all players, all Gold, all Rare.",
     "itemQuantity": 12, "rareQuantity": 12, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 12},
    {"id": 412, "packType": "GOLD", "category": "promo", "priority": 27,
     "name": "Rare Mega Pack", "coins": 55000, "points": 1100,
     "bio": "The biggest pack yet with a whopping 30 items, all Rares.",
     "itemQuantity": 30, "rareQuantity": 30,
     "bronzeQuantity": 0, "silverQuantity": 4, "goldQuantity": 26},
    {"id": 406, "packType": "GOLD", "category": "promo", "priority": 28,
     "name": "Jumbo Rare Players Pack", "coins": 100000, "points": 2000,
     "bio": "The most unique top-rated players, all in a single pack. "
            "Includes 24 items, all players, all Gold, all Rare.",
     "itemQuantity": 24, "rareQuantity": 24, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 24},
    {"id": 413, "packType": "GOLD", "category": "promo", "priority": 29,
     "name": "Ultimate Pack", "coins": 125000, "points": 2500,
     "bio": "The most unique top-rated players, all in a single pack. "
            "Includes 30 items, all players, all Gold, all Rare.",
     "itemQuantity": 30, "rareQuantity": 30, "playersOnly": True,
     "bronzeQuantity": 0, "silverQuantity": 0, "goldQuantity": 30},
)

PACK_OFFERS = PERMANENT_PACK_OFFERS + PROMO_PACK_OFFERS


def load_rotation_config(path: Path = ROTATION_CONFIG) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def active_pack_offers(timestamp: int | None = None,
                       config: dict | None = None) -> tuple:
    import random
    import time

    policy = config if config is not None else load_rotation_config()
    rotation = policy.get("promoRotation", {})
    mode = str(rotation.get("mode", "all")).lower()
    promo_by_id = {int(offer["id"]): offer for offer in PROMO_PACK_OFFERS}
    if mode == "manual":
        ids = [int(value) for value in rotation.get("activePackIds", [])]
    elif mode == "rotating":
        period = max(1, int(rotation.get("periodSeconds", 86_400)))
        anchor = int(rotation.get("anchorTimestamp", 0))
        now = int(time.time() if timestamp is None else timestamp)
        cycle = max(0, (now - anchor) // period)
        count = max(0, min(len(promo_by_id),
                           int(rotation.get("packsPerRotation", 3))))
        ids = list(promo_by_id)
        random.Random(int(rotation.get("seed", 17)) ^ cycle).shuffle(ids)
        ids = ids[:count]
    else:
        ids = list(promo_by_id)
    enabled = {value for value in ids if value in promo_by_id}
    promos = tuple(offer for offer in PROMO_PACK_OFFERS
                   if int(offer["id"]) in enabled)
    return PERMANENT_PACK_OFFERS + promos


def find_active_offer(pack_id: int, timestamp: int | None = None) -> dict | None:
    return next((offer for offer in active_pack_offers(timestamp)
                 if int(offer["id"]) == int(pack_id)), None)


def build_locstrings() -> str:
    import xml.sax.saxutils as su

    units = []

    def unit(key, text):
        units.append('      <trans-unit id="%s" resname="%s"><source>%s'
                     '</source></trans-unit>' % (key, key, su.escape(text)))

    for offer in tuple(PACK_OFFERS) + REWARD_PACK_OFFERS:
        pid = offer["id"]
        unit("FUT_STORE_PACK_%d_NAME" % pid, offer["name"])
        unit("FUT_STORE_PACK_%d_DESC" % pid, offer["bio"])
        unit("FUT_STORE_POINTS_%d" % pid, offer["name"])
    for group, (category, label) in enumerate((("bronze", "Bronze Packs"),
                                               ("silver", "Silver Packs"),
                                               ("gold", "Gold Packs"),
                                               ("special", "Promo Packs")), start=1):
        unit("FUT_STORE_CAT_%s" % category, label)
        unit("FUT_STORE_CAT_%s" % category.upper(), label)
        unit("FUT_STORE_CAT_%d" % group, label)

    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<xliff version="1.2">',
        '  <file original="storepackdescriptions" source-language="en-US"'
        ' datatype="plaintext">',
        '    <body>',
        *units,
        '    </body>',
        '  </file>',
        '</xliff>',
    ]) + "\n"


ART_ASSET_BY_TIER = {"bronze": 1, "silver": 2, "gold": 3, "promo": 3}

DISPLAY_GROUP_BY_TIER = {"bronze": 1, "silver": 2, "gold": 3, "promo": 4,
                         "mypacks": 5}

GROUP_NAME_BY_TIER = {"bronze": "bronze", "silver": "silver",
                      "gold": "gold", "promo": "special", "mypacks": "mypacks"}

TIERS = {"BRONZE": (0, 64), "SILVER": (65, 74),
         "GOLD": (75, 99), "PREMIUM_GOLD": (75, 99)}


def build_offer(offer: dict) -> dict:
    return {
        "id": int(offer["id"]),
        "assetId": ART_ASSET_BY_TIER.get(offer["category"], 1),
        "packType": str(offer["packType"]),
        "description": str(offer["bio"]),
        "state": "active",
        "actionType": "CREATEPACK",
        "dealType": "NONE",
        "saleType": "NONE",
        "firstPartyStoreId": "0",
        "currencies": [
            {"name": "coins", "funds": int(offer["coins"]),
             "finalFunds": int(offer["coins"])},
            {"name": "points", "funds": int(offer["points"]),
             "finalFunds": int(offer["points"])},
        ],
        "points": int(offer["points"]),
        "itemQuantity": int(offer["itemQuantity"]),
        "rareQuantity": int(offer["rareQuantity"]),
        "bronzeQuantity": int(offer["bronzeQuantity"]),
        "silverQuantity": int(offer["silverQuantity"]),
        "goldQuantity": int(offer["goldQuantity"]),
        "quantity": 1,
        "purchaseCount": 0,
        "purchaseLimit": 999999,
        "priority": int(offer["priority"]),
        "sortPriority": int(offer["priority"]),
        "bonus": 0,
        "start": 0,
        "end": 2_147_483_647,
        "isPremium": (offer["packType"] == "PREMIUM_GOLD"
                      or offer["category"] == "promo"),
        "unopened": False,
        "useDefaultImage": True,
        "displayGroupAssetId": DISPLAY_GROUP_BY_TIER.get(
            offer["category"], 1),
        "displayGroupUseDefaultImage": True,
        "displayGroup": {"value": GROUP_NAME_BY_TIER.get(
                             offer["category"], "gold"),
                         "priority": DISPLAY_GROUP_BY_TIER.get(
                             offer["category"], 1)},
        "finalPrice": {},
        "extPrice": {},
        "packContentInfo": {
            "itemQuantity": int(offer["itemQuantity"]),
            "rareQuantity": int(offer["rareQuantity"]),
            "bronzeQuantity": int(offer["bronzeQuantity"]),
            "silverQuantity": int(offer["silverQuantity"]),
            "goldQuantity": int(offer["goldQuantity"]),
        },
    }


def build_owned_offer(offer: dict, priority: int = 1,
                      quantity: int = 1) -> dict:
    row = build_offer(offer)
    row.update({
        "unopened": True,
        "quantity": max(1, int(quantity)),
        "priority": int(priority),
        "sortPriority": int(priority),
        "displayGroupAssetId": DISPLAY_GROUP_BY_TIER["mypacks"],
        "displayGroup": {"value": GROUP_NAME_BY_TIER["mypacks"],
                         "priority": DISPLAY_GROUP_BY_TIER["mypacks"]},
        "currencies": [
            {"name": "coins", "funds": 0, "finalFunds": 0},
            {"name": "points", "funds": 0, "finalFunds": 0},
        ],
        "points": 0,
    })
    return row


def build_store(timestamp: int, unopened_pack_ids: list[int] | None = None) -> dict:
    purchased = [build_offer(o) for o in active_pack_offers(timestamp)]
    counts = {}
    for pack_id in unopened_pack_ids or ():
        counts[int(pack_id)] = counts.get(int(pack_id), 0) + 1
    for priority, (pack_id, quantity) in enumerate(counts.items(), 1):
        offer = find_pack(int(pack_id), timestamp)
        if offer is not None:
            purchased.append(build_owned_offer(offer, priority, quantity))
    return {"purchase": purchased,
            "timestamp": int(timestamp)}


def build_transaction(pack_id: int = 0) -> dict:
    return {
        "transactionId": 0,
        "packId": int(pack_id),
        "firstPartyStoreId": 0,
        "purchasePackType": "NONE",
        "state": "NONE",
    }


MIXED_SHARES = {"player": 0.25, "consumables": 0.50,
                "staff": 1 / 12, "clubItems": 1 / 6}
QUALITY_BANDS = {"bronze": (0, 64), "silver": (65, 74),
                 "gold": (75, 99)}


def _slot_families(offer: dict) -> list[str]:
    wanted = int(offer["itemQuantity"])
    if offer.get("families"):
        return [str(value) for value in offer["families"]]
    if offer.get("playersOnly"):
        return ["player"] * wanted
    counts = {name: int(wanted * share)
              for name, share in MIXED_SHARES.items()}
    order = ("consumables", "player", "clubItems", "staff")
    while sum(counts.values()) < wanted:
        counts[order[(sum(counts.values()) - wanted) % len(order)]] += 1
    while sum(counts.values()) > wanted:
        for name in order:
            if counts[name] > 0:
                counts[name] -= 1
                break
    return [name for name in ("player", "consumables", "staff", "clubItems")
            for _ in range(counts[name])]


def _slot_qualities(offer: dict) -> list[str]:
    return [quality for quality in ("bronze", "silver", "gold")
            for _ in range(int(offer.get(f"{quality}Quantity", 0)))]


def draw_seed(offer_id: int, timestamp: int, persona_id: int = 0,
              sequence: int = 0) -> int:
    return ((int(offer_id) << 20) ^ int(timestamp)
            ^ (int(persona_id) << 44) ^ (int(sequence) << 4))


def pack_contents(offer: dict, players: list, timestamp: int,
                  first_item_id: int = 10_000, *,
                  persona_id: int = 0, sequence: int = 0) -> list:
    import random

    pack_policy = load_rotation_config()
    player_weight_policy = pack_policy.get("playerSelectionWeights", {})
    variant_policy = pack_policy.get("playerVariantPolicy", {})
    by_asset = {int(player["playerid"]): player for player in players}
    recovered_bases = fut_items.base_cards_by_asset()
    selected_variants = fut_items.pack_player_variants(
        base_cards=list(recovered_bases.values()), policy=variant_policy)
    require_recovered_definition = bool(
        set(by_asset).intersection(selected_variants))
    selected_specials = [card for kind, card in selected_variants.values()
                         if kind == "special"]

    base_pool: list[tuple] = []
    for asset_id, player in by_asset.items():
        selected = selected_variants.get(asset_id)
        if selected is not None and selected[0] == "special":
            continue
        card = selected[1] if selected is not None else None
        if require_recovered_definition and card is None:
            continue
        rating = int(card["rating"] if card is not None else player["rating"])
        if card is not None:
            position = str(card.get("preferredPosition", "CM"))
            stats = card.get("headlineStats", [])
        else:
            position = str(player.get(
                "preferredPosition",
                fut_items.POSITIONS.get(player.get("position"), "CM")))
            stats = (fut_items.headline_stats(player)
                     if player.get("attributes") else [rating] * 6)
        weight = fut_player_weights.pool_draw_weight(
            "base", rating, position, stats, player_weight_policy)
        base_pool.append((card, player, rating, weight))

    special_weights = {
        int(card["resourceId"]): fut_player_weights.pool_draw_weight(
            "special", int(card["rating"]),
            str(card.get("preferredPosition", "CM")),
            card.get("headlineStats", [int(card["rating"])] * 6),
            player_weight_policy)
        for card in selected_specials
    }
    minimum_rating = int(offer.get("minimumPlayerRating", 0))
    if minimum_rating:
        base_pool = [entry for entry in base_pool if entry[2] >= minimum_rating]
        selected_specials = [card for card in selected_specials
                             if int(card["rating"]) >= minimum_rating]
    rng = random.Random(draw_seed(offer["id"], timestamp, persona_id, sequence))

    families = _slot_families(offer)
    qualities = _slot_qualities(offer)
    wanted = int(offer["itemQuantity"])
    if len(families) != wanted or len(qualities) != wanted:
        raise ValueError(f"invalid pack template {offer['id']}: "
                         f"{len(families)} families/{len(qualities)} qualities")
    rng.shuffle(families)
    rng.shuffle(qualities)
    rare_indices = set(rng.sample(range(wanted),
                                  min(wanted, int(offer["rareQuantity"]))))
    used_assets: set[int] = set()
    chosen: list[tuple[str, object]] = []

    def player_pool(quality: str, rare: bool) -> list[tuple]:
        low, high = QUALITY_BANDS[quality]
        exact = [entry for entry in base_pool
                 if low <= entry[2] <= high
                 and (entry[0] is None
                      or bool(int(entry[0].get("rareflag", 0))) is rare)]
        return exact

    for index, (family, quality) in enumerate(zip(families, qualities)):
        rare = index in rare_indices
        if family == "player":
            low, high = QUALITY_BANDS[quality]
            candidates = [entry for entry in player_pool(quality, rare)
                          if int(entry[1]["playerid"]) not in used_assets]
            if not candidates:
                candidates = [entry for entry in base_pool
                              if low <= entry[2] <= high
                              and int(entry[1]["playerid"]) not in used_assets]
            if not candidates:
                candidates = player_pool(quality, rare) or base_pool
            combined = [("base", entry, entry[3]) for entry in candidates]
            if rare:
                special_pool = [card for card in selected_specials
                                if low <= int(card["rating"]) <= high
                                and int(card["assetId"]) in by_asset
                                and int(card["assetId"]) not in used_assets]
                combined.extend(
                    ("special", card,
                     special_weights[int(card["resourceId"])])
                    for card in special_pool)
            if not combined:
                if minimum_rating:
                    raise ValueError(f"no eligible {minimum_rating}+ player "
                                     f"for pack {offer['id']}")
                continue
            weights = fut_player_weights.bounded_draw_weights(
                [entry[2] for entry in combined], player_weight_policy)
            kind, definition, _ = rng.choices(
                combined, weights=weights, k=1)[0]
            if kind == "special":
                card = definition
                player = by_asset[int(card["assetId"])]
                used_assets.add(int(card["assetId"]))
                chosen.append(("special", (card, player)))
                continue
            entry = definition
            used_assets.add(int(entry[1]["playerid"]))
            chosen.append(("base", (entry[0], entry[1], rare)))
        else:
            candidates = fut_cards.pack_eligible(family, quality, rare)
            item_types = offer.get("itemTypes") or []
            if item_types:
                wanted_type = str(item_types[min(index, len(item_types) - 1)])
                candidates = [card for card in candidates
                              if str(card.get("itemType", "")) == wanted_type]
            if not candidates:
                raise ValueError(f"empty {quality} {'rare' if rare else 'common'} "
                                 f"{family} pool for pack {offer['id']}")
            weights = [max(1, int(card.get("packWeight", 0) or 0))
                       for card in candidates]
            chosen.append(("card", rng.choices(candidates, weights=weights,
                                                k=1)[0]))

    rng.shuffle(chosen)

    out = []
    for index, (kind, definition) in enumerate(chosen):
        item_id = first_item_id + index
        if kind == "special":
            card, player = definition
            out.append(fut_items.build_special_item(card, player, item_id,
                                                    timestamp))
        elif kind == "base":
            card, player, wanted_rare = definition
            if card is None:
                out.append(fut_items.build_item(player, item_id, timestamp,
                                                rare=wanted_rare))
            else:
                out.append(fut_items.build_base_card_item(
                    card, player, item_id, timestamp))
        else:
            out.append(fut_cards.build_card(definition, item_id, timestamp))
    loan_games = max(0, int(offer.get("loanGames", 0) or 0))
    if loan_games:
        for item in out:
            if str(item.get("itemType", "")) == "player":
                item["loans"] = loan_games
                item["contract"] = loan_games
                item["untradeable"] = True
                item["discardValue"] = 0
    return out


def build_pack_opened(offer: dict, players: list, timestamp: int,
                      first_item_id: int = 10_000,
                      owned_by_resource: dict | None = None, *,
                      persona_id: int = 0, sequence: int = 0) -> dict:
    items = pack_contents(offer, players, timestamp, first_item_id,
                          persona_id=persona_id, sequence=sequence)
    return opened_document(offer, items, owned_by_resource)


def opened_document(offer: dict, items: list[dict],
                    owned_by_resource: dict | None = None) -> dict:
    owned = owned_by_resource or {}
    duplicates = [
        {"itemId": item["id"], "duplicateItemId": owned[item["resourceId"]]}
        for item in items if item.get("resourceId") in owned
    ]
    document = {
        "purchasedPackId": int(offer["id"]),
        "numberItems": len(items),
        "itemList": items,
    }
    if duplicates:
        document["duplicateItemIdList"] = duplicates
    return document
