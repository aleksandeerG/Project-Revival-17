# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
import re
import ssl
import zlib
import secrets
import time
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import health
from accounts import (
    BoundedHTTPRequestHandler,
    REQUEST_TIMEOUT_SECONDS,
    DualProtocolHTTPServer,
    read_limited_body,
)
from events import emit
import fut_cards
import fut_club_stats
import fut_items
import fut_market
from fut_items import (build_item_move, build_special_item, club_items,
                       load_catalogue, load_current_catalogue, load_specials)
from fut_squads import (build_squad, build_squad_list, parse_saved_squad,
                        squad_rating)
from fut_state import (MATCH_PLAYLIST_ONLINE_DRAFT, FutStateStore,
                       SbcValidationError)
import fut_draft
import fut_economy
import fut_packs

SBC_ART_DIR = Path(__file__).resolve().parent / "data" / "sbc-art"
import fut_sbc
import fut_staff_probe
import fut_seasons
import fut_shim_log
import fut_tournaments

GAME = "fifa17"
DEFAULT_PERSONA_ID = 1_000_001
ACCOUNT_NEW = "new"
ACCOUNT_RETURNING = "returning"
ACCOUNT_MODES = (ACCOUNT_NEW, ACCOUNT_RETURNING)
LOCAL_CLUB_ESTABLISHED = 1_451_606_400
LOCAL_CLUB_LAST_ACCESS = 1_483_228_800
LOCAL_CLUB_BADGE_ID = 11
FIFA17_PC_SKU = "FFA17PCC"

UNHANDLED_NOT_FOUND = "404"
UNHANDLED_EMPTY_200 = "empty-200"
UNHANDLED_MODES = (UNHANDLED_NOT_FOUND, UNHANDLED_EMPTY_200)

PRICELIMITS_404 = "404"
PRICELIMITS_PROBE = "probe"
PRICELIMITS_LIVE = "live"
PRICELIMITS_MODES = (PRICELIMITS_LIVE, PRICELIMITS_404, PRICELIMITS_PROBE)
PRICELIMITS_MODE = PRICELIMITS_LIVE

PROBE_MIN_KEYS = 1
PROBE_MAX_KEYS = 4

PROBE_NONCE = f"{int(time.time()) & 0xFFFF:04x}"


PROBE_ARRAY_ROUTES = (
    "/ut/game/fifa17/squad/mode/draft/state",
)

PROBE_KEYS_BY_PREFIX = (
    ("/ut/game/fifa17/hub", 1),
    ("/ut/game/fifa17/leaderboards/options", 2),
    ("/ut/v2/game/fifa17/store/transaction", 3),
)


def probe_key_count(path: str) -> int:
    for prefix, count in PROBE_KEYS_BY_PREFIX:
        if path.startswith(prefix):
            return count
    return PROBE_MIN_KEYS + (zlib.crc32(path.encode("utf-8"))
                             % (PROBE_MAX_KEYS - PROBE_MIN_KEYS + 1))


def build_probe_document(path: str) -> bytes:
    if any(path.startswith(prefix) for prefix in PROBE_ARRAY_ROUTES):
        return b"[]"
    tag = f"{zlib.crc32(path.encode('utf-8')) & 0xFFFFFF:06x}"
    keys = {f"futProbe{PROBE_NONCE}{tag}_{index}": 0
            for index in range(probe_key_count(path))}
    return json.dumps(keys, separators=(",", ":")).encode("utf-8")

FUT_SID_HEADER = "X-UT-SID"
REDACTED = "<redacted>"
LOCAL_PHISHING_TOKEN = "FUT17-LOCAL-PHISH"

SETTINGS_MAX_TRADE_PILE = 100
SETTINGS_OPERATION_TIMEOUT_SEC = 30
SETTINGS_CLUB_CREATE_THRESHOLD = 0
SETTINGS_TOKEN_REDEMPTION_ENABLED = 0

SETTINGS_DRAFT_ENABLED = 1
SETTINGS_OFFLINE_DRAFT_ENABLED = 1
SETTINGS_SINGLE_PLAYER_DRAFT_ENABLED = 1

LOCAL_RECORD_WON = 0
LOCAL_RECORD_DRAW = 0
LOCAL_RECORD_LOSS = 0

LOCAL_DIVISION_OFFLINE = 1
LOCAL_DIVISION_ONLINE = 1

LOCAL_POINTS_LAST_YEAR = 0
LOCAL_RELIABILITY = 99

LOCAL_DRAFT_TOKENS = 0
LOCAL_BID_TOKENS = 0
LOCAL_UNOPENED_PACKS = 0


def build_auth_session(sid: str, now: float | None = None) -> bytes:
    moment = time.time() if now is None else now
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(moment))
    document = {
        "sid": str(sid),
        "serverTime": stamp,
        "lastOnlineTime": stamp,
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_fut_settings() -> bytes:
    configs = [
        {"type": "maximumTradePileSize", "value": SETTINGS_MAX_TRADE_PILE},
        {"type": "getOperationTimeoutSec", "value": SETTINGS_OPERATION_TIMEOUT_SEC},
        {"type": "clubCreateThreshold", "value": SETTINGS_CLUB_CREATE_THRESHOLD},
        {"type": "tokenRedemptionEnabled", "value": SETTINGS_TOKEN_REDEMPTION_ENABLED},
        {"type": "enableDraftMode", "value": SETTINGS_DRAFT_ENABLED},
        {"type": "enableOfflineDraftMode", "value": SETTINGS_OFFLINE_DRAFT_ENABLED},
        {"type": "enableSinglePlayerDraftMode",
         "value": SETTINGS_SINGLE_PLAYER_DRAFT_ENABLED},
    ]
    return json.dumps({"configs": configs}, separators=(",", ":")).encode("utf-8")


def build_trusted_device() -> bytes:
    document = {"trusted": True, "exists": True, "changed": False}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_phishing_question() -> bytes:
    document = {"attempts": 0, "question": "", "token": LOCAL_PHISHING_TOKEN}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_phishing_validation() -> bytes:
    document = {
        "debug": "Answer is correct.",
        "string": "OK",
        "code": "200",
        "reason": "Answer is correct.",
        "token": LOCAL_PHISHING_TOKEN,
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_leaderboard_locstrings() -> bytes:
    document = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<message_set name="fut-locstrings">\n'
        "</message_set>\n"
    )
    return document.encode("utf-8")


def build_user_mass_info(persona_id: int,
                         balances: tuple[int, int] | None = None,
                         squad_list: dict | None = None,
                         squad: dict | None = None,
                         unopened_count: int = 0,
                         divisions: tuple[int, int] | None = None) -> bytes:
    credits, points = balances or (fut_economy.STARTING_CREDITS,
                                   fut_economy.STARTING_POINTS)
    division_offline, division_online = divisions or (
        LOCAL_DIVISION_OFFLINE, LOCAL_DIVISION_ONLINE)
    record = {
        "personaId": persona_id,
        "clubName": LOCAL_CLUB_NAME,
        "clubAbbr": "LCL",
        "accountCreatedPlatformName": "pc",
        "clubNameChangeAllowed": False,
        "established": str(LOCAL_CLUB_ESTABLISHED),
        "divisionOffline": int(division_offline),
        "divisionOnline": int(division_online),
        "won": LOCAL_RECORD_WON,
        "draw": LOCAL_RECORD_DRAW,
        "loss": LOCAL_RECORD_LOSS,
        "fifaPointsFromLastYear": LOCAL_POINTS_LAST_YEAR,
        "fifaPointsTransferredStatus": 0,
        "trophies": 0,
        "currencies": [
            {"name": "coins", "funds": credits, "finalFunds": credits},
            {"name": "points", "funds": points, "finalFunds": points},
        ],
        "sessionCoinsBankBalance": 0,
        "bidTokens": {},
        "feature": {},
        "reliability": {},
        "unopenedPacks": {"preOrderPacks": 0,
                          "recoveredPacks": unopened_count},
    }
    if squad_list is not None:
        record["squadList"] = squad_list
    document = {"userInfo": record}
    if squad is not None:
        document["squad"] = squad
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


LOCAL_CLUB_SQUAD_SIZE = 30

NON_CLUB_LEAGUES = {76, 78, 2136}

_CATALOGUE: list | None = None


def club_players(size: int = LOCAL_CLUB_SQUAD_SIZE) -> list:
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = [player for player in load_current_catalogue()
                      if player.get("leagueid") not in NON_CLUB_LEAGUES]
        emit("fut-club-catalogue", players=len(_CATALOGUE))
    return _CATALOGUE[:size]


def _state(server) -> FutStateStore | None:
    return getattr(server, "fut_state", None)


def _ensure_persona(server, persona_id: int) -> FutStateStore | None:
    state = _state(server)
    if state is None:
        return None
    seed = []
    if getattr(server, "club_items", False):
        size = getattr(server, "club_size", LOCAL_CLUB_SQUAD_SIZE)
        now = int(time.time())
        seed = [club_items([player], 1, offset=0, timestamp=now)[0]
                for player in club_players(size)]
        seed.extend(starter_club_cards(now))
        for item_id, item in enumerate(seed, 1):
            item["id"] = item_id
    state.ensure_persona(persona_id, seed)
    _reconcile_specials(state, persona_id)
    _backfill_club_essentials(server, state, persona_id)
    return state


_SPECIAL_ITEM_TRUTH: dict | None = None
CLUB_ESSENTIALS = ("stadium", "kit", "ball", "custom", "staff")
SPECIAL_RECONCILE_JOB = "special-catalogue-reconcile"
SPECIAL_RECONCILE_VERSION = "1"
CLUB_BACKFILL_JOB = "club-essentials-backfill"
CLUB_BACKFILL_VERSION = "2"

SPECIAL_ITEM_TRUTH_FIELDS = (
    "assetId", "resourceId", "rating", "preferredPosition", "teamid",
    "leagueId", "nation", "rareflag", "discardValue", "attributeList",
    "name",
)


class _NullStore:

    def load_clientdata(self, persona_id, name):
        return []

    def save_clientdata(self, persona_id, name, entries):
        return None


def _sbc_progress(server, persona_id: int) -> dict:
    state = _ensure_persona(server, persona_id)
    return fut_sbc.load_progress(state, persona_id) if state else {}


def _sbc_in_progress(server, persona_id: int) -> set:
    state = _ensure_persona(server, persona_id)
    return fut_sbc.load_in_progress(state, persona_id) if state else set()


def _persona_items_by_id(state, persona_id: int) -> dict:
    if state is None:
        return {}
    out = {}
    for pile in ("club", "squad"):
        for row in state.list_items(int(persona_id), pile):
            try:
                out[int(row.get("id", 0) or 0)] = row
            except (AttributeError, TypeError, ValueError):
                continue
    out.pop(0, None)
    return out


def _submit_sbc_challenge(server, state, persona_id: int, challenge_id: int,
                           set_id: int) -> bytes:
    definition = fut_sbc.challenge_definition(challenge_id)
    if definition is None or int(definition["setId"]) != int(set_id):
        raise SbcValidationError("unknown challenge")
    def item_rewards(awards):
        items = []
        for award in awards:
            if award.get("type") != fut_sbc.AWARD_ITEM:
                continue
            for _ in range(max(1, int(award.get("count", 1)))):
                item = fut_sbc.reward_item(award, timestamp=int(time.time()))
                if item is None:
                    raise SbcValidationError("SBC item reward cannot be resolved")
                items.append(item)
        return items

    def pack_rewards(awards, untradeable):
        rows = []
        for pack_id in fut_sbc.award_packs(awards):
            if fut_packs.find_pack(pack_id) is None:
                raise SbcValidationError("SBC reward pack cannot be resolved")
            rows.append({"packId": int(pack_id),
                         "untradeable": bool(untradeable)})
        return rows

    reward_payload = {
        "challengeItems": item_rewards(definition["challengeAwards"]),
        "setItems": item_rewards(definition["setAwards"]),
        "challengePacks": pack_rewards(
            definition["challengeAwards"], definition["rewardUntradeable"]),
        "setPacks": pack_rewards(
            definition["setAwards"], definition["setRewardUntradeable"]),
    }
    result = state.complete_sbc(
        persona_id, definition,
        lambda items, reported: fut_sbc.evaluate_challenge(
            definition, items, reported), reward_payload)
    paid = not result["repeat"]
    challenge_awards = list(definition["challengeAwards"]) if paid else []
    set_awards = (list(definition["setAwards"])
                  if paid and result["setCompleted"] else [])
    shown_challenge = fut_sbc.wire_awards(challenge_awards)
    shown_set = fut_sbc.wire_awards(set_awards)
    granted = ([{"packId": int(pack_id), "unopened": True}
                for pack_id in fut_sbc.award_packs(
                    list(challenge_awards) + list(set_awards))]
               if paid else [])
    emit("sbs-challenge-submit", challengeId=challenge_id, setId=set_id,
         repeat=result["repeat"],
         coins=result["challengeCoins"] + result["setCoins"],
         packs=granted,
         setCompleted=result["setCompleted"],
         consumed=len(result.get("consumedItemIds", [])))
    return fut_sbc.build_submit_receipt(
        challenge_id, set_id, result["balance"], shown_challenge, shown_set,
        state.unopened_pack_count(persona_id))


def _fold_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z]+", "", text.lower())


def _find_catalogue_player(name: str) -> dict | None:
    wanted = _fold_name(name)
    if not wanted:
        return None
    best = None
    for player in club_players(2_147_483_647):
        for field in ("commonName", "lastName", "name"):
            value = _fold_name(player.get(field, ""))
            if value and value == wanted:
                if best is None or int(player.get("rating", 0)) > int(best.get("rating", 0)):
                    best = player
                break
    return best


def special_item_truth() -> dict:
    global _SPECIAL_ITEM_TRUTH
    if _SPECIAL_ITEM_TRUTH is not None:
        return _SPECIAL_ITEM_TRUTH
    players = {int(player["playerid"]): player for player in load_catalogue()}
    truth = {}
    for card in load_specials():
        player = players.get(int(card["assetId"]))
        if player is None:
            continue
        item = build_special_item(card, player, 1, 0)
        truth[int(card["resourceId"])] = {
            key: item[key] for key in SPECIAL_ITEM_TRUTH_FIELDS
        }
    _SPECIAL_ITEM_TRUTH = truth
    return truth


def _reconcile_specials(state: FutStateStore, persona_id: int) -> None:
    persona_id = int(persona_id)
    truth = special_item_truth()
    if not truth:
        return
    claim = state.claim_persona_maintenance(
        persona_id, SPECIAL_RECONCILE_JOB, SPECIAL_RECONCILE_VERSION)
    if claim is None:
        return
    try:
        result = state.reconcile_special_player_items(
            persona_id, truth)
    except Exception:
        state.abandon_persona_maintenance(
            persona_id, SPECIAL_RECONCILE_JOB, SPECIAL_RECONCILE_VERSION,
            claim)
        return
    state.complete_persona_maintenance(
        persona_id, SPECIAL_RECONCILE_JOB, SPECIAL_RECONCILE_VERSION, claim)
    if result["updated"] or result["removed"]:
        emit("fut-special-catalogue-repair", personaId=persona_id, **result)


def _backfill_club_essentials(server, state, persona_id: int) -> None:
    persona_id = int(persona_id)
    try:
        present = state.club_essentials_present(persona_id)
    except Exception:
        return
    seeding = bool(getattr(server, "club_items", False))
    if not present and not seeding:
        return
    claim = state.claim_persona_maintenance(
        persona_id, CLUB_BACKFILL_JOB, CLUB_BACKFILL_VERSION)
    if claim is None:
        return
    missing = [name for name in CLUB_ESSENTIALS if name not in present]
    try:
        now = int(time.time())
        cards = [card for card in starter_club_cards(now)
                 if str(card.get("itemType", "")) in missing]

        if "kit" not in missing:
            held = {int(item.get("category", 0) or 0)
                    for item in state.list_items(persona_id, "club")
                    if str(item.get("itemType", "")) == "kit"}
            gaps = [slot for slot in KIT_SLOT_CATEGORIES if slot not in held]
            if gaps:
                missing = missing + [f"kit slot {slot}" for slot in gaps]
                cards += [card for card in starter_club_cards(now)
                          if str(card.get("itemType", "")) == "kit"
                          and int(card.get("category", 0) or 0) in gaps]
        if cards:
            added = state.add_club_cards(persona_id, cards)
            if added:
                emit("fut-club-backfill", personaId=persona_id,
                     missing=missing, granted=len(added))
        repaired = state.repair_club_items(persona_id, club_item_truth())
    except Exception:
        state.abandon_persona_maintenance(
            persona_id, CLUB_BACKFILL_JOB, CLUB_BACKFILL_VERSION, claim)
        return
    if repaired:
        emit("fut-club-item-repair", personaId=int(persona_id),
             items=repaired)
    _equip_club_defaults(state, persona_id)
    state.complete_persona_maintenance(
        persona_id, CLUB_BACKFILL_JOB, CLUB_BACKFILL_VERSION, claim)


ACTIVE_SLOT_SOURCES = (
    (100, lambda item: item.get("itemType") == "custom"),
    (101, lambda item: item.get("itemType") == "kit"
          and int(item.get("category", 0) or 0) == 2),
    (102, lambda item: item.get("itemType") == "kit"
          and int(item.get("category", 0) or 0) == 3),
    (103, lambda item: item.get("itemType") == "ball"),
    (104, lambda item: item.get("itemType") == "stadium"),
)


_CLUB_ITEM_TRUTH: dict | None = None
CLUB_ITEM_TRUTH_FIELDS = ("category", "year")


def club_item_truth() -> dict:
    global _CLUB_ITEM_TRUTH
    if _CLUB_ITEM_TRUTH is None:
        try:
            _CLUB_ITEM_TRUTH = {
                int(row["resourceId"]): {
                    key: int(row.get(key, 0) or 0)
                    for key in CLUB_ITEM_TRUTH_FIELDS if key in row}
                for row in fut_cards.load_cards().get("clubItems", [])}
        except Exception:
            _CLUB_ITEM_TRUTH = {}
    return _CLUB_ITEM_TRUTH


def _equip_club_defaults(state, persona_id: int) -> None:
    try:
        held = state.active_slot_items(persona_id)
        items = state.list_items(persona_id, "club")
    except Exception:
        return
    equipped = []
    for slot, matches in ACTIVE_SLOT_SOURCES:
        name = state.ACTIVE_SLOT_STATES[slot]
        if name in held:
            continue
        candidate = next((item for item in items if matches(item)), None)
        if candidate is None:
            continue
        ok, _reason = state.activate_item(persona_id, int(candidate["id"]),
                                          slot)
        if ok:
            equipped.append(name)
    if equipped:
        emit("fut-club-equipped", personaId=int(persona_id), slots=equipped)


STARTER_STAFF = {"manager": 1, "headCoach": 1, "GKCoach": 1,
                 "fitnessCoach": 1, "physio": 1}
STARTER_CLUB_ITEMS = {"custom": 1, "kit": 2, "stadium": 1, "ball": 1}
STARTER_CONSUMABLES = {"contract": 6, "healing": 3,
                       "trainingPlayer": 2, "trainingGk": 1,
                       "position": 1, "playStyle": 1}


KIT_SLOT_CATEGORIES = (2, 3)


def _real_club_team_ids() -> set:
    try:
        return {int(row.get("teamid") or 0) for row in (load_catalogue() or [])}
    except Exception:
        return set()


def _starter_kits(definitions: list) -> list:
    kits = [item for item in definitions if item.get("itemType") == "kit"]
    real = _real_club_team_ids()
    by_team: dict = {}
    for kit in kits:
        by_team.setdefault(kit.get("teamid"), {}).setdefault(
            int(kit.get("category", 0) or 0), kit)
    ordered = sorted(by_team.items(),
                     key=lambda pair: 0 if int(pair[0] or 0) in real else 1)
    for _team, slots in ordered:
        if all(slot in slots for slot in KIT_SLOT_CATEGORIES):
            return [slots[slot] for slot in KIT_SLOT_CATEGORIES]
    out = []
    for slot in KIT_SLOT_CATEGORIES:
        match = next((k for k in kits
                      if int(k.get("category", 0) or 0) == slot), None)
        if match is not None:
            out.append(match)
    return out


def starter_club_cards(timestamp: int) -> list:
    out = []
    for group, wanted, key in (("staff", STARTER_STAFF, "family"),
                               ("clubItems", STARTER_CLUB_ITEMS, "itemType"),
                               ("consumables", STARTER_CONSUMABLES, "family")):
        definitions = fut_cards.family(group)
        for name, count in wanted.items():
            if group == "clubItems" and name == "kit":
                matching = _starter_kits(definitions)
            else:
                matching = [item for item in definitions
                            if item.get(key) == name][:count]
            for definition in matching:
                out.append(fut_cards.build_card(definition, 0, timestamp))
    return out


def filter_club_items(items: list, query: dict,
                      positions: set | None = None) -> list:
    def wanted(name: str):
        value = query.get(name)
        if value in (None, "", "-1", "any"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    level = str(query.get("level", "any") or "any").lower()
    band = QUALITY_BANDS.get(level)
    league, nation, team = wanted("league"), wanted("nation"), wanted("team")
    rarity = None
    if level in ("rare", "sp", "special"):
        rarity = 1

    exact = str(query.get("position", "") or "").strip().upper()
    if exact and exact not in ("ANY", "ALL", "-1"):
        positions = ({exact} if positions is None
                     else {p for p in positions if p == exact})

    out = []
    for item in items:
        if positions is not None and item.get("preferredPosition") not in positions:
            continue
        if band is not None:
            rating = int(item.get("rating", 0) or 0)
            if not band[0] <= rating <= band[1]:
                continue
        if rarity is not None and int(item.get("rareflag", 0) or 0) < rarity:
            continue
        if league is not None and int(item.get("leagueId", 0) or 0) != league:
            continue
        if nation is not None and int(item.get("nation", 0) or 0) != nation:
            continue
        if team is not None and int(item.get("teamid", 0) or 0) != team:
            continue
        out.append(item)
    return out


CATALOGUE_FIELDS = ("bronze", "silver", "gold", "cardassetid", "cardsubtypeid", "leagueId")


def with_catalogue_fields(items: list) -> list:
    by_resource = fut_cards.definitions_by_resource()
    out = []
    for item in items:
        refreshed = dict(item)

        if (str(refreshed.get("itemType", "")) == "player"
                and "loans" not in refreshed):
            rating = int(refreshed.get("rating", 0) or 0)
            if rating:
                value = fut_cards.player_discard_value(
                    rating, int(refreshed.get("rareflag", 0) or 0))
                if value:
                    refreshed["discardValue"] = value

        definition = by_resource.get(int(item.get("resourceId", 0) or 0))
        if definition is not None:
            for key in CATALOGUE_FIELDS:
                if key in definition:
                    refreshed[key] = definition[key]

        if str(refreshed.get("itemType", "")) == "staff":
            subtype = fut_cards.staff_role_subtype(
                int(item.get("resourceId", 0) or 0))
            if subtype:
                refreshed["cardsubtypeid"] = subtype
            if not int(refreshed.get("contract", 0) or 0):
                refreshed["contract"] = fut_cards.STAFF_START_CONTRACT
        out.append(refreshed)
    return out


STAFF_WIRE_ITEM_TYPE: dict = {}


def with_staff_role_item_type(items: list) -> list:
    if not STAFF_WIRE_ITEM_TYPE:
        return items
    family = fut_cards.family_by_resource()
    out = []
    for item in items:
        if str(item.get("itemType", "")) == "staff":
            role = family.get(int(item.get("resourceId", 0) or 0))
            wire = STAFF_WIRE_ITEM_TYPE.get(role)
            if wire:
                item = dict(item, itemType=wire)
        out.append(item)
    return out


def _is_draft_squad_save(saved: dict) -> bool:
    slots = (saved or {}).get("slots") or {}
    for value in slots.values():
        try:
            if int(value) >= fut_draft.DRAFT_ITEM_ID_BASE:
                return True
        except (TypeError, ValueError):
            continue
    return False


def build_club_items(query: dict, enabled: bool = False,
                     size: int = LOCAL_CLUB_SQUAD_SIZE,
                     state: FutStateStore | None = None,
                     persona_id: int = DEFAULT_PERSONA_ID) -> bytes:
    wanted = str(query.get("type", "player") or "player").lower()

    def number(name: str, fallback: int) -> int:
        try:
            return max(0, int(query.get(name, fallback)))
        except (TypeError, ValueError):
            return fallback

    if state is not None:

        positions: set | None = None
        for group, group_positions in POSITION_GROUPS.items():
            if wanted.endswith(group) and wanted != group:
                positions = group_positions
                wanted = wanted[:-len(group)] or "player"
                break

        family = CLUB_SEARCH_FAMILIES.get(str(wanted).lower())
        if fut_staff_probe.enabled() and (family or wanted == "staff"):
            managers = [c for c in fut_cards.load_cards().get("staff", [])
                        if c.get("family") == "manager"]
            probes = fut_staff_probe.build_items(managers)
            total = len(probes)
            start = number("start", 0)
            probes = probes[start:start + number("count", 11)]
            emit("fut-staff-card-probe", cards=len(probes),
                 start=start, total=total)
            return json.dumps({"itemData": probes},
                              separators=(",", ":")).encode("utf-8")

        types = ("staff",) if family else CLUB_SEARCH_TYPES.get(wanted,
                                                               (wanted,))
        items = []
        for kind in types:
            items.extend(state.list_items(persona_id, "club", item_type=kind))
        if family:
            by_resource = fut_cards.family_by_resource()
            items = [item for item in items
                     if by_resource.get(int(item.get("resourceId", 0) or 0))
                     == family]

        items = filter_club_items(items, query, positions)
        reverse = str(query.get("sort", "desc")).lower() != "asc"
        items.sort(key=lambda item: (item.get("discardValue", 0),
                                     item.get("rating", 0),
                                     item.get("id", 0)),
                   reverse=reverse)
        start = number("start", 0)
        items = items[start:start + number("count", 11)]
    elif not enabled:
        return b'{"itemData":[]}'
    elif wanted != "player":
        return b'{"itemData":[]}'
    else:
        items = club_items(club_players(size), number("count", 11),
                           offset=number("start", 0), timestamp=int(time.time()))
    return json.dumps(
        {"itemData": with_staff_role_item_type(with_catalogue_fields(items))},
        separators=(",", ":")).encode("utf-8")


POSITION_GROUPS = {
    "goalkeeper": {"GK"},
    "defender": {"CB", "RB", "LB", "RWB", "LWB"},
    "midfielder": {"CDM", "CM", "CAM", "RM", "LM"},
    "attacker": {"ST", "CF", "RW", "LW", "RF", "LF"},
    "forward": {"ST", "CF", "RW", "LW", "RF", "LF"},
}

QUALITY_BANDS = {"bronze": (0, 64), "silver": (65, 74), "gold": (75, 99)}

CLUB_SEARCH_TYPES = {
    "player": ("player",),
    "staff": ("staff",),
    "equippables": ("kit", "stadium", "ball", "custom"),
    "badge": ("custom",),
    "consumables": ("development", "training"),
    "development": ("development",),
    "training": ("training",),
}

CLUB_SEARCH_FAMILIES = {
    "manager": "manager",
    "headcoach": "headCoach",
    "gkcoach": "GKCoach",
    "fitnesscoach": "fitnessCoach",
    "physio": "physio",
}

LOCAL_SQUAD_ID = 1
LOCAL_SQUAD_NAME = "Local XI"
LOCAL_SQUAD_FORMATION = "f442"


def squad_ids(server, persona_id: int = DEFAULT_PERSONA_ID) -> list:
    state = _ensure_persona(server, persona_id)
    stored = state.squad_ids(persona_id) if state is not None else []
    ordered = sorted({LOCAL_SQUAD_ID} |
                     {i for i in stored if i >= LOCAL_SQUAD_ID})
    if state is None:
        return ordered
    active_id = state.active_squad_id(persona_id, LOCAL_SQUAD_ID)
    if active_id in ordered:
        ordered.remove(active_id)
        ordered.insert(0, active_id)
    return ordered


def local_squad_record(server, persona_id: int = DEFAULT_PERSONA_ID,
                       squad_id: int = LOCAL_SQUAD_ID, *,
                       provision: bool = True) -> tuple[dict, list]:
    state = (_ensure_persona(server, persona_id)
             if provision else _state(server))
    if squad_id == LOCAL_SQUAD_ID:
        size = getattr(server, "club_size", LOCAL_CLUB_SQUAD_SIZE)
        players = (club_players(size)
                   if getattr(server, "club_items", False) else [])
    else:
        players = []
    saved = ((state.load_squad(persona_id, squad_id)
              if state is not None else None) or {})
    stored_name = (state.squad_name(persona_id, squad_id)
                   if state is not None else None)
    legacy_name = saved.get("squadName")
    if not isinstance(legacy_name, str) or not legacy_name:
        legacy_name = None
    return {
        "id": squad_id,
        "squadName": stored_name or legacy_name or (LOCAL_SQUAD_NAME
                                                     if squad_id == LOCAL_SQUAD_ID
                                                     else "Squad %d" % squad_id),
        "formation": saved.get("formation", LOCAL_SQUAD_FORMATION),
        "chemistry": saved.get("chemistry", 0),
        "rating": saved.get("rating", squad_rating(players)),
        "starRating": saved.get("starRating", 0),
    }, players


def build_local_squad_list(server, persona_id: int = DEFAULT_PERSONA_ID) -> bytes:
    squads = []
    for squad_id in squad_ids(server, persona_id):
        record, players = local_squad_record(server, persona_id, squad_id)
        squads.append(record)
    return json.dumps(build_squad_list(squads),
                      separators=(",", ":")).encode("utf-8")


def build_local_squad(server, persona_id: int = DEFAULT_PERSONA_ID,
                     squad_id: int = LOCAL_SQUAD_ID, *,
                     provision: bool = True) -> bytes:
    record, players = local_squad_record(
        server, persona_id, squad_id, provision=provision)
    state = (_ensure_persona(server, persona_id)
             if provision else _state(server))
    saved = (state.load_squad(persona_id, squad_id)
             if state is not None else None)
    if saved:
        record = dict(record)
        for key in ("formation", "chemistry", "rating", "starRating",
                    "custom", "captain", "kicktakers", "manager"):
            if key in saved:
                record[key] = saved[key]
    item_map = None
    manager_map = None
    if state is not None:
        item_map = {int(item["id"]): item
                    for item in state.list_items(persona_id)}
        manager_map = {
            int(item["id"]): item
            for pile in ("club", "squad")
            for item in with_catalogue_fields(
                state.list_items(persona_id, pile, item_type="staff"))}
    document = build_squad(record, players, persona_id, int(time.time()),
                           slots_by_index=saved["slots"] if saved else None,
                           items_by_id=item_map, managers_by_id=manager_map)
    actives = active_club_items(state, persona_id)
    if actives:
        document["actives"] = actives
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def parse_fut_auth_request(body: bytes) -> dict:
    try:
        document = json.loads(body or b"{}")
    except (UnicodeDecodeError, ValueError, TypeError):
        return {}
    if not isinstance(document, dict):
        return {}
    identification = document.get("identification")
    if not isinstance(identification, dict):
        identification = {}
    code = identification.get("authCode")
    claimed: list[int] = []
    for name in ("nuc", "nucleusPersonaId"):
        value = document.get(name)
        if value in (None, ""):
            continue
        try:
            claimed.append(int(value))
        except (TypeError, ValueError):
            return {}
    return {
        "method": str(document.get("method", "") or ""),
        "auth_code": code if isinstance(code, str) else "",
        "device_id": str(document.get("deviceId", "") or ""),
        "claimed_personas": tuple(claimed),
    }


def redacted_fut_headers(headers) -> dict:
    sensitive = {FUT_SID_HEADER.lower(), "authorization", "cookie", "x-session-id"}
    return {
        str(name): (REDACTED if str(name).lower() in sensitive else str(value))
        for name, value in headers.items()
    }


def redacted_fut_path(target: str) -> str:
    split = urlsplit(str(target or ""))
    sensitive = {"access_token", "authcode", "deviceid", "sid", "token"}
    query = [
        (name, REDACTED if name.lower() in sensitive else value)
        for name, value in parse_qsl(split.query, keep_blank_values=True)
    ]
    return urlunsplit(("", "", split.path, urlencode(query), ""))


def redacted_fut_body(path: str, body: bytes) -> str:
    if not body:
        return ""
    if path != "/ut/auth":
        return body.decode("utf-8", "replace")[:4096]
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, ValueError, TypeError):
        return "<redacted-auth-body>"
    if not isinstance(document, dict):
        return "<redacted-auth-body>"
    safe = dict(document)
    for name in ("deviceId", "macAddress"):
        if name in safe:
            safe[name] = REDACTED
    identification = safe.get("identification")
    if isinstance(identification, dict):
        identification = dict(identification)
        if "authCode" in identification:
            identification["authCode"] = REDACTED
        safe["identification"] = identification
    return json.dumps(safe, separators=(",", ":"), ensure_ascii=False)[:4096]


def build_user_info(persona_id: int,
                    balances: tuple[int, int] | None = None,
                    divisions: tuple[int, int] | None = None) -> bytes:
    envelope = json.loads(build_user_mass_info(
        persona_id, balances, divisions=divisions))
    return json.dumps(envelope["userInfo"],
                      separators=(",", ":")).encode("utf-8")


def build_squad_save_ack(squad_id: int) -> bytes:
    return json.dumps({"id": int(squad_id)},
                      separators=(",", ":")).encode("utf-8")


def build_match_create(server, persona_id: int, squad_id: int,
                       match: dict | None = None) -> bytes:
    if squad_id == fut_draft.DRAFT_SQUAD_ID:
        state = _ensure_persona(server, persona_id)
        squad = (fut_draft.build_run_squad(
            fut_draft.load_run(state, persona_id)) if state is not None
            else json.loads(build_local_squad(server, persona_id, 1)))
    else:
        squad = json.loads(build_local_squad(server, persona_id, squad_id))
    document = {
        "squad": squad,
        "startDateTime": int((match or {}).get("created_at", time.time())),
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def save_pre_match_lineup(server, persona_id: int, body: bytes) -> bool:
    try:
        request = json.loads(body or b"{}")
        wanted = [int(row["id"]) for row in request.get("items", [])
                  if isinstance(row, dict)]
    except (ValueError, TypeError, KeyError):
        return False
    if len(wanted) != 11 or len(set(wanted)) != 11:
        return False
    state = _ensure_persona(server, persona_id)
    if state is None:
        return False
    saved = state.save_match_lineup(persona_id, wanted)
    if saved is None:
        return False
    emit("fut-squad-lineup-saved", personaId=int(persona_id),
         matchId=str(saved["match_id"]), squad_id=int(saved["squad_id"]),
         starters=wanted)
    return True


ACTIVES_LIMIT = 5


def active_club_items(state, persona_id: int) -> list:
    if state is None:
        return []
    try:
        held = state.active_slot_items(persona_id)
        if not held:
            return []
        by_id = {int(item["id"]): item
                 for item in state.list_items(persona_id, "club")}
    except Exception:
        return []
    order = ("activeBadge", "activeHomeKit", "activeAwayKit",
             "activeBall", "activeStadium")
    out = []
    for name in order:
        item = by_id.get(int(held.get(name, 0) or 0))
        if item is not None:
            out.append(item)
    return out[:ACTIVES_LIMIT]


def _club_identity_descriptor(item: dict | None) -> dict:
    if not isinstance(item, dict):
        return {}
    try:
        return {
            "categoryId": int(item["category"]),
            "resourceId": int(item["resourceId"]),
            "teamId": int(item["teamid"]),
            "year": int(item["year"]),
        }
    except (KeyError, TypeError, ValueError):
        return {}


def build_opponent_user_list(server, persona_id: int) -> bytes:
    persona_id = int(persona_id)
    if not 0 < persona_id <= 0x7FFF_FFFF_FFFF_FFFF:
        return b'{"user":[]}'
    store = getattr(server, "store", None)
    account = (store.account_by_persona(persona_id)
               if store is not None else None)
    if account is None:
        return b'{"user":[]}'
    state = _ensure_persona(server, int(persona_id))
    if state is None:
        return b'{"user":[]}'

    equipped = {str(item.get("itemState", "")): item
                for item in active_club_items(state, int(persona_id))}
    badge = _club_identity_descriptor(equipped.get("activeBadge"))
    squads = json.loads(build_local_squad_list(server, int(persona_id)))
    record = {
        "clubName": LOCAL_CLUB_NAME,
        "clubAbbr": "LCL",
        "established": str(LOCAL_CLUB_ESTABLISHED),
        "personaId": int(persona_id),
        "teamId": int(badge.get("teamId", 0)),
        "badge": badge,
        "homekit": _club_identity_descriptor(
            equipped.get("activeHomeKit")),
        "awaykit": _club_identity_descriptor(
            equipped.get("activeAwayKit")),
        "squadList": squads,
    }
    return json.dumps({"user": [record]}, separators=(",", ":")).encode("utf-8")


def build_opponent_squad(server, persona_id: int, squad_id: int) -> bytes | None:
    persona_id = int(persona_id)
    if not 0 < persona_id <= 0x7FFF_FFFF_FFFF_FFFF:
        return None
    store = getattr(server, "store", None)
    account = (store.account_by_persona(persona_id)
               if store is not None else None)
    state = _state(server)
    if account is None or state is None or not state.has_persona(persona_id):
        return None
    return build_local_squad(
        server, persona_id, int(squad_id), provision=False)


LOCAL_CLUB_NAME = "Local FUT"
TRADE_STATE_ACTIVE = "active"
TRADE_STATE_EXPIRED = "expired"
TRADE_STATE_INACTIVE = "inactive"
TRADE_STATE_CLOSED = "closed"
BID_STATE_NONE = "none"
TRADE_DURATION_SECONDS = 3600
TIME_EXPIRED = -1


def wire_expires(trade_state: str, expires_at: int, now: int) -> int:
    if str(trade_state) in (TRADE_STATE_EXPIRED, TRADE_STATE_CLOSED):
        return TIME_EXPIRED
    return max(0, int(expires_at) - int(now))


def build_auction_entry(item: dict, trade_id: int, starting_bid: int,
                        buy_now: int, expires: int, *, current_bid: int = 0,
                        bid_state: str = BID_STATE_NONE,
                        trade_state: str | None = TRADE_STATE_ACTIVE,
                        coins_processed: int = 0,
                        watched: bool = False,
                        seller_name: str | None = None,
                        seller_established: int | None = None) -> dict:
    entry = {
        "tradeId": int(trade_id),
        "itemData": item,
        "currentBid": int(current_bid),
        "bidState": str(bid_state),
        "sellerName": str(LOCAL_CLUB_NAME if seller_name is None
                          else seller_name),
        "sellerEstablished": int(LOCAL_CLUB_ESTABLISHED
                                 if seller_established is None
                                 else seller_established),
        "coinsProcessed": int(coins_processed),
        "watched": bool(watched),
    }
    if trade_state is not None:
        entry["startingBid"] = int(starting_bid)
        entry["buyNowPrice"] = int(buy_now)
        entry["expires"] = int(expires)
        entry["tradeState"] = str(trade_state)
    return entry


def build_auction_list(entries: list, credits: int,
                       total: int | None = None) -> bytes:
    document = {"auctionInfo": entries,
                "credits": int(credits),
                "total": int(len(entries) if total is None else total)}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def _build_owner_auction_entry(trade: dict, now: int) -> dict:
    persisted_state = str(trade["trade_state"])
    wire_state = (TRADE_STATE_CLOSED if persisted_state == "sold"
                  else persisted_state)
    return build_auction_entry(
        trade["itemData"], int(trade["trade_id"]),
        int(trade["starting_bid"]), int(trade["buy_now_price"]),
        wire_expires(wire_state, trade["expires_at"], now),
        current_bid=int(trade["current_bid"]),
        bid_state=str(trade["bid_state"]),
        trade_state=(None if persisted_state == TRADE_STATE_INACTIVE
                     else wire_state),
        coins_processed=int(trade["coins_processed"]),
        watched=bool(trade["watched"]),
        seller_name=str(trade.get("seller_name") or LOCAL_CLUB_NAME),
        seller_established=int(trade.get("seller_established")
                               or LOCAL_CLUB_ESTABLISHED))


def build_trade_pile(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_auction_list([], fut_economy.STARTING_CREDITS)
    credits, _points = state.balances(persona_id)
    entries = []
    trades = state.list_trades(persona_id)
    listed_item_ids = set()
    now = int(time.time())
    for trade in trades:
        listed_item_ids.add(int(trade["item_id"]))
        entries.append(_build_owner_auction_entry(trade, now))

    for item in state.list_items(persona_id, "trade"):
        item_id = int(item.get("id", 0) or 0)
        if item_id in listed_item_ids:
            continue
        entries.append(build_auction_entry(
            item, 0, 0, 0, 0, trade_state=None))
    return build_auction_list(entries, credits)


def build_trade_status(server, persona_id: int, trade_ids: list[int]) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_auction_list([], fut_economy.STARTING_CREDITS)
    credits, _points = state.balances(persona_id)
    wanted = {int(trade_id) for trade_id in trade_ids}
    now = int(time.time())
    entries = []
    for trade in state.list_trades(persona_id, now=now):
        if int(trade["trade_id"]) not in wanted:
            continue
        entries.append(_build_owner_auction_entry(trade, now))

    for trade_id in sorted(wanted):
        if any(entry["tradeId"] == trade_id for entry in entries):
            continue
        listing = state.market_listing(
            trade_id, persona_id=persona_id, now=now)
        if listing is not None:
            entries.append(_build_market_auction_entry(listing, now))
    return build_auction_list(entries, credits)


def build_trade_pile_counts(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    total = selling = sold = 0
    if state is not None:
        trades = state.list_trades(persona_id)
        selling = sum(1 for trade in trades
                      if str(trade.get("trade_state", "")) ==
                      TRADE_STATE_ACTIVE)
        sold = sum(1 for trade in trades
                   if str(trade.get("trade_state", "")) == "sold")
        total = len(trades)
    document = {"count": int(total),
                "selling": int(selling),
                "sold": int(sold),
                "notification": 0}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def _build_market_auction_entry(listing: dict, now: int) -> dict:
    state = str(listing["trade_state"])
    if state == "sold":
        state = TRADE_STATE_CLOSED
    if state == "closed" and not int(listing["coins_processed"] or 0):
        state = TRADE_STATE_EXPIRED
    return build_auction_entry(
        listing["itemData"], int(listing["trade_id"]),
        int(listing["starting_bid"]), int(listing["buy_now_price"]),
        wire_expires(state, listing["expires_at"], now),
        current_bid=int(listing["current_bid"]),
        bid_state=str(listing["bid_state"]),
        trade_state=state,
        watched=bool(listing["watched"]) if "watched" in listing.keys()
        else False,
        seller_name=str(listing["seller_name"]),
        seller_established=int(listing["seller_established"]))


def build_market_search(server, persona_id: int, query: dict) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_auction_list([], fut_economy.STARTING_CREDITS)
    credits, _points = state.balances(persona_id)
    now = int(time.time())
    listings, total = state.search_market(
        query, now=now, persona_id=persona_id)
    entries = [_build_market_auction_entry(row, now) for row in listings]
    emit("fut-market-search", personaId=int(persona_id),
         type=str(query.get("type", "")), cat=str(query.get("cat", "")),
         returned=len(entries), total=int(total))
    return build_auction_list(entries, credits, total=total)


def build_price_comparison(server, persona_id: int, resource_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_auction_list([], fut_economy.STARTING_CREDITS)
    credits, _points = state.balances(persona_id)
    now = int(time.time())
    listings = state.market_listings_for_resource(
        resource_id, now=now, persona_id=persona_id)
    entries = [_build_market_auction_entry(row, now) for row in listings]
    return build_auction_list(entries, credits)


def build_offer_envelope(entries: list, credits: int) -> bytes:
    document = {"auctionInfo": entries,
                "credits": int(credits)}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_offer_result(server, persona_id: int, trade_id: int,
                       body: bytes) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_offer_envelope([], fut_economy.STARTING_CREDITS)
    try:
        request = json.loads(body or b"{}")
        bid = int(request.get("bid", 0) or 0)
    except (ValueError, TypeError, AttributeError):
        bid = 0

    listing, reason = state.place_offer(persona_id, trade_id, bid)
    now = int(time.time())
    if listing is None:
        current = state.market_listing(
            trade_id, persona_id=persona_id, now=now)
        rows = [_build_market_auction_entry(current, now)] if current else []
        credits, _points = state.balances(persona_id)
        emit("fut-offer-rejected", personaId=int(persona_id),
             tradeId=int(trade_id), bid=int(bid), reason=reason)
        return build_offer_envelope(rows, credits)

    credits, _points = state.balances(persona_id)
    emit("fut-offer-accepted", personaId=int(persona_id),
         tradeId=int(trade_id), bid=int(bid),
         outcome=str(listing.get("outcome", "")), credits=int(credits))
    return build_offer_envelope(
        [_build_market_auction_entry(listing, now)], credits)


def build_tournament_list(server=None) -> bytes:
    if getattr(server, "tournament_probe_row", False) or TOURNAMENT_PROBE_ROW:
        row = json.loads(build_probe_document(
            f"/ut/game/{GAME}/tournament/row").decode("utf-8"))
        return json.dumps({"tournament": [row]},
                          separators=(",", ":")).encode("utf-8")
    rows = fut_tournaments.build_rows(int(time.time()))
    emit("fut-tournament-list", tournaments=len(rows))
    return json.dumps({"tournament": rows},
                      separators=(",", ":")).encode("utf-8")


def build_season_list(mode: str = fut_seasons.TYPE_OFFLINE) -> bytes:
    rows = fut_seasons.build_rows(int(time.time()), mode)
    emit("fut-season-list", mode=mode, seasons=len(rows))
    return json.dumps({"seasons": rows},
                      separators=(",", ":")).encode("utf-8")


def build_season_user(server=None,
                      persona_id: int = DEFAULT_PERSONA_ID,
                      mode: str = fut_seasons.TYPE_OFFLINE) -> bytes:
    state = (_ensure_persona(server, persona_id) if server is not None else None)
    if state is not None and mode == fut_seasons.TYPE_ONLINE:
        state.ensure_season_progress(persona_id, mode, division_id=1)
    saved = (state.load_season_progress(persona_id, mode)
             if state is not None else None)
    if not saved or not saved.get("user_data"):
        document = {}
    else:
        document = {
            "data": str(saved["user_data"]),
            "dataVersion": str(int(saved["data_version"])),
            "divisionId": int(saved["division_id"]),
            "round": int(saved["round"]),
            "seasonId": int(saved["season_id"]),
            "userPoints": int(saved.get("points", 0)),
        }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def store_season_progress(server, persona_id: int, season_id: int,
                          division_id: int, body: bytes,
                          mode: str = fut_seasons.TYPE_OFFLINE) -> bytes:
    try:
        request = json.loads(body or b"{}")
    except (ValueError, TypeError):
        request = {}
    if not isinstance(request, dict):
        request = {}
    user_data = str(request.get("data", "") or "")
    progress_data = str(request.get("progressData", "") or "")
    state = _ensure_persona(server, persona_id)
    if state is not None and (user_data or progress_data):
        def number(key: str, fallback: int = 0) -> int:
            try:
                return int(request.get(key, fallback) or fallback)
            except (TypeError, ValueError):
                return int(fallback)

        incoming_round = number("round", 1)
        previous = state.load_season_progress(persona_id, mode)
        saved = state.save_season_progress(
            persona_id, season_id, division_id,
            round_number=incoming_round,
            data_version=number("dataVersion"),
            user_data=user_data,
            progress_data_version=number("progressDataVersion"),
            progress_data=progress_data,
            mode=mode)
        rollback = bool(
            previous
            and int(previous["season_id"]) == int(season_id)
            and int(previous["division_id"]) == int(division_id)
            and incoming_round < int(previous["round"])
            and int(saved.get("round", 0)) == int(previous["round"]))
        emit("fut-season-progress-rollback" if rollback
             else "fut-season-progress",
             personaId=int(persona_id), seasonId=int(season_id),
             divisionId=int(division_id), mode=mode,
             incomingRound=incoming_round,
             round=int(saved.get("round", incoming_round)),
             bytes=len(user_data))
    return build_season_user(server, persona_id, mode)


PARTICIPATION_AWARD = 100


def tournament_round_rewards(tournament_id: int) -> list[int]:
    entry = next((row for row in fut_tournaments.CATALOGUE
                  if int(row["id"]) == int(tournament_id)), None)
    return ([fut_economy.coins(coins) for _difficulty, coins in entry["rounds"]]
            if entry is not None else [])


def build_match_end(server, persona_id: int, body: bytes) -> bytes:
    try:
        request = json.loads(body or b"{}")
    except (ValueError, TypeError):
        request = {}
    if not isinstance(request, dict):
        request = {}
    end_reason = str(request.get("endReason", "") or "NO_CONTEST").upper()
    state = _ensure_persona(server, persona_id)
    active = state.active_match(persona_id) if state is not None else None
    tournament_id = int((active or {}).get("tournament_id", 0) or 0)
    settlement = (state.settle_active_match(
        persona_id, end_reason, request,
        tournament_round_rewards=tournament_round_rewards(tournament_id),
        participation_award=PARTICIPATION_AWARD)
        if state is not None else None)
    if settlement is None:
        match_coins = participation = balance = 0
        duplicate = False
        emit("fut-match-end-without-active", personaId=int(persona_id),
             endReason=end_reason)
    else:
        match_coins = int(settlement["match_coins"])
        participation = int(settlement["participation_award"])
        season_coins = int(settlement.get("season_coins", 0))
        balance = int(settlement["balance"])
        duplicate = bool(settlement["duplicate"])
        end_reason = str(settlement.get("end_reason", end_reason) or end_reason)
        outcome = str(settlement.get("tournament_outcome", "") or "")
        if outcome and not duplicate:
            emit("fut-tournament-settled", personaId=int(persona_id),
                 tournamentId=int(settlement["tournament_id"]),
                 previousRound=int(settlement["tournament_round_before"]),
                 round=int(settlement["tournament_round_after"]),
                 outcome=outcome)
    if settlement is None:
        season_coins = 0
    season_end_result = str(
        (settlement or {}).get("season_end_result", "") or "")
    total = match_coins + participation + season_coins
    emit("fut-match-end", personaId=int(persona_id), endReason=end_reason,
         matchCoins=match_coins, participation=participation,
         seasonCoins=season_coins, seasonEndResult=season_end_result,
         credits=balance,
         duplicate=duplicate,
         matchId=str((settlement or {}).get("match_id", "")))

    document = {
        "allCoins": int(total),
        "matchCoins": int(match_coins),
        "participationAward": int(participation),
        "boostConis": 0,
        "boostCountLeft": 0,
        "seasonCoins": int(season_coins),
        "tournamentCoins": int(match_coins),
        "gameModeAward": {"coins": 0},
        "teamOfTournamentWinner": False,
        "matchCoinMultipliers": [],
        "matchCoinPartials": [],
    }
    if season_end_result:
        document["seasonEndResult"] = season_end_result
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_tournament_teams(query: dict) -> bytes:
    def number(key: str, fallback: int) -> int:
        try:
            return int(str(query.get(key, fallback)))
        except (TypeError, ValueError):
            return fallback

    teams = fut_tournaments.opponent_team_ids(number("groupId", 0),
                                              number("count", 15))
    emit("fut-tournament-teams", groupId=number("groupId", 0),
         teams=len(teams))
    return json.dumps({"teamId": teams},
                      separators=(",", ":")).encode("utf-8")


def build_tournament_progress(server, persona_id: int,
                              tournament_id: int | None = None) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        record = {"round": 0, "data_version": 0, "tournament_data": ""}
    else:
        record = state.load_tournament_progress(persona_id, tournament_id)
    document = {
        "round": int(record["round"]),
        "dataVersion": str(int(record["data_version"])),
        "tournamentData": str(record["tournament_data"] or ""),
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def store_tournament_progress(server, persona_id: int, body: bytes,
                              tournament_id: int | None = None) -> bytes:
    try:
        request = json.loads(body or b"{}")
    except (ValueError, TypeError):
        request = {}
    if not isinstance(request, dict):
        request = {}

    def number(name: str) -> int:
        try:
            return int(request.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    state = _ensure_persona(server, persona_id)
    if state is not None:
        saved = state.save_tournament_progress(
            persona_id,
            round_number=number("round"),
            data_version=number("dataVersion"),
            tournament_data=str(request.get("tournamentData", "") or ""),
            progress_data_version=number("progressDataVersion"),
            progress_data=str(request.get("progressData", "") or ""),
            tournament_id=tournament_id)
        emit("fut-tournament-progress-rollback" if saved.get(
                 "settlement_rollback_rejected") else "fut-tournament-progress",
             personaId=int(persona_id),
             round=number("round"), dataVersion=number("dataVersion"),
             bytes=len(str(request.get("tournamentData", "") or "")))
    return build_tournament_progress(server, persona_id, tournament_id)


TOURNAMENT_PROBE_ROW = False


def build_tournament_user_list(server=None,
                               persona_id: int = DEFAULT_PERSONA_ID) -> bytes:
    state = _ensure_persona(server, persona_id) if server is not None else None
    joined = state.resumable_tournament_ids(persona_id) if state else []
    return json.dumps({"tournamentId": joined},
                      separators=(",", ":")).encode("utf-8")


def build_tournament_quit(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    removed = state.clear_tournament_progress(persona_id) if state else 0
    emit("fut-tournament-quit", personaId=int(persona_id), removed=int(removed))
    return json.dumps({"tournamentId": []},
                      separators=(",", ":")).encode("utf-8")


def build_watch_list(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_auction_list([], fut_economy.STARTING_CREDITS)
    credits, _points = state.balances(persona_id)
    now = int(time.time())
    entries = [_build_market_auction_entry(row, now)
               for row in state.bid_listings(persona_id, now=now)]
    return build_auction_list(entries, credits)


def mutate_watch_list(server, persona_id: int, path: str, body: bytes,
                      *, watched: bool) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return build_auction_list([], fut_economy.STARTING_CREDITS)
    trade_id = 0
    match = re.search(r"/(\d+)$", path)
    if match:
        trade_id = int(match.group(1))
    if not trade_id:
        try:
            request = json.loads(body or b"{}")
        except (TypeError, ValueError):
            request = {}
        if isinstance(request, dict):
            for key in ("tradeId", "trade_id", "id"):
                try:
                    trade_id = int(request.get(key, 0) or 0)
                except (TypeError, ValueError):
                    trade_id = 0
                if trade_id:
                    break
    if trade_id:
        if watched:
            state.watch_trade(persona_id, trade_id)
        else:
            state.unwatch_trade(persona_id, trade_id)
    return build_watch_list(server, persona_id)


def build_watch_list_counts(server=None, persona_id: int = 0) -> bytes:
    count = winning = outbid = 0
    state = _ensure_persona(server, persona_id) if server is not None else None
    if state is not None:
        rows = state.bid_listings(persona_id)
        count = len(rows)
        winning = sum(1 for row in rows
                      if str(row["bid_state"]) == FutStateStore.BID_HIGHEST)
        outbid = sum(1 for row in rows
                     if str(row["bid_state"]) == FutStateStore.BID_OUTBID)
    document = {"count": int(count), "winning": int(winning),
                "outbid": int(outbid), "notification": 0}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_auction_house(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    credits = (state.balances(persona_id)[0] if state is not None
               else fut_economy.STARTING_CREDITS)
    return build_auction_list([], credits)


def build_owner_listing(server, persona_id: int,
                        body: bytes) -> tuple[int, bytes, str]:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return 503, b"", "STATE_UNAVAILABLE"
    try:
        request = json.loads(body or b"{}")
    except (ValueError, TypeError):
        request = {}
    if not isinstance(request, dict):
        request = {}
    raw_item = request.get("itemData") or {}
    if isinstance(raw_item, list):
        item = raw_item[0] if raw_item and isinstance(raw_item[0], dict) else {}
    elif isinstance(raw_item, dict):
        item = raw_item
    else:
        item = {}

    def integer(names: tuple[str, ...], default: int = 0) -> int:
        for name in names:
            value = request.get(name)
            if value is None:
                value = item.get(name)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default
        return default

    item_id = integer(("itemId", "id"))
    starting_bid = integer(("startingBid", "startingbid"), FUT_MIN_LISTING_PRICE)
    buy_now = integer(("buyNowPrice", "buyNow", "buyitnow"), 0)
    duration = integer(("duration", "expires"), TRADE_DURATION_SECONDS)
    identity_store = getattr(server, "store", None)
    account = (identity_store.account_by_persona(persona_id)
               if identity_store is not None else None)
    seller_name = (str(account["display_name"]) if account is not None
                   else f"Persona {int(persona_id)}")
    trade, reason = state.create_trade(
        persona_id, item_id, starting_bid, buy_now, duration,
        seller_name=seller_name,
        seller_established=LOCAL_CLUB_ESTABLISHED)
    if trade is None:
        emit("fut-transfer-list-rejected", personaId=int(persona_id),
             itemId=item_id, startingBid=starting_bid, buyNowPrice=buy_now,
             duration=duration, reason=reason)
        return 400, b"", reason

    credits, _points = state.balances(persona_id)
    entry = _build_owner_auction_entry(trade, int(time.time()))
    emit("fut-transfer-listed", personaId=int(persona_id), itemId=item_id,
         tradeId=int(trade["trade_id"]), startingBid=starting_bid,
         buyNowPrice=buy_now, duration=duration)
    return 200, build_auction_list([entry], credits), ""


def cancel_owner_listing(server, persona_id: int, trade_id: int) -> bool:
    state = _ensure_persona(server, persona_id)
    cancelled = bool(state and state.cancel_trade(persona_id, trade_id))
    emit("fut-transfer-cancelled", personaId=int(persona_id),
         tradeId=int(trade_id), success=cancelled)
    return cancelled


def relist_expired_auctions(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        return b"{}"
    relisted, failed = state.relist_expired_trades(persona_id)
    emit("fut-transfer-relisted", personaId=int(persona_id),
         relisted=len(relisted), failed=int(failed),
         tradeIds=[int(trade["trade_id"]) for trade in relisted])
    return b"{}"


FUT_MIN_LISTING_PRICE = 150
FUT_MAX_LISTING_PRICE = 15_000_000


def build_price_limits(query: dict) -> bytes:
    def_id = 0
    for key in ("defId", "defid", "resourceId", "resourceid"):
        try:
            def_id = int(query.get(key, 0) or 0)
        except (TypeError, ValueError):
            def_id = 0
        if def_id:
            break
    if not def_id:
        return json.dumps([], separators=(",", ":")).encode("utf-8")
    minimum, maximum = fut_market.price_limits_for(def_id)
    rows = [{
        "defId": def_id,
        "minPrice": int(minimum),
        "maxPrice": int(maximum),
    }]
    return json.dumps(rows, separators=(",", ":")).encode("utf-8")


def build_price_limits_probe() -> bytes:
    return build_probe_document("/ut/game/%s/marketdata/pricelimits" % GAME)


def build_store_pack_locstrings() -> bytes:
    return fut_packs.build_locstrings().encode("utf-8")


def build_user_credits(balances: tuple[int, int] | None = None,
                       unopened_count: int = 0) -> bytes:
    credits, points = balances or (fut_economy.STARTING_CREDITS,
                                   fut_economy.STARTING_POINTS)
    document = {
        "currencies": [
            {"name": "coins", "funds": credits, "finalFunds": credits},
            {"name": "points", "funds": points, "finalFunds": points},
        ],
        "preOrderPacks": 0,
        "recoveredPacks": max(0, int(unopened_count)),
        "unopenedPacks": {"preOrderPacks": 0,
                            "recoveredPacks": max(0, int(unopened_count))},
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


_TYPE_SLOTS = {"stadium": 104, "custom": 100, "ball": 103}


def _activation_slot(state, persona_id: int, item_id: int,
                     requested) -> int | None:
    if requested is not None:
        try:
            return int(requested)
        except (TypeError, ValueError):
            return None
    try:
        item = next((row for row in state.list_items(persona_id, "club")
                     if int(row.get("id", 0) or 0) == int(item_id)), None)
    except Exception:
        return None
    if item is None:
        return None
    return _TYPE_SLOTS.get(str(item.get("itemType", "")))


def build_item_moves(body: bytes, server=None,
                     persona_id: int = DEFAULT_PERSONA_ID) -> bytes:
    state = _ensure_persona(server, persona_id) if server is not None else None
    if state is None:
        document = build_item_move(body)
    else:
        try:
            request = json.loads(body or b"{}")
        except (ValueError, TypeError):
            request = {}
        entries = request.get("itemData") or []
        if isinstance(entries, dict):
            entries = [entries]

        equips = [entry for entry in entries
                  if str(entry.get("itemState", "")) == "active"]
        if equips:
            results = []
            for entry in equips:
                try:
                    item_id = int(entry["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                slot = _activation_slot(state, persona_id, item_id,
                                        entry.get("activateSlotNumber"))
                if slot is None:
                    results.append({"id": item_id, "success": False,
                                    "reason": "Invalid Slot"})
                    continue
                ok, reason = state.activate_item(persona_id, item_id, slot)
                row = {"id": item_id, "success": bool(ok)}
                if not ok:
                    row["reason"] = reason
                results.append(row)
                emit("fut-item-activate", personaId=int(persona_id),
                     itemId=item_id, slot=slot, success=bool(ok))
            document = {"itemData": results}
            return json.dumps(document, separators=(",", ":")).encode("utf-8")

        results = state.move_items(persona_id, entries)
        if len(entries) > 1:
            for result in results:
                if (not result.get("success") and
                        result.get("reason") == "Duplicate Item Type"):
                    item_id = int(result["id"])
                    result.clear()
                    result.update({"id": item_id,
                                   "pile": "unassigned", "success": True})
        document = {"itemData": results}
    emit("fut-item-move", items=len(document["itemData"]))
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_item_view(server, persona_id: int, item_ids: list[int]) -> bytes:
    state = _ensure_persona(server, persona_id)
    items = state.items_by_ids(persona_id, item_ids) if state is not None else []
    return json.dumps({"itemData": items}, separators=(",", ":")).encode("utf-8")


def build_item_discard(server, persona_id: int, item_ids: list[int]) -> bytes:
    state = _ensure_persona(server, persona_id)
    if state is None:
        credits, sold = fut_economy.STARTING_CREDITS, []
    else:
        credits, sold = state.discard_items(persona_id, item_ids)
    emit("fut-item-discard", itemIds=[item["id"] for item in sold],
         payout=sum(item["discardValue"] for item in sold), credits=credits)
    return json.dumps({"totalCredits": credits}, separators=(",", ":")).encode("utf-8")


def build_purchased_items(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    items = state.list_items(persona_id, "unassigned") if state is not None else []
    owned = state.owned_by_resource(persona_id) if state is not None else {}
    duplicates = [{"itemId": int(item["id"]),
                   "duplicateItemId": int(owned[item["resourceId"]])}
                  for item in items if item.get("resourceId") in owned]
    document = {"itemData": items}
    if duplicates:
        document["duplicateItemIdList"] = duplicates
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


CONSUMABLE_ROUTES = {
    "contracts": ("development", ("contract",)),
    "contract": ("development", ("contract",)),
    "healing": ("development", ("healing",)),
    "fitness": ("development", ("fitness",)),
    "development": ("development", None),
    "training": ("training", ("trainingPlayer", "trainingGk")),
    "position": ("training", ("position",)),
    "playStyle": ("training", ("playStyle",)),
    "formation": ("training", ("formation",)),
    "managerLeagueModifier": ("training", ("leagueModifier",)),
}
_CONSUMABLE_ROUTES_LOWER = {name.lower(): route
                            for name, route in CONSUMABLE_ROUTES.items()}


def build_consumable_items(state, persona_id: int, kind: str) -> bytes:
    if state is None:
        return b'{"itemData":[]}'
    route = CONSUMABLE_ROUTES.get(kind) or _CONSUMABLE_ROUTES_LOWER.get(
        str(kind).lower())
    if route is None:
        items = []
        for item_type in CLUB_SEARCH_TYPES["consumables"]:
            items.extend(state.list_items(persona_id, "club",
                                          item_type=item_type))
    else:
        item_type, families = route
        items = state.list_items(persona_id, "club", item_type=item_type)
        if families is not None:
            by_resource = fut_cards.family_by_resource()
            wanted = set(families)
            items = [i for i in items
                     if by_resource.get(int(i.get("resourceId", 0) or 0))
                     in wanted]

    stacks: dict[int, dict] = {}
    for item in with_catalogue_fields(items):
        resource_id = int(item.get("resourceId", 0) or 0)
        stack = stacks.get(resource_id)
        if stack is None:
            stacks[resource_id] = {
                "item": item,
                "resourceId": resource_id,
                "count": 1,
                "untradeableCount": 1 if item.get("untradeable") else 0,
                "discardValue": int(item.get("discardValue", 0) or 0),
            }
        else:
            stack["count"] += 1
            if item.get("untradeable"):
                stack["untradeableCount"] += 1

    ordered = sorted(stacks.values(),
                     key=lambda s: (-int(s["item"].get("rating", 0) or 0),
                                    s["resourceId"]))
    return json.dumps({"itemData": ordered},
                      separators=(",", ":")).encode("utf-8")


def build_clientdata(state, persona_id: int, name: str) -> bytes:
    entries = state.load_clientdata(persona_id, name) if state else []
    return json.dumps({"entries": entries},
                      separators=(",", ":")).encode("utf-8")


def build_pile_sizes() -> bytes:
    document = {"entries": [
        {"key": 2, "value": SETTINGS_MAX_TRADE_PILE},
        {"key": 4, "value": SETTINGS_MAX_TRADE_PILE},
    ]}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_hub(server, persona_id: int) -> bytes:
    state = _ensure_persona(server, persona_id)
    players = 0
    auction_count = 0
    if state is not None:
        players = sum(1 for item in state.list_items(persona_id, "club")
                      if str(item.get("itemType", "")) == "player")
        auction_count = state.live_auction_count(persona_id)
    document = {"clubPlayers": int(players),
                "auctionCount": int(auction_count),
                "tradePile": json.loads(
                    build_trade_pile_counts(server, persona_id)),
                "watchlist": json.loads(
                    build_watch_list_counts(server, persona_id))}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_club_stats(items: list) -> bytes:
    document = fut_club_stats.build_club_stats(
        items, fut_cards.family_by_resource())
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_store_transaction() -> bytes:
    return json.dumps(fut_packs.build_transaction(),
                      separators=(",", ":")).encode("utf-8")


def build_store_offers(server=None,
                       persona_id: int = DEFAULT_PERSONA_ID) -> bytes:
    state = _ensure_persona(server, persona_id) if server is not None else None
    unopened = state.unopened_pack_ids(persona_id) if state is not None else []
    return json.dumps(fut_packs.build_store(int(time.time()), unopened),
                      separators=(",", ":")).encode("utf-8")


def build_pack_open(server, body: bytes,
                    persona_id: int = DEFAULT_PERSONA_ID) -> bytes:
    pack_id = 0
    try:
        request = json.loads(body or b"{}")
        pack_id = int(request.get("packId", 0))
    except (ValueError, AttributeError, TypeError):
        request = {}
        pack_id = 0
    persona_id = int(persona_id)
    state = _ensure_persona(server, persona_id)
    timestamp = int(time.time())
    owned_reward = bool(state is not None and
                        state.unopened_pack_count(persona_id, pack_id))
    offer = ((fut_packs.find_pack(pack_id, timestamp) if owned_reward else None)
             or fut_packs.find_active_offer(pack_id, timestamp)
             or fut_packs.PERMANENT_PACK_OFFERS[0])
    if state is not None:
        pending = state.list_items(persona_id, "unassigned")
        if pending:
            document = fut_packs.opened_document(
                offer, pending,
                owned_by_resource=state.owned_by_resource(persona_id))
            credits, points = state.balances(persona_id)
            emit("fut-pending-items-recovery", packId=offer["id"],
                 items=document["numberItems"],
                 itemIds=[item["id"] for item in pending],
                 credits=credits, points=points)
            return json.dumps(document, separators=(",", ":")).encode("utf-8")
    pool = club_players(2_147_483_647)
    owned = {}
    if state is not None:
        owned = state.owned_by_resource(persona_id)
    elif getattr(server, "club_items", False):
        size = getattr(server, "club_size", LOCAL_CLUB_SQUAD_SIZE)
        for index, player in enumerate(club_players(size)):
            owned.setdefault(int(player.get("resourceId", player["playerid"])),
                             index + 1)
    items = fut_packs.pack_contents(
        offer, pool, timestamp, persona_id=persona_id,
        sequence=state.item_high_water(persona_id) if state is not None else 0)
    if state is not None:
        currency = str(request.get("currency", "COINS"))
        price = (0 if owned_reward else
                 offer["points"] if currency.upper() == "POINTS" else offer["coins"])
        try:
            if owned_reward:
                opened = state.open_unopened_pack(persona_id, offer["id"], items)
                if opened is None:
                    raise ValueError("unopened pack is no longer available")
                items = opened
                credits, points = state.balances(persona_id)
            else:
                items, credits, points = state.purchase_pack(
                    persona_id, price, items, currency=currency,
                    pack_id=offer["id"])
        except ValueError:
            items = []
            credits, points = state.balances(persona_id)
        emit("fut-wallet", credits=credits, points=points,
             reason="reward-pack-open" if owned_reward else "pack-purchase",
             packId=offer["id"])
    document = fut_packs.opened_document(offer, items, owned_by_resource=owned)
    emit("fut-pack-open", packId=offer["id"], items=document["numberItems"],
         itemIds=[item["id"] for item in items])
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_account_info(
    persona_id: int,
    persona_name: str = "LocalFUT",
    account_mode: str = ACCOUNT_NEW,
) -> bytes:
    if account_mode not in ACCOUNT_MODES:
        raise ValueError(f"unknown FUT account mode: {account_mode}")

    returning = account_mode == ACCOUNT_RETURNING
    clubs = []
    if returning:
        clubs.append(
            {
                "year": "2017",
                "platform": "pc",
                "clubName": "Local FUT",
                "clubAbbr": "LCL",
                "established": LOCAL_CLUB_ESTABLISHED,
                "lastAccessTime": LOCAL_CLUB_LAST_ACCESS,
                "assetId": LOCAL_CLUB_BADGE_ID,
                "badgeId": LOCAL_CLUB_BADGE_ID,
                "skuAccessList": {FIFA17_PC_SKU: LOCAL_CLUB_LAST_ACCESS},
            }
        )

    document = {
        "userAccountInfo": {
            "personas": [
                {
                    "personaId": persona_id,
                    "personaName": persona_name,
                    "returningUser": int(returning),
                    "onlineAccess": True,
                    "trial": False,
                    "userState": None,
                    "userClubList": clubs,
                    "trialFree": False,
                }
            ]
        }
    }
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


class FutCaptureHandler(BoundedHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FIFA17FUTRevival"
    sys_version = ""

    timeout = REQUEST_TIMEOUT_SECONDS


    def log_message(self, fmt, *args):
        return

    def _read_body(self) -> bytes | None:
        return read_limited_body(self, redacted_fut_path(self.path))

    def _claimed_persona_id(self) -> int:
        try:
            return int(self.headers.get("Easw-Session-Data-Nucleus-Id", "") or DEFAULT_PERSONA_ID)
        except ValueError:
            return DEFAULT_PERSONA_ID

    def _persona_id(self) -> int:
        session = getattr(self, "_fut_session", None)
        if session is None:
            raise RuntimeError("authenticated FUT route has no session context")
        return int(session["persona_id"])

    @property
    def request_id(self) -> str:
        existing = getattr(self, "_request_id", "")
        if not existing:
            existing = secrets.token_hex(4)
            self._request_id = existing
        return existing

    def _send(self, status: int, payload: bytes, *, name: str,
              content_type: str = "application/json; charset=utf-8") -> None:
        started = getattr(self, "_request_started", None)
        if started is not None:
            health.record_request("fut",
                                  (time.perf_counter() - started) * 1000.0)
        self.send_response(status)
        self.send_header("X-Request-Id", self.request_id)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)
        started = getattr(self, "_request_started", None)
        elapsed_ms = (round((time.perf_counter() - started) * 1000, 3)
                      if started is not None else None)
        emit("fut-response", name=name, status=status, method=self.command,
             path=redacted_fut_path(self.path), bytes=len(payload),
             elapsedMs=elapsed_ms)

    def _dispatch(self) -> None:
        self._request_started = time.perf_counter()
        self._request_id = ""
        body = self._read_body()
        if body is None:
            return
        path = urlsplit(self.path).path.rstrip("/") or "/"
        emit(
            "fut-request",
            method=self.command,
            requestId=self.request_id,
            path=redacted_fut_path(self.path),
            tls=isinstance(self.connection, ssl.SSLSocket),
            agent=self.headers.get("User-Agent", ""),
            nucleus=self.headers.get("Easw-Session-Data-Nucleus-Id", ""),
            headers=redacted_fut_headers(self.headers),
            body=redacted_fut_body(path, body),
        )

        if path == "/ut/auth":
            limiter = getattr(self.server, "auth_throttle", None)
            source = self.client_address[0]
            if limiter is not None and limiter.blocked(source):
                emit("fut-auth-throttled", peer=source)
                return self._send(429, b"{}", name="ut-auth-throttled")
            request = parse_fut_auth_request(body)
            store = getattr(self.server, "store", None)
            session = None
            if request.get("method") == "authcode" and store is not None:
                session = store.start_fut_session(
                    request.get("auth_code", ""),
                    device_id=request.get("device_id", ""),
                )
            if session is None:
                if limiter is not None:
                    limiter.record_failure(source)
                emit("fut-auth-rejected", reason="invalid auth code or account session")
                return self._send(401, b"{}", name="ut-auth-rejected")
            if limiter is not None:
                limiter.record_success(source)
            claimed = request.get("claimed_personas", ())
            if any(int(value) != int(session["persona_id"]) for value in claimed):
                emit("fut-auth-rejected", reason="persona mismatch",
                     personaId=int(session["persona_id"]))
                return self._send(403, b"{}", name="ut-auth-persona-mismatch")
            emit("fut-authenticated", personaId=int(session["persona_id"]))
            return self._send(
                200, build_auth_session(str(session["sid"])), name="ut-auth")

        if path == "/ut/delete/auth":
            sid = self.headers.get(FUT_SID_HEADER, "")
            store = getattr(self.server, "store", None)
            revoked = bool(store and store.revoke_fut_session(sid))
            emit("fut-auth-revoked", revoked=revoked,
                 sidPresent=bool(sid))
            return self._send(200, b"{}", name="ut-delete-auth")

        accountinfo_path = f"/ut/game/{GAME}/user/accountinfo"
        if path.startswith("/ut/") and path != accountinfo_path:
            sid = self.headers.get(FUT_SID_HEADER, "")
            store = getattr(self.server, "store", None)
            session = store.fut_session(sid) if store is not None else None
            if session is None:
                emit("fut-auth-required", path=path, sidPresent=bool(sid))
                return self._send(401, b"{}", name="fut-auth-required")
            nucleus = self.headers.get("Easw-Session-Data-Nucleus-Id", "")
            if nucleus:
                try:
                    mismatch = int(nucleus) != int(session["persona_id"])
                except ValueError:
                    mismatch = True
                if mismatch:
                    emit("fut-persona-mismatch", path=path,
                         personaId=int(session["persona_id"]))
                    return self._send(403, b"{}", name="fut-persona-mismatch")
            self._fut_session = session

        if path == f"/ut/game/{GAME}/settings":
            return self._send(200, build_fut_settings(), name="fut-settings")

        if path == f"/ut/game/{GAME}/phishing/trusteddevice":
            return self._send(200, build_trusted_device(), name="trusted-device")

        if path in (f"/ut/game/{GAME}/phishing", f"/ut/game/{GAME}/phishing/question"):
            return self._send(200, build_phishing_question(), name="phishing-question")

        if path == f"/ut/game/{GAME}/phishing/validate":
            return self._send(200, build_phishing_validation(), name="phishing-validate")


        if path == f"/ut/game/{GAME}/userMassInfo":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            balances = state.balances(persona_id) if state is not None else None
            squads = json.loads(build_local_squad_list(self.server, persona_id))
            active_id = (state.active_squad_id(persona_id, LOCAL_SQUAD_ID)
                         if state is not None else LOCAL_SQUAD_ID)
            active = json.loads(build_local_squad(self.server, persona_id,
                                                  active_id))
            unopened = (state.unopened_pack_count(persona_id)
                        if state is not None else 0)
            divisions = (state.season_divisions(persona_id)
                         if state is not None else None)
            return self._send(200,
                              build_user_mass_info(persona_id, balances,
                                                   squads, active, unopened,
                                                   divisions),
                              name="user-mass-info")

        if path == f"/ut/game/{GAME}/user/list":
            query = dict(parse_qsl(urlsplit(self.path).query,
                                   keep_blank_values=True))
            try:
                opponent_id = int(query.get("personaIdList", ""))
            except (TypeError, ValueError):
                opponent_id = 0
            return self._send(
                200, build_opponent_user_list(self.server, opponent_id),
                name="opponent-user-list")

        consumable_prefix = f"/ut/game/{GAME}/club/consumables/"
        if path.startswith(consumable_prefix):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            kind = path[len(consumable_prefix):].strip("/").lower()
            return self._send(200,
                              build_consumable_items(state, persona_id, kind),
                              name=f"club-consumables-{kind or 'all'}")

        clientdata_prefix = f"/ut/game/{GAME}/clientdata/"
        if path == f"{clientdata_prefix}pileSize" and self.command == "GET":
            return self._send(200, build_pile_sizes(), name="clientdata-pile-size")
        if path.startswith(clientdata_prefix) and self.command in ("PUT", "POST"):
            name = path[len(clientdata_prefix):].split("?", 1)[0]
            if name == fut_sbc.PROGRESS_KEY or name.startswith(
                    fut_sbc.SQUAD_KEY_PREFIX):
                emit("fut-clientdata-reserved", name=name)
                return self._send(403, b"{}", name="clientdata-reserved")
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is not None:
                try:
                    request = json.loads(body or b"{}")
                except ValueError:
                    request = {}
                entries = request.get("entries")
                if isinstance(entries, list):
                    state.save_clientdata(persona_id, name, entries)
                    emit("fut-clientdata-saved", name=name, entries=len(entries))

        if path == f"/ut/game/{GAME}/hub":
            return self._send(200,
                              build_hub(self.server, self._persona_id()),
                              name="hub")

        if path.startswith(f"/ut/game/{GAME}/club/stats"):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            items = state.list_items(persona_id, "club") if state else []
            return self._send(200, build_club_stats(items), name="club-stats")

        item_path = f"/ut/game/{GAME}/item"
        if path == item_path and self.command == "GET":
            query = dict(parse_qsl(urlsplit(self.path).query))
            ids = [value for value in query.get("idList", "").split(",")
                   if value]
            return self._send(200,
                              build_item_view(self.server, self._persona_id(), ids),
                              name="item-view")

        if path == item_path and self.command in ("PUT", "POST"):
            return self._send(200, build_item_moves(
                body, self.server, self._persona_id()), name="item-move")

        activate = re.fullmatch(re.escape(item_path) + r"/(\d+)", path)
        if activate and self.command in ("PUT", "POST"):
            try:
                request = json.loads(body or b"{}")
            except (ValueError, TypeError):
                request = {}
            entry = dict(request)
            entry.setdefault("id", int(activate.group(1)))
            return self._send(
                200,
                build_item_moves(
                    json.dumps({"itemData": [entry]}).encode("utf-8"),
                    self.server, self._persona_id()),
                name="item-activate")

        discard = re.fullmatch(re.escape(item_path) + r"/(\d+)", path)
        if discard and self.command == "DELETE":
            return self._send(200, build_item_discard(
                self.server, self._persona_id(), [int(discard.group(1))]),
                name="item-discard")

        if path == f"/ut/delete/game/{GAME}/item" and self.command == "POST":
            try:
                request = json.loads(body or b"{}")
            except (ValueError, TypeError):
                request = {}
            ids = request.get("itemId") or request.get("itemIds") or []
            if not isinstance(ids, list):
                ids = [ids]
            entries = request.get("itemData") or []
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if isinstance(entry, dict):
                    ids.append(entry.get("id", entry.get("itemId")))
            return self._send(200, build_item_discard(
                self.server, self._persona_id(), ids), name="items-discard")

        active_by_id = re.fullmatch(
            re.escape(f"/ut/game/{GAME}/squad/active") + r"/(\d+)", path)
        if active_by_id and self.command in ("PUT", "POST"):
            squad_id = int(active_by_id.group(1))
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is not None:
                state.set_active_squad(persona_id, squad_id)
                emit("fut-squad-active", personaId=int(persona_id),
                     squadId=squad_id)
            return self._send(200,
                              build_local_squad(self.server, persona_id,
                                                squad_id),
                              name="squad-active-selected")

        if path == f"/ut/game/{GAME}/squad/active":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            squad_id = (state.active_squad_id(persona_id, LOCAL_SQUAD_ID)
                        if state is not None else LOCAL_SQUAD_ID)
            return self._send(200,
                              build_local_squad(self.server, persona_id,
                                                squad_id),
                              name="squad-active")

        if path == f"/ut/game/{GAME}/tradePile/counts":
            return self._send(
                200, build_trade_pile_counts(self.server, self._persona_id()),
                name="trade-pile-counts")

        if ((path == f"/ut/game/{GAME}/tradePile" and self.command == "DELETE")
                or path == f"/ut/delete/game/{GAME}/tradePile"):
            state = _ensure_persona(self.server, self._persona_id())
            removed = (state.remove_sold_trades(self._persona_id())
                       if state is not None else 0)
            emit("fut-transfer-sold-removed", personaId=self._persona_id(),
                 removed=int(removed))
            return self._send(200, b"{}", name="trade-pile-remove-sold")

        if path == f"/ut/game/{GAME}/tradePile":
            return self._send(200,
                              build_trade_pile(self.server, self._persona_id()),
                              name="trade-pile")

        if path == f"/ut/game/{GAME}/trade/status":
            query = dict(parse_qsl(urlsplit(self.path).query))
            trade_ids = []
            for value in query.get("tradeIds", "").split(","):
                try:
                    trade_ids.append(int(value))
                except ValueError:
                    continue
            return self._send(
                200,
                build_trade_status(self.server, self._persona_id(), trade_ids),
                name="trade-status")

        if path == f"/ut/game/{GAME}/watchList/counts":
            return self._send(200, build_watch_list_counts(
                self.server, self._persona_id()),
                              name="watch-list-counts")

        if path.startswith(f"/ut/game/{GAME}/watchList"):
            if self.command in ("POST", "PUT"):
                return self._send(
                    200, mutate_watch_list(self.server, self._persona_id(),
                                           path, body, watched=True),
                    name="watch-list-add")
            return self._send(200,
                              build_watch_list(self.server, self._persona_id()),
                              name="watch-list")

        if path.startswith(f"/ut/delete/game/{GAME}/watchList"):
            return self._send(
                200, mutate_watch_list(self.server, self._persona_id(), path,
                                       body, watched=False),
                name="watch-list-delete")

        season_root = f"/ut/game/{GAME}/season"
        season_progress = re.fullmatch(
            re.escape(season_root) + r"/(\d+)/division/(\d+)/user", path)
        if season_progress and self.command in ("PUT", "POST"):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            requested = dict(parse_qsl(urlsplit(self.path).query)).get(
                "type", "").strip().upper()
            mode = (requested if requested in (
                fut_seasons.TYPE_OFFLINE, fut_seasons.TYPE_ONLINE) else
                state.current_season_mode(persona_id) if state is not None else
                fut_seasons.TYPE_OFFLINE)
            return self._send(
                200,
                store_season_progress(
                    self.server, persona_id,
                    int(season_progress.group(1)),
                    int(season_progress.group(2)), body, mode),
                name="season-progress")

        if path == f"{season_root}/list" and self.command == "GET":
            requested = dict(parse_qsl(urlsplit(self.path).query)).get(
                "type", "offline").strip().upper()
            mode = (fut_seasons.TYPE_ONLINE
                    if requested == "ONLINE" else fut_seasons.TYPE_OFFLINE)
            state = _ensure_persona(self.server, self._persona_id())
            if state is not None:
                state.select_season_mode(self._persona_id(), mode)
            return self._send(200, build_season_list(mode), name="season-list")

        if path == f"{season_root}/user" and self.command == "GET":
            requested = dict(parse_qsl(urlsplit(self.path).query)).get(
                "type", "offline").strip().upper()
            mode = (fut_seasons.TYPE_ONLINE
                    if requested == "ONLINE" else fut_seasons.TYPE_OFFLINE)
            state = _ensure_persona(self.server, self._persona_id())
            if state is not None:
                state.select_season_mode(self._persona_id(), mode)
            return self._send(
                200, build_season_user(self.server, self._persona_id(), mode),
                name="season-user")

        sbs_root = f"/ut/game/{GAME}/sbs"
        if path == f"{sbs_root}/sets" and self.command == "GET":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            tagged = state.sbc_tagged_sets(persona_id) if state else set()
            return self._send(200, fut_sbc.build_sets(
                _sbc_progress(self.server, persona_id), tagged),
                name="sbs-sets")

        if path == f"{sbs_root}/sets/tag" and self.command in ("PUT", "POST"):
            try:
                request = json.loads(body or b"{}")
            except (TypeError, ValueError):
                request = {}
            raw_id = request.get("setId", request.get("id", 0)) \
                if isinstance(request, dict) else 0
            try:
                set_id = int(raw_id)
            except (TypeError, ValueError):
                set_id = 0
            if fut_sbc.find_set(set_id) is None:
                return self._send(404, b"{}", name="sbs-tag-unknown-set")
            tagged = bool(request.get("taggedByUser",
                                      request.get("tagged", True)))
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is not None:
                state.set_sbc_tag(persona_id, set_id, tagged)
            emit("sbs-set-tag", setId=set_id, tagged=tagged)
            return self._send(200, b"{}", name="sbs-set-tag")

        sbs_challenges = re.fullmatch(
            re.escape(sbs_root) + r"/setId/(\d+)/challenges", path)
        if sbs_challenges and self.command == "GET":
            persona_id = self._persona_id()
            return self._send(200, fut_sbc.build_challenges(
                int(sbs_challenges.group(1)),
                _sbc_progress(self.server, persona_id),
                _sbc_in_progress(self.server, persona_id)),
                name="sbs-challenges")

        sbs_challenge = re.fullmatch(
            re.escape(sbs_root) + r"/challenge/(\d+)(/squad)?", path)
        if sbs_challenge:
            challenge_id = int(sbs_challenge.group(1))
            is_squad_route = bool(sbs_challenge.group(2))
            found = fut_sbc.find_challenge(challenge_id)
            set_id = found[0] if found else 0
            formation = found[3] if found else "f442"
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if found is None:
                emit("sbs-unknown-challenge", challengeId=challenge_id)
                return self._send(404, b"{}", name="sbs-unknown-challenge")

            if self.command == "PUT" and not is_squad_route and state is not None:
                try:
                    receipt = _submit_sbc_challenge(
                        self.server, state, persona_id, challenge_id, set_id)
                except SbcValidationError as error:
                    emit("sbs-submit-refused", challengeId=challenge_id,
                         reasons=error.reasons)
                    return self._send(
                        400, json.dumps({"reason": str(error)},
                                        separators=(",", ":")).encode("utf-8"),
                        name="sbs-challenge-invalid")
                return self._send(200, receipt, name="sbs-challenge-submit")

            if state is not None and is_squad_route and \
                    self.command in ("PUT", "POST"):
                parsed = fut_sbc.parse_submitted_squad(body)
                try:
                    if parsed is None:
                        raise SbcValidationError("invalid squad document")
                    definition = fut_sbc.challenge_definition(challenge_id) or {}
                    fut_sbc.save_submitted_squad(
                        state, persona_id, challenge_id, parsed,
                        repeatable=bool(definition.get("repeatable", False)))
                except SbcValidationError as error:
                    emit("sbs-squad-save-refused", challengeId=challenge_id,
                         reasons=error.reasons)
                    return self._send(
                        400, json.dumps({"reason": str(error)},
                                        separators=(",", ":")).encode("utf-8"),
                        name="sbs-challenge-squad-invalid")
                emit("sbs-challenge-squad-save", challengeId=challenge_id,
                     players=len(parsed.get("slots") or {}),
                     rating=parsed.get("rating", 0),
                     chemistry=parsed.get("chemistry", 0))
            elif not is_squad_route and self.command == "POST":
                emit("sbs-challenge-start", challengeId=challenge_id,
                     setId=set_id,
                     squadId=fut_sbc.challenge_squad_id(challenge_id))
            elif not is_squad_route:
                return self._send(405, b"{}", name="sbs-challenge-method")

            saved = (fut_sbc.load_submitted_squad(state, persona_id,
                                                  challenge_id)
                     if state is not None else None)
            items = _persona_items_by_id(state, persona_id) if state else {}
            return self._send(200, fut_sbc.build_challenge_start(
                challenge_id, set_id, persona_id, formation, saved, items),
                name="sbs-challenge")

        if path == f"/ut/game/{GAME}/squad/mode/draft/state" and \
                self.command == "GET":
            mode = dict(parse_qsl(urlsplit(self.path).query)).get(
                "mode", "").strip().upper()
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is None:
                return self._send(200,
                                  fut_draft.build_state(persona_id=persona_id),
                                  name="draft-state")
            if mode in fut_draft.MODES:
                fut_draft.select_mode(state, persona_id, mode)
            else:
                mode = fut_draft.current_mode(state, persona_id)
            run = fut_draft.load_run(state, persona_id, mode)
            emit("fut-draft-state", mode=mode or "(unset)", state=run["state"],
                 formation=fut_draft.run_formation(run),
                 picks=len(run["picks"]))
            return self._send(200, fut_draft.build_state_for_run(run),
                              name="draft-state")

        draft_award = re.fullmatch(
            f"/ut/game/{GAME}" + r"/squad/mode/(\d+)/draft/grant/award", path)
        if draft_award:
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            mode = fut_draft.mode_from_wire(draft_award.group(1))
            if state is not None:
                fut_draft.select_mode(state, persona_id, mode)
            run = (fut_draft.load_run(state, persona_id, mode)
                   if state is not None
                   else fut_draft.reset_run(_NullStore(), persona_id))
            document = fut_draft.build_award(run)
            reward_mode = (fut_draft.MODE_ONLINE
                           if int(run.get("mode", 0))
                           else fut_draft.MODE_SINGLE_PLAYER)
            coins = fut_draft.draft_award_coins(
                int(run.get("wins", 0)), reward_mode)
            paid = False
            if document != b"[]" and state is not None:
                paid = state.award_credits(
                    persona_id, coins, "draft-award",
                    related_type="draft",
                    related_id=int(run.get("nonce", 0) or 0),
                    idempotency_key="draft-award-%d-%d" % (
                        int(run.get("nonce", 0) or 0),
                        int(run.get("wins", 0)))) is not None
                fut_draft.reset_run(
                    state, persona_id, reward_mode, active=False)
            emit("fut-draft-award", wins=int(run.get("wins", 0)),
                 coins=coins if document != b"[]" else 0, paid=bool(paid))
            return self._send(200, document, name="draft-award")

        draft_choice = re.fullmatch(
            f"/ut/game/{GAME}" + r"/squad/mode/(\d+)/draft/choices/(\w+)",
            path)
        if draft_choice:
            wire_mode = int(draft_choice.group(1))
            mode = fut_draft.mode_from_wire(wire_mode)
            kind = draft_choice.group(2)
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is not None:
                fut_draft.select_mode(state, persona_id, mode)
            run = (fut_draft.load_run(state, persona_id, mode)
                   if state is not None
                   else fut_draft.reset_run(_NullStore(), persona_id))
            position_id = fut_draft.parse_position_id(body)
            emit("fut-draft-choices", pick=kind, wireMode=wire_mode, mode=mode,
                 positionId=position_id, state=run["state"])
            if kind == fut_draft.CHOICE_FORMATION:
                return self._send(200,
                                  fut_draft.build_formation_choices(run),
                                  name="draft-choices-formation")
            if kind == fut_draft.CHOICE_DIFFICULTY:
                return self._send(200, fut_draft.build_difficulty_choices(),
                                  name="draft-choices-difficulty")
            if kind == fut_draft.CHOICE_CAPTAIN:
                return self._send(200, fut_draft.build_captain_choices(
                    persona_id, run, position_id, store=state),
                    name="draft-choices-captain")
            if kind == fut_draft.CHOICE_MANAGER:
                if state is not None:
                    fut_draft.expect_manager_choice(state, persona_id)
                return self._send(200, fut_draft.build_manager_choices(
                    persona_id, run), name="draft-choices-manager")
            return self._send(200, fut_draft.build_player_choices(
                persona_id, run, position_id, store=state),
                name="draft-choices-player")

        if re.fullmatch(f"/ut/game/{GAME}" +
                        r"/(?:squad/mode/)?draft/choose/difficulty", path):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            name = fut_draft.parse_difficulty_name(body)
            if state is None:
                return self._send(200, b"{}", name="draft-choose-difficulty")
            run = fut_draft.choose_difficulty(state, persona_id, name)
            emit("fut-draft-difficulty", difficultyName=name or "(none)",
                 state=run["state"])
            return self._send(200, b"{}", name="draft-choose-difficulty")

        draft_autocomplete = re.fullmatch(
            f"/ut/game/{GAME}" + r"/squad/mode/(\d+)/draft/autocomplete", path)
        if draft_autocomplete and self.command == "PUT":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            mode = fut_draft.mode_from_wire(draft_autocomplete.group(1))
            if state is not None:
                fut_draft.select_mode(state, persona_id, mode)
                run = fut_draft.autocomplete_run(state, persona_id, mode)
                emit("fut-draft-autocomplete", mode=mode,
                     state=run["state"], picks=len(run["picks"]))
            return self._send(200, b"{}", name="draft-autocomplete")

        draft_choose = re.fullmatch(
            f"/ut/game/{GAME}" + r"/squad/mode/(\d+)/draft/choose(?:/(\w+))?",
            path)
        if draft_choose:
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            wire_mode = int(draft_choose.group(1))
            mode = fut_draft.mode_from_wire(wire_mode)
            if state is not None:
                fut_draft.select_mode(state, persona_id, mode)
            try:
                document = json.loads(body or b"{}")
                picked = int(document.get("choiceIndex", 0) or 0)
                position_id = int(document.get("positionId",
                                               document.get("positionid", 0))
                                  or 0)
            except (ValueError, TypeError, AttributeError):
                picked, position_id = 0, 0
            if state is None:
                return self._send(200, b"{}", name="draft-choose")
            layout = fut_draft.parse_swap_layout(body)
            if layout:
                run = fut_draft.apply_swap_layout(state, persona_id, layout)
                emit("fut-draft-swap", seated=len(run["picks"]))
            run = fut_draft.advance_run(state, persona_id, picked, position_id)
            emit("fut-draft-choose", choiceIndex=picked,
                 positionId=position_id, state=run["state"],
                 picks=len(run["picks"]))
            return self._send(200, b"{}", name="draft-choose")

        draft_stats = re.fullmatch(
            f"/ut/game/{GAME}" + r"/draft/mode/(\d+)/stats", path)
        if draft_stats:
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            mode = fut_draft.mode_from_wire(draft_stats.group(1))
            if state is not None:
                fut_draft.select_mode(state, persona_id, mode)
            run = (fut_draft.load_run(state, persona_id, mode)
                   if state is not None else None)
            emit("fut-draft-stats", state=(run or {}).get("state", "INVALID"))
            return self._send(200, fut_draft.build_stats(), name="draft-stats")

        draft_purchase = re.fullmatch(
            f"/ut/game/{GAME}" + r"/purchase/mode/(\d+)/draft", path)
        if draft_purchase and self.command in ("PUT", "POST"):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            mode = fut_draft.mode_from_wire(draft_purchase.group(1))
            if state is None:
                return self._send(200,
                                  fut_draft.build_state(persona_id=persona_id),
                                  name="draft-purchase")
            fut_draft.select_mode(state, persona_id, mode)
            coins, _points = state.balances(persona_id)
            if coins < fut_draft.ENTRY_COINS:
                emit("fut-draft-purchase-refused", coins=coins,
                     price=fut_draft.ENTRY_COINS)
                run = fut_draft.load_run(state, persona_id)
                return self._send(200, fut_draft.build_state_for_run(run),
                                  name="draft-purchase-refused")
            try:
                balance = state.charge_credits(
                    persona_id, fut_draft.ENTRY_COINS, reason="draft-entry",
                    related_type="draft", related_id=mode,
                    idempotency_key=(f"draft-entry:{persona_id}:"
                                     f"{int(time.time())}"))
            except ValueError:
                emit("fut-draft-purchase-refused", coins=coins,
                     price=fut_draft.ENTRY_COINS)
                run = fut_draft.load_run(state, persona_id)
                return self._send(200, fut_draft.build_state_for_run(run),
                                  name="draft-purchase-refused")
            run = fut_draft.reset_run(state, persona_id, mode)
            emit("fut-draft-purchase", mode=mode, state=run["state"],
                 paid=fut_draft.ENTRY_COINS, balance=balance)
            return self._send(200, fut_draft.build_state_for_run(run),
                              name="draft-purchase")

        tournament_root = f"/ut/game/{GAME}/tournament"
        if path == f"{tournament_root}/user" and self.command in ("PUT", "POST"):
            return self._send(200,
                              store_tournament_progress(
                                  self.server, self._persona_id(), body),
                              name="tournament-progress")

        if path == f"{tournament_root}/user/list" and self.command == "GET":
            return self._send(200,
                              build_tournament_user_list(self.server,
                                                         self._persona_id()),
                              name="tournament-user-list")

        if path in (f"{tournament_root}/list", tournament_root) and \
                self.command == "GET":
            return self._send(200, build_tournament_list(self.server),
                              name="tournament-list")

        if path == f"/ut/delete/game/{GAME}/tournament/user" or (
                path == f"{tournament_root}/user" and self.command == "DELETE"):
            return self._send(200,
                              build_tournament_quit(self.server,
                                                    self._persona_id()),
                              name="tournament-quit")

        tournament_user_by_id = re.fullmatch(
            re.escape(tournament_root) + r"/user/(\d+)", path)
        if tournament_user_by_id:
            tournament_id = int(tournament_user_by_id.group(1))
            if self.command in ("PUT", "POST"):
                return self._send(
                    200,
                    store_tournament_progress(
                        self.server, self._persona_id(),
                        body, tournament_id),
                    name="tournament-user-save")
            if self.command == "GET":
                return self._send(
                    200,
                    build_tournament_progress(self.server, self._persona_id(),
                                              tournament_id),
                    name="tournament-user-load")

        if path == f"{tournament_root}/teams" and self.command == "GET":
            return self._send(
                200,
                build_tournament_teams(
                    dict(parse_qsl(urlsplit(self.path).query))),
                name="tournament-teams")

        tournament_by_id = re.fullmatch(
            re.escape(tournament_root) + r"/(\d+)", path)
        if tournament_by_id and self.command == "GET":
            return self._send(200,
                              build_tournament_progress(
                                  self.server, self._persona_id(),
                                  int(tournament_by_id.group(1))),
                              name="tournament-load")

        if path == f"/ut/game/{GAME}/transfermarket":
            query = dict(parse_qsl(urlsplit(self.path).query))
            comparing = any(query.get(alias) for alias in
                            ("definitionId", "defId", "defid", "maskedDefId"))
            label = ("compare-price" if comparing
                     else f"search-{query.get('type', 'any')}")
            return self._send(200,
                              build_market_search(self.server,
                                                  self._persona_id(), query),
                              name=f"market-{label}")

        auction_house_path = f"/ut/game/{GAME}/auctionhouse"

        if path == f"{auction_house_path}/relist" and self.command in ("PUT", "POST"):
            return self._send(200,
                              relist_expired_auctions(self.server,
                                                      self._persona_id()),
                              name="auction-house-relist")

        if path == auction_house_path and self.command == "POST":
            status, payload, _reason = build_owner_listing(
                self.server, self._persona_id(), body)
            return self._send(status, payload, name="auction-house-list")

        if path == auction_house_path and self.command == "GET":
            return self._send(200,
                               build_auction_house(self.server,
                                                   self._persona_id()),
                               name="auction-house")

        if (path == f"/ut/delete/game/{GAME}/trade/sold"
                and self.command == "GET"):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            removed = (state.remove_sold_trades(persona_id)
                       if state is not None else 0)
            emit("fut-transfer-sold-removed", personaId=persona_id,
                 removed=int(removed))
            return self._send(200, b"{}", name="trade-remove-sold")

        offer = re.fullmatch(rf"/ut/game/{GAME}/trade/(\d+)/offer", path)
        if offer and self.command in ("POST", "PUT"):
            return self._send(200,
                              build_offer_result(self.server,
                                                 self._persona_id(),
                                                 int(offer.group(1)), body),
                              name="trade-offer")

        cancel_trade = re.fullmatch(
            rf"/ut/(?:delete/)?game/{GAME}/(?:trade|auctionhouse)/(\d+)", path)
        tunnelled_delete = path.startswith(f"/ut/delete/game/{GAME}/")
        if (cancel_trade and
                (self.command == "DELETE" or
                 (tunnelled_delete and self.command == "GET"))):
            trade_id = int(cancel_trade.group(1))
            if cancel_owner_listing(self.server, self._persona_id(), trade_id):
                return self._send(200, b"", name="transfer-cancel")
            return self._send(404, b"", name="transfer-cancel-missing")

        if path.startswith(f"/ut/game/{GAME}/marketdata/pricelimits"):
            mode = getattr(self.server, "pricelimits_mode", PRICELIMITS_MODE)
            if mode == PRICELIMITS_PROBE:
                return self._send(
                    200,
                    build_price_limits_probe(),
                    name="price-limits-probe")
            if mode == PRICELIMITS_LIVE:
                return self._send(
                    200,
                    build_price_limits(
                        dict(parse_qsl(urlsplit(self.path).query))),
                    name="price-limits")
            return self._send(404, b"", name="price-limits-unimplemented")

        if path.startswith(f"/ut/v2/game/{GAME}/store/transaction"):
            return self._send(200, build_store_transaction(),
                              name="store-transaction")

        if path.startswith(f"/ut/game/{GAME}/store/purchasegroup"):
            return self._send(200, build_store_offers(
                self.server, self._persona_id()), name="store-offers")

        if path == f"/ut/game/{GAME}/purchased/items" and self.command == "POST":
            return self._send(200, build_pack_open(
                self.server, body, self._persona_id()),
                              name="pack-open")

        if path == f"/ut/game/{GAME}/purchased/items" and self.command == "GET":
            return self._send(200, build_purchased_items(
                self.server, self._persona_id()), name="purchased-items")

        if path == f"/ut/game/{GAME}/squad/list":
            return self._send(200, build_local_squad_list(
                self.server, self._persona_id()),
                              name="squad-list")

        delete_squad_prefix = f"/ut/delete/game/{GAME}/squad/"
        if path.startswith(delete_squad_prefix):
            wanted = path[len(delete_squad_prefix):].split("?", 1)[0]
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if wanted.isdigit() and state is not None:
                if state.delete_squad(persona_id, int(wanted)):
                    emit("fut-squad-deleted", squad_id=int(wanted))
            return self._send(200,
                              build_local_squad_list(self.server, persona_id),
                              name="squad-deleted")

        squad_path = f"/ut/game/{GAME}/squad"
        opponent_squad = re.fullmatch(
            re.escape(squad_path) + r"/(\d+)/user/(\d+)", path)
        if opponent_squad is not None and self.command == "GET":
            squad_id = int(opponent_squad.group(1))
            opponent_id = int(opponent_squad.group(2))
            payload = build_opponent_squad(
                self.server, opponent_id, squad_id)
            if payload is None:
                return self._send(
                    404, b"{}", name="opponent-squad-not-found")
            return self._send(
                200,
                payload,
                name="opponent-squad")

        if path == f"{squad_path}/{fut_draft.DRAFT_SQUAD_ID}":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is None:
                return self._send(200, b"{}", name="draft-squad")
            if self.command in ("PUT", "POST"):
                layout = fut_draft.parse_swap_layout(body)
                if layout:
                    fut_draft.apply_swap_layout(state, persona_id, layout)
                fut_draft.absorb_squad_save(state, persona_id, body)
                emit("fut-draft-squad-save", bytes=len(body or b""))
            run = fut_draft.load_run(state, persona_id)
            squad = fut_draft.build_run_squad(run)
            custom = fut_draft.load_custom(state, persona_id)
            if custom:
                squad["custom"] = custom
            return self._send(
                200, json.dumps(squad, separators=(",", ":")).encode("utf-8"),
                name="draft-squad")

        if path == squad_path or (path.startswith(squad_path + "/")
                                  and path[len(squad_path) + 1:].isdigit()):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            tail = path[len(squad_path) + 1:]
            squad_id = int(tail) if tail.isdigit() else LOCAL_SQUAD_ID
            if self.command == "POST" and not tail and state is not None:
                requested = ""
                try:
                    requested = str(json.loads(body or b"{}")
                                    .get("squadName", "") or "")
                except (ValueError, AttributeError):
                    requested = ""
                if not requested and getattr(
                        self.server, "recover_squad_name", False):
                    requested = fut_shim_log.recent_entered_text() or ""
                    if requested:
                        emit("fut-squad-name-recovered", squad_id="new",
                             name=requested)
                squad_id = state.create_squad(persona_id, requested)
                emit("fut-squad-created", squad_id=squad_id, name=requested)
            elif self.command in ("PUT", "POST"):
                saved = parse_saved_squad(body)
                if saved is not None and _is_draft_squad_save(saved):
                    if state is not None:
                        fut_draft.absorb_squad_save(state, persona_id, body)
                    emit("fut-draft-squad-save-misaddressed",
                         squadId=squad_id, slots=len(saved.get("slots", {})))
                    return self._send(200,
                                      build_local_squad(self.server,
                                                        persona_id, squad_id),
                                      name="squad-saved-draft")
                if saved is not None:
                    existing = ((state.load_squad(persona_id, squad_id)
                                 if state is not None else None) or {})
                    merged = dict(existing)
                    merged.update(saved)
                    if state is not None:
                        state.save_squad(persona_id, merged, squad_id)
                        state.set_active_squad(persona_id, squad_id)
                    emit("fut-squad-saved", squad_id=squad_id,
                         slots=len(merged.get("slots", {})))
                try:
                    wanted_name = str(json.loads(body or b"{}")
                                      .get("squadName", "") or "")
                except (ValueError, AttributeError):
                    wanted_name = ""
                if not wanted_name and getattr(
                        self.server, "recover_squad_name", False):
                    recovered = fut_shim_log.recent_entered_text()
                    if recovered:
                        wanted_name = recovered
                        emit("fut-squad-name-recovered", squad_id=squad_id,
                             name=recovered)
                if wanted_name and state is not None:
                    state.rename_squad(persona_id, squad_id, wanted_name)
                    emit("fut-squad-renamed", squad_id=squad_id,
                         name=wanted_name)
            response = (build_squad_save_ack(squad_id)
                        if self.command in ("PUT", "POST")
                        else build_local_squad(self.server, persona_id,
                                               squad_id))
            return self._send(200, response,
                              name=f"squad-{self.command.lower()}")

        if path == f"/ut/game/{GAME}/user/credits":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            balances = state.balances(persona_id) if state is not None else None
            unopened = (state.unopened_pack_count(persona_id)
                        if state is not None else 0)
            return self._send(200, build_user_credits(balances, unopened),
                              name="user-credits")

        if path == f"/ut/game/{GAME}/club":
            query = dict(parse_qsl(urlsplit(self.path).query))
            items = getattr(self.server, "club_items", False)
            size = getattr(self.server, "club_size", LOCAL_CLUB_SQUAD_SIZE)
            state = _ensure_persona(self.server, self._persona_id())
            return self._send(200, build_club_items(query, enabled=items,
                                                    size=size, state=state,
                                                    persona_id=self._persona_id()),
                              name=f"club-search-{query.get('type', 'any')}")

        if path == f"/ut/game/{GAME}/match/reset":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            reset = (state.reset_active_match(persona_id)
                     if state is not None else 0)
            emit("fut-match-reset", personaId=int(persona_id), reset=reset)
            return self._send(200, b"{}", name="match-reset")

        if path == f"/ut/game/{GAME}/user" and self.command == "GET":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            balances = state.balances(persona_id) if state is not None else None
            divisions = (state.season_divisions(persona_id)
                         if state is not None else None)
            return self._send(200, build_user_info(
                persona_id, balances, divisions),
                              name="user-data")

        if path == f"/ut/game/{GAME}/match/keepalive":
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            if state is not None:
                state.touch_active_match(persona_id)
            return self._send(200, b"{}", name="match-keepalive")

        if path == f"/ut/game/{GAME}/match/ready" and self.command == "PUT":
            try:
                ready = json.loads(body or b"{}")
            except (UnicodeDecodeError, ValueError, TypeError):
                ready = {}
            if not isinstance(ready, dict):
                ready = {}
            items = ready.get("items", [])
            emit(
                "fut-match-ready",
                personaId=int(self._persona_id()),
                matchId=ready.get("matchId", 0),
                opponentPersonaId=ready.get("opponentPersonaId", 0),
                items=len(items) if isinstance(items, list) else 0,
            )
            return self._send(200, b"{}", name="match-ready")

        if path == f"/ut/game/{GAME}/match/end" and self.command in ("PUT", "POST"):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            active_match = (state.active_match(persona_id)
                            if state is not None else None)
            is_draft_match = (
                active_match is not None
                and int(active_match.get("squad_id", 0) or 0)
                == fut_draft.DRAFT_SQUAD_ID)
            if state is not None and is_draft_match:
                draft_mode = (
                    fut_draft.MODE_ONLINE
                    if active_match.get("playlist")
                    == MATCH_PLAYLIST_ONLINE_DRAFT
                    else fut_draft.MODE_SINGLE_PLAYER)
                run = fut_draft.load_run(state, persona_id, draft_mode)
                if run["active"] and run["state"] == fut_draft.STATE_READY_FOR_MATCH:
                    try:
                        report = json.loads(body or b"{}")
                    except (ValueError, TypeError):
                        report = {}
                    reason = str((report or {}).get("endReason", "") or "").upper()
                    run = fut_draft.record_match_result(
                        state, persona_id, reason, mode=draft_mode)
                    emit("fut-draft-match-end", endReason=reason or "(none)",
                         mode=draft_mode,
                         result=(fut_seasons.canonical_match_result(reason)
                                 or "NO_CONTEST"),
                         wins=run["wins"], active=run["active"])

        if path == f"/ut/game/{GAME}/match/end" and self.command in ("POST", "PUT"):
            return self._send(
                200, build_match_end(self.server, self._persona_id(), body),
                name="match-end")

        if path == f"/ut/game/{GAME}/match" and self.command in ("POST", "PUT"):
            persona_id = self._persona_id()
            state = _ensure_persona(self.server, persona_id)
            played = 0
            match = None
            if self.command == "POST":
                try:
                    opening = json.loads(body or b"{}")
                except (ValueError, TypeError):
                    opening = {}
                if not isinstance(opening, dict):
                    opening = {}
                try:
                    played = int(opening.get("squadId", 0) or 0)
                except (AttributeError, TypeError, ValueError):
                    played = 0
                if played > 0 and played != fut_draft.DRAFT_SQUAD_ID:
                    if state is not None:
                        state.set_active_squad(persona_id, played)
                if played == fut_draft.DRAFT_SQUAD_ID and state is not None:
                    snapshot = fut_draft.build_run_squad(
                        fut_draft.load_run(state, persona_id))
                else:
                    snapshot = (state.load_squad(persona_id, played or 1)
                                if state is not None else None)
                if state is not None:
                    match = state.start_match(
                        persona_id, opening, squad_snapshot=snapshot)
            else:
                save_pre_match_lineup(self.server, persona_id, body)
                if state is not None:
                    state.touch_active_match(persona_id)
            emit("fut-match", route=("create" if self.command == "POST"
                                     else "update"),
                 personaId=int(persona_id),
                 matchId=str((match or {}).get("match_id", "")),
                 body=(body or b"")[:200].decode("utf-8", "replace"))
            response = (build_match_create(self.server, persona_id,
                                           played or 1, match)
                        if self.command == "POST" else b"{}")
            return self._send(200, response, name="match-create")

        if path == f"/ut/game/{GAME}/user/accountinfo":
            account_mode = getattr(self.server, "account_mode", ACCOUNT_NEW)
            delay_ms = max(0, getattr(self.server, "accountinfo_delay_ms", 0))
            if delay_ms:
                emit("fut-delay", name="accountinfo-probe", milliseconds=delay_ms)
                time.sleep(delay_ms / 1000)
            return self._send(
                200,
                build_account_info(self._claimed_persona_id(), account_mode=account_mode),
                name=f"accountinfo-{account_mode}",
            )

        mode = getattr(self.server, "unhandled_mode", UNHANDLED_NOT_FOUND)
        emit("fut-unhandled", method=self.command,
             path=redacted_fut_path(self.path), mode=mode)
        if mode == UNHANDLED_EMPTY_200:
            return self._send(200, b"{}", name="capture-empty-200")

        sbc_art = re.fullmatch(r"/fut/sbc/gen\d+/.*?/([A-Za-z0-9_]+\.png)", path)
        if sbc_art:
            art = SBC_ART_DIR / sbc_art.group(1)
            if art.parent == SBC_ART_DIR and art.is_file():
                return self._send(200, art.read_bytes(), name="sbc-art",
                                  content_type="image/png")
            emit("sbc-art-missing", image=sbc_art.group(1))

        if path.startswith("/fut/packs/loc/storepackdescriptions"):
            return self._send(200, build_store_pack_locstrings(),
                              name="store-pack-descriptions",
                              content_type="application/xml; charset=utf-8")

        if path.startswith("/ut/"):
            document = build_probe_document(path)
            emit("fut-probe", path=path, keys=probe_key_count(path))
            return self._send(200, document, name="unimplemented-probe")
        return self._send(404, b"", name="capture-not-found")

    do_GET = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch
    do_PATCH = _dispatch
    do_HEAD = _dispatch


class FutCaptureServer(DualProtocolHTTPServer):
    pass
