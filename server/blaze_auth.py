# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import time
from dataclasses import dataclass, replace
import secrets
import threading
from typing import Any

import tdf


USER_SESSIONS_COMPONENT = 0x7802
CONNECTION_GROUP_TYPE = 2
LOCAL_CONNECTION_GROUP_ID = 0x0540A9C0
MAX_CONNECTION_GROUP_ID = 0x7FFFFFFF


@dataclass(frozen=True)
class LoginIdentity:
    persona_id: int
    display_name: str
    locale: int
    login_time: int
    connection_group_id: int = LOCAL_CONNECTION_GROUP_ID


class BlazeSessionRegistry:

    def __init__(
        self,
        first_group_id: int | None = None,
        store: Any = None,
    ) -> None:
        if first_group_id is None:
            first_group_id = secrets.randbelow(MAX_CONNECTION_GROUP_ID) + 1
        if not 1 <= int(first_group_id) <= MAX_CONNECTION_GROUP_ID:
            raise ValueError("first connection-group id must be a positive int32")
        self._next_group_id = int(first_group_id)
        self._by_group: dict[int, tuple[LoginIdentity, int]] = {}
        self._by_persona: dict[int, int] = {}
        self._lock = threading.Lock()
        self._store = store
        self._load()

    def _load(self) -> None:
        if self._store is None:
            return
        try:
            rows = self._store.blaze_sessions()
        except Exception:
            return
        for row in rows:
            identity = LoginIdentity(
                persona_id=int(row["persona_id"]),
                display_name=str(row["display_name"]),
                locale=int(row["locale"]),
                login_time=int(row["login_time"]),
                connection_group_id=int(row["group_id"]),
            )
            self._by_group[identity.connection_group_id] = (
                identity, int(row["expires_at"]))
            self._by_persona[identity.persona_id] = identity.connection_group_id

    def register(self, identity: LoginIdentity, expires_at: int) -> LoginIdentity:
        current = int(time.time())
        expires_at = int(expires_at)
        if expires_at <= current:
            raise ValueError("cannot register an expired Blaze identity")
        with self._lock:
            self._prune_locked(current)
            group_id = self._by_persona.get(identity.persona_id)
            if group_id is None:
                group_id = self._allocate_id_locked()
                self._by_persona[identity.persona_id] = group_id
            registered = replace(identity, connection_group_id=group_id)
            self._by_group[group_id] = (registered, expires_at)
        if self._store is not None:
            try:
                self._store.save_blaze_session(
                    group_id, registered.persona_id, registered.display_name,
                    registered.locale, registered.login_time, expires_at)
            except Exception:
                pass
        return registered

    def resolve_persona(self, persona_id: int) -> LoginIdentity | None:
        current = int(time.time())
        with self._lock:
            self._prune_locked(current)
            group_id = self._by_persona.get(int(persona_id))
            if group_id is None:
                return None
            entry = self._by_group.get(group_id)
            return entry[0] if entry is not None else None

    def resolve(self, connection_group_id: int) -> LoginIdentity | None:
        current = int(time.time())
        with self._lock:
            self._prune_locked(current)
            entry = self._by_group.get(int(connection_group_id))
            return entry[0] if entry is not None else None

    def _prune_locked(self, current: int) -> None:
        expired = [
            group_id
            for group_id, (_identity, expiry) in self._by_group.items()
            if expiry <= current
        ]
        for group_id in expired:
            identity, _expiry = self._by_group.pop(group_id)
            if self._by_persona.get(identity.persona_id) == group_id:
                del self._by_persona[identity.persona_id]

    def _allocate_id_locked(self) -> int:
        for _ in range(MAX_CONNECTION_GROUP_ID):
            candidate = self._next_group_id
            self._next_group_id = (
                1 if candidate >= MAX_CONNECTION_GROUP_ID else candidate + 1
            )
            if candidate not in self._by_group:
                return candidate
        raise RuntimeError("all Blaze connection-group ids are in use")


def parse_login_code(payload: bytes) -> str:
    try:
        document = tdf.summarise(tdf.decode(payload))
    except tdf.TdfError:
        return ""
    code = document.get("AUTH")
    return code if isinstance(code, str) else ""


def build_login_response(identity: LoginIdentity) -> bytes:
    persona_id = identity.persona_id
    session_key = f"{persona_id:X}"
    persona = (
        tdf.string(b"DSNM", identity.display_name)
        + tdf.u32(b"LAST", 0)
        + tdf.u32(b"PID", persona_id)
        + tdf.u32(b"PLAT", 4)
        + tdf.u32(b"STAS", 0)
        + tdf.u32(b"XREF", persona_id)
    )
    session = (
        tdf.u32(b"1CON", 0)
        + tdf.u32(b"BUID", persona_id)
        + tdf.boolean(b"FRST", False)
        + tdf.string(b"KEY", session_key)
        + tdf.u32(b"LLOG", identity.login_time)
        + tdf.string(b"MAIL", "local@fifa17.invalid")
        + tdf.group(b"PDTL", persona)
        + tdf.u32(b"UID", persona_id)
    )
    return (
        tdf.u32(b"CNTX", 0)
        + tdf.u32(b"ERRC", 0)
        + tdf.string(b"SKEY", session_key)
        + tdf.boolean(b"ANON", False)
        + tdf.u32(b"NTOS", 0)
        + tdf.group(b"SESS", session)
        + tdf.boolean(b"SPAM", False)
        + tdf.boolean(b"UNDR", False)
    )


def build_user_authenticated(identity: LoginIdentity) -> bytes:
    persona_id = identity.persona_id
    return (
        tdf.u32(b"1CON", 0)
        + tdf.u32(b"ALOC", identity.locale)
        + tdf.u32(b"BUID", persona_id)
        + tdf.object_id(
            b"CGID",
            USER_SESSIONS_COMPONENT,
            CONNECTION_GROUP_TYPE,
            identity.connection_group_id,
        )
        + tdf.string(b"DSNM", identity.display_name)
        + tdf.boolean(b"FRST", False)
        + tdf.string(b"KEY", f"{persona_id:X}")
        + tdf.u32(b"LAST", 0)
        + tdf.u32(b"LLOG", identity.login_time)
        + tdf.string(b"MAIL", "local@fifa17.invalid")
        + tdf.string(b"NASP", "cem_ea_id")
        + tdf.u32(b"PID", persona_id)
        + tdf.u32(b"PLAT", 4)
        + tdf.u32(b"UID", persona_id)
        + tdf.u32(b"USTP", 0)
        + tdf.u32(b"XREF", persona_id)
    )


def _build_extended_session_data(identity: LoginIdentity) -> bytes:
    qos = (
        tdf.u32(b"BWHR", 0)
        + tdf.u32(b"DBPS", 0)
        + tdf.u32(b"NAHR", 0)
        + tdf.u32(b"NATT", 0)
        + tdf.u32(b"UBPS", 0)
    )
    empty_ip = (
        tdf.u32(b"IP", 0)
        + tdf.u32(b"MACI", 0)
        + tdf.u16(b"PORT", 0)
    )
    address = tdf.union(
        b"ADDR", 2,
        tdf.group(
            b"VALU",
            tdf.group(b"EXIP", empty_ip)
            + tdf.group(b"INIP", empty_ip)
            + tdf.u32(b"MACI", 0),
        ),
    )
    return (
        address
        + tdf.string(b"BPS", "")
        + tdf.string(b"CTY", "")
        + tdf.unset_variable(b"CVAR")
        + tdf.map_u32(b"DMAP", ((0x78020001, 0),))
        + tdf.u32(b"HWFG", 0)
        + tdf.string(b"ISP", "")
        + tdf.list_u32(b"PSLM", ())
        + tdf.group(b"QDAT", qos)
        + tdf.string(b"TZ", "")
        + tdf.u32(b"UATT", 0)
        + tdf.list_object_ids(
            b"ULST",
            ((USER_SESSIONS_COMPONENT, CONNECTION_GROUP_TYPE,
              identity.connection_group_id),),
        )
    )


def build_user_added(identity: LoginIdentity) -> bytes:
    persona_id = identity.persona_id
    user = (
        tdf.u32(b"AID", persona_id)
        + tdf.u32(b"ALOC", identity.locale)
        + tdf.blob(b"EXBB")
        + tdf.u32(b"EXID", persona_id)
        + tdf.u32(b"ID", persona_id)
        + tdf.string(b"NAME", identity.display_name)
        + tdf.string(b"NASP", "cem_ea_id")
        + tdf.u32(b"ORIG", persona_id)
        + tdf.u32(b"PIDI", 0)
    )
    return (tdf.group(b"DATA", _build_extended_session_data(identity))
            + tdf.group(b"USER", user))


def build_user_extended_data_update(identity: LoginIdentity) -> bytes:
    return (
        tdf.group(b"DATA", _build_extended_session_data(identity))
        + tdf.boolean(b"SUBS", True)
        + tdf.u32(b"USID", identity.persona_id)
    )


def identity_from_code(
    store: Any,
    code: str,
    locale: int,
    accepted_codes: dict[str, tuple[int, int]],
) -> LoginIdentity | None:
    now = int(time.time())
    cached = accepted_codes.get(code)
    if cached is not None and cached[1] > now:
        persona_id = cached[0]
    else:
        row = store.consume_auth_code(code) if store is not None and code else None
        if row is None:
            return None
        persona_id = int(row["persona_id"])
        accepted_codes[code] = (persona_id, int(row["expires_at"]))
    account = store.account_by_persona(persona_id) if store is not None else None
    if account is None or not bool(account["approved"]):
        return None
    return LoginIdentity(
        persona_id=persona_id,
        display_name=str(account["display_name"]),
        locale=locale,
        login_time=now,
    )
