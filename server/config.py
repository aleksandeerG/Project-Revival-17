# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import ipaddress
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import fut_economy

LOOPBACK = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"

PROFILE_LOCAL = "local"
PROFILE_SERVER = "server"

DEFAULT_ACCOUNTS_PORT = 5139
DEFAULT_REDIRECTOR_PORT = 42230
DEFAULT_BLAZE_PORT = 44321
DEFAULT_FUT_PORT = 8080

PROTOCOL_VERSION = "1"
CONTENT_VERSION = "1"

LAUNCHER_VERSION = "0.1.0"
MINIMUM_LAUNCHER_VERSION = "0.1.0"

ADVERTISE_FIELDS = (
    "advertise_accounts",
    "advertise_blaze",
    "advertise_fut",
    "advertise_content",
)

_PORT_FIELDS = ("accounts_port", "redirector_port", "blaze_port", "fut_port")
_SCALAR_FIELDS = ("bind_host", "status_url", "protocol_version",
                  "content_version", "launcher_version",
                  "minimum_launcher_version")
_LIST_FIELDS = ("allow", "operator_allow")
_PROFILE_KEYS = frozenset(
    ADVERTISE_FIELDS + _PORT_FIELDS + _SCALAR_FIELDS + _LIST_FIELDS
    + ("advertise", "bind"))
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")

# Top-level [economy] keys and their bounds. Server-wide, not per profile:
# every profile shares one club database.
_ECONOMY_BOUNDS = {
    "starting_coins": (0, fut_economy.MAX_BALANCE),
    "starting_points": (0, fut_economy.MAX_BALANCE),
    "coin_reward_multiplier": (fut_economy.MIN_MULTIPLIER,
                               fut_economy.MAX_MULTIPLIER),
    "offline_competition_reward_multiplier": (fut_economy.MIN_MULTIPLIER,
                                              fut_economy.MAX_MULTIPLIER),
    "online_competition_reward_multiplier": (fut_economy.MIN_MULTIPLIER,
                                             fut_economy.MAX_MULTIPLIER),
}


@dataclass(frozen=True)
class EconomyConfig:
    starting_coins: int = fut_economy.DEFAULT_STARTING_CREDITS
    starting_points: int = fut_economy.DEFAULT_STARTING_POINTS
    coin_reward_multiplier: int = fut_economy.DEFAULT_COIN_REWARD_MULTIPLIER
    offline_competition_reward_multiplier: int = (
        fut_economy.DEFAULT_OFFLINE_COMPETITION_REWARD_MULTIPLIER)
    online_competition_reward_multiplier: int = (
        fut_economy.DEFAULT_ONLINE_COMPETITION_REWARD_MULTIPLIER)

    def apply(self) -> None:
        fut_economy.configure(
            starting_credits=self.starting_coins,
            starting_points=self.starting_points,
            coin_reward_multiplier=self.coin_reward_multiplier,
            offline_competition_reward_multiplier=(
                self.offline_competition_reward_multiplier),
            online_competition_reward_multiplier=(
                self.online_competition_reward_multiplier))

    def summary(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in _ECONOMY_BOUNDS}


def _economy(values: object, where: str) -> EconomyConfig:
    if not isinstance(values, dict):
        raise ValueError("[economy] in %s must be a table" % where)
    unknown = sorted(set(values) - set(_ECONOMY_BOUNDS))
    if unknown:
        raise ValueError("unknown economy setting%s in %s: %s"
                         % ("" if len(unknown) == 1 else "s", where,
                            ", ".join(unknown)))
    for key, value in values.items():
        low, high = _ECONOMY_BOUNDS[key]
        fut_economy.check_whole_number("economy.%s" % key, value, low, high)
    return EconomyConfig(**values)


def valid_host(host: str) -> bool:
    if not isinstance(host, str) or host != host.strip():
        return False
    if "%" in host:
        return False
    try:
        encoded = host.encode("ascii")
    except UnicodeEncodeError:
        return False
    if not encoded or len(encoded) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host[:-1].split(".") if host.endswith(".") else host.split(".")
        return bool(labels) and all(_DNS_LABEL.fullmatch(label) for label in labels)


def valid_advertised_host(host: str) -> bool:
    if not valid_host(host):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not address.is_unspecified and not address.is_multicast


@dataclass(frozen=True)
class ServiceConfig:

    profile: str = PROFILE_LOCAL
    bind_host: str = LOOPBACK
    accounts_port: int = DEFAULT_ACCOUNTS_PORT
    redirector_port: int = DEFAULT_REDIRECTOR_PORT
    blaze_port: int = DEFAULT_BLAZE_PORT
    fut_port: int = DEFAULT_FUT_PORT
    advertise_accounts: str = LOOPBACK
    advertise_blaze: str = LOOPBACK
    advertise_fut: str = LOOPBACK
    advertise_content: str = LOOPBACK
    status_url: str = ""
    protocol_version: str = PROTOCOL_VERSION
    content_version: str = CONTENT_VERSION
    launcher_version: str = LAUNCHER_VERSION
    minimum_launcher_version: str = MINIMUM_LAUNCHER_VERSION
    allow: tuple[str, ...] = ()
    operator_allow: tuple[str, ...] = (
        "127.0.0.1", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "fc00::/7", "fe80::/10")
    economy: EconomyConfig = EconomyConfig()

    @property
    def fut_base_url(self) -> str:
        return "%s://%s:%d/" % (
            "http" if self.binds_loopback_only else "https",
            self.advertise_fut, self.fut_port)

    @property
    def content_base_url(self) -> str:
        return "%s://%s:%d/" % (
            "http" if self.binds_loopback_only else "https",
            self.advertise_content, self.fut_port)

    @property
    def require_transport_tls(self) -> bool:
        return not self.binds_loopback_only

    @property
    def binds_loopback_only(self) -> bool:
        return is_loopback(self.bind_host)

    def advertised_ip_addresses(self) -> tuple[str, ...]:
        found: list[str] = []
        for field in ADVERTISE_FIELDS:
            value = getattr(self, field)
            try:
                ipaddress.IPv4Address(value)
            except ValueError:
                continue
            if value not in found:
                found.append(value)
        return tuple(found)

    def advertised_certificate_names(self) -> tuple[str, ...]:
        found: list[str] = []
        for field in ADVERTISE_FIELDS:
            value = str(getattr(self, field) or "").strip()
            if value and value not in found:
                found.append(value)
        return tuple(found)

    def summary(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "bind": self.bind_host,
            "ports": {
                "accounts": self.accounts_port,
                "redirector": self.redirector_port,
                "blaze": self.blaze_port,
                "fut": self.fut_port,
            },
            "advertise": {
                "accounts": self.advertise_accounts,
                "blaze": self.advertise_blaze,
                "fut": self.advertise_fut,
                "content": self.advertise_content,
            },
            "fut_base_url": self.fut_base_url,
            "transport": {
                "accounts": "tls" if self.require_transport_tls else "dual",
                "redirector": "tls",
                "blaze": "tls" if self.require_transport_tls else "tcp",
                "fut": "tls" if self.require_transport_tls else "dual",
                "knock": "tls",
            },
            "status_url": self.status_url,
            "protocol_version": self.protocol_version,
            "content_version": self.content_version,
            "economy": self.economy.summary(),
        }


def is_loopback(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


BUILTIN_PROFILES: dict[str, dict[str, object]] = {
    PROFILE_LOCAL: {"bind": LOOPBACK, "advertise": LOOPBACK},
    PROFILE_SERVER: {"bind": ALL_INTERFACES, "advertise": ""},
}


def _apply(config: ServiceConfig, values: dict[str, object],
           where: str) -> ServiceConfig:
    unknown = sorted(set(values) - _PROFILE_KEYS)
    if unknown:
        raise ValueError("unknown setting%s in %s: %s"
                         % ("" if len(unknown) == 1 else "s", where,
                            ", ".join(unknown)))
    changes: dict[str, object] = {}
    if "bind" in values:
        changes["bind_host"] = str(values["bind"])
    if "advertise" in values:
        for field in ADVERTISE_FIELDS:
            changes[field] = str(values["advertise"])
    for field in ADVERTISE_FIELDS:
        if field in values:
            changes[field] = str(values[field])
    for field in _PORT_FIELDS:
        if field in values:
            changes[field] = int(values[field])
    for field in _SCALAR_FIELDS:
        if field in values:
            changes[field] = str(values[field])
    for field in _LIST_FIELDS:
        if field in values:
            raw = values[field]
            if isinstance(raw, str):
                raw = [part for part in raw.replace(",", " ").split() if part]
            if not isinstance(raw, (list, tuple)):
                raise ValueError("%s in %s must be a list of addresses, "
                                 "networks or hostnames" % (field, where))
            changes[field] = tuple(str(item).strip() for item in raw
                                   if str(item).strip())
    return replace(config, **changes)


def load(path: Path | str | None = None, *, profile: str | None = None,
         overrides: dict[str, object] | None = None) -> ServiceConfig:
    document: dict[str, object] = {}
    source = Path(path) if path is not None else None
    if source is not None and source.exists():
        with open(source, "rb") as handle:
            document = tomllib.load(handle)

    file_profiles = document.get("profiles", {})
    if not isinstance(file_profiles, dict):
        raise ValueError("[profiles] must be a table of named profiles")

    selected = (profile
                or str(document.get("default_profile", "") or "")
                or PROFILE_LOCAL)
    known = set(BUILTIN_PROFILES) | set(file_profiles)
    if selected not in known:
        raise ValueError("unknown profile %r; known profiles are %s"
                         % (selected, ", ".join(sorted(known))))

    config = ServiceConfig(profile=selected)
    if selected in BUILTIN_PROFILES:
        config = _apply(config, BUILTIN_PROFILES[selected],
                        "built-in profile %r" % selected)

    for name, body in file_profiles.items():
        if isinstance(body, dict) and "economy" in body:
            raise ValueError(
                "[economy] applies to the whole server; move it out of "
                "profile %r in %s to the top level" % (name, source))
    if "economy" in document:
        config = replace(config,
                         economy=_economy(document["economy"], str(source)))

    top_level = {key: value for key, value in document.items()
                 if key not in {"profiles", "default_profile", "economy"}}
    if top_level:
        config = _apply(config, top_level, str(source))

    section = file_profiles.get(selected, {})
    if section:
        if not isinstance(section, dict):
            raise ValueError("profile %r must be a table" % selected)
        config = _apply(config, section, "profile %r in %s" % (selected, source))

    if overrides:
        config = _apply(config, {key: value for key, value in overrides.items()
                                 if value is not None}, "command line")

    if not config.bind_host:
        raise ValueError("profile %r has no bind address" % selected)
    if not valid_host(config.bind_host):
        raise ValueError("profile %r has an invalid bind host" % selected)
    for field in ADVERTISE_FIELDS:
        value = getattr(config, field)
        if not value:
            raise ValueError(
                "profile %r advertises no %s address. Set `advertise` to the "
                "address other machines reach this one on."
                % (selected, field.removeprefix("advertise_")))
        if not valid_advertised_host(value):
            raise ValueError("profile %r has an invalid %s host"
                             % (selected, field.removeprefix("advertise_")))
    for field in _PORT_FIELDS:
        if not 1 <= getattr(config, field) <= 65535:
            raise ValueError("%s must be between 1 and 65535" % field)
    return config
