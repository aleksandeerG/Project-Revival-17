# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import time

import tdf


SERVICE_NAME = "fifa-2017-pc"
TRIAL_SERVICE_NAME = "fifa-2017-pc-trial"

POSTAUTH_SERVICE_NAME = TRIAL_SERVICE_NAME


OBSERVED_CONFIG_IDS = (
    "OSDK_CORE",
    "OSDK_CLIENT",
    "OSDK_NUCLEUS",
    "OSDK_WEBOFFER",
    "OSDK_ABUSE_REPORTING",
    "OSDK_XMS_ABUSE_REPORTING",
)

CLIENT_CONFIGS: dict[str, tuple[tuple[str, str], ...]] = {
    config_id: () for config_id in OBSERVED_CONFIG_IDS
}

FUT_CAPTURE_BASE_URL = "http://127.0.0.1:8080/"


def _osdk_client_config(base_url: str) -> tuple[tuple[str, str], ...]:
    return (
        ("FUT_RS4_BASE_URL", base_url),
        ("FUT_URI", base_url),
        ("FUT_ENABLE_MENU", "1"),
        ("FUTDYNAMICMESSAGES_URL_BASE", base_url.rstrip("/")),
        ("FUT/ROSTERUPDATE_URL", base_url + "rosterupdate"),
    )


CLIENT_CONFIGS["OSDK_CLIENT"] = _osdk_client_config(FUT_CAPTURE_BASE_URL)


def set_fut_base_url(base_url: str) -> str:
    global FUT_CAPTURE_BASE_URL
    base_url = str(base_url)
    if not base_url.endswith("/"):
        base_url += "/"
    FUT_CAPTURE_BASE_URL = base_url
    CLIENT_CONFIGS["OSDK_CLIENT"] = _osdk_client_config(base_url)
    return base_url


SERVER_VERSIONING_ABSENT = "absent"
SERVER_VERSIONING_MATCH = "match"
SERVER_VERSIONING_OFF = "off"
SERVER_VERSIONING_MODES = (
    SERVER_VERSIONING_ABSENT,
    SERVER_VERSIONING_MATCH,
    SERVER_VERSIONING_OFF,
)
DEFAULT_SERVER_VERSIONING = SERVER_VERSIONING_ABSENT


def server_versioning_values(mode: str, client_version: str) -> tuple[tuple[str, str], ...]:
    if mode == SERVER_VERSIONING_OFF:
        return (("SV_ENABLE_SERVER_VERSIONING", "0"),)
    if mode == SERVER_VERSIONING_MATCH:
        version = client_version if client_version.isdigit() else "0"
        return (
            ("SV_ENABLE_SERVER_VERSIONING", "1"),
            ("SV_CLIENT_CHANGELIST", version),
            ("SV_SERVER_VERSION", version),
        )
    return ()


FUT_DIRECT_BOOT_VALUES: tuple[tuple[str, str], ...] = (
    ("FUT_DIRECT_BOOT", "1"),
)


def build_ping_response() -> bytes:
    return tdf.u32(b"STIM", int(time.time()))


def build_fetch_config_response(
    config_id: str | None,
    *,
    extra: tuple[tuple[str, str], ...] = (),
) -> bytes:
    values = CLIENT_CONFIGS.get(config_id or "", ())
    if extra:
        present = {key for key, _ in values}
        values = values + tuple((k, v) for k, v in extra if k not in present)
    return tdf.map_strings(b"CONF", values)


def build_postauth_response(
    persona_id: int,
    *,
    locale: int = 0x656E5553,
    service_name: str = POSTAUTH_SERVICE_NAME,
) -> bytes:
    telemetry = (
        tdf.string(b"ADRS", "127.0.0.1")
        + tdf.boolean(b"ANON", False)
        + tdf.string(b"DISA", "")
        + tdf.u32(b"EDCT", 0)
        + tdf.string(b"FILT", "-UION/****")
        + tdf.u32(b"LOC", locale)
        + tdf.u32(b"MINR", 0)
        + tdf.string(b"NOOK", "")
        + tdf.u16(b"PORT", 0)
        + tdf.u16(b"SDLY", 15000)
        + tdf.string(b"SESS", "LOCAL-FIFA17-TELEMETRY")
        + tdf.string(b"SKEY", "")
        + tdf.u16(b"SPCT", 0)
        + tdf.string(b"STIM", "")
        + tdf.string(b"SVNM", "telemetry-3-common")
    )
    ticker = (
        tdf.string(b"ADRS", "127.0.0.1")
        + tdf.u16(b"PORT", 0)
        + tdf.string(b"SKEY", f"{persona_id},127.0.0.1:0,{service_name},0")
    )
    user_options = tdf.u32(b"TMOP", 0) + tdf.u32(b"UID", persona_id)
    return (
        tdf.group(b"TELE", telemetry)
        + tdf.group(b"TICK", ticker)
        + tdf.group(b"UROP", user_options)
    )

BASELINE_COMPONENT_IDS = (
    0x0001,
    0x0019,
    0x0004,
    0x001C,
    0x0007,
    0x0009,
    0xF802,
    0x7800,
    0x000F,
    0x7801,
    0x7802,
    0x7803,
    0x7805,
    0x7806,
    0x07D0,
)

SERVED_ONLY_COMPONENT_IDS = (
    0x000A,
    0x000B,
    0x081C,
    0x08C9,
)

SERVED_COMPONENT_IDS = BASELINE_COMPONENT_IDS + SERVED_ONLY_COMPONENT_IDS

COMPONENT_SETS: dict[str, tuple[int, ...]] = {
    "baseline": BASELINE_COMPONENT_IDS,
    "served": SERVED_COMPONENT_IDS,
}
DEFAULT_COMPONENT_SET = "baseline"

PREAUTH_COMPONENT_IDS = SERVED_COMPONENT_IDS


def _qos_body(mode: str) -> bytes:
    if mode == "fifa14":
        return (
            tdf.group(
                b"BWPS",
                tdf.string(b"PSA", "0") + tdf.u16(b"PSP", 0) + tdf.string(b"SNA", "prod-sjc"),
            )
            + tdf.u16(b"LNP", 1)
            + tdf.empty_map(b"LTPS", tdf.STRING, tdf.GROUP)
            + tdf.u32(b"SVID", 0x45410805)
        )
    return (
        tdf.u16(b"LNP", 0)
        + tdf.empty_map(b"LTPS", tdf.STRING, tdf.GROUP)
        + tdf.u32(b"SVID", 0x45410805)
    )


def build_preauth_response(
    service_name: str = SERVICE_NAME,
    *,
    qoss: str = "fifa14",
    minimal: bool = False,
    components: str | tuple[int, ...] = DEFAULT_COMPONENT_SET,
) -> bytes:
    if isinstance(components, str):
        try:
            component_ids = COMPONENT_SETS[components]
        except KeyError:
            raise ValueError(
                f"component set must be one of {tuple(COMPONENT_SETS)}"
            ) from None
    else:
        component_ids = tuple(components)
    client_config = tdf.map_strings(
        b"CONF",
        (
            ("pingPeriod", "30s"),
            ("voipHeadsetUpdateRate", "1000"),
            ("xlspConnectionIdleTimeout", "300"),
        ),
    )
    qoss_field = b"" if qoss == "omit" else tdf.group(b"QOSS", _qos_body(qoss))

    if minimal:
        return (
            tdf.string(b"ASRC", "303107")
            + tdf.list_u32(b"CIDS", component_ids)
            + qoss_field
            + tdf.string(b"RSRC", "303107")
            + tdf.string(b"SVER", "Blaze 15.1 local FIFA 17\n")
        )
    return (
        tdf.boolean(b"ANON", False)
        + tdf.string(b"ASRC", "303107")
        + tdf.list_u32(b"CIDS", component_ids)
        + tdf.string(b"CNGN", "")
        + tdf.group(b"CONF", client_config)
        + tdf.string(b"INST", service_name)
        + tdf.boolean(b"MINR", False)
        + tdf.string(b"NASP", "cem_ea_id")
        + tdf.string(b"PILD", "")
        + tdf.string(b"PLAT", "pc")
        + tdf.string(b"PTAG", "")
        + qoss_field
        + tdf.string(b"RSRC", "303107")
        + tdf.string(b"SVER", "Blaze 15.1 local FIFA 17\n")
    )


PREAUTH_VARIANTS = [
    ("full-fifa14", {"qoss": "fifa14"}),
    ("empty-qoss", {"qoss": "empty"}),
    ("omit-qoss", {"qoss": "omit"}),
    ("minimal-empty-qoss", {"qoss": "empty", "minimal": True}),
]
