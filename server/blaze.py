# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import socket
import socketserver
import ssl
import threading
import time
from typing import Any

import access
import fire2
import tdf
from blaze_auth import (
    BlazeSessionRegistry,
    build_login_response,
    build_user_added,
    build_user_authenticated,
    build_user_extended_data_update,
    identity_from_code,
    parse_login_code,
)
from blaze_bootstrap import (
    CLIENT_CONFIGS,
    COMPONENT_SETS,
    DEFAULT_COMPONENT_SET,
    DEFAULT_SERVER_VERSIONING,
    FUT_DIRECT_BOOT_VALUES,
    SERVER_VERSIONING_MODES,
    build_fetch_config_response,
    build_ping_response,
    build_postauth_response,
    build_preauth_response,
    server_versioning_values,
)
from blaze_census import (
    CENSUS_COMPONENT,
    SERVER_CENSUS_NOTIFICATION,
    SUBSCRIBE_UPDATES_COMMAND,
    build_server_census_notification,
    build_subscribe_updates_response,
)
from blaze_frontend import (
    DEFAULT_ENTITLEMENT_TYPE_MODE,
    ENTITLEMENT_TYPE_MODES,
    build_frontend_response,
)
from blaze_gamesetup import (
    ADVANCE_GAME_STATE_COMMAND,
    FINALIZE_GAME_CREATION_COMMAND,
    GAME_ENTRY_TYPE_DIRECT,
    GAME_STATE_NAMES,
    MESH_ENDPOINTS_CONNECTED_COMMAND,
    SET_PLAYER_ATTRIBUTES_COMMAND,
    MESH_ENDPOINTS_CONNECTION_LOST_COMMAND,
    GAME_STATE_IN_GAME,
    PLAYER_STATE_ACTIVE_CONNECTED,
    PLAYER_REMOVED_NOTIFICATION,
    REMOVE_PLAYER_COMMAND,
    build_game_player_state_notification,
    build_game_state_change_notification,
    build_player_attrib_notification,
    build_player_join_completed_notification,
    build_player_removed_notification,
    GAME_SETUP_NOTIFICATION,
    GamePlayer,
    GameRegistry,
    build_game_setup_notification,
    parse_advance_game_state_request,
    parse_finalize_game_creation_request,
    parse_mesh_connection_request,
    parse_remove_player_request,
    parse_set_player_attributes_request,
)
from blaze_games import (
    CANCEL_MATCHMAKING_COMMAND,
    GAMEMANAGER_COMPONENT,
    MATCHMAKING_FAILED_NOTIFICATION,
    MATCHMAKING_RESULT_NAMES,
    MATCHMAKING_RESULT_SESSION_CANCELED,
    MATCHMAKING_RESULT_SESSION_TIMED_OUT,
    MATCHMAKING_RESULT_SUCCESS_CREATED_GAME,
    MATCHMAKING_RESULT_SUCCESS_JOINED_NEW_GAME,
    MATCHMAKING_RESULT_SUCCESS_CREATED_GAME,
    START_MATCHMAKING_COMMAND,
    PLAYLIST_ONLINE_DRAFT,
    PLAYLIST_ONLINE_SEASONS,
    PLAYLIST_UNRESOLVED,
    MatchmakingService,
    build_matchmaking_failed_notification,
    build_matchmaking_finished_notification,
    build_matchmaking_result_notification,
    build_start_matchmaking_response,
    parse_cancel_matchmaking_request,
    parse_start_matchmaking_criteria,
    parse_start_matchmaking_duration,
    parse_start_matchmaking_creation_data,
    parse_start_matchmaking_game_version,
    parse_start_matchmaking_identity,
    parse_start_matchmaking_network_address,
)
from events import emit

REPLY_NONE = "none"
REPLY_EMPTY = "empty"
REPLY_BOOTSTRAP = "bootstrap"
REPLY_MODES = (REPLY_NONE, REPLY_EMPTY, REPLY_BOOTSTRAP)

UTIL_COMPONENT = 0x0009
PREAUTH_COMMAND = 0x0007
PING_COMMAND = 0x0002
FETCH_CONFIG_COMMAND = 0x0001
POSTAUTH_COMMAND = 0x0008
IDLE_POLL_SECONDS = 30.0

UNDECODED_PAYLOAD_LOG_LIMIT = 8192

MAX_BLAZE_CONNECTIONS = 64

MATCHMAKING_TICK_SECONDS = 0.25

MESH_TELEMETRY_COMMAND = 171
MESH_TELEMETRY_LOG_SECONDS = 10.0

GAME_STATE_CHANGE_NOTIFICATION = 100

PLAYER_ATTRIB_CHANGE_NOTIFICATION = 90

GAME_LIFECYCLE_COMMANDS = (
    ADVANCE_GAME_STATE_COMMAND,
    SET_PLAYER_ATTRIBUTES_COMMAND,
    FINALIZE_GAME_CREATION_COMMAND,
    MESH_ENDPOINTS_CONNECTED_COMMAND,
    MESH_ENDPOINTS_CONNECTION_LOST_COMMAND,
)

GAMEMANAGER_SWEEP_SETTLE_SECONDS = 6.0
GAMEMANAGER_SWEEP_DEFAULT_DELAY = 8.0
GAMEMANAGER_SETUP_SETTLE_SECONDS = 6.0

GAMEREPORTING_COMPONENT = 0x001C
SUBMIT_GAME_REPORT = 0x0001
SUBMIT_OFFLINE_GAME_REPORT = 0x0002
GAME_REPORTING_RESULT_NOTIFICATION = 0x0072

AUTH_COMPONENT = 0x0001
LOGIN_COMMAND = 0x000A

LOGOUT_COMMAND = 0x0046
AUTH70_EMPTY = "empty"
AUTH70_ERROR = "error"
AUTH70_SILENT = "silent"
AUTH70_MODES = (AUTH70_EMPTY, AUTH70_ERROR, AUTH70_SILENT)
USER_SESSIONS_COMPONENT = 0x7802
USER_AUTHENTICATED_NOTIFICATION = 0x0008
USER_ADDED_NOTIFICATION = 0x0002
USER_EXTENDED_DATA_NOTIFICATION = 0x0001


DISPATCHED_NOTIFICATION_IDS = frozenset(
    (3,) + tuple(range(10, 17)) + tuple(range(20, 26))
    + (30, 40, 41, 60, 70, 71, 80, 90, 95, 100)
    + tuple(range(110, 126)) + (135, 201, 202, 230)
)


def parse_sweep_ids(text: str) -> tuple[int, ...]:
    if not text.strip():
        return ()
    ids = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        value = int(piece, 0)
        if value not in DISPATCHED_NOTIFICATION_IDS:
            raise ValueError(
                f"GameManager notification {value} has no dispatcher case; "
                f"sweepable ids are {sorted(DISPATCHED_NOTIFICATION_IDS)}")
        if value not in ids:
            ids.append(value)
    return tuple(ids)


def build_game_report_result(report_id: int) -> bytes:
    report_id = max(0, int(report_id))
    return (tdf.u32(b"EROR", 0)
            + tdf.u32(b"FNL", 1)
            + tdf.u32(b"GHID", report_id)
            + tdf.u32(b"GRID", report_id))


def redact_filter_user_text(decoded: Any) -> dict[str, Any]:
    listing = decoded.get("TLST") if isinstance(decoded, dict) else None
    count = len(listing.get("values", [])) if isinstance(listing, dict) else 0
    return {"TLST": {
        "elementType": listing.get("elementType")
                       if isinstance(listing, dict) else None,
        "count": count,
        "values": ["<redacted>"] * count,
    }}

def _preauth_body(handler, _header, _payload):
    components = getattr(handler.server, "preauth_components", DEFAULT_COMPONENT_SET)
    return build_preauth_response(qoss="empty", components=components), {
        "components": components,
    }


def _ping_body(_handler, _header, _payload):
    return build_ping_response()


def _fetch_config_body(handler, _header, payload):
    config_id = ""
    try:
        document = tdf.summarise(tdf.decode(payload))
        config_id = str(document.get("CFID", "") or "")
    except tdf.TdfError:
        pass
    mode = getattr(handler.server, "server_versioning", DEFAULT_SERVER_VERSIONING)
    extra = server_versioning_values(mode, getattr(handler, "client_version", ""))
    if config_id == "OSDK_CLIENT" and getattr(handler.server, "fut_direct_boot", False):
        extra = extra + FUT_DIRECT_BOOT_VALUES
    return build_fetch_config_response(config_id, extra=extra), {
        "configId": config_id,
        "knownConfig": config_id in CLIENT_CONFIGS,
        "serverVersioning": mode,
        "serverVersioningKeys": [key for key, _ in extra],
    }


HANDLERS = {
    (UTIL_COMPONENT, PREAUTH_COMMAND): ("preauth", _preauth_body),
    (UTIL_COMPONENT, PING_COMMAND): ("ping", _ping_body),
    (UTIL_COMPONENT, FETCH_CONFIG_COMMAND): ("fetch-client-config", _fetch_config_body),
}


def _paired_player(
    identity: Any,
    search: Any,
    *,
    slot_id: int,
    team_index: int,
) -> tuple[GamePlayer, dict[str, Any]]:
    network = search.network
    internal_ip = (network.internal_ip if network.has_internal
                   else search.source_address)
    internal_port = network.internal_port if network.has_internal else 3659
    if network.has_external:
        external_ip, external_port = network.external_ip, network.external_port
        external_source = "client"
    else:
        external_ip, external_port = search.source_address, internal_port
        external_source = "blaze-tcp-source"
    player = GamePlayer(
        persona_id=identity.persona_id,
        display_name=identity.display_name,
        connection_group_id=identity.connection_group_id,
        internal_ip=internal_ip, internal_port=internal_port,
        external_ip=external_ip, external_port=external_port,
        slot_id=slot_id, team_index=team_index, locale=identity.locale)
    addressing = {
        "internal": f"{internal_ip}:{internal_port}",
        "internalSource": "client" if network.has_internal else "blaze-tcp-source",
        "external": f"{external_ip}:{external_port}",
        "externalSource": external_source,
    }
    return player, addressing


class NotificationRouter:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: list[Any] = []
        self._source_personas: dict[str, set[int]] = {}

    def register(self, connection: Any) -> None:
        with self._lock:
            self._connections.append(connection)

    def unregister(self, connection: Any) -> None:
        with self._lock:
            try:
                self._connections.remove(connection)
            except ValueError:
                pass

    def bind(self, connection: Any, identity: Any) -> None:
        source_address = str(connection.client_address[0])
        with self._lock:
            self._source_personas.setdefault(source_address, set()).add(
                int(identity.persona_id))

    def source_is_unambiguous(self, source_address: str, persona_id: int) -> bool:
        if not source_address:
            return False
        with self._lock:
            return self._source_personas.get(source_address) == {int(persona_id)}

    def candidates(self, persona_id: int, source_address: str) -> list[Any]:
        with self._lock:
            live = list(self._connections)
        owned = [c for c in live
                 if getattr(c, "auth_identity", None) is not None
                 and c.auth_identity.persona_id == persona_id]
        shared = []
        if self.source_is_unambiguous(source_address, persona_id):
            shared = [c for c in live
                      if getattr(c, "auth_identity", None) is None
                      and c.client_address[0] == source_address]
        return list(reversed(owned)) + list(reversed(shared))

    def deliver(
        self,
        component: int,
        command: int,
        body: bytes,
        *,
        persona_id: int,
        source_address: str,
    ) -> str | None:
        frame = fire2.build_notification(component, command, body)
        for connection in self.candidates(persona_id, source_address):
            if connection.send_raw(frame):
                return f"{connection.client_address[0]}:{connection.client_address[1]}"
            self.unregister(connection)
        return None


class BlazeCaptureHandler(socketserver.BaseRequestHandler):
    def setup(self) -> None:
        self.send_lock = threading.Lock()
        self.auth_identity = None
        super().setup()

    def send_frame(self, data: bytes) -> None:
        with self.send_lock:
            self.request.sendall(data)

    def send_raw(self, data: bytes) -> bool:
        try:
            self.send_frame(data)
        except (OSError, ssl.SSLError, ValueError):
            return False
        return True

    def handle(self) -> None:
        server: Any = self.server
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        emit("blaze-connected", port=server.server_address[1], peer=peer,
             reply_mode=server.reply_mode)

        self.request.settimeout(IDLE_POLL_SECONDS)
        self.client_locale = 0x656E5553
        self.client_version = ""
        self.auth_identity = None
        self.mesh_frame_logged = False
        frames = 0
        idle_periods = 0
        server.notifications.register(self)
        try:
            while True:
                try:
                    header, payload, raw = fire2.receive_frame(self.request)
                except fire2.Fire2Error as error:
                    emit("blaze-frame-rejected", peer=peer, error=str(error),
                         frames=frames)
                    break
                except fire2.Fire2Idle:
                    idle_periods += 1
                    if idle_periods == 1 or idle_periods % 10 == 0:
                        emit("blaze-quiet", peer=peer, frames=frames,
                             seconds=int(idle_periods * IDLE_POLL_SECONDS))
                    continue
                except fire2.Fire2Error as error:
                    emit("blaze-framing-error", peer=peer, error=str(error), frame_index=frames + 1)
                    break
                if not raw:
                    break
                frames += 1

                if header is None:
                    emit("blaze-short-read", peer=peer, raw_hex=raw.hex(), frame_index=frames)
                    break

                decoded: Any = None
                decode_error: str | None = None
                if payload:
                    try:
                        decoded = tdf.summarise(tdf.decode(payload))
                    except tdf.TdfError as error:
                        decode_error = str(error)

                if header.component == UTIL_COMPONENT and header.command == PREAUTH_COMMAND:
                    try:
                        client_info = (decoded or {}).get("CINF", {})
                        self.client_locale = int(client_info.get("LOC", self.client_locale))
                        self.client_version = str(client_info.get("CVER", "") or "")
                    except (AttributeError, TypeError, ValueError):
                        pass

                logged_decoded = decoded
                logged_payload_hex = (
                    payload[:UNDECODED_PAYLOAD_LOG_LIMIT].hex()
                    if decode_error else "")
                if (
                    header.component == AUTH_COMPONENT
                    and header.command == LOGIN_COMMAND
                ):
                    logged_payload_hex = ""
                    if isinstance(decoded, dict):
                        logged_decoded = dict(decoded)
                        auth = logged_decoded.get("AUTH")
                        logged_decoded["AUTH"] = (
                            f"<redacted:{len(auth)} chars>"
                            if isinstance(auth, str) else "<redacted>"
                        )
                elif header.component == UTIL_COMPONENT and header.command == 20:
                    logged_payload_hex = ""
                    logged_decoded = redact_filter_user_text(decoded)

                suppress_frame = (
                    header.component == GAMEMANAGER_COMPONENT
                    and header.command == MESH_TELEMETRY_COMMAND
                    and self.mesh_frame_logged
                )
                if (header.component == GAMEMANAGER_COMPONENT
                        and header.command == MESH_TELEMETRY_COMMAND):
                    self.mesh_frame_logged = True

                if not suppress_frame:
                    emit(
                        "blaze-frame",
                        peer=peer,
                        direction="in",
                        frame_index=frames,
                        **header.as_dict(),
                        header_hex=raw[:16].hex(),
                        decoded=logged_decoded,
                        decode_error=decode_error,
                        payload_hex=logged_payload_hex,
                    )

                if header.component == GAMEMANAGER_COMPONENT:
                    identity = self.auth_identity
                    server.note_gamemanager_frame(
                        header.command,
                        peer,
                        persona_id=(identity.persona_id
                                    if identity is not None else None),
                        source_address=self.client_address[0],
                    )
                self._respond(header, payload, peer)
        except (OSError, ssl.SSLError) as error:
            emit("blaze-io-error", peer=peer, error=str(error), frames=frames)
        finally:
            server.notifications.unregister(self)
            self._release_games(peer, "the persona has no live Blaze connection")
            emit("blaze-disconnected", peer=peer, frames=frames)

    def _release_games(self, peer: str, reason: str) -> None:
        server: Any = self.server
        identity = self.auth_identity
        if identity is None:
            return
        if server.notifications.candidates(
                identity.persona_id, self.client_address[0]):
            return
        for game_id, remaining in server.games.remove_persona(
                identity.persona_id):
            emit("game-participant-removed", peer=peer,
                 personaId=identity.persona_id, gameId=game_id,
                 remainingPersonaIds=list(remaining), reason=reason)

    def _game_request_identity(self, game_id: int) -> Any:
        identity = self.auth_identity
        if identity is not None:
            return identity
        server: Any = self.server
        source = self.client_address[0]
        owners = [participant
                  for participant in server.games.participants(game_id)
                  if participant.source_address
                  and participant.source_address == source]
        if len(owners) != 1:
            return None
        return server.blaze_sessions.resolve_persona(owners[0].persona_id)

    def _reject_game_request(
        self, header: "fire2.Fire2Header", peer: str, reason: str,
    ) -> None:
        self.send_frame(fire2.build_error(header, tdf.u32(b"ERRC", 1)))
        emit("game-lifecycle-rejected", peer=peer,
             component=header.component, command=header.command,
             reason=reason)

    def _notify_game_participants(
        self,
        game_id: int,
        command: int,
        body: bytes,
        *,
        name: str,
        **fields: Any,
    ) -> list[int]:
        server: Any = self.server
        delivered: list[int] = []
        for participant in server.games.participants(game_id):
            peer = server.notifications.deliver(
                GAMEMANAGER_COMPONENT, command, body,
                persona_id=participant.persona_id,
                source_address=participant.source_address)
            if peer is not None:
                delivered.append(participant.persona_id)
            emit("blaze-notification", peer=peer or "", name=name,
                 component=GAMEMANAGER_COMPONENT, command=command,
                 bytes=len(body), personaId=participant.persona_id,
                 gameId=game_id, delivered=peer is not None, **fields)
        return delivered

    def _respond_game_lifecycle(
        self, header: "fire2.Fire2Header", payload: bytes, peer: str,
    ) -> None:
        server: Any = self.server
        command = header.command
        if command == ADVANCE_GAME_STATE_COMMAND:
            parsed = parse_advance_game_state_request(payload)
            if parsed is None:
                self._reject_game_request(
                    header, peer, "unreadable advance-game-state request")
                return
            game_id, state = parsed
            identity = self._game_request_identity(game_id)
            if identity is None:
                self._reject_game_request(
                    header, peer, "no identity owns this game from here")
                return
            transition = server.games.advance_state(
                game_id, identity.persona_id, state)
            if transition is None:
                self._reject_game_request(
                    header, peer, "persona is not in the requested game")
                return
            self.send_frame(fire2.build_reply(header, b""))
            emit("blaze-reply", peer=peer,
                 name="game-manager-advance-game-state",
                 component=header.component,
                 componentName=header.component_name, command=command, bytes=0,
                 personaId=identity.persona_id, gameId=game_id,
                 previousState=GAME_STATE_NAMES.get(
                     transition.previous_state, transition.previous_state),
                 gameState=GAME_STATE_NAMES.get(state, state),
                 changed=transition.changed)
            if transition.changed:
                body = build_game_state_change_notification(game_id, state)
                self._notify_game_participants(
                    game_id, GAME_STATE_CHANGE_NOTIFICATION, body,
                    name="game-manager-game-state-change",
                    gameState=GAME_STATE_NAMES.get(state, state))
            return

        if command == FINALIZE_GAME_CREATION_COMMAND:
            parsed = parse_finalize_game_creation_request(payload)
            if parsed is None:
                self._reject_game_request(
                    header, peer, "unreadable finalize-game-creation request")
                return
            game_id, np_session_id = parsed
            identity = self._game_request_identity(game_id)
            if identity is None:
                self._reject_game_request(
                    header, peer, "no identity owns this game from here")
                return
            changed = server.games.set_np_session(
                game_id, identity.persona_id, np_session_id)
            if changed is None:
                self._reject_game_request(
                    header, peer, "persona is not in the requested game")
                return
            self.send_frame(fire2.build_reply(header, b""))
            emit("blaze-reply", peer=peer,
                 name="game-manager-finalize-game-creation",
                 component=header.component,
                 componentName=header.component_name, command=command, bytes=0,
                 personaId=identity.persona_id, gameId=game_id,
                 npSessionId=np_session_id, changed=changed)
            return

        if command == SET_PLAYER_ATTRIBUTES_COMMAND:
            parsed = parse_set_player_attributes_request(payload)
            if parsed is None:
                self._reject_game_request(
                    header, peer, "unreadable set-player-attributes request")
                return
            game_id, subject_id, attributes = parsed
            identity = self._game_request_identity(game_id)
            if identity is None:
                self._reject_game_request(
                    header, peer, "no identity owns this game from here")
                return
            if subject_id != identity.persona_id:
                self._reject_game_request(
                    header, peer, "a player may only set its own attributes")
                return
            merged = server.games.set_player_attributes(
                game_id, identity.persona_id, attributes)
            if merged is None:
                self._reject_game_request(
                    header, peer, "persona is not in the requested game")
                return
            self.send_frame(fire2.build_reply(header, b""))
            emit("blaze-reply", peer=peer,
                 name="game-manager-set-player-attributes",
                 component=header.component,
                 componentName=header.component_name, command=command, bytes=0,
                 personaId=identity.persona_id, gameId=game_id,
                 attributes=dict(attributes), merged=dict(merged),
                 announcedBy=list(
                     server.games.players_with_attributes(game_id)))
            server.announce_player_attributes(
                game_id, identity.persona_id, merged, self)
            return

        connected = command == MESH_ENDPOINTS_CONNECTED_COMMAND
        request = parse_mesh_connection_request(payload)
        if request is None:
            self._reject_game_request(
                header, peer, "unreadable mesh-connection request")
            return
        identity = self._game_request_identity(request.game_id)
        if identity is None:
            self._reject_game_request(
                header, peer, "no identity owns this game from here")
            return
        link = server.games.record_mesh_link(
            identity.persona_id, request, connected=connected,
            now=time.time())
        if link is None:
            self._reject_game_request(
                header, peer, "persona is not in the requested game")
            return
        self.send_frame(fire2.build_reply(header, b""))
        participant = server.games.participant(
            request.game_id, identity.persona_id)
        emit("blaze-reply", peer=peer,
             name=("game-manager-mesh-endpoints-connected" if connected
                   else "game-manager-mesh-endpoints-connection-lost"),
             component=header.component, componentName=header.component_name,
             command=command, bytes=0, personaId=identity.persona_id,
             gameId=request.game_id,
             targetConnectionGroupId=request.target_connection_group_id,
             targetIsSelf=(participant is not None
                           and participant.connection_group_id
                           == request.target_connection_group_id),
             connected=connected, flags=request.flags,
             latencyMs=request.latency_ms, packetLoss=request.packet_loss)

        if not (connected and server.games.mesh_complete(
                request.game_id, identity.persona_id)):
            return
        if server.player_state_notification:
            body = build_game_player_state_notification(
                request.game_id, identity.persona_id,
                PLAYER_STATE_ACTIVE_CONNECTED)
            self._notify_game_participants(
                request.game_id, server.player_state_notification, body,
                name="game-manager-player-state-change",
                joinedPersonaId=identity.persona_id,
                playerState="ACTIVE_CONNECTED")
        if server.player_join_completed_notification:
            body = build_player_join_completed_notification(
                request.game_id, identity.persona_id, int(time.time()))
            self._notify_game_participants(
                request.game_id, server.player_join_completed_notification,
                body, name="game-manager-player-join-completed",
                joinedPersonaId=identity.persona_id)
        server.start_player_state_sweep(request.game_id)
        return

    def _respond_remove_player(
        self, header: "fire2.Fire2Header", payload: bytes, peer: str,
    ) -> None:
        server: Any = self.server
        request = parse_remove_player_request(payload)
        if request is None:
            self._reject_game_request(
                header, peer, "unreadable remove-player request")
            return

        identity = self.auth_identity
        if identity is None:
            identity = server.blaze_sessions.resolve(
                request.connection_group_id)
        if (identity is None
                or identity.persona_id != request.player_id
                or identity.connection_group_id
                != request.connection_group_id):
            self._reject_game_request(
                header, peer,
                "remove-player identity does not match its connection group")
            return

        remaining = server.games.remove_participant(
            request.game_id, request.player_id)
        self.send_frame(fire2.build_reply(header, b""))
        emit("blaze-reply", peer=peer,
             name="game-manager-remove-player",
             component=header.component,
             componentName=header.component_name,
             command=header.command, bytes=0,
             personaId=request.player_id,
             connectionGroupId=request.connection_group_id,
             gameId=request.game_id,
             playerRemovedReason=request.reason,
             playerRemovedTitleContext=request.title_context,
             titleContextString=request.title_context_string,
             removed=remaining is not None,
             remainingPersonaIds=(list(remaining)
                                  if remaining is not None else []))
        if remaining is None:
            return

        body = build_player_removed_notification(
            request.game_id,
            request.player_id,
            request.reason,
            title_context=request.title_context,
            locked_for_preferred_joins=False,
        )

        departing_delivered = self.send_raw(fire2.build_notification(
            GAMEMANAGER_COMPONENT, PLAYER_REMOVED_NOTIFICATION, body))
        emit(
            "blaze-notification",
            peer=peer if departing_delivered else "",
            name="game-manager-player-removed",
            component=GAMEMANAGER_COMPONENT,
            command=PLAYER_REMOVED_NOTIFICATION,
            bytes=len(body),
            personaId=request.player_id,
            gameId=request.game_id,
            delivered=departing_delivered,
            recipientRole="departing",
            removedPersonaId=request.player_id,
            playerRemovedReason=request.reason,
            playerRemovedTitleContext=request.title_context,
            lockedForPreferredJoins=False,
        )
        self._notify_game_participants(
            request.game_id,
            PLAYER_REMOVED_NOTIFICATION,
            body,
            name="game-manager-player-removed",
            removedPersonaId=request.player_id,
            playerRemovedReason=request.reason,
            playerRemovedTitleContext=request.title_context,
            lockedForPreferredJoins=False,
        )

    def _respond(self, header: "fire2.Fire2Header", payload: bytes, peer: str) -> None:
        server: Any = self.server
        if server.reply_mode == REPLY_NONE:
            emit(
                "blaze-observed-no-reply",
                peer=peer,
                component=header.component,
                componentName=header.component_name,
                command=header.command,
                msgType=header.msg_type,
                msgTypeName=header.type_name,
            )
            return

        if header.msg_type == fire2.PING:
            self.send_frame(fire2.build_ping_reply(header))
            emit("blaze-reply", peer=peer, name="protocol-ping", component=0,
                 componentName=header.component_name, command=0, bytes=0,
                 msgTypeName="ping-reply")
            return

        if header.msg_type != fire2.MESSAGE:
            emit("blaze-nonrequest-observed", peer=peer, component=header.component,
                 componentName=header.component_name, command=header.command,
                 msgType=header.msg_type, msgTypeName=header.type_name)
            return

        if server.reply_mode == REPLY_EMPTY:
            self.send_frame(fire2.build_reply(header, b""))
            emit("blaze-unhandled", peer=peer, component=header.component,
                 componentName=header.component_name, command=header.command,
                 note="answered with empty success by explicit empty reply mode")
            return

        if header.component == AUTH_COMPONENT and header.command == LOGIN_COMMAND:
            code = parse_login_code(payload)
            with server.auth_lock:
                identity = identity_from_code(
                    server.identity_store,
                    code,
                    self.client_locale,
                    server.accepted_auth_codes,
                )
            if identity is None:
                body = tdf.u32(b"ERRC", 1)
                self.send_frame(fire2.build_error(header, body))
                emit("blaze-auth-rejected", peer=peer, component=header.component,
                     command=header.command, reason="invalid, expired, or unapproved auth code")
                return

            accepted = server.accepted_auth_codes.get(code)
            if accepted is None:
                self.send_frame(
                    fire2.build_error(header, tdf.u32(b"ERRC", 1)))
                emit("blaze-auth-rejected", peer=peer,
                     component=header.component, command=header.command,
                     reason="successful code had no session expiry")
                return
            identity = server.blaze_sessions.register(identity, accepted[1])
            body = build_login_response(identity)
            self.auth_identity = identity
            server.notifications.bind(self, identity)
            self.send_frame(fire2.build_reply(header, body))
            emit("blaze-reply", peer=peer, name="authentication-login",
                 component=header.component, componentName=header.component_name,
                 command=header.command, bytes=len(body), personaId=identity.persona_id,
                 connectionGroupId=identity.connection_group_id,
                 schema="blaze15-session")

            time.sleep(0.05)
            notification_body = build_user_authenticated(identity)
            self.send_frame(fire2.build_notification(
                USER_SESSIONS_COMPONENT,
                USER_AUTHENTICATED_NOTIFICATION,
                notification_body,
            ))
            emit("blaze-notification", peer=peer, name="user-authenticated",
                 component=USER_SESSIONS_COMPONENT,
                 command=USER_AUTHENTICATED_NOTIFICATION,
                 bytes=len(notification_body), personaId=identity.persona_id,
                 connectionGroupId=identity.connection_group_id)
            return

        if header.component == UTIL_COMPONENT and header.command == POSTAUTH_COMMAND:
            identity = self.auth_identity
            if identity is None:
                self.send_frame(fire2.build_error(header, tdf.u32(b"ERRC", 1)))
                emit("blaze-postauth-rejected", peer=peer, reason="connection is not authenticated")
                return
            body = build_postauth_response(
                identity.persona_id,
                locale=identity.locale,
            )
            self.send_frame(fire2.build_reply(header, body))
            emit("blaze-reply", peer=peer, name="util-post-auth",
                 component=header.component, componentName=header.component_name,
                 command=header.command, bytes=len(body), personaId=identity.persona_id)

            time.sleep(0.05)
            notifications = (
                ("user-added", USER_ADDED_NOTIFICATION, build_user_added(identity)),
                (
                    "user-extended-data",
                    USER_EXTENDED_DATA_NOTIFICATION,
                    build_user_extended_data_update(identity),
                ),
            )
            for name, command, notification_body in notifications:
                self.send_frame(fire2.build_notification(
                    USER_SESSIONS_COMPONENT,
                    command,
                    notification_body,
                ))
                emit("blaze-notification", peer=peer, name=name,
                     component=USER_SESSIONS_COMPONENT, command=command,
                     bytes=len(notification_body), personaId=identity.persona_id)
                time.sleep(0.05)
            return

        if header.component == AUTH_COMPONENT and header.command == LOGOUT_COMMAND:
            mode = getattr(server, "auth70_reply", AUTH70_EMPTY)
            if mode == AUTH70_SILENT:
                emit("blaze-logout-unanswered", peer=peer, mode=mode,
                     command=header.command,
                     note="deliberately unanswered; experiment only")
                return
            if mode == AUTH70_ERROR:
                self.send_frame(fire2.build_error(header, tdf.u32(b"ERRC", 1)))
            else:
                self.send_frame(fire2.build_reply(header, b""))
            emit("blaze-reply", peer=peer, name="authentication-logout",
                 component=header.component, componentName=header.component_name,
                 command=header.command, bytes=0, mode=mode,
                 requestBytes=len(payload))
            return

        if (header.component == GAMEMANAGER_COMPONENT
                and header.command == START_MATCHMAKING_COMMAND):
            identity = self.auth_identity
            identity_reference = parse_start_matchmaking_identity(payload)
            if identity is None and identity_reference is not None:
                identity = server.blaze_sessions.resolve(
                    identity_reference.connection_group_id)
            if (identity is not None and identity_reference is not None
                    and (identity_reference.connection_group_id
                         != identity.connection_group_id
                         or (identity_reference.persona_id is not None
                             and identity_reference.persona_id
                             != identity.persona_id))):
                identity = None
            if identity is None:
                self.send_frame(
                    fire2.build_error(header, tdf.u32(b"ERRC", 1)))
                emit("matchmaking-rejected", peer=peer,
                     command=header.command,
                     reason="connection is not authenticated")
                return
            if self.auth_identity is None:
                self.auth_identity = identity
                server.notifications.bind(self, identity)
            requested = parse_start_matchmaking_duration(payload)
            override = getattr(server, "matchmaking_duration_override", None)
            duration = override if override else requested
            sweep_seconds = server.gamemanager_sweep_seconds(identity.persona_id)
            if sweep_seconds:
                duration = max(duration or 0.0, sweep_seconds)
            network = parse_start_matchmaking_network_address(payload)
            playlist, progression = server.matchmaking_context(
                identity.persona_id)
            session, created = server.game_manager.start(
                identity.persona_id, payload,
                source_address=self.client_address[0],
                duration_seconds=duration,
                criteria=parse_start_matchmaking_criteria(payload),
                playlist=playlist,
                progression=progression,
                game_version=parse_start_matchmaking_game_version(payload),
                network=network,
                **{k: v for k, v in
                   parse_start_matchmaking_creation_data(payload).items()
                   if k in ("entry_criteria", "queue_capacity")})
            body = build_start_matchmaking_response(session.session_id)
            self.send_frame(fire2.build_reply(header, body))
            emit("blaze-reply", peer=peer,
                 name="game-manager-start-matchmaking",
                 component=header.component,
                 componentName=header.component_name,
                 command=header.command,
                 bytes=len(body),
                 personaId=identity.persona_id,
                 connectionGroupId=identity.connection_group_id,
                 matchmakingSessionId=session.session_id,
                 created=created,
                 requestSha256=session.request_sha256,
                 requestedDurationSeconds=requested,
                 durationSeconds=session.duration_seconds,
                 gameVersion=session.game_version,
                 gameModeName=session.criteria.game_mode_name,
                 totalPlayers=session.criteria.total_players,
                 playlist=session.playlist,
                 progression=dict(session.progression),
                 exactCriteria=dict(session.criteria.exact_rules),
                 internalAddress=(f"{session.network.internal_ip}:"
                                  f"{session.network.internal_port}"
                                  if session.network.has_internal else ""),
                 externalAddress=(f"{session.network.external_ip}:"
                                  f"{session.network.external_port}"
                                  if session.network.has_external else ""))
            server.report_pair_candidates()
            server.start_gamemanager_sweep(
                identity, self.client_address[0], session)
            return

        if (header.component == GAMEMANAGER_COMPONENT
                and header.command == MESH_TELEMETRY_COMMAND):
            self.send_frame(fire2.build_reply(header, b""))
            try:
                report = tdf.summarise(tdf.decode(payload)) if payload else {}
            except tdf.TdfError:
                report = {}
            server.note_mesh_telemetry(peer, report)
            return

        if (header.component == GAMEMANAGER_COMPONENT
                and header.command == CANCEL_MATCHMAKING_COMMAND):
            identity = self.auth_identity
            session_id = parse_cancel_matchmaking_request(payload)
            if session_id is None:
                self.send_frame(
                    fire2.build_error(header, tdf.u32(b"ERRC", 1)))
                emit("matchmaking-rejected", peer=peer,
                     command=header.command,
                     reason="unreadable cancel-matchmaking request")
                return
            cancelled_session = None
            if identity is None:
                cancelled_session = server.game_manager.cancel_from_source(
                    self.client_address[0], session_id)
            if identity is None and cancelled_session is None:
                self.send_frame(
                    fire2.build_error(header, tdf.u32(b"ERRC", 1)))
                emit("matchmaking-rejected", peer=peer,
                     command=header.command,
                     reason="connection is not authenticated")
                return
            if cancelled_session is None:
                cancelled_session = server.game_manager.cancel_session(
                    identity.persona_id, session_id)
            persona_id = (
                identity.persona_id
                if identity is not None else cancelled_session.persona_id
            )
            self.send_frame(fire2.build_reply(header, b""))
            cancelled = cancelled_session is not None
            emit("blaze-reply", peer=peer,
                 name="game-manager-cancel-matchmaking",
                 component=header.component,
                 componentName=header.component_name,
                 command=header.command,
                 bytes=0,
                 personaId=persona_id,
                 matchmakingSessionId=session_id or 0,
                 cancelled=cancelled)
            if cancelled_session is not None:
                notification_body = build_matchmaking_failed_notification(
                    cancelled_session.session_id,
                    cancelled_session.persona_id,
                    MATCHMAKING_RESULT_SESSION_CANCELED,
                )
                self.send_frame(fire2.build_notification(
                    GAMEMANAGER_COMPONENT,
                    MATCHMAKING_FAILED_NOTIFICATION,
                    notification_body,
                ))
                emit("blaze-notification", peer=peer,
                     name="game-manager-matchmaking-cancelled",
                     component=GAMEMANAGER_COMPONENT,
                     command=MATCHMAKING_FAILED_NOTIFICATION,
                     bytes=len(notification_body),
                     personaId=cancelled_session.persona_id,
                     matchmakingSessionId=cancelled_session.session_id,
                     matchmakingResult=MATCHMAKING_RESULT_NAMES[
                         MATCHMAKING_RESULT_SESSION_CANCELED])
            return

        if (header.component == GAMEMANAGER_COMPONENT
                and header.command == REMOVE_PLAYER_COMMAND):
            self._respond_remove_player(header, payload, peer)
            return

        if (header.component == GAMEMANAGER_COMPONENT
                and header.command in GAME_LIFECYCLE_COMMANDS):
            self._respond_game_lifecycle(header, payload, peer)
            return

        if (
            header.component == CENSUS_COMPONENT
            and header.command == SUBSCRIBE_UPDATES_COMMAND
        ):
            body = build_subscribe_updates_response()
            self.send_frame(fire2.build_reply(header, body))
            emit("blaze-reply", peer=peer, name="census-subscribe-updates",
                 component=header.component, componentName=header.component_name,
                 command=header.command, bytes=len(body), schema="fifa17-runtime-descriptor")

            time.sleep(0.05)
            notification_body = build_server_census_notification()
            self.send_frame(fire2.build_notification(
                CENSUS_COMPONENT,
                SERVER_CENSUS_NOTIFICATION,
                notification_body,
            ))
            emit("blaze-notification", peer=peer, name="server-census-data",
                 component=CENSUS_COMPONENT, command=SERVER_CENSUS_NOTIFICATION,
                 bytes=len(notification_body), items=0)
            return

        if (header.component == GAMEREPORTING_COMPONENT
                and header.command in (
                    SUBMIT_GAME_REPORT, SUBMIT_OFFLINE_GAME_REPORT)):
            identity = self.auth_identity
            if identity is None:
                self.send_frame(
                    fire2.build_error(header, tdf.u32(b"ERRC", 1)))
                emit("game-report-rejected", peer=peer,
                     reason="connection is not authenticated")
                return
            state = getattr(server, "fut_state", None)
            accepted = None
            if state is not None:
                try:
                    report = tdf.summarise(tdf.decode(payload)) if payload else {}
                except tdf.TdfError as error:
                    report = {}
                    emit("game-report-undecodable", peer=peer,
                         personaId=identity.persona_id,
                         bytes=len(payload), reason=str(error))
                accepted = state.accept_game_report(
                    identity.persona_id, report)
            report_id = int(accepted["report_id"]) if accepted else 0
            self.send_frame(fire2.build_reply(header, b""))
            report_name = ("submit-game-report"
                           if header.command == SUBMIT_GAME_REPORT
                           else "submit-offline-game-report")
            emit("blaze-reply", peer=peer, name=report_name,
                 component=header.component,
                 componentName=header.component_name,
                 command=header.command, bytes=0, reportId=report_id)
            if state is not None and accepted is None:
                emit("game-report-rejected", peer=peer,
                     personaId=identity.persona_id,
                     reason="no active authoritative match")

            notification_body = build_game_report_result(report_id)
            self.send_frame(fire2.build_notification(
                GAMEREPORTING_COMPONENT,
                GAME_REPORTING_RESULT_NOTIFICATION,
                notification_body,
            ))
            emit("blaze-notification", peer=peer, name="game-reporting-result",
                 component=GAMEREPORTING_COMPONENT,
                 command=GAME_REPORTING_RESULT_NOTIFICATION,
                 bytes=len(notification_body), reportId=report_id)
            return

        identity = self.auth_identity
        frontend = build_frontend_response(
            header.component,
            header.command,
            payload,
            persona_id=identity.persona_id if identity is not None else 0,
            locale=identity.locale if identity is not None else self.client_locale,
            entitlement_type_mode=getattr(
                server, "entitlement_type_mode", DEFAULT_ENTITLEMENT_TYPE_MODE
            ),
        )
        if frontend is not None:
            name, body, details = frontend
            self.send_frame(fire2.build_reply(header, body))
            emit("blaze-reply", peer=peer, name=name, component=header.component,
                 componentName=header.component_name, command=header.command,
                 bytes=len(body), schema="blaze15", **details)
            return

        handler = HANDLERS.get((header.component, header.command))
        if handler is not None:
            name, builder = handler
            built = builder(self, header, payload)
            details = {}
            if isinstance(built, tuple):
                body, details = built
            else:
                body = built
            self.send_frame(fire2.build_reply(header, body))
            emit("blaze-reply", peer=peer, name=name, component=header.component,
                 componentName=header.component_name, command=header.command, bytes=len(body),
                 **details)
            return

        self.send_frame(fire2.build_reply(header, b""))
        emit("blaze-unhandled", peer=peer, component=header.component,
             componentName=header.component_name, command=header.command,
             note="answered with empty success; response body not yet implemented")


class BlazeCaptureServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        reply_mode: str = REPLY_BOOTSTRAP,
        identity_store: Any = None,
        preauth_components: str = DEFAULT_COMPONENT_SET,
        auth70_reply: str = AUTH70_EMPTY,
        server_versioning: str = DEFAULT_SERVER_VERSIONING,
        fut_direct_boot: bool = False,
        entitlement_type_mode: str = DEFAULT_ENTITLEMENT_TYPE_MODE,
        ssl_context: ssl.SSLContext | None = None,
        matchmaking_duration_override: float | None = None,
        gamemanager_sweep_ids: tuple[int, ...] = (),
        gamemanager_sweep_delay: float = GAMEMANAGER_SWEEP_DEFAULT_DELAY,
        gamemanager_sweep_persona: int | None = None,
        gamemanager_result_probe: int | None = None,
        gamemanager_setup_ids: tuple[int, ...] = (),
        pairing_enabled: bool = False,
        pairing_result_notification: bool = False,
        player_join_completed_notification: int = 0,
        player_state_notification: int = 0,
        player_state_sweep: tuple[int, ...] = (),
        player_attrib_notification: int = PLAYER_ATTRIB_CHANGE_NOTIFICATION,
        player_attrib_sweep: tuple[int, ...] = (),
        advance_on_player_request: str = "",
        player_state_sweep_delay: float = 1.5,
        gamemanager_setup_reasons: tuple[int, ...] = (),
        gamemanager_setup_marker: str = "",
        gamemanager_setup_notification: int = 0,
        gamemanager_setup_control: bool = False,
        gamemanager_finished_ids: tuple[int, ...] = (),
        gamemanager_game_states: tuple[int, ...] = (),
    ) -> None:
        setup_ids = tuple(int(i) for i in gamemanager_setup_ids)
        if reply_mode not in REPLY_MODES:
            raise ValueError(f"reply mode must be one of {REPLY_MODES}")
        if preauth_components not in COMPONENT_SETS:
            raise ValueError(f"component set must be one of {tuple(COMPONENT_SETS)}")
        if auth70_reply not in AUTH70_MODES:
            raise ValueError(f"command 70 reply must be one of {AUTH70_MODES}")
        if server_versioning not in SERVER_VERSIONING_MODES:
            raise ValueError(
                f"server versioning must be one of {SERVER_VERSIONING_MODES}"
            )
        if entitlement_type_mode not in ENTITLEMENT_TYPE_MODES:
            raise ValueError(
                f"entitlement type must be one of {tuple(ENTITLEMENT_TYPE_MODES)}"
            )
        if (matchmaking_duration_override is not None
                and float(matchmaking_duration_override) <= 0):
            raise ValueError("matchmaking duration override must be positive")
        if ((gamemanager_sweep_ids or gamemanager_result_probe is not None)
                and not gamemanager_sweep_persona):
            raise ValueError(
                "a GameManager experiment must name the persona it may touch")
        if (gamemanager_result_probe is not None
                and gamemanager_result_probe not in MATCHMAKING_RESULT_NAMES):
            raise ValueError(
                "result probe must be a recovered MatchmakingResult value")
        if setup_ids and gamemanager_result_probe is None:
            raise ValueError("a staged game setup requires a result probe")
        if len(setup_ids) > 1:
            raise ValueError(
                "a result probe may stage exactly one setup id; grouped ids "
                "produced an ambiguous client crash")
        if (setup_ids and setup_ids != (GAME_SETUP_NOTIFICATION,)
                and not gamemanager_setup_control):
            raise ValueError(
                "a result probe may stage only the recovered GameSetup id 20; "
                "pass gamemanager_setup_control to stage a different one as a "
                "deliberate control")
        if gamemanager_setup_control and len(setup_ids) != 1:
            raise ValueError(
                "a setup control stages exactly one id, so a crash is "
                "attributable to it")
        if (setup_ids
                and gamemanager_result_probe
                != MATCHMAKING_RESULT_SUCCESS_CREATED_GAME):
            raise ValueError(
                "the synthetic local-host setup requires result 0 "
                "(SUCCESS_CREATED_GAME)")
        self.server_versioning = server_versioning
        self.fut_direct_boot = fut_direct_boot
        self.entitlement_type_mode = entitlement_type_mode
        self.ssl_context = ssl_context
        self.reply_mode = reply_mode
        self.identity_store = identity_store
        self.preauth_components = preauth_components
        self.auth70_reply = auth70_reply
        self.game_manager = MatchmakingService()
        self.blaze_sessions = BlazeSessionRegistry(store=identity_store)
        self.notifications = NotificationRouter()
        self.matchmaking_duration_override = matchmaking_duration_override
        self.gamemanager_sweep_ids = tuple(int(i) for i in gamemanager_sweep_ids)
        self.gamemanager_sweep_delay = max(1.0, float(gamemanager_sweep_delay))
        self.gamemanager_sweep_persona = (
            int(gamemanager_sweep_persona)
            if gamemanager_sweep_persona else None)
        self.gamemanager_result_probe = (
            int(gamemanager_result_probe)
            if gamemanager_result_probe is not None else None)
        self.gamemanager_setup_ids = setup_ids
        self.pairing_enabled = bool(pairing_enabled)
        self.pairing_result_notification = bool(pairing_result_notification)
        self.player_join_completed_notification = int(
            player_join_completed_notification)
        self.player_state_notification = int(player_state_notification)
        self.player_state_sweep = tuple(int(i) for i in player_state_sweep)
        self.player_attrib_notification = int(player_attrib_notification)
        self.player_attrib_sweep = tuple(int(i) for i in player_attrib_sweep)
        self._attrib_swept: set[int] = set()
        self.advance_on_player_request = str(advance_on_player_request or "")
        self.player_state_sweep_delay = float(player_state_sweep_delay)
        self._player_state_swept: set[int] = set()
        self.gamemanager_setup_reasons = tuple(
            int(r) for r in gamemanager_setup_reasons)
        self.gamemanager_setup_marker = str(gamemanager_setup_marker)
        self.gamemanager_setup_control = bool(gamemanager_setup_control)
        self.gamemanager_setup_notification = (
            int(gamemanager_setup_notification)
            or GAME_SETUP_NOTIFICATION)
        self.gamemanager_finished_ids = tuple(
            int(i) for i in gamemanager_finished_ids)
        self.gamemanager_game_states = tuple(
            int(g) for g in gamemanager_game_states)
        self.games = GameRegistry()
        self._swept: set[int] = set()
        self.accepted_auth_codes: dict[str, tuple[int, int]] = {}
        self.auth_lock = threading.Lock()
        self.max_connections = MAX_BLAZE_CONNECTIONS
        self.access = None
        self._connection_lock = threading.Lock()
        self._active_connections = 0
        self._peak_connections = 0
        self._mesh_telemetry: dict[str, dict] = {}
        self._matchmaking_stop = threading.Event()
        self._sweep_active = False
        self._sweep_last_id: int | None = None
        self._sweep_reaction: tuple[int | None, int, str] | None = None
        self._sweep_target_persona: int | None = None
        self._sweep_source_address = ""
        super().__init__(server_address, BlazeCaptureHandler)
        self._matchmaking_thread = threading.Thread(
            target=self._matchmaking_deadlines,
            name="matchmaking-deadlines",
            daemon=True,
        )
        self._matchmaking_thread.start()

    def note_mesh_telemetry(self, peer: str, decoded: Any) -> None:
        now = time.time()
        with self._connection_lock:
            state = self._mesh_telemetry.setdefault(peer, {"count": 0, "at": 0.0})
            state["count"] += 1
            if now - state["at"] < MESH_TELEMETRY_LOG_SECONDS:
                return
            state["at"] = now
            reported = state["count"]
            state["count"] = 0

        peers = []
        try:
            for entry in decoded.get("RPTS", {}).get("values", []):
                fields = {row["tag"]: row["value"] for row in entry}
                peers.append({
                    "remoteConnGroupId": fields.get("RCID"),
                    "latencyMs": fields.get("LATC"),
                    "packetLoss": fields.get("PKTL"),
                    "received": fields.get("RCVD"),
                    "sent": fields.get("SENT"),
                })
        except (AttributeError, KeyError, TypeError):
            peers = []
        emit("mesh-telemetry", peer=peer,
             component=GAMEMANAGER_COMPONENT, command=MESH_TELEMETRY_COMMAND,
             gameId=(decoded or {}).get("GID") if isinstance(decoded, dict) else None,
             localConnGroupId=(decoded or {}).get("LCID")
             if isinstance(decoded, dict) else None,
             reportsSinceLastLine=reported, remotes=peers,
             note="answered with empty success; summarised, not per frame")

    def matchmaking_context(
            self, persona_id: int) -> tuple[str, tuple[tuple[str, str], ...]]:
        state = getattr(self, "fut_state", None)
        match = state.active_match(persona_id) if state is not None else None
        if not match:
            return PLAYLIST_UNRESOLVED, ()
        playlist = str(match.get("playlist", PLAYLIST_UNRESOLVED))
        progress: list[tuple[str, str]] = []
        if playlist == PLAYLIST_ONLINE_SEASONS:
            progress.append(("divisionId", str(int(
                match.get("division_id", 0) or 0))))
        elif playlist == PLAYLIST_ONLINE_DRAFT:
            import fut_draft
            run = fut_draft.load_run(
                state, persona_id, fut_draft.MODE_ONLINE)
            progress.append(("wins", str(int(run.get("wins", 0)))))
        return playlist, tuple(progress)

    def report_pair_candidates(self) -> None:
        for first, second in self.game_manager.pair_candidates():
            emit("matchmaking-pair-candidate",
                 sessions=[first.session_id, second.session_id],
                 personas=[first.persona_id, second.persona_id],
                 gameModeName=first.criteria.game_mode_name,
                 playlist=first.playlist,
                 progression=[dict(first.progression),
                              dict(second.progression)],
                 totalPlayers=first.criteria.total_players,
                 exactCriteria=dict(first.criteria.exact_rules),
                 overlapSeconds=round(
                     abs(first.created_at - second.created_at), 3),
                 note="criteria-compatible; not paired, setup id unconfirmed")
        if self.pairing_enabled:
            self.pair_compatible_searches()

    def pair_compatible_searches(self) -> None:
        for first, second in self.game_manager.pair_candidates():
            state = getattr(self, "fut_state", None)
            if state is not None:
                active = [state.active_match(search.persona_id)
                          for search in (first, second)]
                if any(not match or match.get("playlist") != search.playlist
                       for match, search in zip(active, (first, second))):
                    emit("matchmaking-pair-abandoned",
                         personas=[first.persona_id, second.persona_id],
                         playlist=first.playlist,
                         reason="an active FUT match no longer matches its queue")
                    continue
            host_identity = self.blaze_sessions.resolve_persona(first.persona_id)
            away_identity = self.blaze_sessions.resolve_persona(second.persona_id)
            if host_identity is None or away_identity is None:
                emit("matchmaking-pair-abandoned",
                     personas=[first.persona_id, second.persona_id],
                     reason="a paired persona has no live Blaze identity")
                continue
            if any(not self.notifications.candidates(s.persona_id, s.source_address)
                   for s in (first, second)):
                emit("matchmaking-pair-abandoned",
                     personas=[first.persona_id, second.persona_id],
                     reason="a paired persona has no notification connection")
                continue
            claimed = self.game_manager.claim_pair(first, second)
            if claimed is None:
                emit("matchmaking-pair-abandoned",
                     personas=[first.persona_id, second.persona_id],
                     reason="a search changed or expired while pairing")
                continue

            host, host_addressing = _paired_player(
                host_identity, first, slot_id=0, team_index=0)
            away, away_addressing = _paired_player(
                away_identity, second, slot_id=1, team_index=1)
            exact_rules = dict(first.criteria.exact_rules)
            game_attributes = [
                ("Gamemode_Name",
                 first.criteria.game_mode_name or "fut_online_h2h"),
            ]
            for key in ("OSDK_gameMode", "OSDK_rosterVersion"):
                if key in exact_rules:
                    game_attributes.append((key, exact_rules[key]))
            game = self.games.create(
                (host, away), host_persona_id=host.persona_id,
                game_mode_name=first.criteria.game_mode_name or "fut_online_h2h",
                game_settings=3087,
                entry_criteria=first.entry_criteria,
                queue_capacity=first.queue_capacity,
                protocol_version=first.game_version,
                created_at=time.time(),
                routing_addresses={
                    host.persona_id: first.source_address,
                    away.persona_id: second.source_address},
                attributes=tuple(game_attributes))
            delivered_personas = []
            for search, result in (
                (first, MATCHMAKING_RESULT_SUCCESS_CREATED_GAME),
                (second, MATCHMAKING_RESULT_SUCCESS_JOINED_NEW_GAME),
            ):
                setup = build_game_setup_notification(
                    game, search.session_id, search.persona_id,
                    matchmaking_result=result)
                peer = self.notifications.deliver(
                    GAMEMANAGER_COMPONENT, GAME_SETUP_NOTIFICATION, setup,
                    persona_id=search.persona_id,
                    source_address=search.source_address)
                emit("blaze-notification", peer=peer or "",
                     name="game-manager-game-setup",
                     component=GAMEMANAGER_COMPONENT,
                     command=GAME_SETUP_NOTIFICATION, bytes=len(setup),
                     personaId=search.persona_id, gameId=game.game_id,
                     delivered=peer is not None)
                if peer is not None:
                    delivered_personas.append(search.persona_id)

            if len(delivered_personas) != 2:
                removed = self.games.discard(game.game_id) or ()
                restored = self.game_manager.restore_pair(first, second)
                emit("matchmaking-pair-delivery-failed",
                     gameId=game.game_id,
                     personas=[host.persona_id, away.persona_id],
                     sessions=[first.session_id, second.session_id],
                     deliveredPersonaIds=delivered_personas,
                     removedPersonaIds=list(removed),
                     restoredSessionIds=[s.session_id for s in restored])
                continue

            emit("matchmaking-paired", gameId=game.game_id,
                 personas=[host.persona_id, away.persona_id],
                 sessions=[first.session_id, second.session_id],
                 hostPersonaId=host.persona_id,
                 hostAddressing=host_addressing,
                 awayAddressing=away_addressing,
                 gameVersion=game.protocol_version,
                 playlist=first.playlist,
                 gameModeName=game.game_mode_name)

            if not self.pairing_result_notification:
                continue
            for search, result in (
                (first, MATCHMAKING_RESULT_SUCCESS_CREATED_GAME),
                (second, MATCHMAKING_RESULT_SUCCESS_JOINED_NEW_GAME),
            ):
                body = build_matchmaking_result_notification(
                    search.session_id, search.persona_id, result,
                    fit_score=100, max_fit_score=100,
                    game_entry_type=GAME_ENTRY_TYPE_DIRECT,
                    time_to_match=int(
                        (time.time() - search.created_at) * 1_000_000))
                peer = self.notifications.deliver(
                    GAMEMANAGER_COMPONENT, MATCHMAKING_FAILED_NOTIFICATION,
                    body, persona_id=search.persona_id,
                    source_address=search.source_address)
                emit("blaze-notification", peer=peer or "",
                     name="game-manager-matchmaking-succeeded",
                     component=GAMEMANAGER_COMPONENT,
                     command=MATCHMAKING_FAILED_NOTIFICATION,
                     bytes=len(body), personaId=search.persona_id,
                     matchmakingSessionId=search.session_id,
                     matchmakingResult=MATCHMAKING_RESULT_NAMES[result],
                     gameId=game.game_id, delivered=peer is not None)

    def announce_player_attributes(
        self, game_id: int, persona_id: int,
        attributes: tuple[tuple[str, str], ...], connection: Any,
    ) -> None:
        body = build_player_attrib_notification(game_id, persona_id, attributes)
        if self.player_attrib_notification:
            connection._notify_game_participants(
                game_id, self.player_attrib_notification, body,
                name="game-manager-player-attrib-change",
                aboutPersonaId=persona_id, attributes=dict(attributes))

        ready = self.games.players_with_request(game_id)
        everyone = tuple(p.persona_id
                         for p in self.games.participants(game_id))
        enough = (set(ready) >= set(everyone)
                  if self.advance_on_player_request == "all" else bool(ready))
        if self.advance_on_player_request and everyone and enough:
            transition = self.games.advance_state(
                game_id, persona_id, GAME_STATE_IN_GAME)
            if transition is not None and transition.changed:
                state_body = build_game_state_change_notification(
                    game_id, GAME_STATE_IN_GAME)
                connection._notify_game_participants(
                    game_id, GAME_STATE_CHANGE_NOTIFICATION, state_body,
                    name="game-manager-game-state-change",
                    gameState="IN_GAME", readyPersonaIds=list(ready),
                    gate=self.advance_on_player_request,
                    note="the ATTR REQ gate was satisfied")
        elif self.advance_on_player_request:
            emit("game-start-waiting", gameId=game_id,
                 readyPersonaIds=list(ready),
                 waitingOnPersonaIds=[p for p in everyone if p not in ready],
                 gate=self.advance_on_player_request,
                 note="not every participant has asked with ATTR REQ yet")
        if not self.player_attrib_sweep:
            return
        with self._connection_lock:
            if game_id in self._attrib_swept:
                return
            self._attrib_swept.add(game_id)
        threading.Thread(
            target=self._player_attrib_sweep,
            args=(game_id, persona_id, attributes),
            name="player-attrib-sweep", daemon=True).start()

    def _player_attrib_sweep(
        self, game_id: int, persona_id: int,
        attributes: tuple[tuple[str, str], ...],
    ) -> None:
        body = build_player_attrib_notification(game_id, persona_id, attributes)
        emit("player-attrib-sweep-start", gameId=game_id,
             aboutPersonaId=persona_id,
             candidates=list(self.player_attrib_sweep),
             delaySeconds=self.player_state_sweep_delay)
        tried = []
        for notification in self.player_attrib_sweep:
            if self._matchmaking_stop.is_set():
                break
            participants = self.games.participants(game_id)
            if not participants:
                emit("player-attrib-sweep-done", gameId=game_id,
                     candidatesTried=tried,
                     note="the game ended before the sweep finished")
                return
            if not all(self.games.mesh_complete(game_id, p.persona_id)
                       for p in participants):
                emit("player-attrib-sweep-abandoned", gameId=game_id,
                     candidatesTried=tried,
                     note="a participant dropped its mesh; the remaining "
                          "candidates were not tested")
                return
            for target in participants:
                if target.persona_id == persona_id:
                    continue
                peer = self.notifications.deliver(
                    GAMEMANAGER_COMPONENT, notification, body,
                    persona_id=target.persona_id,
                    source_address=target.source_address)
                emit("player-attrib-sweep-send", gameId=game_id,
                     command=notification, aboutPersonaId=persona_id,
                     personaId=target.persona_id, bytes=len(body),
                     peer=peer or "", delivered=peer is not None)
            tried.append(notification)
            self._matchmaking_stop.wait(self.player_state_sweep_delay)
            answered = [p for p in self.games.players_with_attributes(game_id)
                        if p != persona_id]
            if answered:
                emit("player-attrib-sweep-identified", gameId=game_id,
                     command=notification, answeredBy=answered,
                     note="another player announced its own attributes after "
                          "this notification id")
                return
        emit("player-attrib-sweep-done", gameId=game_id, candidatesTried=tried,
             note="every candidate id was tried against a live game and no "
                  "other player answered")

    def start_player_state_sweep(self, game_id: int) -> None:
        if not self.player_state_sweep:
            return
        participants = self.games.participants(game_id)
        if len(participants) < 2 or not all(
                self.games.mesh_complete(game_id, p.persona_id)
                for p in participants):
            return
        with self._connection_lock:
            if game_id in self._player_state_swept:
                return
            self._player_state_swept.add(game_id)
        threading.Thread(
            target=self._player_state_sweep, args=(game_id,),
            name="player-state-sweep", daemon=True).start()

    def _player_state_sweep(self, game_id: int) -> None:
        emit("player-state-sweep-start", gameId=game_id,
             candidates=list(self.player_state_sweep),
             delaySeconds=self.player_state_sweep_delay)
        tried: list[int] = []
        last = 0
        for notification in self.player_state_sweep:
            if self._matchmaking_stop.is_set():
                break
            participants = self.games.participants(game_id)
            if not participants:
                emit("player-state-sweep-done", gameId=game_id,
                     candidatesTried=tried,
                     note="the game ended before the sweep finished")
                return
            if not all(self.games.mesh_complete(game_id, p.persona_id)
                       for p in participants):
                emit("player-state-sweep-abandoned", gameId=game_id,
                     candidatesTried=tried, lastCommand=last,
                     note="a participant dropped its mesh; the remaining "
                          "candidates were not tested")
                return
            for participant in participants:
                body = build_game_player_state_notification(
                    game_id, participant.persona_id,
                    PLAYER_STATE_ACTIVE_CONNECTED)
                for target in participants:
                    peer = self.notifications.deliver(
                        GAMEMANAGER_COMPONENT, notification, body,
                        persona_id=target.persona_id,
                        source_address=target.source_address)
                    emit("player-state-sweep-send", gameId=game_id,
                         command=notification,
                         aboutPersonaId=participant.persona_id,
                         personaId=target.persona_id, bytes=len(body),
                         peer=peer or "", delivered=peer is not None)
            tried.append(notification)
            last = notification
            self._matchmaking_stop.wait(self.player_state_sweep_delay)
            if self.games.state(game_id) == GAME_STATE_IN_GAME:
                emit("player-state-sweep-identified", gameId=game_id,
                     command=notification,
                     note="the game reached IN_GAME under this notification id")
                return
        emit("player-state-sweep-done", gameId=game_id,
             candidatesTried=tried,
             note="every candidate id was tried against a live game and it "
                  "never reached IN_GAME")

    def _arm_sweep(self, persona_id: int, source_address: str) -> None:
        with self._connection_lock:
            self._sweep_active = True
            self._sweep_target_persona = int(persona_id)
            self._sweep_source_address = source_address
            self._sweep_reaction = None

    def _disarm_sweep(self) -> None:
        with self._connection_lock:
            self._sweep_active = False
            self._sweep_target_persona = None
            self._sweep_source_address = ""

    def note_gamemanager_frame(
        self,
        command: int,
        peer: str,
        *,
        persona_id: int | None = None,
        source_address: str = "",
    ) -> None:
        if command in (START_MATCHMAKING_COMMAND, CANCEL_MATCHMAKING_COMMAND):
            return
        with self._connection_lock:
            if not self._sweep_active or self._sweep_reaction is not None:
                return
            target = self._sweep_target_persona
            if target is None or source_address != self._sweep_source_address:
                return
            if persona_id is not None and int(persona_id) != target:
                return
            if (persona_id is None
                    and not self.notifications.source_is_unambiguous(
                        source_address, target)):
                return
            self._sweep_reaction = (self._sweep_last_id, int(command), peer)
        emit("gamemanager-sweep-reaction",
             afterNotification=self._sweep_reaction[0],
             clientCommand=int(command), peer=peer,
             note="the client answered a swept notification; remaining ids "
                  "are not sent")

    def sweeps_persona(self, persona_id: int) -> bool:
        return bool(self.gamemanager_sweep_ids
                    and self.gamemanager_sweep_persona is not None
                    and int(persona_id) == self.gamemanager_sweep_persona)

    def gamemanager_sweep_seconds(self, persona_id: int) -> float:
        if (self.gamemanager_game_states
                and self.gamemanager_sweep_persona is not None
                and int(persona_id) == self.gamemanager_sweep_persona):
            with self._connection_lock:
                if int(persona_id) in self._swept:
                    return 0.0
            return (GAMEMANAGER_SWEEP_SETTLE_SECONDS
                    + (len(self.gamemanager_game_states) + 2)
                    * self.gamemanager_sweep_delay)
        if (self.gamemanager_finished_ids
                and self.gamemanager_sweep_persona is not None
                and int(persona_id) == self.gamemanager_sweep_persona):
            with self._connection_lock:
                if int(persona_id) in self._swept:
                    return 0.0
            return (GAMEMANAGER_SWEEP_SETTLE_SECONDS
                    + (len(self.gamemanager_finished_ids) + 2)
                    * self.gamemanager_sweep_delay)
        if (self.gamemanager_setup_reasons
                and self.gamemanager_sweep_persona is not None
                and int(persona_id) == self.gamemanager_sweep_persona):
            with self._connection_lock:
                if int(persona_id) in self._swept:
                    return 0.0
            return (GAMEMANAGER_SWEEP_SETTLE_SECONDS
                    + len(self.gamemanager_setup_reasons)
                    * self.gamemanager_sweep_delay
                    + self.gamemanager_sweep_delay)
        if not self.sweeps_persona(persona_id):
            return 0.0
        with self._connection_lock:
            if int(persona_id) in self._swept:
                return 0.0
        return (GAMEMANAGER_SWEEP_SETTLE_SECONDS
                + len(self.gamemanager_sweep_ids) * self.gamemanager_sweep_delay
                + self.gamemanager_sweep_delay)

    def start_gamemanager_sweep(
        self,
        identity: Any,
        source_address: str,
        session: Any,
    ) -> None:
        if not (self.gamemanager_sweep_ids
                or self.gamemanager_game_states
                or self.gamemanager_finished_ids
                or self.gamemanager_setup_reasons
                or self.gamemanager_result_probe is not None):
            return
        if (self.gamemanager_sweep_persona is None
                or int(identity.persona_id) != self.gamemanager_sweep_persona):
            return
        with self._connection_lock:
            if identity.persona_id in self._swept:
                return
            self._swept.add(identity.persona_id)
        if self.gamemanager_game_states:
            threading.Thread(
                target=self._gamemanager_state_sequence,
                args=(identity, source_address, session),
                name="gamemanager-state-sequence", daemon=True).start()
            return
        if self.gamemanager_finished_ids:
            threading.Thread(
                target=self._gamemanager_finished_sweep,
                args=(identity, source_address, session),
                name="gamemanager-finished-sweep", daemon=True).start()
            return
        if self.gamemanager_setup_reasons:
            threading.Thread(
                target=self._gamemanager_setup_reason_sweep,
                args=(identity, source_address, session),
                name="gamemanager-setup-reasons", daemon=True).start()
            return
        if self.gamemanager_result_probe is not None:
            threading.Thread(
                target=self._gamemanager_result_probe,
                args=(identity, source_address, session),
                name="gamemanager-result-probe", daemon=True).start()
            return
        threading.Thread(
            target=self._gamemanager_sweep,
            args=(identity, source_address, session),
            name="gamemanager-sweep",
            daemon=True,
        ).start()

    def _gamemanager_state_sequence(
        self,
        identity: Any,
        source_address: str,
        session: Any,
    ) -> None:
        local = GamePlayer(
            persona_id=identity.persona_id,
            display_name=identity.display_name,
            connection_group_id=identity.connection_group_id,
            internal_ip=source_address or "127.0.0.1", internal_port=3659,
            slot_id=0, team_index=0, locale=identity.locale)
        opponent = GamePlayer(
            persona_id=identity.persona_id + 1, display_name="probe",
            connection_group_id=identity.connection_group_id + 1,
            internal_ip=source_address or "127.0.0.1", internal_port=3660,
            slot_id=1, team_index=1, locale=identity.locale)
        game = self.games.create(
            (local, opponent), host_persona_id=local.persona_id,
            game_mode_name="fut_online_h2h", game_settings=3087,
            entry_criteria=session.entry_criteria,
            queue_capacity=session.queue_capacity,
            protocol_version=session.game_version, created_at=time.time(),
            routing_addresses={identity.persona_id: source_address},
            attributes=(("Gamemode_Name", "fut_online_h2h"),
                        ("OSDK_gameMode", "81")))
        setup = build_game_setup_notification(
            game, session.session_id, identity.persona_id,
            matchmaking_result=MATCHMAKING_RESULT_SUCCESS_CREATED_GAME)
        self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)
        peer = self.notifications.deliver(
            GAMEMANAGER_COMPONENT, GAME_SETUP_NOTIFICATION, setup,
            persona_id=identity.persona_id, source_address=source_address)
        emit("gamemanager-state-sequence-start", personaId=identity.persona_id,
             gameId=game.game_id, states=list(self.gamemanager_game_states),
             setupBytes=len(setup), setupDelivered=peer is not None)

        self._arm_sweep(identity.persona_id, source_address)
        for state in self.gamemanager_game_states:
            if self._matchmaking_stop.is_set() or self._sweep_reaction:
                break
            self._matchmaking_stop.wait(self.gamemanager_sweep_delay)
            self._sweep_last_id = state
            body = build_game_state_change_notification(game.game_id, state)
            peer = self.notifications.deliver(
                GAMEMANAGER_COMPONENT, GAME_STATE_CHANGE_NOTIFICATION, body,
                persona_id=identity.persona_id, source_address=source_address)
            emit("gamemanager-state-sequence-send",
                 personaId=identity.persona_id, gameId=game.game_id,
                 component=GAMEMANAGER_COMPONENT,
                 command=GAME_STATE_CHANGE_NOTIFICATION,
                 gameState=state, gameStateName=GAME_STATE_NAMES.get(state, state),
                 bytes=len(body), peer=peer or "", delivered=peer is not None)
        self._sweep_active = False
        if self._sweep_reaction is not None:
            after, command, peer = self._sweep_reaction
            emit("gamemanager-state-identified", personaId=identity.persona_id,
                 afterGameState=after, clientCommand=command, peer=peer)
        emit("gamemanager-state-sequence-done", personaId=identity.persona_id)

    def _gamemanager_finished_sweep(
        self,
        identity: Any,
        source_address: str,
        session: Any,
    ) -> None:
        local = GamePlayer(
            persona_id=identity.persona_id,
            display_name=identity.display_name,
            connection_group_id=identity.connection_group_id,
            internal_ip=source_address or "127.0.0.1", internal_port=3659,
            slot_id=0, team_index=0, locale=identity.locale)
        opponent = GamePlayer(
            persona_id=identity.persona_id + 1, display_name="probe",
            connection_group_id=identity.connection_group_id + 1,
            internal_ip=source_address or "127.0.0.1", internal_port=3660,
            slot_id=1, team_index=1, locale=identity.locale)
        game = self.games.create(
            (local, opponent), host_persona_id=local.persona_id,
            game_mode_name="fut_online_h2h", game_settings=3087,
            entry_criteria=session.entry_criteria,
            queue_capacity=session.queue_capacity,
            protocol_version=session.game_version, created_at=time.time(),
            routing_addresses={identity.persona_id: source_address},
            attributes=(("Gamemode_Name", "fut_online_h2h"),
                        ("OSDK_gameMode", "81")))
        setup = build_game_setup_notification(
            game, session.session_id, identity.persona_id,
            matchmaking_result=MATCHMAKING_RESULT_SUCCESS_CREATED_GAME)
        self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)
        peer = self.notifications.deliver(
            GAMEMANAGER_COMPONENT, GAME_SETUP_NOTIFICATION, setup,
            persona_id=identity.persona_id, source_address=source_address)
        emit("gamemanager-finished-sweep-start", personaId=identity.persona_id,
             ids=list(self.gamemanager_finished_ids), gameId=game.game_id,
             setupBytes=len(setup), setupDelivered=peer is not None,
             matchmakingSessionId=session.session_id)

        body = build_matchmaking_finished_notification(
            session.session_id, identity.persona_id,
            MATCHMAKING_RESULT_SUCCESS_CREATED_GAME,
            session_duration_microseconds=int(
                session.duration_seconds * 1_000_000),
            max_fit_score=100)
        self._arm_sweep(identity.persona_id, source_address)
        for notification in self.gamemanager_finished_ids:
            if self._matchmaking_stop.is_set() or self._sweep_reaction:
                break
            self._matchmaking_stop.wait(self.gamemanager_sweep_delay)
            self._sweep_last_id = notification
            peer = self.notifications.deliver(
                GAMEMANAGER_COMPONENT, notification, body,
                persona_id=identity.persona_id, source_address=source_address)
            emit("gamemanager-finished-sweep-send",
                 personaId=identity.persona_id,
                 component=GAMEMANAGER_COMPONENT, command=notification,
                 bytes=len(body), peer=peer or "", delivered=peer is not None)
        self._sweep_active = False
        if self._sweep_reaction is not None:
            after, command, peer = self._sweep_reaction
            emit("gamemanager-finished-identified",
                 personaId=identity.persona_id, notification=after,
                 clientCommand=command, peer=peer)
        emit("gamemanager-finished-sweep-done", personaId=identity.persona_id)

    def _gamemanager_setup_reason_sweep(
        self,
        identity: Any,
        source_address: str,
        session: Any,
    ) -> None:
        local = GamePlayer(
            persona_id=identity.persona_id,
            display_name=identity.display_name,
            connection_group_id=identity.connection_group_id,
            internal_ip=source_address or "127.0.0.1", internal_port=3659,
            slot_id=0, team_index=0, locale=identity.locale)
        opponent = GamePlayer(
            persona_id=identity.persona_id + 1, display_name="probe",
            connection_group_id=identity.connection_group_id + 1,
            internal_ip=source_address or "127.0.0.1", internal_port=3660,
            slot_id=1, team_index=1, locale=identity.locale)
        marker = self.gamemanager_setup_marker
        game = self.games.create(
            (local, opponent), host_persona_id=local.persona_id,
            game_mode_name=marker or "fut_online_h2h", game_settings=3087,
            entry_criteria=session.entry_criteria,
            queue_capacity=session.queue_capacity,
            protocol_version=session.game_version, created_at=time.time(),
            routing_addresses={identity.persona_id: source_address},
            attributes=(("Gamemode_Name", marker or "fut_online_h2h"),
                        ("OSDK_gameMode", "81")))
        emit("gamemanager-reason-sweep-start", marker=marker,
             gameName=game.game_mode_name, personaId=identity.persona_id,
             reasons=list(self.gamemanager_setup_reasons),
             gameId=game.game_id, matchmakingSessionId=session.session_id)
        self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)
        self._arm_sweep(identity.persona_id, source_address)
        for reason in self.gamemanager_setup_reasons:
            if self._matchmaking_stop.is_set() or self._sweep_reaction:
                break
            self._sweep_last_id = reason
            body = build_game_setup_notification(
                game, session.session_id, identity.persona_id,
                setup_reason=reason)
            peer = self.notifications.deliver(
                GAMEMANAGER_COMPONENT, self.gamemanager_setup_notification,
                body,
                persona_id=identity.persona_id, source_address=source_address)
            emit("gamemanager-reason-sweep-send",
                 personaId=identity.persona_id, setupReason=reason,
                 component=GAMEMANAGER_COMPONENT,
                 command=self.gamemanager_setup_notification, bytes=len(body),
                 peer=peer or "", delivered=peer is not None)
            if peer is not None:
                consumed = self.game_manager.cancel_session(
                    identity.persona_id, session.session_id)
                if consumed is not None:
                    emit("matchmaking-search-consumed",
                         personaId=identity.persona_id,
                         matchmakingSessionId=session.session_id,
                         gameId=game.game_id,
                         reason="a game setup was delivered for this search")
            self._matchmaking_stop.wait(self.gamemanager_sweep_delay)
        self._sweep_active = False
        if self._sweep_reaction is not None:
            after, command, peer = self._sweep_reaction
            emit("gamemanager-reason-identified",
                 personaId=identity.persona_id, setupReason=after,
                 clientCommand=command, peer=peer,
                 note="the client answered a game setup sent with this reason")
        emit("gamemanager-reason-sweep-done", personaId=identity.persona_id)

    def _gamemanager_result_probe(
        self,
        identity: Any,
        source_address: str,
        session: Any,
    ) -> None:
        result = self.gamemanager_result_probe
        if self.gamemanager_setup_ids:
            local = GamePlayer(
                persona_id=identity.persona_id,
                display_name=identity.display_name,
                connection_group_id=identity.connection_group_id,
                internal_ip=source_address or "127.0.0.1",
                internal_port=3659, slot_id=0, team_index=0,
                locale=identity.locale)
            opponent = GamePlayer(
                persona_id=identity.persona_id + 1, display_name="probe",
                connection_group_id=identity.connection_group_id + 1,
                internal_ip="192.0.2.1", internal_port=3659,
                slot_id=1, team_index=1, locale=identity.locale)
            game = self.games.create(
                (local, opponent), host_persona_id=local.persona_id,
                game_mode_name="fut_online_h2h", game_settings=3087,
            entry_criteria=session.entry_criteria,
            queue_capacity=session.queue_capacity,
                protocol_version=session.game_version, created_at=time.time(),
            routing_addresses={identity.persona_id: source_address},
                attributes=(("Gamemode_Name", "fut_online_h2h"),
                            ("OSDK_gameMode", "81")))
            setup = build_game_setup_notification(
                game, session.session_id, identity.persona_id,
                matchmaking_result=result)
            self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)
            for notification in self.gamemanager_setup_ids:
                peer = self.notifications.deliver(
                    GAMEMANAGER_COMPONENT, notification, setup,
                    persona_id=identity.persona_id,
                    source_address=source_address)
                emit("gamemanager-probe-setup", personaId=identity.persona_id,
                     component=GAMEMANAGER_COMPONENT, command=notification,
                     bytes=len(setup), gameId=game.game_id, peer=peer or "",
                     delivered=peer is not None)
                self._matchmaking_stop.wait(GAMEMANAGER_SETUP_SETTLE_SECONDS)
        else:
            self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)

        finished = self.game_manager.cancel_session(
            identity.persona_id, session.session_id)
        if finished is None:
            emit("gamemanager-probe-skipped", personaId=identity.persona_id,
                 matchmakingSessionId=session.session_id,
                 note="search already gone before the result was sent")
            return
        body = build_matchmaking_result_notification(
            finished.session_id, finished.persona_id, result,
            fit_score=100, max_fit_score=100,
            game_entry_type=GAME_ENTRY_TYPE_DIRECT,
            time_to_match=int(
                (time.time() - finished.created_at) * 1_000_000))
        self._arm_sweep(finished.persona_id, finished.source_address)
        self._sweep_last_id = MATCHMAKING_FAILED_NOTIFICATION
        try:
            peer = self.notifications.deliver(
                GAMEMANAGER_COMPONENT, MATCHMAKING_FAILED_NOTIFICATION, body,
                persona_id=finished.persona_id,
                source_address=finished.source_address)
            emit("gamemanager-probe-result", personaId=identity.persona_id,
                 component=GAMEMANAGER_COMPONENT,
                 command=MATCHMAKING_FAILED_NOTIFICATION,
                 matchmakingSessionId=finished.session_id,
                 matchmakingResult=MATCHMAKING_RESULT_NAMES.get(result, result),
                 rslt=result, bytes=len(body), peer=peer or "",
                 delivered=peer is not None,
                 setupIds=list(self.gamemanager_setup_ids))
            self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)
        finally:
            self._disarm_sweep()

    def _gamemanager_sweep(
        self,
        identity: Any,
        source_address: str,
        session: Any,
    ) -> None:
        local = GamePlayer(
            persona_id=identity.persona_id,
            display_name=identity.display_name,
            connection_group_id=identity.connection_group_id,
            internal_ip=source_address or "127.0.0.1",
            internal_port=3659,
            slot_id=0,
            team_index=0,
            locale=identity.locale,
        )
        opponent = GamePlayer(
            persona_id=identity.persona_id + 1,
            display_name="sweep",
            connection_group_id=identity.connection_group_id + 1,
            internal_ip="192.0.2.1",
            internal_port=3659,
            slot_id=1,
            team_index=1,
            locale=identity.locale,
        )
        game = self.games.create(
            (local, opponent),
            host_persona_id=local.persona_id,
            game_mode_name="fut_online_h2h",
            game_settings=3087,
            entry_criteria=session.entry_criteria,
            queue_capacity=session.queue_capacity,
            protocol_version=session.game_version,
            created_at=time.time(),
            routing_addresses={identity.persona_id: source_address},
            attributes=(("Gamemode_Name", "fut_online_h2h"),
                        ("OSDK_gameMode", "81")),
        )
        body = build_game_setup_notification(
            game, session.session_id, identity.persona_id)
        emit("gamemanager-sweep-start", personaId=identity.persona_id,
             ids=list(self.gamemanager_sweep_ids), gameId=game.game_id,
             matchmakingSessionId=session.session_id,
             bytes=len(body), delaySeconds=self.gamemanager_sweep_delay,
             note="synthetic NotifyGameSetup per candidate id; a wrong id "
                  "should decode to a defaulted object and do nothing")
        self._matchmaking_stop.wait(GAMEMANAGER_SWEEP_SETTLE_SECONDS)

        self._arm_sweep(identity.persona_id, source_address)
        try:
            for notification in self.gamemanager_sweep_ids:
                if self._matchmaking_stop.is_set():
                    return
                if self._sweep_reaction is not None:
                    break
                self._sweep_last_id = notification
                peer = self.notifications.deliver(
                    GAMEMANAGER_COMPONENT, notification, body,
                    persona_id=identity.persona_id,
                    source_address=source_address)
                emit("gamemanager-sweep-send", personaId=identity.persona_id,
                     component=GAMEMANAGER_COMPONENT, command=notification,
                     bytes=len(body), gameId=game.game_id,
                     peer=peer or "", delivered=peer is not None)
                self._matchmaking_stop.wait(self.gamemanager_sweep_delay)
        finally:
            self._disarm_sweep()
        if self._sweep_reaction is not None:
            after, command, peer = self._sweep_reaction
            emit("gamemanager-sweep-identified",
                 personaId=identity.persona_id, notification=after,
                 clientCommand=command, peer=peer,
                 note="this notification id is the one the client acted on")
            return
        cancelled = self.game_manager.cancel_session(
            identity.persona_id, session.session_id)
        if cancelled is None:
            emit("gamemanager-sweep-control-skipped",
                 personaId=identity.persona_id,
                 matchmakingSessionId=session.session_id,
                 note="search already gone; no control was sent")
        else:
            control = build_matchmaking_failed_notification(
                cancelled.session_id, cancelled.persona_id,
                MATCHMAKING_RESULT_SESSION_CANCELED)
            peer = self.notifications.deliver(
                GAMEMANAGER_COMPONENT, MATCHMAKING_FAILED_NOTIFICATION,
                control, persona_id=cancelled.persona_id,
                source_address=cancelled.source_address)
            emit("gamemanager-sweep-control", personaId=identity.persona_id,
                 component=GAMEMANAGER_COMPONENT,
                 command=MATCHMAKING_FAILED_NOTIFICATION,
                 matchmakingSessionId=cancelled.session_id,
                 matchmakingResult=MATCHMAKING_RESULT_NAMES[
                     MATCHMAKING_RESULT_SESSION_CANCELED],
                 bytes=len(control), peer=peer or "",
                 delivered=peer is not None,
                 note="if the client leaves the search screen here, delivery "
                      "and decoding work and the swept ids really were silent")
        emit("gamemanager-sweep-done", personaId=identity.persona_id,
             ids=list(self.gamemanager_sweep_ids))

    def _matchmaking_deadlines(self) -> None:
        while not self._matchmaking_stop.is_set():
            try:
                expired = self.game_manager.expire_due()
            except Exception as error:
                emit("matchmaking-expiry-error", error=str(error))
                expired = []
            for session in expired:
                self._complete_timed_out(session)

            if self.pairing_enabled:
                try:
                    self.pair_compatible_searches()
                except Exception as error:
                    emit("matchmaking-pair-error", error=str(error))

            deadline = self.game_manager.next_expiry()
            if deadline is None:
                wait = MATCHMAKING_TICK_SECONDS
            else:
                wait = max(0.01, min(MATCHMAKING_TICK_SECONDS,
                                     deadline - time.time()))
            self._matchmaking_stop.wait(wait)

    def _complete_timed_out(self, session: Any) -> None:
        body = build_matchmaking_failed_notification(
            session.session_id,
            session.persona_id,
            MATCHMAKING_RESULT_SESSION_TIMED_OUT,
        )
        peer = self.notifications.deliver(
            GAMEMANAGER_COMPONENT,
            MATCHMAKING_FAILED_NOTIFICATION,
            body,
            persona_id=session.persona_id,
            source_address=session.source_address,
        )
        if peer is None:
            emit("matchmaking-timeout-undeliverable",
                 personaId=session.persona_id,
                 matchmakingSessionId=session.session_id,
                 sourceAddress=session.source_address,
                 elapsedSeconds=round(time.time() - session.created_at, 3))
            return
        emit("blaze-notification", peer=peer,
             name="game-manager-matchmaking-timed-out",
             component=GAMEMANAGER_COMPONENT,
             command=MATCHMAKING_FAILED_NOTIFICATION,
             bytes=len(body),
             personaId=session.persona_id,
             matchmakingSessionId=session.session_id,
             matchmakingResult=MATCHMAKING_RESULT_NAMES[
                 MATCHMAKING_RESULT_SESSION_TIMED_OUT],
             durationSeconds=session.duration_seconds,
             elapsedSeconds=round(time.time() - session.created_at, 3))

    def server_close(self) -> None:
        self._matchmaking_stop.set()
        thread = getattr(self, "_matchmaking_thread", None)
        if thread is not None:
            thread.join(timeout=2.0)
        super().server_close()

    def verify_request(self, request, client_address):
        return access.refuse(self, client_address)

    def process_request(self, request, client_address):
        with self._connection_lock:
            if (self.max_connections
                    and self._active_connections >= self.max_connections):
                emit("blaze-connection-refused",
                     peer="%s:%s" % (client_address[0], client_address[1]),
                     active=self._active_connections,
                     limit=self.max_connections)
                self.shutdown_request(request)
                return
            self._active_connections += 1
            self._peak_connections = max(self._peak_connections,
                                         self._active_connections)
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            if self.ssl_context is not None:
                try:
                    request.settimeout(10.0)
                    request = self.ssl_context.wrap_socket(
                        request, server_side=True)
                    request.settimeout(None)
                except (ssl.SSLError, OSError) as error:
                    emit("blaze-tls-handshake-failed",
                         peer=f"{client_address[0]}:{client_address[1]}",
                         error=str(error))
                    self.shutdown_request(request)
                    return
            super().process_request_thread(request, client_address)
        finally:
            with self._connection_lock:
                self._active_connections -= 1

    def handle_error(self, request, client_address):
        emit("blaze-handler-error", peer=f"{client_address[0]}:{client_address[1]}")
