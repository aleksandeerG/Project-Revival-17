# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import os
import re
import hashlib
import threading
import time
from datetime import datetime, timedelta

_SQUAD_INPUT = re.compile(
    r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\]\s+\[SQUAD-INPUT\]\s+"
    r"candidate='([^']+)'\s+ageMs=(\d+)")
_CONSUMED = re.compile(r"^([0-9a-f]{64})$")

DEFAULT_LOG = r"C:\Games\FIFA 17\fifa17-revival-log.txt"
MAX_AGE_SECONDS = 2.0
TAIL_BYTES = 256 * 1024
_consume_lock = threading.Lock()
_consumed_records: set[tuple[str, str]] = set()


def _log_path() -> str:
    return os.environ.get("FUT_SHIM_LOG", DEFAULT_LOG)


def _consumed_path(log_path: str) -> str:
    return log_path + ".squad-consumed"


def _tail(path: str, size: int = TAIL_BYTES) -> list:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            start = max(0, handle.tell() - size)
            handle.seek(start)
            blob = handle.read()
    except OSError:
        return []
    return blob.decode("utf-8", "replace").splitlines()


def recent_entered_text(now: float | None = None,
                        max_age: float = MAX_AGE_SECONDS,
                        wait_seconds: float = 0.1) -> str | None:
    path = _log_path()
    consumed_path = _consumed_path(path)
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        with _consume_lock:
            lines = _tail(path)
            consumed = {match.group(1) for line in _tail(consumed_path)
                        if (match := _CONSUMED.match(line.strip())) is not None}
            when = datetime.fromtimestamp(now if now is not None else time.time())
            for line in reversed(lines):
                stripped = line.strip()
                squad_match = _SQUAD_INPUT.match(stripped)
                if squad_match is None:
                    continue
                digest = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
                record = (path, digest)
                if digest in consumed or record in _consumed_records:
                    break
                text = squad_match.group(5)
                input_age = int(squad_match.group(6)) / 1000.0
                stamp = when.replace(hour=int(squad_match.group(1)),
                                     minute=int(squad_match.group(2)),
                                     second=int(squad_match.group(3)),
                                     microsecond=int(squad_match.group(4)) * 1000)
                if stamp > when:
                    stamp -= timedelta(days=1)
                request_age = (when - stamp).total_seconds()
                if input_age <= max_age and 0 <= request_age <= max_age:
                    _consumed_records.add(record)
                    try:
                        with open(consumed_path, "a", encoding="ascii") as handle:
                            handle.write(digest + "\n")
                    except OSError:
                        pass
                    return text
                break
        if now is not None or time.monotonic() >= deadline:
            return None
        time.sleep(0.005)
