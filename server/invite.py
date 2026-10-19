# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import base64
import json
import secrets

from config import valid_advertised_host

INVITE_VERSION = 1
INVITE_PREFIX = "FUT1-"

GENERATED_PASSWORD_BYTES = 18
MAXIMUM_HOST_BYTES = 16
MAXIMUM_CODE_LENGTH = 16 * 1024
MAXIMUM_SECRET_LENGTH = 512
MAXIMUM_PROFILE_LENGTH = 128


def valid_host(host: str) -> bool:
    if not valid_advertised_host(host):
        return False
    try:
        encoded = host.encode("ascii")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= MAXIMUM_HOST_BYTES


def _normalise_and_validate(payload: dict) -> dict:
    version = payload.get("v")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("invalid invite version")
    if version != INVITE_VERSION:
        raise ValueError("unsupported invite version %r" % (version,))

    host = payload.get("host")
    if not valid_host(host):
        raise ValueError("invalid invite host")

    port_names = ("red", "acc", "blz", "fut", "cdn", "knock")
    for field in port_names:
        port = payload.get(field)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("invalid invite port %s" % field)

    token = payload.get("token")
    username = payload.get("user")
    password = payload.get("pass")
    if (not isinstance(token, str) or not token.strip() or
            len(token) > MAXIMUM_SECRET_LENGTH):
        raise ValueError("invalid enrollment token")
    if (not isinstance(username, str) or not username or
            not isinstance(password, str) or not password or
            len(username) > MAXIMUM_SECRET_LENGTH or
            len(password) > MAXIMUM_SECRET_LENGTH):
        raise ValueError("invalid invite credentials")
    if "\n" in username or "\r" in username or "\n" in password or "\r" in password:
        raise ValueError("invite credentials contain a newline")

    pin_value = payload.get("pin")
    if not isinstance(pin_value, str):
        raise ValueError("invalid certificate pin")
    clean_pin = pin_value.replace(":", "").strip()
    if len(clean_pin) != 64 or any(character not in "0123456789abcdefABCDEF"
                                   for character in clean_pin):
        raise ValueError("invalid certificate pin")

    name = payload.get("name")
    if name is None or isinstance(name, str) and not name.strip():
        name = "Friends Server"
    elif not isinstance(name, str):
        raise ValueError("invalid invite profile name")
    else:
        name = name[:MAXIMUM_PROFILE_LENGTH]

    normalised = dict(payload)
    normalised["name"] = name
    normalised["pin"] = clean_pin.upper()
    return normalised


def generate_password() -> str:
    return secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)


def encode(
    *,
    name: str,
    host: str,
    redirector_port: int,
    accounts_port: int,
    blaze_port: int,
    fut_port: int,
    cdn_port: int,
    knock_port: int,
    token: str,
    username: str,
    password: str,
    pin: str,
) -> str:
    payload = {
        "v": INVITE_VERSION,
        "name": name,
        "host": host,
        "red": redirector_port,
        "acc": accounts_port,
        "blz": blaze_port,
        "fut": fut_port,
        "cdn": cdn_port,
        "knock": knock_port,
        "token": token,
        "user": username,
        "pass": password,
        "pin": pin,
    }
    payload = _normalise_and_validate(payload)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return INVITE_PREFIX + base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode(code: str) -> dict:
    if not isinstance(code, str) or len(code) > MAXIMUM_CODE_LENGTH:
        raise ValueError("corrupted invite code")
    text = "".join(code.split())
    if not text.upper().startswith(INVITE_PREFIX):
        raise ValueError("not an invite code")

    body = text[len(INVITE_PREFIX):]
    padding = "=" * (-len(body) % 4)
    try:
        raw = base64.b64decode(body + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("corrupted invite code") from error

    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise ValueError("corrupted invite code") from error

    if not isinstance(payload, dict):
        raise ValueError("corrupted invite code")
    return _normalise_and_validate(payload)
