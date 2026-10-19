# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import json
from typing import Any

import health
import throttle
from accounts import BoundedHTTPRequestHandler, REQUEST_TIMEOUT_SECONDS, DualProtocolHTTPServer
from events import emit

MAX_KNOCK_BODY = 1024

KNOCK_ATTEMPTS = 5
KNOCK_WINDOW_SECONDS = 300
KNOCK_COOLDOWN_SECONDS = 900

MAX_CLIENT_VERSION = 32


class KnockHandler(BoundedHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = ""
    sys_version = ""
    timeout = REQUEST_TIMEOUT_SECONDS

    def send_response(self, code, message=None):
        self.log_request(code)
        self.send_response_only(code, message)

    def log_message(self, fmt, *args):
        return

    def _send(self, status: int, document: dict[str, Any] | None = None) -> None:
        payload = json.dumps(document or {}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._send(404, {"message": "not found"})

    def do_POST(self) -> None:
        server: Any = self.server
        source = self.client_address[0]
        if self.path.split("?", 1)[0].rstrip("/") != "/knock":
            return self._send(404, {"message": "not found"})
        if not getattr(server, "enrollment_enabled", True):
            emit("knock-disabled", peer=source)
            return self._send(404, {"message": "not found"})

        limiter = getattr(server, "knock_throttle", None)
        if limiter is not None and limiter.blocked(source):
            emit("knock-throttled", peer=source)
            return self._send(429, {"message": "too many attempts"})

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_KNOCK_BODY:
            emit("knock-refused", peer=source, reason="body")
            return self._send(400, {"message": "bad request"})

        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            request = None
        token = ""
        client_version = ""
        if isinstance(request, dict):
            token = str(request.get("token", "") or "")
            client_version = str(request.get("version", "") or "")[:MAX_CLIENT_VERSION]

        store = getattr(server, "store", None)
        enrolled = store.enroll(token, source) if store is not None else None
        if enrolled is None:
            if limiter is not None:
                limiter.record_failure(source)
            emit("knock-rejected", peer=source)
            return self._send(401, {"message": "unauthorized"})

        if limiter is not None:
            limiter.record_success(source)
        game_access = getattr(server, "game_access", None)
        if game_access is not None:
            game_access.admit(source, int(enrolled["expires_at"]))
        remaining = max(0, int(enrolled["expires_at"]) - int(self._now()))
        emit("knock-accepted", peer=source, token=enrolled["name"],
             seconds=remaining, client=client_version or None)
        health.observe_launcher_version(client_version)

        self._send(200, {
            "expiresIn": remaining,
            "launcherVersion": getattr(server, "launcher_version", ""),
            "minimumLauncherVersion": getattr(server, "minimum_launcher_version", ""),
            "serverVersion": getattr(server, "server_version_value", ""),
            "protocolVersion": getattr(server, "protocol_version", ""),
            "contentVersion": getattr(server, "content_version", ""),
        })

    @staticmethod
    def _now() -> float:
        import time
        return time.time()


class KnockServer(DualProtocolHTTPServer):

    def __init__(self, server_address, ssl_context=None, *,
                 launcher_version: str = "",
                 minimum_launcher_version: str = "",
                 server_version: str = "",
                 protocol_version: str = "",
                 content_version: str = "") -> None:
        super().__init__(server_address, KnockHandler, ssl_context)
        self.max_request_body = MAX_KNOCK_BODY
        self.require_tls = True
        self.enrollment_enabled = True
        self.launcher_version = launcher_version
        self.minimum_launcher_version = minimum_launcher_version
        self.server_version_value = server_version
        self.protocol_version = protocol_version
        self.content_version = content_version
        self.knock_throttle = throttle.FailureThrottle(
            attempts=KNOCK_ATTEMPTS,
            window=KNOCK_WINDOW_SECONDS,
            cooldown=KNOCK_COOLDOWN_SECONDS)

    def verify_request(self, request, client_address):
        return True
