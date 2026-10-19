# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

from typing import Any

import tdf


AUTHENTICATION_COMPONENT = 1
STATS_COMPONENT = 7
UTIL_COMPONENT = 9
CLUBS_COMPONENT = 11
MESSAGING_COMPONENT = 15
ASSOCIATION_LISTS_COMPONENT = 25
USER_SESSIONS_COMPONENT = 0x7802
SPONSORED_EVENTS_COMPONENT = 0x081C
OSDK_SETTINGS_COMPONENT = 2249

CONTENT_BASE_URL = "http://127.0.0.1:8080/"


def set_content_base_url(base_url: str) -> str:
    global CONTENT_BASE_URL
    base_url = str(base_url)
    if not base_url.endswith("/"):
        base_url += "/"
    CONTENT_BASE_URL = base_url
    return base_url


def _summary(payload: bytes) -> dict[str, Any]:
    try:
        result = tdf.summarise(tdf.decode(payload))
    except tdf.TdfError:
        return {}
    return result if isinstance(result, dict) else {}


def build_telemetry_response(locale: int) -> bytes:
    return (
        tdf.string(b"ADRS", "127.0.0.1")
        + tdf.boolean(b"ANON", False)
        + tdf.blob(b"BKEY")
        + tdf.u32(b"CTRY", 0)
        + tdf.string(b"DISA", "")
        + tdf.boolean(b"EDCT", False)
        + tdf.string(b"FILT", "-UION/****")
        + tdf.u32(b"LOC", locale)
        + tdf.boolean(b"MINR", False)
        + tdf.string(b"NOOK", "")
        + tdf.string(b"PENV", "")
        + tdf.u32(b"PORT", 0)
        + tdf.string(b"PURL", "")
        + tdf.u32(b"SDLY", 15_000)
        + tdf.string(b"SESS", "LOCAL-FIFA17-TELEMETRY")
        + tdf.string(b"SKEY", "")
        + tdf.u32(b"SPCT", 0)
        + tdf.string(b"STIM", "")
        + tdf.string(b"SVNM", "telemetry-3-common")
    )


def build_user_setting_response(key: str) -> bytes:
    return tdf.string(b"DATA", "") + tdf.string(b"KEY", key)


def build_user_settings_all_response() -> bytes:
    return tdf.map_strings(b"SMAP", ())


def build_filter_user_text_response(payload: bytes) -> tuple[bytes, list[str]]:
    try:
        fields = tdf.decode(payload)
    except tdf.TdfError:
        return tdf.list_groups(b"TLST", ()), []
    matching = [field for field in fields if field["tag"] == "TLST"]
    if len(matching) != 1 or matching[0]["type"] != tdf.LIST:
        return tdf.list_groups(b"TLST", ()), []
    tlst = matching[0]
    listing = tlst["value"]
    if not isinstance(listing, dict) or listing.get("elementType") != tdf.GROUP:
        return tdf.list_groups(b"TLST", ()), []
    values = listing.get("values", [])
    texts: list[str] = []
    entries: list[bytes] = []
    for value in values:
        if not isinstance(value, list):
            return tdf.list_groups(b"TLST", ()), []
        tags = [field["tag"] for field in value]
        if len(tags) != len(set(tags)):
            return tdf.list_groups(b"TLST", ()), []
        entry = {field["tag"]: field for field in value}
        dirt = entry.get("DIRT")
        user_text = entry.get("UTXT")
        if (dirt is None or dirt["type"] != tdf.VAR_INT or
                not isinstance(dirt["value"], int) or
                dirt["value"] not in (0, 1, 2) or
                user_text is None or user_text["type"] != tdf.STRING or
                not isinstance(user_text["value"], str)):
            return tdf.list_groups(b"TLST", ()), []
        text = user_text["value"]
        texts.append(text)
        entries.append(
            tdf.u32(b"DIRT", 0)
            + tdf.string(b"UTXT", text)
        )
    return tdf.list_groups(b"TLST", tuple(entries)), texts


ENTITLEMENT_TYPE_ONLINE_ACCESS = 0
ENTITLEMENT_TYPE_TRIAL_ONLINE_ACCESS = 1
ENTITLEMENT_TYPE_MODES = {
    "online-access": (ENTITLEMENT_TYPE_ONLINE_ACCESS,),
    "trial-online-access": (ENTITLEMENT_TYPE_TRIAL_ONLINE_ACCESS,),
    "both": (ENTITLEMENT_TYPE_ONLINE_ACCESS, ENTITLEMENT_TYPE_TRIAL_ONLINE_ACCESS),
}
DEFAULT_ENTITLEMENT_TYPE_MODE = "trial-online-access"


def build_entitlements_response(
    persona_id: int,
    groups: tuple[str, ...],
    *,
    type_mode: str = DEFAULT_ENTITLEMENT_TYPE_MODE,
) -> bytes:
    try:
        type_values = ENTITLEMENT_TYPE_MODES[type_mode]
    except KeyError:
        raise ValueError(
            f"entitlement type mode must be one of {tuple(ENTITLEMENT_TYPE_MODES)}"
        ) from None

    requested = groups or ("FIFA17PCBoxContent",)
    grants: list[bytes] = []
    entitlement_id = 0
    for group_name in requested:
        for type_value in type_values:
            entitlement_id += 1
            grants.append(
                tdf.string(b"DEVI", "")
                + tdf.string(b"GDAY", "2016-09-27T00:00:00Z")
                + tdf.string(b"GNAM", group_name)
                + tdf.u32(b"ID", entitlement_id)
                + tdf.boolean(b"ISCO", False)
                + tdf.u32(b"PID", persona_id)
                + tdf.string(b"PJID", "FIFA17")
                + tdf.u32(b"PRCA", 2)
                + tdf.string(b"PRID", "fifa17_pc")
                + tdf.u32(b"STAT", 1)
                + tdf.u32(b"STRC", 1)
                + tdf.string(b"TAG", "FIFA17PCFUTContentUnlocks")
                + tdf.string(b"TDAY", "")
                + tdf.u32(b"TYPE", type_value)
                + tdf.u32(b"UCNT", 0)
                + tdf.u32(b"VER", 1)
            )
    return tdf.list_groups(b"NLST", tuple(grants))


def _clubs_settings() -> bytes:
    return b"".join(
        tdf.u32(tag, 0)
        for tag in (b"CLDS", b"MXEV", b"MXRV", b"PUHR", b"SOVR", b"STRT")
    )


def _period_ids() -> bytes:
    return b"".join(
        tdf.u32(tag, 0)
        for tag in (
            b"DBUF", b"DHOU", b"DLY", b"DRET", b"MBUF", b"MDAY", b"MHOU",
            b"MLY", b"MRET", b"WBUF", b"WDAY", b"WHOU", b"WLY", b"WRET",
        )
    )


def _osdk_settings() -> bytes:
    ticker_filter = (
        tdf.string(b"ID", "O_TKfilter")
        + tdf.u32(b"LOCF", 0)
        + tdf.u32(b"TOGG", 0)
    )
    return tdf.list_groups(b"LSST", (ticker_filter,))


def _osdk_setting_groups() -> bytes:
    ticker_group = (
        tdf.string(b"ID", "O_SG_TCKR")
        + tdf.list_strings(b"LSET", ("O_TKfilter",))
    )
    return tdf.list_groups(b"LGRP", (ticker_group,))


def build_frontend_response(
    component: int,
    command: int,
    payload: bytes,
    *,
    persona_id: int,
    locale: int,
    entitlement_type_mode: str = DEFAULT_ENTITLEMENT_TYPE_MODE,
) -> tuple[str, bytes, dict[str, Any]] | None:
    route = (component, command)
    if route == (UTIL_COMPONENT, 5):
        return "util-telemetry-server", build_telemetry_response(locale), {}
    if route == (UTIL_COMPONENT, 10):
        key = str(_summary(payload).get("KEY", "") or "")
        return "util-user-setting", build_user_setting_response(key), {"settingKey": key}
    if route == (UTIL_COMPONENT, 12):
        return "util-user-settings-all", build_user_settings_all_response(), {}
    if route == (UTIL_COMPONENT, 20):
        body, texts = build_filter_user_text_response(payload)
        return "util-filter-user-text", body, {
            "count": len(texts),
        }
    if route == (AUTHENTICATION_COMPONENT, 32):
        values = _summary(payload).get("GNLS", {}).get("values", [])
        groups = tuple(value for value in values if isinstance(value, str))
        body = build_entitlements_response(
            persona_id, groups, type_mode=entitlement_type_mode
        )
        return "authentication-list-entitlements", body, {
            "groups": list(groups),
            "entitlementTypes": list(ENTITLEMENT_TYPE_MODES[entitlement_type_mode]),
        }

    typed: dict[tuple[int, int], tuple[str, bytes]] = {
        (USER_SESSIONS_COMPONENT, 8): ("user-sessions-update-hardware-flags", b""),
        (UTIL_COMPONENT, 28): ("util-set-client-state", b""),
        (MESSAGING_COMPONENT, 2): ("messaging-fetch-count", tdf.u32(b"MCNT", 0)),
        (ASSOCIATION_LISTS_COMPONENT, 6): (
            "association-lists-empty", tdf.list_groups(b"LMAP", ()),
        ),
        (CLUBS_COMPONENT, 2600): ("clubs-component-settings", _clubs_settings()),
        (CLUBS_COMPONENT, 1600): (
            "clubs-invitations-empty", tdf.list_groups(b"CIST", ()),
        ),
        (STATS_COMPONENT, 15): (
            "stats-key-scopes-empty", tdf.empty_map(b"KSIT", tdf.STRING, tdf.GROUP),
        ),
        (STATS_COMPONENT, 3): (
            "stats-groups-empty", tdf.list_groups(b"GRPS", ()),
        ),
        (STATS_COMPONENT, 20): ("stats-period-ids", _period_ids()),
        (OSDK_SETTINGS_COMPONENT, 1): ("osdk-settings", _osdk_settings()),
        (OSDK_SETTINGS_COMPONENT, 2): (
            "osdk-setting-groups", _osdk_setting_groups(),
        ),
        (SPONSORED_EVENTS_COMPONENT, 3): (
            "sponsored-events-local-url",
            tdf.string(b"URL", CONTENT_BASE_URL + "sponsored-events"),
        ),
    }
    result = typed.get(route)
    return (result[0], result[1], {}) if result is not None else None
