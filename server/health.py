# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import threading
import time
from typing import Any

import events

SERVER_VERSION = "project-revival-17/0.1.0"

_STARTED_AT = time.time()
_LOCK = threading.Lock()
_LAUNCHER_VERSIONS: dict[str, dict[str, float | int]] = {}
_MAX_LAUNCHER_VERSIONS = 64
_READY = True
_DRAINING_SINCE: float | None = None

_LATENCY: dict[str, list[float]] = {}
_LOCKS: list["TimedLock"] = []


class TimedLock:

    __slots__ = ("_lock", "_name", "_waited_ms", "_acquisitions", "_max_wait_ms")

    def __init__(self, name: str) -> None:
        self._lock = threading.RLock()
        self._name = name
        self._waited_ms = 0.0
        self._acquisitions = 0
        self._max_wait_ms = 0.0
        _LOCKS.append(self)

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        started = time.perf_counter()
        got = self._lock.acquire(blocking, timeout)
        if got:
            waited = (time.perf_counter() - started) * 1000.0
            self._waited_ms += waited
            self._acquisitions += 1
            if waited > self._max_wait_ms:
                self._max_wait_ms = waited
        return got

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "TimedLock":
        self.acquire()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()

    def stats(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "acquisitions": self._acquisitions,
            "waitedMs": round(self._waited_ms, 3),
            "maxWaitMs": round(self._max_wait_ms, 3),
        }


def record_request(surface: str, elapsed_ms: float) -> None:
    with _LOCK:
        entry = _LATENCY.get(surface)
        if entry is None:
            _LATENCY[surface] = [1.0, float(elapsed_ms), float(elapsed_ms)]
        else:
            entry[0] += 1
            entry[1] += float(elapsed_ms)
            entry[2] = max(entry[2], float(elapsed_ms))


def begin_draining() -> None:
    global _READY, _DRAINING_SINCE
    with _LOCK:
        if _READY:
            _READY = False
            _DRAINING_SINCE = time.time()


def is_ready() -> bool:
    with _LOCK:
        return _READY


def reset_for_tests() -> None:
    global _READY, _DRAINING_SINCE
    with _LOCK:
        _READY = True
        _DRAINING_SINCE = None
        _LATENCY.clear()
        _LAUNCHER_VERSIONS.clear()


def liveness() -> dict[str, Any]:
    return {"status": "alive",
            "uptimeSeconds": round(time.time() - _STARTED_AT, 1),
            "version": SERVER_VERSION}


def readiness(listeners: dict[str, int] | None = None, *,
              servers: dict[str, Any] | None = None,
              identity_store=None, fut_state=None, access_list=None) -> dict[str, Any]:
    with _LOCK:
        ready = _READY
        draining_since = _DRAINING_SINCE
    failures: list[str] = []
    if servers:
        for name, server in servers.items():
            thread = getattr(server, "_serve_thread", None)
            if thread is not None and not thread.is_alive():
                failures.append(f"listener {name} is not running")
            if getattr(server, "socket", None) is None or server.socket.fileno() < 0:
                failures.append(f"listener {name} socket is closed")
    for name, store in (("identity database", identity_store),
                        ("FUT database", fut_state)):
        if store is not None:
            ok, detail = store.health_check()
            if not ok:
                failures.append(f"{name}: {detail}")
    if access_list is not None:
        state = access_list.describe()
        if state["refreshRunning"] is False:
            failures.append("access refresh worker is not running")
    ready = bool(ready and not failures)
    document: dict[str, Any] = {
        "status": "ready" if ready else ("draining" if draining_since else "not-ready"),
        "ready": ready,
        "version": SERVER_VERSION,
    }
    if failures:
        document["failures"] = failures
    if draining_since is not None:
        document["drainingForSeconds"] = round(time.time() - draining_since, 1)
    if listeners:
        document["listeners"] = dict(listeners)
    return document


def snapshot(*, identity_store=None, fut_state=None,
             listeners: dict[str, int] | None = None,
             servers: dict[str, Any] | None = None,
             access_list=None, auth_throttle=None) -> dict[str, Any]:
    with _LOCK:
        latency = {
            surface: {
                "count": int(count),
                "meanMs": round(total / count, 3) if count else 0.0,
                "maxMs": round(peak, 3),
            }
            for surface, (count, total, peak) in _LATENCY.items()
        }
        launcher_versions = {
            version: {"knocks": int(values["knocks"]),
                      "lastSeen": int(values["lastSeen"])}
            for version, values in _LAUNCHER_VERSIONS.items()
        }
    actual_readiness = readiness(
        listeners,
        servers=servers,
        identity_store=identity_store,
        fut_state=fut_state,
        access_list=access_list,
    )["ready"]
    document: dict[str, Any] = {
        "version": SERVER_VERSION,
        "uptimeSeconds": round(time.time() - _STARTED_AT, 1),
        "ready": actual_readiness,
        "threads": threading.active_count(),
        "requestLatency": latency,
        "databaseWaits": [lock.stats() for lock in _LOCKS],
        "logging": events.stats(),
        "launcherVersions": launcher_versions,
    }
    if listeners:
        document["listeners"] = dict(listeners)
    if servers:
        document["connections"] = {
            name: {
                "active": getattr(server, "_active_connections", 0),
                "peak": getattr(server, "_peak_connections", 0),
                "limit": getattr(server, "max_connections", 0),
            }
            for name, server in servers.items()
        }
    if access_list is not None:
        document["access"] = access_list.describe()
    if auth_throttle is not None:
        document["authThrottle"] = auth_throttle.stats()
    if identity_store is not None and fut_state is not None:
        try:
            document["presence"] = identity_store.presence(
                in_match=fut_state.personas_in_match())
        except Exception:
            document["presence"] = None
    if fut_state is not None:
        try:
            document["matches"] = fut_state.match_counts()
            document["auctions"] = fut_state.auction_counts()
        except Exception:
            pass
    return document


def observe_launcher_version(version: str, *, now: float | None = None) -> None:
    value = str(version or "")[:32]
    if not value:
        return
    current = time.time() if now is None else float(now)
    with _LOCK:
        entry = _LAUNCHER_VERSIONS.setdefault(value, {"knocks": 0, "lastSeen": current})
        entry["knocks"] = int(entry["knocks"]) + 1
        entry["lastSeen"] = current
        if len(_LAUNCHER_VERSIONS) > _MAX_LAUNCHER_VERSIONS:
            oldest = min(_LAUNCHER_VERSIONS,
                         key=lambda item: float(_LAUNCHER_VERSIONS[item]["lastSeen"]))
            del _LAUNCHER_VERSIONS[oldest]
