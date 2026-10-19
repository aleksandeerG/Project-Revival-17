# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from collections.abc import Callable

from events import emit

HOSTNAME_REFRESH_SECONDS = 300
ENROLLMENT_REFRESH_SECONDS = 5


def _network(text: str) -> ipaddress._BaseNetwork | None:
    try:
        return ipaddress.ip_network(text, strict=False)
    except ValueError:
        return None


class AccessList:

    def __init__(self, entries: list[str] | tuple[str, ...] = (),
                 *, refresh_seconds: int = HOSTNAME_REFRESH_SECONDS,
                 enrolled: Callable[[], set[str]] | None = None,
                 enrollment_refresh_seconds: int = ENROLLMENT_REFRESH_SECONDS) -> None:
        self._lock = threading.Lock()
        self._networks: list[ipaddress._BaseNetwork] = []
        self._hostnames: list[str] = []
        self._resolved: dict[str, set[str]] = {}
        self._resolved_at = 0.0
        self._enrolled_addresses: set[str] = set()
        self._enrolled_at = 0.0
        self._refresh_seconds = max(0, int(refresh_seconds))
        self._enrollment_refresh_seconds = max(
            1, int(enrollment_refresh_seconds))
        self._rejected = 0
        self._enrolled = enrolled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error = ""
        for raw in entries:
            entry = str(raw).strip()
            if not entry:
                continue
            network = _network(entry)
            if network is not None:
                self._networks.append(network)
            else:
                self._hostnames.append(entry)
        if self._hostnames or self._enrolled is not None:
            self.refresh_now()

    @property
    def configured(self) -> bool:
        return bool(self._networks or self._hostnames
                    or self._enrolled is not None)

    @property
    def rejected(self) -> int:
        return self._rejected

    def describe(self) -> dict[str, object]:
        with self._lock:
            return {
                "networks": [str(net) for net in self._networks],
                "hostnames": list(self._hostnames),
                "resolved": {name: sorted(addresses)
                             for name, addresses in self._resolved.items()},
                "rejected": self._rejected,
                "enrollment": self._enrolled is not None,
                "enrolledAddresses": len(self._enrolled_addresses),
                "refreshRunning": bool(self._thread and self._thread.is_alive()),
                "lastRefreshError": self._last_error,
            }

    def refresh_now(self, *, dns: bool = True, enrollment: bool = True) -> None:
        now = time.monotonic()
        names = self._hostnames if dns else ()
        if dns:
            with self._lock:
                self._resolved_at = now
        for name in names:
            try:
                infos = socket.getaddrinfo(name, None)
            except OSError as error:
                with self._lock:
                    keeping = sorted(self._resolved.get(name, ()))
                    self._last_error = str(error)
                emit("access-hostname-unresolved", host=name, error=str(error),
                     keeping=keeping)
                continue
            addresses = {info[4][0] for info in infos}
            with self._lock:
                changed = addresses != self._resolved.get(name)
                self._resolved[name] = addresses
                self._last_error = ""
            if changed:
                emit("access-hostname-updated", host=name,
                     addresses=sorted(addresses))
        if enrollment and self._enrolled is not None:
            with self._lock:
                self._enrolled_at = now
            try:
                addresses = set(self._enrolled())
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                emit("access-enrollment-unavailable", error=str(error))
            else:
                with self._lock:
                    self._enrolled_addresses = addresses
                    self._last_error = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="access-refresh", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            now = time.monotonic()
            with self._lock:
                dns_due = bool(self._hostnames) and (
                    self._refresh_seconds == 0
                    or now - self._resolved_at >= self._refresh_seconds)
                enrolled_due = self._enrolled is not None and (
                    now - self._enrolled_at >= self._enrollment_refresh_seconds)
            if dns_due or enrolled_due:
                self.refresh_now(dns=dns_due, enrollment=enrolled_due)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def admit(self, address: str, _expires_at: int | None = None) -> None:
        with self._lock:
            self._enrolled_addresses.add(str(address))

    def permits(self, address: str) -> bool:
        if not self.configured:
            return True
        try:
            candidate = ipaddress.ip_address(address)
        except ValueError:
            return False
        with self._lock:
            for network in self._networks:
                if candidate.version == network.version and candidate in network:
                    return True
            for addresses in self._resolved.values():
                if address in addresses:
                    return True
            if address in self._enrolled_addresses:
                return True
            self._rejected += 1
        return False


def refuse(server, client_address) -> bool:
    access = getattr(server, "access", None)
    if access is None or not access.configured:
        return True
    address = client_address[0] if client_address else ""
    if access.permits(address):
        return True
    emit("access-refused", peer="%s:%s" % (address,
                                           client_address[1] if client_address else 0),
         listener=server.server_address[1])
    return False
