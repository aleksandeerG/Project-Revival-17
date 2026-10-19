# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_KEEP = 10

_NEWLINE_BYTES = len(os.linesep.encode("utf-8"))

_LOCK = threading.Lock()
_SINK: TextIO | None = None
_ECHO = True
_PATH: Path | None = None
_MAX_BYTES = DEFAULT_MAX_BYTES
_KEEP = DEFAULT_KEEP
_WRITTEN = 0
_QUEUE_LIMIT = 4096
_QUEUE: queue.Queue[str | object] | None = None
_WORKER: threading.Thread | None = None
_SENTINEL = object()
_DROPPED = 0
_LAST_ERROR = ""


def configure(log_path: Path | None = None, echo: bool = True, *,
              max_bytes: int = DEFAULT_MAX_BYTES,
              keep: int = DEFAULT_KEEP) -> None:
    global _SINK, _ECHO, _PATH, _MAX_BYTES, _KEEP, _WRITTEN, _QUEUE, _WORKER
    close()
    _ECHO = echo
    _MAX_BYTES = max(0, int(max_bytes))
    _KEEP = max(0, int(keep))
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _PATH = log_path
        try:
            _WRITTEN = log_path.stat().st_size
        except OSError:
            _WRITTEN = 0
        _SINK = log_path.open("a", encoding="utf-8", buffering=1)
    if _SINK is not None or _ECHO:
        _QUEUE = queue.Queue(maxsize=_QUEUE_LIMIT)
        _WORKER = threading.Thread(
            target=_writer, args=(_QUEUE,), name="event-log-writer", daemon=True)
        _WORKER.start()


def _rotate_locked() -> None:
    global _SINK, _WRITTEN
    if _PATH is None:
        return
    try:
        if _SINK is not None:
            _SINK.close()
            _SINK = None
        if _KEEP == 0:
            _PATH.unlink(missing_ok=True)
        else:
            oldest = _PATH.with_name(_PATH.name + ".%d" % _KEEP)
            oldest.unlink(missing_ok=True)
            for index in range(_KEEP - 1, 0, -1):
                source = _PATH.with_name(_PATH.name + ".%d" % index)
                if source.exists():
                    source.replace(
                        _PATH.with_name(_PATH.name + ".%d" % (index + 1)))
            if _PATH.exists():
                _PATH.replace(_PATH.with_name(_PATH.name + ".1"))
        _WRITTEN = 0
    except OSError:
        pass
    finally:
        if _SINK is None:
            try:
                _SINK = _PATH.open("a", encoding="utf-8", buffering=1)
                _WRITTEN = _PATH.stat().st_size
            except OSError:
                _SINK = None


def close() -> None:
    global _SINK, _QUEUE, _WORKER
    with _LOCK:
        pending, worker = _QUEUE, _WORKER
        _QUEUE = None
        _WORKER = None
    if pending is not None and worker is not None:
        pending.put(_SENTINEL)
        pending.join()
        worker.join(timeout=5.0)
    with _LOCK:
        if _SINK is not None:
            try:
                _SINK.close()
            except OSError:
                pass
            _SINK = None


def flush() -> None:
    with _LOCK:
        pending = _QUEUE
    if pending is not None:
        pending.join()


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "queued": _QUEUE.qsize() if _QUEUE is not None else 0,
            "capacity": _QUEUE_LIMIT,
            "dropped": _DROPPED,
            "lastError": _LAST_ERROR,
            "writerAlive": bool(_WORKER and _WORKER.is_alive()),
        }


def _writer(pending: queue.Queue[str | object]) -> None:
    global _WRITTEN, _LAST_ERROR
    while True:
        item = pending.get()
        try:
            if item is _SENTINEL:
                return
            line = str(item)
            try:
                if _ECHO:
                    print(line, file=sys.stderr, flush=True)
                if _SINK is not None:
                    _SINK.write(line + "\n")
                    _WRITTEN += len(line.encode("utf-8")) + _NEWLINE_BYTES
                    if _MAX_BYTES and _WRITTEN >= _MAX_BYTES:
                        _rotate_locked()
                _LAST_ERROR = ""
            except Exception as error:
                _LAST_ERROR = str(error)
        finally:
            pending.task_done()


def emit(kind: str, **fields: Any) -> None:
    global _DROPPED
    record = {"ts": round(time.time(), 3), "kind": kind}
    record.update(fields)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _LOCK:
        pending = _QUEUE
    if pending is None:
        return
    try:
        pending.put_nowait(line)
    except queue.Full:
        with _LOCK:
            _DROPPED += 1
