# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import tdf


CENSUS_COMPONENT = 0x000A
SUBSCRIBE_UPDATES_COMMAND = 0x0005
SERVER_CENSUS_NOTIFICATION = 0x0001

MICROSECONDS_PER_SECOND = 1_000_000
CENSUS_NOTIFICATION_PERIOD = 60 * MICROSECONDS_PER_SECOND
NOTIFICATION_TIMEOUT = 120 * MICROSECONDS_PER_SECOND
RESUBSCRIBE_TIMEOUT = 15 * MICROSECONDS_PER_SECOND


def build_subscribe_updates_response() -> bytes:
    return (
        tdf.u32(b"CNP", CENSUS_NOTIFICATION_PERIOD)
        + tdf.u32(b"NTMT", NOTIFICATION_TIMEOUT)
        + tdf.u32(b"RTMT", RESUBSCRIBE_TIMEOUT)
    )


def build_server_census_notification() -> bytes:
    return (
        tdf.u32(b"CNP", CENSUS_NOTIFICATION_PERIOD)
        + tdf.u32(b"NTMT", NOTIFICATION_TIMEOUT)
        + tdf.u32(b"RTMT", RESUBSCRIBE_TIMEOUT)
        + tdf.list_groups(b"TDFL", ())
    )
