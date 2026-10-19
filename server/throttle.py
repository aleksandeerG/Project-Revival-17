# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import threading
import time

from events import emit

DEFAULT_ATTEMPTS = 6
DEFAULT_WINDOW_SECONDS = 60
DEFAULT_COOLDOWN_SECONDS = 60


class FailureThrottle:
    def __init__(self, *, attempts: int = DEFAULT_ATTEMPTS,
                 window: int = DEFAULT_WINDOW_SECONDS,
                 cooldown: int = DEFAULT_COOLDOWN_SECONDS) -> None:
        self._attempts = max(1, int(attempts))
        self._window = max(1, int(window))
        self._cooldown = max(1, int(cooldown))
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._refusals = 0

    def blocked(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        with self._lock:
            until = self._blocked_until.get(key)
            if until is None:
                return False
            if current >= until:
                self._blocked_until.pop(key, None)
                self._failures.pop(key, None)
                return False
            self._refusals += 1
            return True

    def record_failure(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        with self._lock:
            recent = [stamp for stamp in self._failures.get(key, ())
                      if current - stamp < self._window]
            recent.append(current)
            self._failures[key] = recent
            if len(recent) >= self._attempts:
                self._blocked_until[key] = current + self._cooldown
                self._failures.pop(key, None)
                emit("auth-throttled", key=key, attempts=len(recent),
                     seconds=self._cooldown)
                return True
        return False

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._blocked_until.pop(key, None)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"trackedSources": len(self._failures),
                    "blockedSources": len(self._blocked_until),
                    "refusals": self._refusals}
