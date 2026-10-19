# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import socket
import time
import struct
from dataclasses import dataclass

HEADER_SIZE = 16
MAX_PAYLOAD_SIZE = 64 * 1024

FRAME_DEADLINE_SECONDS = 120.0

MESSAGE = 0
REPLY = 1
NOTIFICATION = 2
ERROR_REPLY = 3
PING = 4
PING_REPLY = 5

MESSAGE_TYPE_NAMES = {
    MESSAGE: "message",
    REPLY: "reply",
    NOTIFICATION: "notification",
    ERROR_REPLY: "error",
    PING: "ping",
    PING_REPLY: "ping-reply",
}


class Fire2Error(ValueError):
    pass

COMPONENT_NAMES = {
    0x0009: "Util",
    0x0001: "Authentication",
    0x0004: "GameManager",
    0x0007: "Stats",
    0x000F: "Messaging",
    0x001C: "GameReporting",
    0x0019: "AssociationLists",
    0x0801: "Redirector",
    0x0A: "Census",
    0x7802: "UserSessions",
    0x7D0: "Clubs",
}


@dataclass(frozen=True)
class Fire2Header:
    payload_size: int
    metadata_size: int
    component: int
    command: int
    msg_num: int
    msg_type: int
    options: int = 0

    @property
    def component_name(self) -> str:
        return COMPONENT_NAMES.get(self.component, f"0x{self.component:04X}")

    @property
    def type_name(self) -> str:
        return MESSAGE_TYPE_NAMES.get(self.msg_type, f"unknown({self.msg_type})")

    def as_dict(self) -> dict:
        return {
            "payloadSize": self.payload_size,
            "metadataSize": self.metadata_size,
            "component": self.component,
            "componentName": self.component_name,
            "command": self.command,
            "msgNum": self.msg_num,
            "msgType": self.msg_type,
            "msgTypeName": self.type_name,
            "options": self.options,
        }


def parse_header(data: bytes) -> Fire2Header | None:
    if len(data) < HEADER_SIZE:
        return None
    payload_size, metadata_size, component, command = struct.unpack_from(">IHHH", data, 0)
    msg_num = (data[11] << 8) | data[12]
    flags = data[13]
    return Fire2Header(
        payload_size=payload_size,
        metadata_size=metadata_size,
        component=component,
        command=command,
        msg_num=msg_num,
        msg_type=flags >> 5,
        options=flags & 0x1F,
    )


def build_frame(
    component: int,
    command: int,
    msg_type: int,
    msg_num: int,
    payload: bytes,
    *,
    metadata_size: int = 0,
    options: int = 0,
) -> bytes:
    flags = ((msg_type & 0x7) << 5) | (options & 0x1F)
    header = struct.pack(">IHHH", len(payload), metadata_size, component, command)
    header += bytes([
        0,
        (msg_num >> 8) & 0xFF,
        msg_num & 0xFF,
        flags,
        0,
        0,
    ])
    return header + payload


def build_reply(request: Fire2Header, payload: bytes) -> bytes:
    return build_frame(request.component, request.command, REPLY, request.msg_num, payload)


def build_error(request: Fire2Header, payload: bytes = b"") -> bytes:
    return build_frame(request.component, request.command, ERROR_REPLY, request.msg_num, payload)


def build_ping_reply(request: Fire2Header, payload: bytes = b"") -> bytes:
    return build_frame(request.component, request.command, PING_REPLY, request.msg_num, payload)


def build_notification(component: int, command: int, payload: bytes, msg_num: int = 0) -> bytes:
    return build_frame(component, command, NOTIFICATION, msg_num, payload)


class Fire2Idle(Exception):
    pass


def _receive_exact(sock: socket.socket, length: int, *, allow_idle: bool = False,
                   deadline: float | None = None) -> tuple[bytes, float | None]:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        if deadline is not None and time.monotonic() >= deadline:
            raise Fire2Error(
                "a frame declaring %d bytes exceeded its %.0f-second deadline"
                % (length, FRAME_DEADLINE_SECONDS))
        try:
            chunk = sock.recv(remaining)
        except (TimeoutError, socket.timeout):
            if not chunks and allow_idle:
                raise Fire2Idle from None
            if deadline is not None and time.monotonic() >= deadline:
                raise Fire2Error(
                    "a frame declaring %d bytes stalled with %d still missing"
                    % (length, remaining))
            continue
        if not chunk:
            break
        if deadline is None:
            deadline = time.monotonic() + FRAME_DEADLINE_SECONDS
        elif time.monotonic() >= deadline:
            raise Fire2Error(
                "a frame declaring %d bytes exceeded its %.0f-second deadline"
                % (length, FRAME_DEADLINE_SECONDS))
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks), deadline


def receive_exact(sock: socket.socket, length: int, *, allow_idle: bool = False) -> bytes:
    data, _deadline = _receive_exact(sock, length, allow_idle=allow_idle)
    return data


def receive_frame(sock: socket.socket) -> tuple[Fire2Header | None, bytes, bytes]:
    head, deadline = _receive_exact(sock, HEADER_SIZE, allow_idle=True)
    if len(head) < HEADER_SIZE:
        return None, b"", head
    header = parse_header(head)
    assert header is not None
    if header.payload_size > MAX_PAYLOAD_SIZE:
        raise Fire2Error(
            f"declared payload size {header.payload_size} exceeds "
            f"the {MAX_PAYLOAD_SIZE}-byte safety limit"
        )
    payload, _deadline = _receive_exact(
        sock, header.payload_size, deadline=deadline)
    return header, payload, head + payload
