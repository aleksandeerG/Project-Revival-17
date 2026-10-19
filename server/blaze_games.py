# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import ipaddress
import secrets
import threading
import time

import tdf


GAMEMANAGER_COMPONENT = 0x0004
START_MATCHMAKING_COMMAND = 0x000D
CANCEL_MATCHMAKING_COMMAND = 0x000E
MATCHMAKING_FAILED_NOTIFICATION = 0x000A

MATCHMAKING_RESULT_SUCCESS_CREATED_GAME = 0
MATCHMAKING_RESULT_SUCCESS_JOINED_NEW_GAME = 1
MATCHMAKING_RESULT_SUCCESS_JOINED_EXISTING_GAME = 2
MATCHMAKING_RESULT_SESSION_TIMED_OUT = 3
MATCHMAKING_RESULT_SESSION_CANCELED = 4
MATCHMAKING_RESULT_SESSION_TERMINATED = 5
MATCHMAKING_RESULT_SESSION_ERROR_GAME_SETUP_FAILED = 6
MATCHMAKING_RESULT_SESSION_QOS_VALIDATION_FAILED = 7
MATCHMAKING_RESULT_SUCCESS_PSEUDO_CREATE_GAME = 8

MATCHMAKING_RESULT_NAMES = {
    MATCHMAKING_RESULT_SUCCESS_CREATED_GAME: "SUCCESS_CREATED_GAME",
    MATCHMAKING_RESULT_SUCCESS_JOINED_NEW_GAME: "SUCCESS_JOINED_NEW_GAME",
    MATCHMAKING_RESULT_SUCCESS_JOINED_EXISTING_GAME:
        "SUCCESS_JOINED_EXISTING_GAME",
    MATCHMAKING_RESULT_SESSION_TIMED_OUT: "SESSION_TIMED_OUT",
    MATCHMAKING_RESULT_SESSION_CANCELED: "SESSION_CANCELED",
    MATCHMAKING_RESULT_SESSION_TERMINATED: "SESSION_TERMINATED",
    MATCHMAKING_RESULT_SESSION_ERROR_GAME_SETUP_FAILED:
        "SESSION_ERROR_GAME_SETUP_FAILED",
    MATCHMAKING_RESULT_SESSION_QOS_VALIDATION_FAILED:
        "SESSION_QOS_VALIDATION_FAILED",
    MATCHMAKING_RESULT_SUCCESS_PSEUDO_CREATE_GAME:
        "SUCCESS_PSEUDO_CREATE_GAME",
}

SESSION_DURATION_MICROSECONDS_PER_SECOND = 1_000_000
DEFAULT_SESSION_DURATION_SECONDS = 20.0
MIN_SESSION_DURATION_SECONDS = 1.0
MAX_SESSION_DURATION_SECONDS = 3600.0

EXACT_MATCH_THRESHOLD = "OSDK_matchExact"

_MAX_SESSION_ID = 0x7FFFFFFF

PLAYLIST_ONLINE_SINGLE = "online_single"
PLAYLIST_ONLINE_SEASONS = "online_seasons"
PLAYLIST_ONLINE_DRAFT = "online_draft"
PLAYLIST_UNRESOLVED = "unresolved"
MATCHMAKING_PLAYLISTS = frozenset({
    PLAYLIST_ONLINE_SINGLE, PLAYLIST_ONLINE_SEASONS, PLAYLIST_ONLINE_DRAFT,
})


def _clamp_duration(seconds: float | None) -> float:
    if seconds is None:
        return DEFAULT_SESSION_DURATION_SECONDS
    return min(MAX_SESSION_DURATION_SECONDS,
               max(MIN_SESSION_DURATION_SECONDS, float(seconds)))


@dataclass(frozen=True, slots=True)
class MatchmakingCriteria:

    game_mode_name: str = ""
    total_players: int = 0
    exact_rules: tuple[tuple[str, str], ...] = ()

    def matches(self, other: "MatchmakingCriteria") -> bool:
        return (self.game_mode_name == other.game_mode_name
                and self.total_players == other.total_players
                and self.exact_rules == other.exact_rules)


@dataclass(frozen=True, slots=True)
class MatchmakingSession:

    session_id: int
    persona_id: int
    request_sha256: str
    created_at: float
    source_address: str
    duration_seconds: float = DEFAULT_SESSION_DURATION_SECONDS
    expires_at: float = 0.0
    criteria: MatchmakingCriteria = field(default_factory=MatchmakingCriteria)
    playlist: str = PLAYLIST_UNRESOLVED
    progression: tuple[tuple[str, str], ...] = ()
    game_version: str = ""
    entry_criteria: tuple[tuple[str, str], ...] = ()
    queue_capacity: int = 0
    network: ClientNetworkAddress = field(
        default_factory=lambda: ClientNetworkAddress())


@dataclass(frozen=True, slots=True)
class ClientNetworkAddress:

    internal_ip: str = ""
    internal_port: int = 0
    external_ip: str = ""
    external_port: int = 0

    @property
    def has_internal(self) -> bool:
        return bool(self.internal_ip) and self.internal_port > 0

    @property
    def has_external(self) -> bool:
        return bool(self.external_ip) and self.external_port > 0


@dataclass(frozen=True, slots=True)
class MatchmakingIdentityReference:

    connection_group_id: int
    persona_id: int | None


class MatchmakingService:

    def __init__(self, first_session_id: int | None = None) -> None:
        if first_session_id is None:
            first_session_id = secrets.randbelow(_MAX_SESSION_ID) + 1
        if not 1 <= int(first_session_id) <= _MAX_SESSION_ID:
            raise ValueError("first matchmaking session id must be a positive int32")
        self._next_session_id = int(first_session_id)
        self._by_persona: dict[int, MatchmakingSession] = {}
        self._by_session: dict[int, MatchmakingSession] = {}
        self._lock = threading.Lock()

    def start(
        self,
        persona_id: int,
        request_payload: bytes,
        *,
        source_address: str = "",
        duration_seconds: float | None = None,
        criteria: MatchmakingCriteria | None = None,
        playlist: str = PLAYLIST_UNRESOLVED,
        progression: tuple[tuple[str, str], ...] = (),
        game_version: str = "",
        entry_criteria: tuple[tuple[str, str], ...] = (),
        queue_capacity: int = 0,
        network: "ClientNetworkAddress | None" = None,
        now: float | None = None,
    ) -> tuple[MatchmakingSession, bool]:
        persona_id = int(persona_id)
        if persona_id <= 0:
            raise ValueError("persona id must be positive")
        digest = hashlib.sha256(request_payload).hexdigest()
        moment = time.time() if now is None else float(now)
        duration = _clamp_duration(duration_seconds)
        with self._lock:
            existing = self._by_persona.get(persona_id)
            if existing is not None:
                if source_address and source_address != existing.source_address:
                    existing = replace(existing, source_address=source_address)
                    self._by_persona[persona_id] = existing
                    self._by_session[existing.session_id] = existing
                return existing, False

            session_id = self._allocate_id_locked()
            session = MatchmakingSession(
                session_id=session_id,
                persona_id=persona_id,
                request_sha256=digest,
                created_at=moment,
                source_address=str(source_address),
                duration_seconds=duration,
                expires_at=moment + duration,
                criteria=criteria or MatchmakingCriteria(),
                playlist=(str(playlist) if str(playlist) in
                          MATCHMAKING_PLAYLISTS else PLAYLIST_UNRESOLVED),
                progression=tuple(progression),
                game_version=str(game_version),
                entry_criteria=tuple(entry_criteria),
                queue_capacity=int(queue_capacity),
                network=network or ClientNetworkAddress(),
            )
            self._by_persona[persona_id] = session
            self._by_session[session_id] = session
            return session, True

    def cancel(self, persona_id: int, session_id: int) -> bool:
        return self.cancel_session(persona_id, session_id) is not None

    def cancel_session(
        self,
        persona_id: int,
        session_id: int,
    ) -> MatchmakingSession | None:
        persona_id = int(persona_id)
        session_id = int(session_id)
        if persona_id <= 0 or session_id <= 0:
            return None
        with self._lock:
            session = self._by_persona.get(persona_id)
            if session is None or session.session_id != session_id:
                return None
            self._remove_locked(session)
            return session

    def active_for_persona(self, persona_id: int) -> MatchmakingSession | None:
        with self._lock:
            return self._by_persona.get(int(persona_id))

    def claim_pair(
        self, first: MatchmakingSession, second: MatchmakingSession,
    ) -> tuple[MatchmakingSession, MatchmakingSession] | None:
        with self._lock:
            if (first.persona_id == second.persona_id
                    or self._by_session.get(first.session_id) != first
                    or self._by_session.get(second.session_id) != second):
                return None
            if not self._compatible(first, second):
                return None
            moment = time.time()
            if any(s.expires_at and s.expires_at <= moment
                   for s in (first, second)):
                return None
            self._remove_locked(first)
            self._remove_locked(second)
            return first, second

    def restore_pair(
        self, first: MatchmakingSession, second: MatchmakingSession,
    ) -> tuple[MatchmakingSession, ...]:
        restored = []
        with self._lock:
            for session in (first, second):
                if (session.persona_id in self._by_persona
                        or session.session_id in self._by_session):
                    continue
                self._by_persona[session.persona_id] = session
                self._by_session[session.session_id] = session
                restored.append(session)
        return tuple(restored)

    def active_by_id(self, session_id: int) -> MatchmakingSession | None:
        with self._lock:
            return self._by_session.get(int(session_id))

    def cancel_from_source(
        self,
        source_address: str,
        session_id: int,
    ) -> MatchmakingSession | None:
        session_id = int(session_id)
        if session_id <= 0 or not source_address:
            return None
        with self._lock:
            session = self._by_session.get(session_id)
            if session is None or session.source_address != source_address:
                return None
            self._remove_locked(session)
            return session

    def expire_due(self, now: float | None = None) -> list[MatchmakingSession]:
        moment = time.time() if now is None else float(now)
        with self._lock:
            due = [session for session in self._by_session.values()
                   if session.expires_at and session.expires_at <= moment]
            for session in due:
                self._remove_locked(session)
        return sorted(due, key=lambda session: session.session_id)

    def next_expiry(self) -> float | None:
        with self._lock:
            deadlines = [session.expires_at
                         for session in self._by_session.values()
                         if session.expires_at]
        return min(deadlines) if deadlines else None

    def pair_candidates(
        self,
    ) -> list[tuple[MatchmakingSession, MatchmakingSession]]:
        with self._lock:
            pending = sorted(self._by_session.values(),
                             key=lambda session: (session.created_at,
                                                  session.session_id))
        pairs: list[tuple[MatchmakingSession, MatchmakingSession]] = []
        taken: set[int] = set()
        for index, session in enumerate(pending):
            if session.session_id in taken:
                continue
            for other in pending[index + 1:]:
                if other.session_id in taken:
                    continue
                if other.persona_id == session.persona_id:
                    continue
                if not self._compatible(session, other):
                    continue
                taken.add(session.session_id)
                taken.add(other.session_id)
                pairs.append((session, other))
                break
        return pairs

    @staticmethod
    def _compatible(first: MatchmakingSession,
                    second: MatchmakingSession) -> bool:
        return (first.playlist in MATCHMAKING_PLAYLISTS
                and first.playlist == second.playlist
                and first.criteria.matches(second.criteria))

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_session)

    def _remove_locked(self, session: MatchmakingSession) -> None:
        self._by_session.pop(session.session_id, None)
        if self._by_persona.get(session.persona_id) is session:
            del self._by_persona[session.persona_id]

    def _allocate_id_locked(self) -> int:
        for _ in range(_MAX_SESSION_ID):
            candidate = self._next_session_id
            self._next_session_id = (
                1 if candidate >= _MAX_SESSION_ID else candidate + 1
            )
            if candidate not in self._by_session:
                return candidate
        raise RuntimeError("all matchmaking session ids are in use")


def build_start_matchmaking_response(session_id: int) -> bytes:
    session_id = int(session_id)
    if not 1 <= session_id <= _MAX_SESSION_ID:
        raise ValueError("matchmaking session id must be a positive int32")
    return tdf.u32(b"MSID", session_id)


def build_matchmaking_failed_notification(
    session_id: int,
    persona_id: int,
    result: int = MATCHMAKING_RESULT_SESSION_CANCELED,
) -> bytes:
    session_id = int(session_id)
    persona_id = int(persona_id)
    result = int(result)
    if not 1 <= session_id <= _MAX_SESSION_ID:
        raise ValueError("matchmaking session id must be a positive int32")
    if persona_id <= 0:
        raise ValueError("persona id must be positive")
    if result not in MATCHMAKING_RESULT_NAMES:
        raise ValueError("result must be a recovered MatchmakingResult value")
    return b"".join((
        tdf.u32(b"MAXF", 0),
        tdf.u32(b"MSCD", 0),
        tdf.u32(b"MSID", session_id),
        tdf.u32(b"RSLT", result),
        tdf.u32(b"TOUT", 0),
        tdf.u32(b"TTM", 0),
        tdf.u32(b"USID", persona_id),
    ))


def build_matchmaking_result_notification(
    session_id: int,
    persona_id: int,
    result: int,
    *,
    fit_score: int = 0,
    max_fit_score: int = 0,
    game_entry_type: int = 0,
    time_to_match: int = 0,
) -> bytes:
    session_id = int(session_id)
    persona_id = int(persona_id)
    if not 1 <= session_id <= _MAX_SESSION_ID:
        raise ValueError("matchmaking session id must be a positive int32")
    if persona_id <= 0:
        raise ValueError("persona id must be positive")
    if int(result) not in MATCHMAKING_RESULT_NAMES:
        raise ValueError("result must be a recovered MatchmakingResult value")
    return b"".join((
        tdf.u32(b"FIT", int(fit_score)),
        tdf.u32(b"GENT", int(game_entry_type)),
        tdf.u32(b"MAXF", int(max_fit_score)),
        tdf.u32(b"MSCD", 0),
        tdf.u32(b"MSID", session_id),
        tdf.u32(b"RSLT", int(result)),
        tdf.u32(b"TOUT", 0),
        tdf.u32(b"TTM", int(time_to_match)),
        tdf.u32(b"USID", persona_id),
    ))


def build_matchmaking_finished_notification(
    session_id: int,
    persona_id: int,
    result: int,
    *,
    session_duration_microseconds: int = 0,
    max_fit_score: int = 0,
    scenario_id: int = 0,
) -> bytes:
    session_id = int(session_id)
    persona_id = int(persona_id)
    if not 1 <= session_id <= _MAX_SESSION_ID:
        raise ValueError("matchmaking session id must be a positive int32")
    if persona_id <= 0:
        raise ValueError("persona id must be positive")
    if int(result) not in MATCHMAKING_RESULT_NAMES:
        raise ValueError("result must be a recovered MatchmakingResult value")
    return b"".join((
        tdf.u32(b"DURA", int(session_duration_microseconds)),
        tdf.u32(b"MAXF", int(max_fit_score)),
        tdf.u32(b"MSCD", int(scenario_id)),
        tdf.u32(b"MSID", session_id),
        tdf.u32(b"RSLT", int(result)),
        tdf.u32(b"USID", persona_id),
    ))


def build_matchmaking_cancelled_notification(
    session_id: int,
    persona_id: int,
) -> bytes:
    return build_matchmaking_failed_notification(
        session_id, persona_id, MATCHMAKING_RESULT_SESSION_CANCELED)


def build_matchmaking_timed_out_notification(
    session_id: int,
    persona_id: int,
) -> bytes:
    return build_matchmaking_failed_notification(
        session_id, persona_id, MATCHMAKING_RESULT_SESSION_TIMED_OUT)


def parse_cancel_matchmaking_request(payload: bytes) -> int | None:
    try:
        value = tdf.summarise(tdf.decode(payload)).get("MSID")
        session_id = int(value)
    except (AttributeError, TypeError, ValueError, tdf.TdfError):
        return None
    return session_id if 1 <= session_id <= _MAX_SESSION_ID else None


def parse_start_matchmaking_duration(payload: bytes) -> float | None:
    try:
        document = tdf.summarise(tdf.decode(payload))
    except (AttributeError, TypeError, tdf.TdfError):
        return None
    return session_duration_from_document(document)


def session_duration_from_document(document: object) -> float | None:
    try:
        microseconds = int(document.get("SSDT", {}).get("DUR"))
    except (AttributeError, TypeError, ValueError):
        return None
    if microseconds <= 0:
        return None
    return microseconds / SESSION_DURATION_MICROSECONDS_PER_SECOND


def parse_start_matchmaking_creation_data(payload: bytes) -> dict:
    try:
        document = tdf.summarise(tdf.decode(payload))
        creation = document.get("GMCD", {})
    except (AttributeError, TypeError, tdf.TdfError):
        return {}
    criteria = []
    for key, value in _map_pairs(creation.get("CRIT")):
        criteria.append((str(key), str(value)))
    out = {"entry_criteria": tuple(criteria)}
    for tag, name in (("QCAP", "queue_capacity"), ("GSET", "game_settings"),
                      ("NTOP", "network_topology"), ("PRES", "presence_mode"),
                      ("VOIP", "voip_topology"), ("GMRG", "game_mod_register")):
        try:
            out[name] = int(creation[tag])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def parse_start_matchmaking_game_version(payload: bytes) -> str:
    try:
        document = tdf.summarise(tdf.decode(payload))
        return str(document.get("CMGD", {}).get("GVER", "") or "")
    except (AttributeError, TypeError, tdf.TdfError):
        return ""


def _ip_address(node: object) -> tuple[str, int]:
    if not isinstance(node, dict):
        return "", 0
    try:
        address = int(node.get("IP", 0))
        port = int(node.get("PORT", 0))
    except (TypeError, ValueError):
        return "", 0
    if address <= 0 or not 0 < port <= 0xFFFF:
        return "", 0
    try:
        return str(ipaddress.IPv4Address(address)), port
    except (ipaddress.AddressValueError, ValueError):
        return "", 0


def parse_start_matchmaking_network_address(
    payload: bytes,
) -> ClientNetworkAddress:
    try:
        document = tdf.summarise(tdf.decode(payload))
        union = document.get("CMGD", {}).get("PNET", {})
        field_node = union.get("field") if isinstance(union, dict) else None
        value = (field_node or {}).get("VALU") if isinstance(field_node, dict) else None
    except (AttributeError, TypeError, tdf.TdfError):
        return ClientNetworkAddress()
    if not isinstance(value, dict):
        return ClientNetworkAddress()
    internal_ip, internal_port = _ip_address(value.get("INIP"))
    external_ip, external_port = _ip_address(value.get("EXIP"))
    return ClientNetworkAddress(
        internal_ip=internal_ip, internal_port=internal_port,
        external_ip=external_ip, external_port=external_port)


def _map_pairs(node: object) -> list[tuple[object, object]]:
    if not isinstance(node, dict):
        return []
    values = node.get("values")
    if not isinstance(values, list):
        return []
    return [(entry[0], entry[1]) for entry in values
            if isinstance(entry, (list, tuple)) and len(entry) == 2]


def _rule_fields(rule: object) -> dict[str, object]:
    if not isinstance(rule, list):
        return {}
    fields: dict[str, object] = {}
    for entry in rule:
        if isinstance(entry, dict) and "tag" in entry:
            fields[str(entry["tag"])] = entry.get("value")
    return fields


def _rule_scalar(value: object) -> str | None:
    if isinstance(value, dict):
        values = value.get("values")
        if isinstance(values, list) and len(values) == 1:
            return str(values[0])
        return None
    if isinstance(value, (str, int)):
        return str(value)
    return None


def parse_start_matchmaking_criteria(payload: bytes) -> MatchmakingCriteria:
    try:
        document = tdf.summarise(tdf.decode(payload))
    except (AttributeError, TypeError, tdf.TdfError):
        return MatchmakingCriteria()
    return criteria_from_document(document)


def criteria_from_document(document: object) -> MatchmakingCriteria:
    if not isinstance(document, dict):
        return MatchmakingCriteria()

    game_mode_name = ""
    for key, value in _map_pairs(document.get("GMCD", {}).get("ATTR")):
        if str(key) == "Gamemode_Name":
            game_mode_name = str(value)
            break

    try:
        total_players = int(
            document.get("CRD", {}).get("TOTS", {}).get("MAXS", 0))
    except (AttributeError, TypeError, ValueError):
        total_players = 0

    exact_rules: list[tuple[str, str]] = []
    for key, rule in _map_pairs(document.get("CRD", {}).get("GARC")):
        fields = _rule_fields(rule)
        if str(fields.get("THLD", "")) != EXACT_MATCH_THRESHOLD:
            continue
        scalar = _rule_scalar(fields.get("VALU"))
        if scalar is None:
            continue
        exact_rules.append((str(key), scalar))

    return MatchmakingCriteria(
        game_mode_name=game_mode_name,
        total_players=total_players,
        exact_rules=tuple(sorted(exact_rules)),
    )


def parse_start_matchmaking_identity(
    payload: bytes,
) -> MatchmakingIdentityReference | None:
    try:
        document = tdf.summarise(tdf.decode(payload))
        player_join = document.get("PLJD", {})
        group = player_join.get("BTPL", {})
        if (int(group.get("component")) != 0x7802
                or int(group.get("entityType")) != 2):
            return None
        group_id = int(group.get("entityId"))
        if group_id <= 0:
            return None

        persona_ids: set[int] = set()
        players = player_join.get("PLDL", {}).get("values", [])
        for fields in players:
            player = tdf.summarise(fields)
            user = player.get("USID", {})
            persona_id = int(user.get("ID", 0))
            if persona_id > 0:
                persona_ids.add(persona_id)
        if len(persona_ids) > 1:
            return None
        persona_id = next(iter(persona_ids)) if persona_ids else None
        return MatchmakingIdentityReference(group_id, persona_id)
    except (AttributeError, TypeError, ValueError, tdf.TdfError):
        return None
