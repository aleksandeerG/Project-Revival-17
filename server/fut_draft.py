# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import fut_economy

import hashlib
import json
import secrets
from collections import Counter
from pathlib import Path

import fut_cards
import fut_items
import fut_squads

STATE_CAPTAIN = "CAPTAIN_DRAFT"
STATE_FORMATION = "FORMATION_DRAFT"
STATE_MANAGER = "MANAGER_DRAFT"
STATE_PLAYER = "PLAYER_DRAFT"
STATE_COMPLETED = "COMPLETED_DRAFT"
STATE_READY_FOR_MATCH = "READY_FOR_MATCH"
STATE_READY_FOR_REWARDS = "READY_FOR_REWARDS"

STATE_SEQUENCE = (STATE_CAPTAIN, STATE_FORMATION, STATE_MANAGER, STATE_PLAYER,
                  STATE_READY_FOR_MATCH)

DIFFICULTIES = ("BEGINNER", "AMATEUR", "SEMIPRO", "PRO", "WORLDCLASS",
                "LEGENDARY")

MODE_SINGLE_PLAYER = "SINGLE_PLAYER"
MODE_ONLINE = "ONLINE"
MODES = (MODE_SINGLE_PLAYER, MODE_ONLINE)

WIRE_MODE_ONLINE = 0
WIRE_MODE_SINGLE_PLAYER = 1


def mode_from_wire(value: int | str) -> str:
    try:
        wire_mode = int(value)
    except (TypeError, ValueError):
        raise ValueError("unknown draft wire mode: %r" % (value,))
    if wire_mode == WIRE_MODE_ONLINE:
        return MODE_ONLINE
    if wire_mode == WIRE_MODE_SINGLE_PLAYER:
        return MODE_SINGLE_PLAYER
    raise ValueError("unknown draft wire mode: %s" % wire_mode)

ENTRY_COINS = 15_000
ENTRY_DRAFT_TOKENS = 0
ENTRY_POINTS = 0


def entrance_criteria() -> dict:
    return {
        "COINS": ENTRY_COINS,
        "DRAFT_TOKEN": ENTRY_DRAFT_TOKENS,
        "POINTS": ENTRY_POINTS,
    }


DRAFT_SQUAD_ID = 900_001


def draft_squad(persona_id: int, formation: str = "f442") -> dict:
    return fut_squads.build_empty_squad(
        DRAFT_SQUAD_ID, persona_id, DRAFT_SQUAD_NAME, formation,
        fut_squads.SQUAD_TYPE_DRAFT)


def build_state(state: str = STATE_CAPTAIN, games_won: int = 0,
                param1: str = "", param2: str = "0",
                persona_id: int | None = None,
                formation: str = "f442") -> bytes:
    if state not in STATE_SEQUENCE + (STATE_COMPLETED, STATE_READY_FOR_REWARDS):
        raise ValueError(f"not a client draft state: {state!r}")
    if not isinstance(param2, str):
        raise TypeError("stateParam2 is read as a string, then converted")
    document = [{
        "entranceCriteria": entrance_criteria(),
        "gamesWonCurrentMatch": games_won,
        "roundsInfo": [],
        "squadState": state,
        "stateParam1": param1,
        "stateParam2": param2,
    }]
    if persona_id is not None:
        document[0]["squad"] = draft_squad(persona_id, formation)
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_stats(drafts_completed: int = 0, games_won: int = 0,
                games_lost: int = 0, scored: int = 0, conceded: int = 0,
                champion: int = 0) -> bytes:
    document = {
        "draftsCompleted": drafts_completed,
        "draftChampion": champion,
        "gamesWon": games_won,
        "gamesLost": games_lost,
        "scoredGoals": scored,
        "concededGoals": conceded,
        "passAccuracyTotal": 0,
        "bestBuilderScore": 0,
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def build_choices(entries: list, position_id: int = 0, tier: int = 0) -> bytes:
    document = {
        "positionid": position_id,
        "tier": tier,
        "choices": list(entries),
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def choice_entry(item: dict, index: int, formation: str = "") -> dict:
    entry = {
        "index": index,
        "itemData": item,
    }
    if formation:
        entry["formation"] = formation
    return entry


CHOICES_PER_PICK = 5

DRAFT_ITEM_ID_BASE = 900_000_000

SQUAD_TYPE_DRAFT = "DRAFT_SQUAD"
DRAFT_SQUAD_NAME = "Draft Squad"

DRAFT_MIN_RATING = 75


POSITION_ENUM = {
    0: "GK", 1: "SW", 2: "RWB", 3: "RB", 4: "CB", 5: "CB", 6: "CB",
    7: "LB", 8: "LWB", 9: "CDM", 10: "CDM", 11: "CDM", 12: "RM",
    13: "CM", 14: "CM", 15: "CM", 16: "LM", 17: "CAM", 18: "CAM",
    19: "CAM", 20: "CF", 21: "CF", 22: "CF", 23: "RW", 24: "ST",
    25: "ST", 26: "ST", 27: "LW",
}

_SLOTS_FILE = "fifa17_formation_slots.json"
_FORMATION_SLOTS: dict | None = None

_BENCH_POSITIONS = {
    11: ("GK",),
    12: ("RWB", "RB", "CB", "LB", "LWB"),
    13: ("RWB", "RB", "CB", "LB", "LWB"),
    14: ("CDM", "RM", "CM", "LM", "CAM"),
    15: ("CDM", "RM", "CM", "LM", "CAM"),
    16: ("CDM", "RM", "CM", "LM", "CAM", "CF", "RW", "ST", "LW"),
    17: ("CF", "RW", "ST", "LW"),
}

_SLOT_ALTERNATES = {"LWB": ("LWB", "LB"), "RWB": ("RWB", "RB")}

STATE_PICK_DIFFICULTY = "PICK_DIFFICULTY"

STATE_INVALID = "INVALID"

RUN_SEQUENCE = (STATE_PICK_DIFFICULTY, STATE_FORMATION, STATE_CAPTAIN,
                STATE_PLAYER, STATE_READY_FOR_MATCH)

CHOICE_DIFFICULTY = "difficulty"
CHOICE_FORMATION = "formation"
CHOICE_CAPTAIN = "captain"
CHOICE_PLAYER = "player"
CHOICE_MANAGER = "manager"
CHOICE_KINDS = (CHOICE_DIFFICULTY, CHOICE_FORMATION, CHOICE_CAPTAIN,
                CHOICE_PLAYER, CHOICE_MANAGER)

DRAFT_FORMATIONS = ("f442", "f433", "f4231", "f41212", "f352", "f4141",
                    "f451", "f4222", "f532", "f343")
FORMATION_POOL = DRAFT_FORMATIONS
FORMATION_CHOICES = 5

CHOICES_PER_PICK = 5
DRAFT_SQUAD_SLOTS = 23
PLAYER_PICKS = DRAFT_SQUAD_SLOTS - 1

DRAFT_ITEM_ID_BASE = 900_000_000
DRAFT_SQUAD_ITEM_BASE = 910_000_000


def offer_item_id(slot: int, index: int) -> int:
    return DRAFT_ITEM_ID_BASE + int(slot) * 8 + int(index)


def squad_item_id(slot: int) -> int:
    return DRAFT_SQUAD_ITEM_BASE + int(slot)

LEGEND_LEAGUE_ID = 76

DRAFT_MIN_RATING = 75

DRAFT_POOL_DEPTH = 8

RUN_KEY = "draftRun"
RUN_KEY_SINGLE_PLAYER = "draftRun:singlePlayer"
RUN_KEY_ONLINE = "draftRun:online"
CONTEXT_KEY = "draftRun:selectedMode"
_META_STAGE = 100
_META_FORMATION = 101
_META_LAST_POSITION = 102
_META_MODE = 103
_META_DIFFICULTY = 104
_META_ACTIVE = 105
_META_STAR_RATING = 106
_META_CHEMISTRY = 107
_META_MANAGER = 108
_META_AWAITING_MANAGER = 116
_META_NONCE = 109
_META_WINS = 110
_META_LOSSES = 111

DRAFT_ROUNDS = 4

MANAGER_SLOT = 23
MANAGER_ITEM_ID = 920_000_000
MANAGER_CHOICES = 5

CUSTOM_KEY = "draftCustom"
CUSTOM_KEY_SINGLE_PLAYER = "draftCustom:singlePlayer"
CUSTOM_KEY_ONLINE = "draftCustom:online"

OFFER_BASE = 1_000
OFFER_STRIDE = 8
OFFER_CAPTAIN_SLOT = 30


def formation_slots() -> dict:
    global _FORMATION_SLOTS
    if _FORMATION_SLOTS is None:
        path = Path(__file__).resolve().parent / "data" / _SLOTS_FILE
        if path.is_file():
            _FORMATION_SLOTS = {k: tuple(v) for k, v in
                                json.loads(path.read_text(encoding="utf-8")).items()}
        else:
            _FORMATION_SLOTS = {}
    return _FORMATION_SLOTS


def allowed_positions(formation: str, position_id: int) -> tuple:
    try:
        slot = int(position_id)
    except (TypeError, ValueError):
        return ()
    if slot in _BENCH_POSITIONS:
        return _BENCH_POSITIONS[slot]
    if slot > 17:
        return ()
    slots = formation_slots().get(str(formation or "").lower(), ())
    if not 0 <= slot < len(slots):
        return ()
    target = slots[slot]
    return _SLOT_ALTERNATES.get(target, (target,))


def _run_key(mode: str) -> str:
    if mode == MODE_SINGLE_PLAYER:
        return RUN_KEY_SINGLE_PLAYER
    if mode == MODE_ONLINE:
        return RUN_KEY_ONLINE
    raise ValueError("unknown draft mode: %s" % mode)


def _custom_key(mode: str) -> str:
    if mode == MODE_SINGLE_PLAYER:
        return CUSTOM_KEY_SINGLE_PLAYER
    if mode == MODE_ONLINE:
        return CUSTOM_KEY_ONLINE
    raise ValueError("unknown draft mode: %s" % mode)


def select_mode(store, persona_id: int, mode: str) -> str:
    if mode not in MODES:
        raise ValueError("unknown draft mode: %s" % mode)
    store.save_clientdata(
        int(persona_id), CONTEXT_KEY,
        [{"key": 0, "value": 1 if mode == MODE_ONLINE else 0}])
    return mode


def current_mode(store, persona_id: int) -> str:
    for entry in (store.load_clientdata(int(persona_id), CONTEXT_KEY) or []):
        try:
            if int(entry.get("key", -1)) == 0:
                return MODE_ONLINE if int(entry.get("value", 0)) else \
                    MODE_SINGLE_PLAYER
        except (AttributeError, TypeError, ValueError):
            continue
    return MODE_SINGLE_PLAYER


def load_run(store, persona_id: int, mode: str | None = None) -> dict:
    selected = mode or current_mode(store, persona_id)
    if selected not in MODES:
        raise ValueError("unknown draft mode: %s" % selected)
    entries = store.load_clientdata(int(persona_id), _run_key(selected)) or []
    if not entries:
        legacy = store.load_clientdata(int(persona_id), RUN_KEY) or []
        legacy_mode = 0
        for entry in legacy:
            try:
                if int(entry.get("key", -1)) == _META_MODE:
                    legacy_mode = int(entry.get("value", 0))
                    break
            except (AttributeError, TypeError, ValueError):
                continue
        wanted_mode = 1 if selected == MODE_ONLINE else 0
        if legacy and legacy_mode == wanted_mode:
            entries = legacy
    values = {}
    for entry in entries:
        try:
            values[int(entry.get("key", -1))] = int(entry.get("value", 0))
        except (AttributeError, TypeError, ValueError):
            continue
    stage = values.get(_META_STAGE, 0)
    if not 0 <= stage < len(RUN_SEQUENCE):
        stage = 0
    formation = values.get(_META_FORMATION, 0)
    if not 0 <= formation < len(DRAFT_FORMATIONS):
        formation = 0
    active = bool(values.get(_META_ACTIVE, 0))
    return {
        "active": active,
        "state": RUN_SEQUENCE[stage] if active else STATE_INVALID,
        "stateIndex": stage,
        "formation": formation,
        "lastPositionId": values.get(_META_LAST_POSITION, 0),
        "mode": values.get(
            _META_MODE, 1 if selected == MODE_ONLINE else 0),
        "difficulty": values.get(_META_DIFFICULTY, 0),
        "starRating": values.get(_META_STAR_RATING, 0),
        "chemistry": values.get(_META_CHEMISTRY, 0),
        "manager": values.get(_META_MANAGER, 0),
        "awaitingManager": bool(values.get(_META_AWAITING_MANAGER, 0)),
        "nonce": values.get(_META_NONCE, 0),
        "wins": values.get(_META_WINS, 0),
        "losses": values.get(_META_LOSSES, 0),
        "picks": {slot: values[slot] for slot in range(DRAFT_SQUAD_SLOTS)
                  if values.get(slot)},
        "offers": _offers_from(values),
        "personaId": int(persona_id),
    }


def _offers_from(values: dict) -> dict:
    out = {}
    for slot in list(range(DRAFT_SQUAD_SLOTS)) + [OFFER_CAPTAIN_SLOT]:
        base = OFFER_BASE + slot * OFFER_STRIDE
        ids = [values[base + index] for index in range(CHOICES_PER_PICK)
               if values.get(base + index)]
        if ids:
            out[slot] = ids
    return out


def save_run(store, persona_id: int, run: dict) -> None:
    entries = [
        {"key": _META_STAGE, "value": int(run["stateIndex"])},
        {"key": _META_FORMATION, "value": int(run["formation"])},
        {"key": _META_LAST_POSITION, "value": int(run["lastPositionId"])},
        {"key": _META_MODE, "value": int(run["mode"])},
        {"key": _META_DIFFICULTY, "value": int(run.get("difficulty", 0))},
        {"key": _META_ACTIVE, "value": 1 if run.get("active") else 0},
        {"key": _META_STAR_RATING, "value": int(run.get("starRating", 0))},
        {"key": _META_CHEMISTRY, "value": int(run.get("chemistry", 0))},
        {"key": _META_MANAGER, "value": int(run.get("manager", 0))},
        {"key": _META_AWAITING_MANAGER,
         "value": int(bool(run.get("awaitingManager")))},
        {"key": _META_NONCE, "value": int(run.get("nonce", 0))},
        {"key": _META_WINS, "value": int(run.get("wins", 0))},
        {"key": _META_LOSSES, "value": int(run.get("losses", 0))},
    ]
    entries += [{"key": int(slot), "value": int(asset)}
                for slot, asset in sorted(run.get("picks", {}).items())
                if asset]
    for slot, ids in sorted(run.get("offers", {}).items()):
        base = OFFER_BASE + int(slot) * OFFER_STRIDE
        entries += [{"key": base + index, "value": int(resource)}
                    for index, resource in enumerate(ids[:CHOICES_PER_PICK])]
    mode = MODE_ONLINE if int(run.get("mode", 0)) else MODE_SINGLE_PLAYER
    store.save_clientdata(int(persona_id), _run_key(mode), entries)


def reset_run(store, persona_id: int, mode: str = MODE_SINGLE_PLAYER,
              active: bool = True) -> dict:
    select_mode(store, persona_id, mode)
    first_state = (STATE_FORMATION if mode == MODE_ONLINE
                   else STATE_PICK_DIFFICULTY)
    first_index = RUN_SEQUENCE.index(first_state)
    run = {"active": bool(active),
           "state": first_state if active else STATE_INVALID,
           "stateIndex": first_index, "formation": 0,
           "lastPositionId": 0, "mode": 1 if mode == MODE_ONLINE else 0,
           "difficulty": 0, "picks": {}, "offers": {},
           "starRating": 0, "chemistry": 0, "manager": 0,
           "nonce": secrets.randbits(30) or 1,
           "wins": 0, "losses": 0,
           "personaId": int(persona_id)}
    save_run(store, persona_id, run)
    return run


def choose_difficulty(store, persona_id: int, name: str) -> dict:
    run = load_run(store, persona_id)
    if not run["active"]:
        return run
    wanted = str(name or "").strip().upper()
    if wanted in DIFFICULTIES:
        run["difficulty"] = DIFFICULTIES.index(wanted)
    if run["state"] == STATE_PICK_DIFFICULTY:
        run["stateIndex"] = RUN_SEQUENCE.index(STATE_FORMATION)
        run["state"] = STATE_FORMATION
    save_run(store, persona_id, run)
    return run


def parse_difficulty_name(body: bytes | None) -> str:
    try:
        document = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return ""
    if not isinstance(document, dict):
        return ""
    return str(document.get("difficultyName", "") or "")


def record_match(store, persona_id: int, won: bool,
                 mode: str | None = None) -> dict:
    run = load_run(store, persona_id, mode)
    if not run["active"]:
        return run
    if won:
        run["wins"] = min(DRAFT_ROUNDS, int(run.get("wins", 0)) + 1)
    else:
        run["losses"] = int(run.get("losses", 0)) + 1
    finished = (not won) or run["wins"] >= DRAFT_ROUNDS
    if finished:
        run["active"] = False
        run["state"] = STATE_READY_FOR_REWARDS
    save_run(store, persona_id, run)
    return run


def record_match_result(store, persona_id: int, result: str,
                        mode: str | None = None) -> dict:
    value = str(result or "").strip().upper()
    if value in ("WIN", "DNF_WIN", "DNF_DRAW"):
        return record_match(store, persona_id, won=True, mode=mode)
    if value in ("LOSS", "DNF_LOSS", "QUIT", "FORFEIT"):
        return record_match(store, persona_id, won=False, mode=mode)
    return load_run(store, persona_id, mode)


def run_formation(run: dict) -> str:
    index = run.get("formation", 0)
    if not 0 <= index < len(DRAFT_FORMATIONS):
        index = 0
    return DRAFT_FORMATIONS[index]


def advance_run(store, persona_id: int, choice_index: int = 0,
                position_id: int = 0) -> dict:
    run = load_run(store, persona_id)
    if not run["active"]:
        return run
    state = run["state"]
    if state in (STATE_PICK_DIFFICULTY, STATE_FORMATION):
        offered = formation_offer(run)
        index = max(0, min(int(choice_index), len(offered) - 1))
        run["formation"] = DRAFT_FORMATIONS.index(offered[index])
        run["stateIndex"] = RUN_SEQUENCE.index(STATE_CAPTAIN)
        run["picks"] = {}
        run["offers"] = {}
    elif (state == STATE_MANAGER or int(position_id) == MANAGER_SLOT
            or run.get("awaitingManager")):
        run["awaitingManager"] = False
        if MANAGERS_IMPLEMENTED:
            offered = manager_offer(persona_id, run)
            if offered and 0 <= int(choice_index) < len(offered):
                run["manager"] = int(offered[int(choice_index)]["resourceId"])
        run["lastPositionId"] = MANAGER_SLOT
        run["stateIndex"] = RUN_SEQUENCE.index(STATE_READY_FOR_MATCH)
    elif state in (STATE_CAPTAIN, STATE_PLAYER):
        players = offer_for(store, persona_id, run, position_id,
                            captain=(state == STATE_CAPTAIN), remember=False)
        if players and 0 <= int(choice_index) < len(players):
            run["picks"][int(position_id)] = int(
                players[int(choice_index)]["resourceId"])
        run["lastPositionId"] = int(position_id)
        run["stateIndex"] = RUN_SEQUENCE.index(STATE_PLAYER)
        if len(run["picks"]) >= DRAFT_SQUAD_SLOTS:
            run["stateIndex"] = RUN_SEQUENCE.index(STATE_READY_FOR_MATCH)
    run["state"] = RUN_SEQUENCE[run["stateIndex"]]
    save_run(store, persona_id, run)
    return run


def autocomplete_run(store, persona_id: int,
                     mode: str | None = None) -> dict:
    run = load_run(store, persona_id, mode)
    can_fill = (run["state"] == STATE_PLAYER
                or (run["state"] == STATE_READY_FOR_MATCH
                    and len(run["picks"]) < DRAFT_SQUAD_SLOTS))
    if not run["active"] or not can_fill:
        return run

    for slot in range(DRAFT_SQUAD_SLOTS):
        if slot in run["picks"]:
            continue
        rows = offer_for(store, persona_id, run, slot, remember=True)
        if not rows:
            continue
        run["picks"][slot] = int(rows[0]["resourceId"])
        run["lastPositionId"] = slot

    if len(run["picks"]) >= DRAFT_SQUAD_SLOTS:
        run["stateIndex"] = RUN_SEQUENCE.index(STATE_READY_FOR_MATCH)
        run["state"] = STATE_READY_FOR_MATCH
    save_run(store, persona_id, run)
    return run


_POOL_CACHE: list | None = None


def _pool() -> list:
    global _POOL_CACHE
    if _POOL_CACHE is None:
        base = []
        for player in fut_items.load_current_catalogue():
            if player.get("rating", 0) < DRAFT_MIN_RATING:
                continue
            if int(player.get("leagueid", 0) or 0) == LEGEND_LEAGUE_ID:
                continue
            if not player.get("preferredPosition"):
                continue
            row = dict(player)
            row.setdefault("resourceId", int(row["playerid"]))
            base.append(row)
        by_asset = {int(row["playerid"]): row
                    for row in fut_items.load_catalogue()}
        specials = []
        for card in fut_items.active_specials():
            if int(card.get("rating", 0)) < DRAFT_MIN_RATING:
                continue
            player = by_asset.get(int(card.get("assetId", 0)))
            if player is None:
                continue
            if int(player.get("leagueid", 0) or 0) == LEGEND_LEAGUE_ID:
                continue
            row = dict(player)
            row["rating"] = int(card["rating"])
            row["resourceId"] = int(card["resourceId"])
            position = card.get("preferredPosition")
            if not position:
                position = POSITION_ENUM.get(int(row.get("position", -1) or -1))
            if not position:
                continue
            row["preferredPosition"] = position
            row["_special"] = card
            specials.append(row)
        _POOL_CACHE = base + specials
    return _POOL_CACHE


_MANAGERS: list | None = None


def managers() -> list:
    global _MANAGERS
    if _MANAGERS is None:
        cards = fut_cards.load_cards()
        staff = cards.get("staff", []) if isinstance(cards, dict) else []
        _MANAGERS = sorted(
            (row for row in staff if row.get("family") == "manager"),
            key=lambda row: -int(row.get("rating", 0)))
    return _MANAGERS


def manager_offer(persona_id: int, run: dict) -> list:
    pool = managers()
    if not pool:
        return []
    top = pool[:max(MANAGER_CHOICES * DRAFT_POOL_DEPTH, MANAGER_CHOICES)]
    digest = hashlib.sha256(
        "|".join(str(part) for part in
                 (persona_id, run.get("nonce", 0), run.get("formation", 0),
                  run.get("difficulty", 0), "manager")).encode())
    cursor = int.from_bytes(digest.digest()[:8], "big")
    chosen, taken = [], set()
    for step in range(MANAGER_CHOICES):
        index = (cursor + step * 7919) % len(top)
        for probe in range(len(top)):
            candidate = (index + probe) % len(top)
            if candidate not in taken:
                taken.add(candidate)
                chosen.append(top[candidate])
                break
    return chosen


MANAGERS_IMPLEMENTED = True


def expect_manager_choice(store, persona_id: int) -> dict:
    run = load_run(store, persona_id)
    if not run["active"]:
        return run
    run["awaitingManager"] = True
    save_run(store, persona_id, run)
    return run


def build_manager_choices(persona_id: int, run: dict,
                          timestamp: int = 0) -> bytes:
    if not MANAGERS_IMPLEMENTED:
        return build_choices([], position_id=MANAGER_SLOT, tier=0)
    entries = [choice_entry(
        fut_cards.build_card(card, offer_item_id(MANAGER_SLOT, index),
                             timestamp), index)
        for index, card in enumerate(manager_offer(persona_id, run))]
    return build_choices(entries, position_id=MANAGER_SLOT, tier=0)


def run_manager_item(run: dict, timestamp: int = 0) -> dict | None:
    resource = int(run.get("manager", 0) or 0)
    if not resource:
        return None
    for card in managers():
        if int(card.get("resourceId", 0)) == resource:
            return fut_cards.build_card(card, MANAGER_ITEM_ID, timestamp)
    return None


def _card_item(player: dict, item_id: int, timestamp: int) -> dict:
    special = player.get("_special")
    if special is None:
        return fut_items.build_item(player, item_id, timestamp)
    return fut_items.build_special_item(special, player, item_id, timestamp)


def _shares(player: dict, affinity: dict) -> bool:
    return (player.get("leagueid") in affinity.get("leagues", ())
            or player.get("nationid") in affinity.get("nations", ())
            or player.get("teamid") in affinity.get("clubs", ()))


def picked_assets(run: dict, skip_slot: int | None = None) -> set:
    by_resource = _by_resource()
    out = set()
    for slot, resource in run.get("picks", {}).items():
        if skip_slot is not None and int(slot) == int(skip_slot):
            continue
        row = by_resource.get(int(resource))
        if row is not None:
            out.add(int(row.get("playerid", 0)))
    return out


def _by_resource() -> dict:
    return {int(row["resourceId"]): row for row in _pool()}


def squad_affinity(run: dict) -> dict:
    by_resource = _by_resource()
    leagues, nations, clubs = set(), set(), set()
    for asset in run.get("picks", {}).values():
        player = by_resource.get(int(asset))
        if player is None:
            continue
        leagues.add(player.get("leagueid"))
        nations.add(player.get("nationid"))
        clubs.add(player.get("teamid"))
    return {"leagues": leagues, "nations": nations, "clubs": clubs}


def _draw(seed_parts: tuple, count: int, positions: tuple = (),
          affinity: dict | None = None, exclude: set | None = None) -> list:
    pool = _pool()
    if exclude:
        blocked = set(exclude)
        narrowed = [row for row in pool
                    if int(row.get("playerid", 0)) not in blocked]
        pool = narrowed or pool
    if positions:
        wanted = set(positions)
        matching = [row for row in pool
                    if row.get("preferredPosition") in wanted]
        pool = matching or pool
    if not pool:
        return []

    digest = hashlib.sha256("|".join(str(part) for part in seed_parts).encode())
    cursor = int.from_bytes(digest.digest()[:8], "big")

    ranked = sorted(pool, key=lambda row: -int(row.get("rating", 0)))
    top = ranked[:max(count * DRAFT_POOL_DEPTH, count)]

    if affinity and any(affinity.values()):
        linked = [row for row in top if _shares(row, affinity)]
        keep = max(1, (count * 2) // 3)
        if len(linked) >= keep:
            others = [row for row in top if not _shares(row, affinity)]
            top = linked[:keep * 3] + others

    chosen, taken, seen_assets = [], set(), set()
    for step in range(count):
        index = (cursor + step * 7919) % len(top)
        for probe in range(len(top)):
            candidate = (index + probe) % len(top)
            if candidate in taken:
                continue
            asset = int(top[candidate].get("playerid", 0))
            if asset in seen_assets:
                taken.add(candidate)
                continue
            taken.add(candidate)
            seen_assets.add(asset)
            chosen.append(top[candidate])
            break
    return chosen


def parse_swap_layout(body: bytes | None) -> list | None:
    try:
        document = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(document, dict):
        return None
    ids = document.get("swapPlayerDefIds")
    if not isinstance(ids, list) or not ids:
        return None
    out = []
    for value in ids[:DRAFT_SQUAD_SLOTS]:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            out.append(0)
    return out


def apply_swap_layout(store, persona_id: int, layout: list) -> dict:
    run = load_run(store, persona_id)
    if not run["active"] or not layout:
        return run
    held = Counter(int(resource)
                   for resource in run.get("picks", {}).values())
    seated, used = {}, Counter()
    for slot, resource in enumerate(layout):
        resource = int(resource or 0)
        if (not resource or resource not in held
                or used[resource] >= held[resource]):
            continue
        if not 0 <= slot < DRAFT_SQUAD_SLOTS:
            continue
        seated[slot] = resource
        used[resource] += 1
    if not seated:
        return run
    if len(layout) < DRAFT_SQUAD_SLOTS:
        for slot, resource in run.get("picks", {}).items():
            resource = int(resource)
            if used[resource] < held[resource] and int(slot) not in seated:
                seated[int(slot)] = int(resource)
                used[resource] += 1
    lost = len(run.get("picks", {})) - len(seated)
    if lost > 0 and len(seated) < len(run.get("picks", {})) // 2:
        return run
    run["picks"] = seated
    save_run(store, persona_id, run)
    return run


def absorb_squad_save(store, persona_id: int, body: bytes | None) -> dict:
    run = load_run(store, persona_id)
    if not run["active"]:
        return run
    try:
        document = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return run
    if not isinstance(document, dict):
        return run
    changed = False
    for key, field in (("starRating", "starRating"), ("chemistry", "chemistry")):
        try:
            value = int(document.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if value and value != run.get(field):
            run[field] = value
            changed = True
    layout = {}
    for entry in document.get("players") or []:
        if not isinstance(entry, dict):
            continue
        item = entry.get("itemData")
        if not isinstance(item, dict):
            continue
        try:
            slot = int(entry.get("index", -1))
            item_id = int(item.get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        source = item_id - DRAFT_SQUAD_ITEM_BASE
        if 0 <= slot < DRAFT_SQUAD_SLOTS and 0 <= source < DRAFT_SQUAD_SLOTS:
            layout[slot] = source
    if layout:
        picks = run.get("picks", {})
        seated = {}
        for slot, source in sorted(layout.items()):
            resource = picks.get(source)
            if resource and resource not in seated.values():
                seated[slot] = resource
        if seated and len(seated) >= len(picks) // 2:
            if seated != picks:
                run["picks"] = seated
                changed = True

    custom = document.get("custom")
    if isinstance(custom, str) and custom:
        mode = MODE_ONLINE if int(run.get("mode", 0)) else MODE_SINGLE_PLAYER
        store.save_clientdata(int(persona_id), _custom_key(mode),
                              [{"key": index, "value": ord(character)}
                               for index, character in enumerate(custom[:512])])
    if changed:
        save_run(store, persona_id, run)
    return run


def load_custom(store, persona_id: int, mode: str | None = None) -> str:
    selected = mode or current_mode(store, persona_id)
    entries = store.load_clientdata(
        int(persona_id), _custom_key(selected)) or []
    if not entries:
        legacy = store.load_clientdata(int(persona_id), RUN_KEY) or []
        legacy_mode = 0
        for entry in legacy:
            try:
                if int(entry.get("key", -1)) == _META_MODE:
                    legacy_mode = int(entry.get("value", 0))
                    break
            except (AttributeError, TypeError, ValueError):
                continue
        wanted_mode = 1 if selected == MODE_ONLINE else 0
        if legacy and legacy_mode == wanted_mode:
            entries = store.load_clientdata(int(persona_id), CUSTOM_KEY) or []
    out = []
    for entry in sorted(entries, key=lambda e: int(e.get("key", 0))):
        try:
            out.append(chr(int(entry["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return "".join(out)


def parse_position_id(body: bytes | None) -> int:
    try:
        document = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return 0
    if not isinstance(document, dict):
        return 0
    value = document.get("positionId", document.get("positionid", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


CAPTAIN_LINES = (("GK",), ("RB", "CB", "LB"), ("CDM", "CM", "CAM"),
                 ("RM", "LM", "RW", "LW"), ("ST", "CF"))


def _offer(persona_id: int, run: dict, position_id: int,
           captain: bool = False) -> list:
    formation = run_formation(run)
    seed = (persona_id, run.get("nonce", 0), run.get("formation", 0),
            run.get("difficulty", 0),
            "captain" if captain else "player", int(position_id))
    if captain:
        out, taken = [], set(picked_assets(run))
        for index, line in enumerate(CAPTAIN_LINES[:CHOICES_PER_PICK]):
            drawn = _draw(seed + (index,), 1, line, exclude=taken)
            if drawn:
                out.append(drawn[0])
                taken.add(int(drawn[0].get("playerid", 0)))
        return out or _draw(seed, CHOICES_PER_PICK)
    positions = allowed_positions(formation, position_id)
    return _draw(seed, CHOICES_PER_PICK, positions, squad_affinity(run),
                 picked_assets(run))


def offer_for(store, persona_id: int, run: dict, position_id: int,
              captain: bool = False, remember: bool = True) -> list:
    slot = OFFER_CAPTAIN_SLOT if captain else int(position_id)
    stored = run.get("offers", {}).get(slot)
    if stored:
        by_resource = _by_resource()
        rows = [by_resource[resource] for resource in stored
                if resource in by_resource]
        blocked = picked_assets(run)
        kept = [row for row in rows
                if int(row.get("playerid", 0)) not in blocked]
        if len(kept) == len(stored):
            return kept
        if kept:
            taken = {int(row.get("playerid", 0)) for row in kept}
            fresh = _offer(persona_id, run, position_id, captain)
            for row in fresh:
                if len(kept) >= CHOICES_PER_PICK:
                    break
                asset = int(row.get("playerid", 0))
                if asset in taken or asset in blocked:
                    continue
                taken.add(asset)
                kept.append(row)
            if remember and store is not None:
                run.setdefault("offers", {})[slot] = [
                    int(row["resourceId"]) for row in kept]
                save_run(store, persona_id, run)
            return kept
    rows = _offer(persona_id, run, position_id, captain)
    if remember and rows and store is not None:
        run.setdefault("offers", {})[slot] = [int(row["resourceId"])
                                              for row in rows]
        save_run(store, persona_id, run)
    return rows


def build_captain_choices(persona_id: int, run: dict,
                          position_id: int = 0, timestamp: int = 0,
                          store=None) -> bytes:
    players = offer_for(store, persona_id, run, position_id, captain=True)
    entries = [choice_entry(
        _card_item(player, offer_item_id(OFFER_CAPTAIN_SLOT, index), timestamp),
        index) for index, player in enumerate(players)]
    return build_choices(entries, position_id=position_id, tier=0)


def build_player_choices(persona_id: int, run: dict, position_id: int,
                         timestamp: int = 0, store=None) -> bytes:
    players = offer_for(store, persona_id, run, position_id, captain=False)
    entries = [choice_entry(
        _card_item(player, offer_item_id(position_id, index), timestamp),
        index) for index, player in enumerate(players)]
    return build_choices(entries, position_id=position_id, tier=0)


def formation_offer(run: dict) -> tuple:
    pool = list(FORMATION_POOL)
    nonce = int(run.get("nonce", 0) or 0)
    if not nonce:
        return tuple(pool[:FORMATION_CHOICES])
    digest = hashlib.sha256(f"formations|{nonce}".encode()).digest()
    cursor = int.from_bytes(digest[:8], "big")
    chosen = []
    for step in range(min(FORMATION_CHOICES, len(pool))):
        index = (cursor + step * 7919) % len(pool)
        chosen.append(pool.pop(index))
    return tuple(chosen)


def build_formation_choices(run: dict | None = None) -> bytes:
    entries = [{"index": index, "formation": name}
               for index, name in enumerate(formation_offer(run or {}))]
    return build_choices(entries, position_id=0, tier=0)


def build_difficulty_choices() -> bytes:
    entries = [{"choiceIndex": index, "difficulty": index,
                "difficultyName": name}
               for index, name in enumerate(DIFFICULTIES)]
    return build_choices(entries, position_id=0, tier=0)


STARTING_XI = 11


def build_run_squad(run: dict, timestamp: int = 0) -> dict:
    persona_id = run.get("personaId", 0)
    squad = fut_squads.build_empty_squad(
        DRAFT_SQUAD_ID, persona_id, DRAFT_SQUAD_NAME, run_formation(run),
        fut_squads.SQUAD_TYPE_DRAFT)
    by_resource = _by_resource()
    for slot, asset in sorted(run.get("picks", {}).items()):
        player = by_resource.get(int(asset))
        if player is None or not 0 <= slot < len(squad["players"]):
            continue
        squad["players"][slot]["itemData"] = _card_item(
            player, squad_item_id(slot), timestamp)
        squad["players"][slot]["kitNumber"] = slot + 1
    manager = run_manager_item(run, timestamp) if MANAGERS_IMPLEMENTED else None
    squad["manager"] = [manager] if manager else [{"id": 0, "dream": False}]
    if run.get("starRating"):
        squad["starRating"] = int(run["starRating"])
    if run.get("chemistry"):
        squad["chemistry"] = int(run["chemistry"])
    return squad


DRAFT_AWARD_COINS = (2_000, 5_000, 9_000, 15_000, 30_000)

AWARD_TYPE_COINS = 1


def draft_award_coins(wins: int, mode: str = MODE_SINGLE_PLAYER) -> int:
    if mode not in MODES:
        raise ValueError("unknown draft mode: %s" % mode)
    index = max(0, min(int(wins or 0), len(DRAFT_AWARD_COINS) - 1))
    reward_mode = (fut_economy.REWARD_MODE_ONLINE
                   if mode == MODE_ONLINE
                   else fut_economy.REWARD_MODE_OFFLINE)
    return fut_economy.competition_coins(
        DRAFT_AWARD_COINS[index], reward_mode)


def build_award(run: dict) -> bytes:
    if run.get("active", True):
        return b"[]"
    if not (int(run.get("wins", 0)) or int(run.get("losses", 0))):
        return b"[]"
    mode = (MODE_ONLINE if int(run.get("mode", 0)) else MODE_SINGLE_PLAYER)
    coins = draft_award_coins(int(run.get("wins", 0)), mode)
    return json.dumps([{"type": AWARD_TYPE_COINS, "value": int(coins)}],
                      separators=(",", ":")).encode("utf-8")


def build_state_for_run(run: dict) -> bytes:
    state = run["state"]
    played = bool(int(run.get("wins", 0)) or int(run.get("losses", 0)))
    if not run.get("active", True) and not played:
        return json.dumps([{
            "entranceCriteria": entrance_criteria(),
            "gamesWonCurrentMatch": 0,
            "roundsInfo": [],
            "squadState": STATE_INVALID,
            "stateParam1": "INVALID",
            "stateParam2": "0",
        }], separators=(",", ":")).encode("utf-8")
    if not run.get("active", True):
        return json.dumps([{
            "entranceCriteria": entrance_criteria(),
            "gamesWonCurrentMatch": int(run.get("wins", 0)),
            "roundsInfo": [],
            "squadState": STATE_READY_FOR_REWARDS,
            "stateParam1": "INVALID",
            "stateParam2": str(DRAFT_SQUAD_SLOTS),
            "squad": build_run_squad(run),
        }], separators=(",", ":")).encode("utf-8")
    param1 = "PLAYER" if state == STATE_PLAYER else "INVALID"
    if state in (STATE_READY_FOR_MATCH, STATE_READY_FOR_REWARDS,
                 STATE_COMPLETED, STATE_MANAGER):
        param2 = str(DRAFT_SQUAD_SLOTS)
    else:
        param2 = str(int(run.get("lastPositionId", 0)))
    document = [{
        "entranceCriteria": entrance_criteria(),
        "gamesWonCurrentMatch": int(run.get("wins", 0)),
        "roundsInfo": [],
        "squadState": state,
        "stateParam1": param1,
        "stateParam2": param2,
        "squad": build_run_squad(run),
    }]
    return json.dumps(document, separators=(",", ":")).encode("utf-8")
