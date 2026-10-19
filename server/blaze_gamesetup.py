# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import secrets
import threading

import tdf


GAME_STATE_NEW_STATE = 0
GAME_STATE_INITIALIZING = 1
GAME_STATE_INACTIVE_VIRTUAL = 2
GAME_STATE_CONNECTION_VERIFICATION = 3
GAME_STATE_PRE_GAME = 130
GAME_STATE_IN_GAME = 131
GAME_STATE_POST_GAME = 4
GAME_STATE_MIGRATING = 5
GAME_STATE_DESTRUCTING = 6
GAME_STATE_RESETABLE = 7
GAME_STATE_UNRESPONSIVE = 9
GAME_STATE_GAME_GROUP_INITIALIZED = 16

GAME_STATE_NAMES = {
    GAME_STATE_NEW_STATE: "NEW_STATE",
    GAME_STATE_INITIALIZING: "INITIALIZING",
    GAME_STATE_INACTIVE_VIRTUAL: "INACTIVE_VIRTUAL",
    GAME_STATE_CONNECTION_VERIFICATION: "CONNECTION_VERIFICATION",
    GAME_STATE_PRE_GAME: "PRE_GAME",
    GAME_STATE_IN_GAME: "IN_GAME",
    GAME_STATE_POST_GAME: "POST_GAME",
    GAME_STATE_MIGRATING: "MIGRATING",
    GAME_STATE_DESTRUCTING: "DESTRUCTING",
    GAME_STATE_RESETABLE: "RESETABLE",
    GAME_STATE_UNRESPONSIVE: "UNRESPONSIVE",
    GAME_STATE_GAME_GROUP_INITIALIZED: "GAME_GROUP_INITIALIZED",
}

TOPOLOGY_CLIENT_SERVER_PEER_HOSTED = 0
TOPOLOGY_CLIENT_SERVER_DEDICATED = 1
TOPOLOGY_PEER_TO_PEER_FULL_MESH = 130
TOPOLOGY_PEER_TO_PEER_PARTIAL_MESH = 131
TOPOLOGY_NETWORK_DISABLED = 255

PLAYER_STATE_RESERVED = 0
PLAYER_STATE_QUEUED = 1
PLAYER_STATE_ACTIVE_CONNECTING = 2
PLAYER_STATE_ACTIVE_MIGRATING = 3
PLAYER_STATE_ACTIVE_CONNECTED = 4
PLAYER_STATE_ACTIVE_KICK_PENDING = 5

PLAYER_STATE_NAMES = {
    PLAYER_STATE_RESERVED: "RESERVED",
    PLAYER_STATE_QUEUED: "QUEUED",
    PLAYER_STATE_ACTIVE_CONNECTING: "ACTIVE_CONNECTING",
    PLAYER_STATE_ACTIVE_MIGRATING: "ACTIVE_MIGRATING",
    PLAYER_STATE_ACTIVE_CONNECTED: "ACTIVE_CONNECTED",
    PLAYER_STATE_ACTIVE_KICK_PENDING: "ACTIVE_KICK_PENDING",
}

SLOT_PUBLIC_PARTICIPANT = 0
SLOT_PRIVATE_PARTICIPANT = 1

JOIN_BY_MATCHMAKING = 2

GAME_ENTRY_TYPE_DIRECT = 0

GAME_SETUP_NOTIFICATION = 20
JOINING_PLAYER_INITIATE_CONNECTIONS_NOTIFICATION = 22

ADVANCE_GAME_STATE_COMMAND = 0x0003
SET_PLAYER_ATTRIBUTES_COMMAND = 0x0008
FINALIZE_GAME_CREATION_COMMAND = 0x000F
REMOVE_PLAYER_COMMAND = 0x0016
MESH_ENDPOINTS_CONNECTED_COMMAND = 0x0041
MESH_ENDPOINTS_CONNECTION_LOST_COMMAND = 0x0043

PLAYER_REMOVED_NOTIFICATION = 0x0028

VOIP_PEER_TO_PEER = 2
PRESENCE_MODE_STANDARD = 1

USER_SESSIONS_COMPONENT = 0x7802
CONNECTION_GROUP_ENTITY_TYPE = 2

CONN_DISCONNECTED = 0
CONN_ESTABLISHING_CONNECTION = 1
CONN_CONNECTED = 2

SETUP_REASON_DATALESS = 0
SETUP_REASON_RESET_DEDICATED_SERVER = 1
SETUP_REASON_INDIRECT_JOIN_GAME = 2
SETUP_REASON_MATCHMAKING = 3
SETUP_REASON_INDIRECT_MATCHMAKING = 4


def _address_value(ip: str, port: int) -> bytes:
    return (tdf.u32(b"IP", int(ipaddress.IPv4Address(ip)))
            + tdf.u32(b"MACI", 0)
            + tdf.u16(b"PORT", int(port)))


def network_address_value(
    internal_ip: str,
    internal_port: int,
    external_ip: str | None = None,
    external_port: int | None = None,
) -> bytes:
    external_ip = external_ip or internal_ip
    external_port = internal_port if external_port is None else external_port
    return bytes([2]) + tdf.group(
        b"VALU",
        tdf.group(b"EXIP", _address_value(external_ip, external_port))
        + tdf.group(b"INIP", _address_value(internal_ip, internal_port))
        + tdf.u32(b"MACI", 0),
    )


def build_network_address_list(tag: bytes, addresses) -> bytes:
    values = list(addresses)
    return (tdf.encode_tag(tag, tdf.LIST)
            + bytes([tdf.TAGGED_UNION])
            + tdf.encode_varint(len(values))
            + b"".join(values))


def build_network_address(
    internal_ip: str,
    internal_port: int,
    external_ip: str | None = None,
    external_port: int | None = None,
) -> bytes:
    external_ip = external_ip or internal_ip
    external_port = internal_port if external_port is None else external_port
    return tdf.union(b"PNET", 2, tdf.group(
        b"VALU",
        tdf.group(b"EXIP", _address_value(external_ip, external_port))
        + tdf.group(b"INIP", _address_value(internal_ip, internal_port))
        + tdf.u32(b"MACI", 0),
    ))


@dataclass(frozen=True, slots=True)
class GamePlayer:

    persona_id: int
    display_name: str
    connection_group_id: int
    internal_ip: str
    internal_port: int
    slot_id: int
    team_index: int
    external_ip: str | None = None
    external_port: int | None = None
    locale: int = 0x656E5553
    state: int = PLAYER_STATE_ACTIVE_CONNECTING
    joined_at: int = 0


@dataclass(frozen=True, slots=True)
class GameSession:

    game_id: int
    host_persona_id: int
    players: tuple[GamePlayer, ...]
    game_mode_name: str
    game_settings: int
    game_type: int = 0
    network_topology: int = TOPOLOGY_PEER_TO_PEER_FULL_MESH
    voip_topology: int = VOIP_PEER_TO_PEER
    presence_mode: int = PRESENCE_MODE_STANDARD
    state: int = GAME_STATE_INITIALIZING
    protocol_version: str = ""
    attributes: tuple[tuple[str, str], ...] = ()
    entry_criteria: tuple[tuple[str, str], ...] = ()
    queue_capacity: int = 0
    created_at: float = 0.0

    def host(self) -> GamePlayer:
        for player in self.players:
            if player.persona_id == self.host_persona_id:
                return player
        raise ValueError("game session has no host among its players")

    def opponent_of(self, persona_id: int) -> GamePlayer | None:
        for player in self.players:
            if player.persona_id != persona_id:
                return player
        return None


def build_replicated_game_player(player: GamePlayer, game_id: int) -> bytes:
    return (
        tdf.u32(b"CONG", player.connection_group_id)
        + tdf.u32(b"CSID", player.slot_id)
        + tdf.u32(b"EXID", player.persona_id)
        + tdf.u32(b"GID", game_id)
        + tdf.u32(b"JVMM", 1)
        + tdf.u32(b"LOC", player.locale)
        + tdf.string(b"NAME", player.display_name)
        + tdf.string(b"NASP", "cem_ea_id")
        + tdf.u32(b"PID", player.persona_id)
        + build_network_address(
            player.internal_ip, player.internal_port,
            player.external_ip, player.external_port)
        + tdf.string(b"ROLE", "")
        + tdf.u32(b"SID", player.slot_id)
        + tdf.u32(b"SLOT", SLOT_PUBLIC_PARTICIPANT)
        + tdf.u32(b"STAT", player.state)
        + tdf.u32(b"TIDX", player.team_index)
        + tdf.u32(b"TIME", player.joined_at)
        + tdf.object_id(b"UGID", USER_SESSIONS_COMPONENT,
                        CONNECTION_GROUP_ENTITY_TYPE,
                        player.connection_group_id)
        + tdf.u32(b"UID", player.persona_id)
    )


def build_replicated_game_data(game: GameSession) -> bytes:
    host = game.host()
    host_info = (
        tdf.u32(b"CONG", host.connection_group_id)
        + tdf.u32(b"CSID", host.slot_id)
        + tdf.u32(b"HPID", host.persona_id)
        + tdf.u32(b"HSES", host.persona_id)
        + tdf.u32(b"HSLT", host.slot_id)
    )
    return (
        tdf.list_u32(b"ADMN", [host.persona_id])
        + tdf.map_strings(b"ATTR", list(game.attributes))
        + tdf.list_u32(b"CAP", [len(game.players), 0, 0, 0])
        + tdf.map_strings(b"CRIT", list(game.entry_criteria))
        + tdf.u32(b"GGTY", game.game_type)
        + tdf.u32(b"GID", game.game_id)
        + tdf.u32(b"GMRG", 0)
        + tdf.string(b"GNAM", game.game_mode_name)
        + tdf.u32(b"GSET", game.game_settings)
        + tdf.u32(b"GSTA", game.state)
        + tdf.string(b"GTYP", "")
        + tdf.string(b"GURL", "")
        + build_network_address_list(b"HNET", (
            network_address_value(
                host.internal_ip, host.internal_port,
                host.external_ip, host.external_port),))
        + tdf.u32(b"MCAP", len(game.players))
        + tdf.u32(b"MNCP", len(game.players))
        + tdf.u32(b"NTOP", game.network_topology)
        + tdf.group(b"PHST", host_info)
        + tdf.u32(b"PRES", game.presence_mode)
        + tdf.string(b"PSAS", "")
        + tdf.u32(b"QCAP", game.queue_capacity)
        + tdf.group(b"RNFO", b"")
        + tdf.group(b"THST", host_info)
        + tdf.list_u32(b"TIDS", sorted({p.team_index for p in game.players}))
        + tdf.u32(b"VOIP", game.voip_topology)
        + tdf.string(b"VSTR", game.protocol_version)
    )


def build_game_setup_notification(
    game: GameSession,
    matchmaking_session_id: int,
    persona_id: int,
    *,
    setup_reason: int = SETUP_REASON_MATCHMAKING,
    matchmaking_result: int = 0,
    qos_telemetry_interval: int = 0,
    qos_duration_ms: int = 5000,
    qos_interval_ms: int = 1000,
    qos_packet_size: int = 1200,
) -> bytes:
    context = (
        tdf.u32(b"FIT", 0)
        + tdf.u32(b"GENT", GAME_ENTRY_TYPE_DIRECT)
        + tdf.u32(b"MAXF", 0)
        + tdf.u32(b"MSCD", 0)
        + tdf.u32(b"MSID", int(matchmaking_session_id))
        + tdf.u32(b"RSLT", int(matchmaking_result))
        + tdf.u32(b"TOUT", 0)
        + tdf.u32(b"TTM", 0)
        + tdf.u32(b"USID", int(persona_id))
    )
    return (
        tdf.group(b"GAME", build_replicated_game_data(game))
        + tdf.u32(b"LFPJ", 0)
        + tdf.string(b"MNAM", "")
        + tdf.list_groups(b"PROS", tuple(
            build_replicated_game_player(player, game.game_id)
            for player in game.players))
        + tdf.group(b"QOSS",
                    tdf.u32(b"DURA", qos_duration_ms)
                    + tdf.u32(b"INTV", qos_interval_ms)
                    + tdf.u32(b"SIZE", qos_packet_size))
        + tdf.u32(b"QOSV", 0)
        + tdf.empty_list(b"QUEU", tdf.GROUP)
        + tdf.union(b"REAS", setup_reason, tdf.group(
            b"MMSC" if setup_reason == SETUP_REASON_MATCHMAKING else b"VALU",
            context))
        + tdf.u32(b"TELM", int(qos_telemetry_interval))
    )


def build_game_state_change_notification(game_id: int, state: int) -> bytes:
    if state not in GAME_STATE_NAMES:
        raise ValueError("state must be a recovered GameState value")
    return tdf.u32(b"GID", int(game_id)) + tdf.u32(b"GSTA", int(state))


def build_player_attrib_notification(
    game_id: int, persona_id: int, attributes: tuple[tuple[str, str], ...],
) -> bytes:
    return (tdf.map_strings(b"ATTR", list(attributes))
            + tdf.u32(b"GID", int(game_id))
            + tdf.u32(b"PID", int(persona_id)))


def parse_set_player_attributes_request(
    payload: bytes,
) -> tuple[int, int, tuple[tuple[str, str], ...]] | None:
    document = _document(payload)
    if document is None:
        return None
    game_id = _positive(document, "GID")
    persona_id = _positive(document, "PID")
    if game_id is None or persona_id is None:
        return None
    node = document.get("ATTR")
    values = node.get("values") if isinstance(node, dict) else None
    if not isinstance(values, list):
        return None
    attributes = tuple(
        (str(entry[0]), str(entry[1])) for entry in values
        if isinstance(entry, (list, tuple)) and len(entry) == 2)
    return game_id, persona_id, attributes


def build_player_join_completed_notification(
    game_id: int, persona_id: int, joined_at: int = 0,
) -> bytes:
    return (tdf.u32(b"GID", int(game_id))
            + tdf.u32(b"PID", int(persona_id))
            + tdf.u32(b"TIME", int(joined_at)))


def build_game_player_state_notification(
    game_id: int, persona_id: int, state: int,
) -> bytes:
    if state not in PLAYER_STATE_NAMES:
        raise ValueError("state must be a recovered PlayerState value")
    return (tdf.u32(b"GID", int(game_id))
            + tdf.u32(b"PID", int(persona_id))
            + tdf.u32(b"STAT", int(state)))


def build_player_removed_notification(
    game_id: int,
    persona_id: int,
    reason: int,
    *,
    title_context: int = 0,
    locked_for_preferred_joins: bool = False,
) -> bytes:
    return (
        tdf.u32(b"CNTX", int(title_context))
        + tdf.u32(b"GID", int(game_id))
        + tdf.boolean(b"LFPJ", bool(locked_for_preferred_joins))
        + tdf.u32(b"PID", int(persona_id))
        + tdf.u32(b"REAS", int(reason))
    )


def build_player_joining_notification(
    game_id: int,
    player: GamePlayer,
    *,
    validate_qos: bool = False,
) -> bytes:
    return (
        tdf.u32(b"GID", int(game_id))
        + tdf.group(b"PDAT", build_replicated_game_player(player, game_id))
        + tdf.u32(b"QOST", 1 if validate_qos else 0)
    )


def _document(payload: bytes) -> dict | None:
    try:
        return tdf.summarise(tdf.decode(payload))
    except tdf.TdfError:
        return None


def _positive(document: dict, tag: str) -> int | None:
    value = document.get(tag)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


@dataclass(frozen=True, slots=True)
class MeshConnectionRequest:

    game_id: int
    target_connection_group_id: int
    flags: int = 0
    latency_ms: int = 0
    packet_loss: float = 0.0


@dataclass(frozen=True, slots=True)
class RemovePlayerRequest:

    game_id: int
    player_id: int
    connection_group_id: int
    reason: int
    title_context: int = 0
    title_context_string: str = ""


def parse_remove_player_request(payload: bytes) -> RemovePlayerRequest | None:
    document = _document(payload)
    if document is None:
        return None
    game_id = _positive(document, "GID")
    player_id = _positive(document, "PID")
    group = document.get("BTPL")
    context = document.get("CNTX")
    reason = document.get("REAS")
    context_string = document.get("SCTX")
    if (game_id is None or player_id is None
            or not isinstance(group, dict)
            or group.get("component") != USER_SESSIONS_COMPONENT
            or group.get("entityType") != CONNECTION_GROUP_ENTITY_TYPE):
        return None
    connection_group_id = group.get("entityId")
    if (not isinstance(connection_group_id, int)
            or isinstance(connection_group_id, bool)
            or connection_group_id <= 0
            or not isinstance(context, int) or isinstance(context, bool)
            or context < 0
            or not isinstance(reason, int) or isinstance(reason, bool)
            or reason < 0
            or not isinstance(context_string, str)):
        return None
    return RemovePlayerRequest(
        game_id=game_id,
        player_id=player_id,
        connection_group_id=connection_group_id,
        reason=reason,
        title_context=context,
        title_context_string=context_string,
    )


def parse_mesh_connection_request(payload: bytes) -> MeshConnectionRequest | None:
    document = _document(payload)
    if document is None:
        return None
    game_id = _positive(document, "GID")
    target = document.get("TCG")
    if game_id is None or not isinstance(target, dict):
        return None
    entity_id = target.get("entityId")
    if (target.get("component") != USER_SESSIONS_COMPONENT
            or target.get("entityType") != CONNECTION_GROUP_ENTITY_TYPE
            or not isinstance(entity_id, int) or entity_id <= 0):
        return None
    qos = document.get("QOSI")
    latency = loss = 0
    if isinstance(qos, dict):
        latency = qos.get("PING", 0)
        loss = qos.get("LOSS", 0.0)
    flags = document.get("FLGS", 0)
    return MeshConnectionRequest(
        game_id=game_id,
        target_connection_group_id=entity_id,
        flags=flags if isinstance(flags, int) else 0,
        latency_ms=latency if isinstance(latency, int) else 0,
        packet_loss=float(loss) if isinstance(loss, (int, float)) else 0.0,
    )


def parse_advance_game_state_request(payload: bytes) -> tuple[int, int] | None:
    document = _document(payload)
    if document is None:
        return None
    game_id = _positive(document, "GID")
    state = document.get("GSTA")
    if game_id is None or not isinstance(state, int) or isinstance(state, bool):
        return None
    if state not in GAME_STATE_NAMES:
        return None
    return game_id, state


def parse_finalize_game_creation_request(payload: bytes) -> tuple[int, str] | None:
    document = _document(payload)
    if document is None:
        return None
    game_id = _positive(document, "GID")
    np_session_id = document.get("NPSI", "")
    if game_id is None or not isinstance(np_session_id, str):
        return None
    return game_id, np_session_id


@dataclass(frozen=True, slots=True)
class MeshLink:

    target_connection_group_id: int
    connected: bool
    flags: int = 0
    latency_ms: int = 0
    packet_loss: float = 0.0
    updated_at: float = 0.0


@dataclass
class GameParticipant:

    persona_id: int
    connection_group_id: int
    source_address: str = ""
    np_session_id: str = ""
    links: dict[int, MeshLink] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)

    def connected_targets(self) -> tuple[int, ...]:
        return tuple(sorted(target for target, link in self.links.items()
                            if link.connected))


@dataclass(frozen=True, slots=True)
class StateTransition:

    game_id: int
    persona_id: int
    previous_state: int
    state: int

    @property
    def changed(self) -> bool:
        return self.previous_state != self.state


MAX_GAME_ID = 0x7FFFFFFF


def _random_game_id() -> int:
    return secrets.randbelow(MAX_GAME_ID) + 1


@dataclass
class GameRegistry:

    _next_game_id: int = field(default_factory=lambda: _random_game_id())
    _games: dict[int, GameSession] = field(default_factory=dict)
    _states: dict[int, int] = field(default_factory=dict)
    _participants: dict[int, dict[int, GameParticipant]] = field(
        default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False)

    @classmethod
    def starting_at(cls, first_game_id: int) -> "GameRegistry":
        if not 1 <= int(first_game_id) <= MAX_GAME_ID:
            raise ValueError("a game id must be a positive int32")
        return cls(_next_game_id=int(first_game_id))

    def create(
        self,
        players: tuple[GamePlayer, ...],
        *,
        host_persona_id: int,
        game_mode_name: str,
        game_settings: int,
        created_at: float = 0.0,
        attributes: tuple[tuple[str, str], ...] = (),
        protocol_version: str = "",
        entry_criteria: tuple[tuple[str, str], ...] = (),
        queue_capacity: int = 0,
        routing_addresses: dict[int, str] | None = None,
    ) -> GameSession:
        if len(players) < 2:
            raise ValueError("a head-to-head game needs two players")
        routes = routing_addresses or {}
        with self._lock:
            game_id = self._next_game_id
            self._next_game_id = (
                1 if game_id >= MAX_GAME_ID else game_id + 1)
            game = GameSession(
                game_id=game_id,
                host_persona_id=int(host_persona_id),
                players=tuple(players),
                game_mode_name=game_mode_name,
                game_settings=int(game_settings),
                created_at=created_at,
                attributes=tuple(attributes),
                protocol_version=str(protocol_version),
                entry_criteria=tuple(entry_criteria),
                queue_capacity=int(queue_capacity),
            )
            game.host()
            self._games[game_id] = game
            self._states[game_id] = game.state
            self._participants[game_id] = {
                player.persona_id: GameParticipant(
                    persona_id=player.persona_id,
                    connection_group_id=player.connection_group_id,
                    source_address=str(routes.get(player.persona_id, "")))
                for player in game.players
            }
            return game

    def get(self, game_id: int) -> GameSession | None:
        with self._lock:
            return self._games.get(int(game_id))

    def __len__(self) -> int:
        with self._lock:
            return len(self._games)

    def game_for(self, game_id: int, persona_id: int) -> GameSession | None:
        with self._lock:
            game = self._games.get(int(game_id))
            if game is None:
                return None
            if int(persona_id) not in self._participants.get(int(game_id), {}):
                return None
            return game

    def participant(
        self, game_id: int, persona_id: int,
    ) -> GameParticipant | None:
        with self._lock:
            return self._participants.get(int(game_id), {}).get(int(persona_id))

    def participants(self, game_id: int) -> tuple[GameParticipant, ...]:
        with self._lock:
            return tuple(sorted(
                self._participants.get(int(game_id), {}).values(),
                key=lambda participant: participant.persona_id))

    def state(self, game_id: int) -> int | None:
        with self._lock:
            return self._states.get(int(game_id))

    def games_for_persona(self, persona_id: int) -> tuple[int, ...]:
        persona_id = int(persona_id)
        with self._lock:
            return tuple(sorted(
                game_id for game_id, members in self._participants.items()
                if persona_id in members))

    def advance_state(
        self, game_id: int, persona_id: int, state: int,
    ) -> StateTransition | None:
        with self._lock:
            game = self.game_for(game_id, persona_id)
            if game is None or int(state) not in GAME_STATE_NAMES:
                return None
            game_id = int(game_id)
            previous = self._states.get(game_id, game.state)
            self._states[game_id] = int(state)
            return StateTransition(
                game_id=game_id, persona_id=int(persona_id),
                previous_state=previous, state=int(state))

    def set_np_session(
        self, game_id: int, persona_id: int, np_session_id: str,
    ) -> bool | None:
        with self._lock:
            if self.game_for(game_id, persona_id) is None:
                return None
            participant = self.participant(game_id, persona_id)
            if participant is None:
                return None
            changed = participant.np_session_id != str(np_session_id)
            participant.np_session_id = str(np_session_id)
            return changed

    def record_mesh_link(
        self,
        persona_id: int,
        request: MeshConnectionRequest,
        *,
        connected: bool,
        now: float = 0.0,
    ) -> MeshLink | None:
        with self._lock:
            if self.game_for(request.game_id, persona_id) is None:
                return None
            participant = self.participant(request.game_id, persona_id)
            if participant is None:
                return None
            link = MeshLink(
                target_connection_group_id=request.target_connection_group_id,
                connected=bool(connected),
                flags=request.flags,
                latency_ms=request.latency_ms,
                packet_loss=request.packet_loss,
                updated_at=float(now),
            )
            participant.links[request.target_connection_group_id] = link
            return link

    def mesh_complete(self, game_id: int, persona_id: int) -> bool:
        with self._lock:
            participant = self.participant(game_id, persona_id)
            if participant is None:
                return False
            others = {other.connection_group_id
                      for other in self.participants(game_id)
                      if other.persona_id != int(persona_id)}
            if not others:
                return False
            return all(group in participant.links
                       and participant.links[group].connected
                       for group in others)

    def set_player_attributes(
        self, game_id: int, persona_id: int,
        attributes: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...] | None:
        with self._lock:
            if self.game_for(game_id, persona_id) is None:
                return None
            participant = self.participant(game_id, persona_id)
            if participant is None:
                return None
            participant.attributes.update(
                {str(k): str(v) for k, v in attributes})
            return tuple(sorted(participant.attributes.items()))

    def players_with_request(self, game_id: int) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(
                p.persona_id for p in self.participants(game_id)
                if p.attributes.get("REQ")))

    def players_with_attributes(self, game_id: int) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(
                p.persona_id for p in self.participants(game_id)
                if p.attributes))

    def discard(self, game_id: int) -> tuple[int, ...] | None:
        game_id = int(game_id)
        with self._lock:
            game = self._games.pop(game_id, None)
            if game is None:
                return None
            members = self._participants.pop(game_id, {})
            self._states.pop(game_id, None)
            return tuple(sorted(members))

    def remove_participant(
        self, game_id: int, persona_id: int,
    ) -> tuple[int, ...] | None:
        game_id = int(game_id)
        with self._lock:
            members = self._participants.get(game_id)
            if members is None or int(persona_id) not in members:
                return None
            del members[int(persona_id)]
            remaining = tuple(sorted(members))
            if not remaining:
                self._participants.pop(game_id, None)
                self._states.pop(game_id, None)
                self._games.pop(game_id, None)
            return remaining

    def remove_persona(
        self, persona_id: int,
    ) -> tuple[tuple[int, tuple[int, ...]], ...]:
        removed = []
        with self._lock:
            for game_id in self.games_for_persona(persona_id):
                remaining = self.remove_participant(game_id, persona_id)
                if remaining is not None:
                    removed.append((game_id, remaining))
        return tuple(removed)
