# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import struct
from typing import Any


VAR_INT = 0x0
STRING = 0x1
BLOB = 0x2
GROUP = 0x3
LIST = 0x4
MAP = 0x5
TAGGED_UNION = 0x6
VARIABLE = 0x7
OBJECT_TYPE = 0x8
OBJECT_ID = 0x9
FLOAT = 0xA

TYPE_NAMES = {
    VAR_INT: "varint",
    STRING: "string",
    BLOB: "blob",
    GROUP: "group",
    LIST: "list",
    MAP: "map",
    TAGGED_UNION: "union",
    VARIABLE: "variable",
    OBJECT_TYPE: "object-type",
    OBJECT_ID: "object-id",
    FLOAT: "float",
}

FLOAT_SIZE = 4

GROUP_TERMINATOR = b"\x00"
UNION_UNSET = 0x7F


class TdfError(ValueError):
    pass


def encode_tag(tag: bytes, value_type: int) -> bytes:
    if not tag or len(tag) > 4:
        raise TdfError(f"invalid TDF tag {tag!r}")
    out = [0, 0, 0, value_type & 0xFF]
    length = len(tag)
    if length > 0:
        out[0] |= (tag[0] & 0x40) << 1
        out[0] |= (tag[0] & 0x10) << 2
        out[0] |= (tag[0] & 0x0F) << 2
    if length > 1:
        out[0] |= (tag[1] & 0x40) >> 5
        out[0] |= (tag[1] & 0x10) >> 4
        out[1] |= (tag[1] & 0x0F) << 4
    if length > 2:
        out[1] |= (tag[2] & 0x40) >> 3
        out[1] |= (tag[2] & 0x10) >> 2
        out[1] |= (tag[2] & 0x0C) >> 2
        out[2] |= (tag[2] & 0x03) << 6
    if length > 3:
        out[2] |= (tag[3] & 0x40) >> 1
        out[2] |= tag[3] & 0x1F
    return bytes(out)


def decode_tag(encoded: bytes) -> str:
    if len(encoded) != 3:
        raise TdfError("a TDF tag must contain exactly three encoded bytes")
    values = (
        (encoded[0] >> 2) & 0x3F,
        ((encoded[0] & 0x03) << 4) | ((encoded[1] >> 4) & 0x0F),
        ((encoded[1] & 0x0F) << 2) | ((encoded[2] >> 6) & 0x03),
        encoded[2] & 0x3F,
    )
    return "".join(chr(value + 0x20) for value in values).rstrip()


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise TdfError("negative TDF varints are not used by this protocol")
    if value < 0x40:
        return bytes([value])
    out = bytearray()
    out.append((value & 0x3F) | 0x80)
    value >>= 6
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def decode_varint(payload: bytes, offset: int = 0) -> tuple[int, int]:
    if offset >= len(payload):
        raise TdfError("missing TDF varint")
    first = payload[offset]
    offset += 1
    value = first & 0x3F
    shift = 6
    current = first
    while current & 0x80:
        if offset >= len(payload):
            raise TdfError("truncated TDF varint")
        current = payload[offset]
        offset += 1
        value |= (current & 0x7F) << shift
        shift += 7
    return value, offset


def _decode_value(payload: bytes, offset: int, value_type: int) -> tuple[Any, int]:
    if value_type == VAR_INT:
        return decode_varint(payload, offset)

    if value_type == STRING:
        length, offset = decode_varint(payload, offset)
        end = offset + length
        if length < 1 or end > len(payload) or payload[end - 1] != 0:
            raise TdfError("invalid or truncated TDF string")
        try:
            return payload[offset : end - 1].decode("utf-8"), end
        except UnicodeDecodeError as error:
            raise TdfError("invalid UTF-8 in TDF string") from error

    if value_type == BLOB:
        length, offset = decode_varint(payload, offset)
        end = offset + length
        if end > len(payload):
            raise TdfError("truncated TDF blob")
        return payload[offset:end], end

    if value_type == GROUP:
        return _decode_fields(payload, offset, stop_at_group_end=True)

    if value_type == LIST:
        if offset >= len(payload):
            raise TdfError("missing TDF list element type")
        element_type = payload[offset]
        count, offset = decode_varint(payload, offset + 1)
        values = []
        for _ in range(count):
            value, offset = _decode_value(payload, offset, element_type)
            values.append(value)
        return {"elementType": element_type, "values": values}, offset

    if value_type == MAP:
        if offset + 2 > len(payload):
            raise TdfError("missing TDF map key/value types")
        key_type, mapped_type = payload[offset : offset + 2]
        count, offset = decode_varint(payload, offset + 2)
        values = []
        for _ in range(count):
            key, offset = _decode_value(payload, offset, key_type)
            value, offset = _decode_value(payload, offset, mapped_type)
            values.append((key, value))
        return {"keyType": key_type, "valueType": mapped_type, "values": values}, offset

    if value_type == TAGGED_UNION:
        if offset >= len(payload):
            raise TdfError("missing TDF tagged-union discriminator")
        active_member = payload[offset]
        offset += 1
        if active_member == UNION_UNSET:
            return {"activeMember": active_member, "field": None}, offset
        fields, offset = _decode_fields(payload, offset, max_fields=1)
        if len(fields) != 1:
            raise TdfError("tagged union did not contain exactly one active field")
        return {"activeMember": active_member, "field": fields[0]}, offset

    if value_type == VARIABLE:
        is_set, offset = decode_varint(payload, offset)
        if not is_set:
            return {"tdfId": None, "fields": []}, offset
        tdf_id, offset = decode_varint(payload, offset)
        fields, offset = _decode_fields(payload, offset, stop_at_group_end=True)
        return {"tdfId": tdf_id, "fields": fields}, offset

    if value_type == OBJECT_TYPE:
        component, offset = decode_varint(payload, offset)
        entity_type, offset = decode_varint(payload, offset)
        return {"component": component, "entityType": entity_type}, offset

    if value_type == FLOAT:
        end = offset + FLOAT_SIZE
        if end > len(payload):
            raise TdfError("truncated TDF float")
        return struct.unpack(">f", payload[offset:end])[0], end

    if value_type == OBJECT_ID:
        component, offset = decode_varint(payload, offset)
        entity_type, offset = decode_varint(payload, offset)
        entity_id, offset = decode_varint(payload, offset)
        return {"component": component, "entityType": entity_type, "entityId": entity_id}, offset

    raise TdfError(f"unsupported TDF value type 0x{value_type:02x}")


def _decode_fields(
    payload: bytes,
    offset: int = 0,
    *,
    stop_at_group_end: bool = False,
    max_fields: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    fields: list[dict[str, Any]] = []
    while offset < len(payload) and (max_fields is None or len(fields) < max_fields):
        if payload[offset] == 0:
            if not stop_at_group_end:
                raise TdfError(f"unexpected TDF group terminator at offset {offset}")
            return fields, offset + 1
        if offset + 4 > len(payload):
            raise TdfError("truncated TDF field header")
        tag = decode_tag(payload[offset : offset + 3])
        value_type = payload[offset + 3]
        value, next_offset = _decode_value(payload, offset + 4, value_type)
        fields.append({"tag": tag, "type": value_type, "value": value})
        offset = next_offset
    if stop_at_group_end and max_fields is None:
        raise TdfError("unterminated TDF group")
    return fields, offset


def decode(payload: bytes) -> list[dict[str, Any]]:
    fields, offset = _decode_fields(payload)
    if offset != len(payload):
        raise TdfError(f"trailing TDF bytes at offset {offset}")
    return fields


def summarise(fields: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in fields:
        tag = field["tag"]
        value = field["value"]
        if field["type"] == GROUP and isinstance(value, list):
            out[tag] = summarise(value)
        elif field["type"] == BLOB and isinstance(value, bytes):
            out[tag] = f"<{len(value)} bytes>"
        elif field["type"] == VARIABLE and isinstance(value, dict):
            out[tag] = (
                None if value.get("tdfId") is None
                else {"tdfId": value["tdfId"], "fields": summarise(value["fields"])}
            )
        elif field["type"] == TAGGED_UNION and isinstance(value, dict):
            inner = value.get("field")
            out[tag] = {
                "activeMember": value.get("activeMember"),
                "field": summarise([inner]) if inner else None,
            }
        else:
            out[tag] = value
    return out


def raw_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return encode_varint(len(encoded) + 1) + encoded + b"\x00"


def u32(tag: bytes, value: int) -> bytes:
    return encode_tag(tag, VAR_INT) + encode_varint(value)


def u16(tag: bytes, value: int) -> bytes:
    return encode_tag(tag, VAR_INT) + encode_varint(value)


def boolean(tag: bytes, value: bool) -> bytes:
    return encode_tag(tag, VAR_INT) + bytes([1 if value else 0])


def string(tag: bytes, value: str) -> bytes:
    return encode_tag(tag, STRING) + raw_string(value)


def blob(tag: bytes, value: bytes = b"") -> bytes:
    return encode_tag(tag, BLOB) + encode_varint(len(value)) + value


def float32(tag: bytes, value: float) -> bytes:
    return encode_tag(tag, FLOAT) + struct.pack(">f", float(value))


def object_id(tag: bytes, component: int, entity_type: int, entity_id: int) -> bytes:
    return (
        encode_tag(tag, OBJECT_ID)
        + encode_varint(component)
        + encode_varint(entity_type)
        + encode_varint(entity_id)
    )


def group(tag: bytes, body: bytes) -> bytes:
    return encode_tag(tag, GROUP) + body + GROUP_TERMINATOR


def union(tag: bytes, active_member: int, body: bytes = b"") -> bytes:
    return encode_tag(tag, TAGGED_UNION) + bytes([active_member]) + body


def list_u32(tag: bytes, values: list[int] | tuple[int, ...]) -> bytes:
    return (
        encode_tag(tag, LIST)
        + bytes([VAR_INT])
        + encode_varint(len(values))
        + b"".join(encode_varint(value) for value in values)
    )


def list_strings(tag: bytes, values: list[str] | tuple[str, ...]) -> bytes:
    return (
        encode_tag(tag, LIST)
        + bytes([STRING])
        + encode_varint(len(values))
        + b"".join(raw_string(value) for value in values)
    )


def list_groups(tag: bytes, values: list[bytes] | tuple[bytes, ...]) -> bytes:
    return (
        encode_tag(tag, LIST)
        + bytes([GROUP])
        + encode_varint(len(values))
        + b"".join(value + GROUP_TERMINATOR for value in values)
    )


def list_object_ids(
    tag: bytes,
    values: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...],
) -> bytes:
    return (
        encode_tag(tag, LIST)
        + bytes([OBJECT_ID])
        + encode_varint(len(values))
        + b"".join(
            encode_varint(component)
            + encode_varint(entity_type)
            + encode_varint(entity_id)
            for component, entity_type, entity_id in values
        )
    )


def map_strings(tag: bytes, values: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> bytes:
    return (
        encode_tag(tag, MAP)
        + bytes([STRING, STRING])
        + encode_varint(len(values))
        + b"".join(raw_string(key) + raw_string(value) for key, value in values)
    )


def map_u32(tag: bytes, values: list[tuple[int, int]] | tuple[tuple[int, int], ...]) -> bytes:
    return (
        encode_tag(tag, MAP)
        + bytes([VAR_INT, VAR_INT])
        + encode_varint(len(values))
        + b"".join(encode_varint(key) + encode_varint(value) for key, value in values)
    )


def empty_list(tag: bytes, value_type: int) -> bytes:
    return encode_tag(tag, LIST) + bytes([value_type]) + encode_varint(0)


def empty_map(tag: bytes, key_type: int, value_type: int) -> bytes:
    return encode_tag(tag, MAP) + bytes([key_type, value_type]) + encode_varint(0)


def unset_variable(tag: bytes) -> bytes:
    return encode_tag(tag, VARIABLE) + encode_varint(0)


def variable(tag: bytes, tdf_id: int, body: bytes) -> bytes:
    return (encode_tag(tag, VARIABLE) + encode_varint(1)
            + encode_varint(tdf_id) + body + b"\x00")
