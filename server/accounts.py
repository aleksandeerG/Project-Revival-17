# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import http.client
import json
import secrets
import socket
import ssl
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import access
import health
import throttle
from events import emit
from identity import IdentityStore

SERVER_VERSION = health.SERVER_VERSION

UA_GAME_SHIM_PREFIX = "EAApp/PC"
REDACTED = "<redacted>"
_SENSITIVE_HEADERS = {
    "authorization", "cookie", "x-session-id", "x-ut-sid",
}
_SENSITIVE_FIELDS = {
    "access_token", "auth_code", "authcode", "code", "device_token",
    "password", "secret", "session_id", "sid", "token",
}


def redacted_accounts_path(target: str) -> str:
    split = urlsplit(str(target or ""))
    pairs = [
        (name, REDACTED if name.lower() in _SENSITIVE_FIELDS else value)
        for name, value in parse_qsl(split.query, keep_blank_values=True)
    ]
    return urlunsplit(("", "", split.path, urlencode(pairs), ""))


def redacted_accounts_headers(headers) -> dict[str, str]:
    return {
        str(name): (REDACTED if str(name).lower() in _SENSITIVE_HEADERS
                    else str(value))
        for name, value in headers.items()
    }


def redacted_accounts_body(body: bytes) -> str:
    if not body:
        return ""
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, ValueError, TypeError):
        return "<redacted-unparsed-body>"

    def scrub(value):
        if isinstance(value, dict):
            return {
                str(name): (REDACTED if str(name).lower() in _SENSITIVE_FIELDS
                            else scrub(item))
                for name, item in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return json.dumps(
        scrub(document), separators=(",", ":"), ensure_ascii=False)[:2048]


MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_REQUEST_HEADER_BYTES = 32 * 1024
MAX_CONNECTIONS = 64
REQUEST_TIMEOUT_SECONDS = 30.0
TLS_PEEK_TIMEOUT_SECONDS = 10.0


class ConnectionBudget:

    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self.limit and self.active >= self.limit:
                return False
            self.active += 1
            self.peak = max(self.peak, self.active)
            return True

    def release(self) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)


def read_limited_body(handler, path: str) -> bytes | None:
    try:
        length = int(handler.headers.get("Content-Length", "0") or 0)
    except ValueError:
        return b""
    if length <= 0:
        return b""
    limit = getattr(handler.server, "max_request_body", MAX_REQUEST_BODY_BYTES)
    if limit and length > limit:
        emit("request-body-refused", path=path, method=handler.command,
             declared=length, limit=limit)
        handler.close_connection = True
        try:
            handler.send_response(413)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
        except OSError:
            pass
        return None
    return handler.rfile.read(length)


class DualProtocolHTTPServer(ThreadingHTTPServer):

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, server_address, handler_class, ssl_context: ssl.SSLContext | None = None):
        self.ssl_context = ssl_context
        self.require_tls = False
        self.store: IdentityStore | None = None
        self.fut_state = None
        self.max_request_body = MAX_REQUEST_BODY_BYTES
        self.max_connections = MAX_CONNECTIONS
        self.connection_budget = None
        self.access = None
        self.operator_access = None
        self.auth_throttle = throttle.FailureThrottle()
        self._connection_lock = threading.Lock()
        self._active_connections = 0
        self._peak_connections = 0
        super().__init__(server_address, handler_class)

    def verify_request(self, request, client_address):
        return access.refuse(self, client_address)

    def process_request(self, request, client_address):
        budget = self.connection_budget
        if budget is not None and not budget.acquire():
            emit("connection-refused", peer="%s:%s" % client_address,
                 active=budget.active, limit=budget.limit, scope="http-global")
            self.shutdown_request(request)
            return
        with self._connection_lock:
            if (self.max_connections
                    and self._active_connections >= self.max_connections):
                emit("connection-refused",
                     peer="%s:%s" % (client_address[0], client_address[1]),
                     active=self._active_connections,
                     limit=self.max_connections)
                self.shutdown_request(request)
                if budget is not None:
                    budget.release()
                return
            self._active_connections += 1
            self._peak_connections = max(self._peak_connections,
                                         self._active_connections)
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            try:
                request = self._upgrade(request, client_address)
            except OSError:
                self.shutdown_request(request)
                return
            try:
                self.finish_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)
        finally:
            with self._connection_lock:
                self._active_connections -= 1
            if self.connection_budget is not None:
                self.connection_budget.release()

    def get_request(self):
        return self.socket.accept()

    def _upgrade(self, connection, address):
        connection.settimeout(TLS_PEEK_TIMEOUT_SECONDS)
        first = connection.recv(1, socket.MSG_PEEK)
        if first[:1] == b"\x16":
            if self.ssl_context is None:
                raise OSError(
                    "TLS connection received but no certificate is configured")
            try:
                connection = self.ssl_context.wrap_socket(connection, server_side=True)
            except (ssl.SSLError, OSError) as exc:
                emit("tls-handshake-failed", peer=f"{address[0]}:{address[1]}", error=str(exc))
                raise OSError(str(exc)) from exc
        elif self.require_tls:
            emit("plaintext-connection-refused",
                 peer=f"{address[0]}:{address[1]}",
                 listener=self.server_address[1])
            raise OSError("plaintext is disabled on this listener")
        connection.settimeout(None)
        return connection

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        peer = f"{client_address[0]}:{client_address[1]}"
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError,
                              BrokenPipeError, TimeoutError)):
            emit("client-disconnected", peer=peer, error=type(error).__name__)
            return
        emit("request-error", peer=peer, error=type(error).__name__,
             message=str(error), traceback=traceback.format_exc())


class BoundedHTTPRequestHandler(BaseHTTPRequestHandler):

    max_header_bytes = MAX_REQUEST_HEADER_BYTES

    def parse_request(self) -> bool:
        original = self.rfile

        class LimitedReader:
            def __init__(self, wrapped, limit):
                self.wrapped, self.remaining = wrapped, limit

            def readline(self, size=-1):
                maximum = self.remaining + 1
                if size >= 0:
                    maximum = min(maximum, size)
                line = self.wrapped.readline(maximum)
                self.remaining -= len(line)
                if self.remaining < 0:
                    raise http.client.LineTooLong("aggregate request headers")
                return line

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

        self.rfile = LimitedReader(original, self.max_header_bytes)
        try:
            return super().parse_request()
        finally:
            self.rfile = original


class AccountsHandler(BoundedHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FIFA17FUTRevival"
    sys_version = ""

    timeout = REQUEST_TIMEOUT_SECONDS


    @property
    def store(self) -> IdentityStore:
        store = getattr(self.server, "store", None)
        if store is None:
            raise RuntimeError("server has no IdentityStore attached")
        return store

    @property
    def over_tls(self) -> bool:
        return isinstance(self.connection, ssl.SSLSocket)

    def client_kind(self) -> str:
        agent = self.headers.get("User-Agent", "")
        if agent.startswith(UA_GAME_SHIM_PREFIX):
            return "version.dll"
        return "launcher-or-tool" if agent else "unknown"

    def log_message(self, fmt, *args):
        return

    def _read_body(self) -> bytes | None:
        return read_limited_body(self, redacted_accounts_path(self.path))

    @property
    def request_id(self) -> str:
        existing = getattr(self, "_request_id", "")
        if not existing:
            existing = secrets.token_hex(4)
            self._request_id = existing
        return existing

    def _send_json(self, status: int, document: Any, *, name: str) -> None:
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        started = getattr(self, "_request_started", None)
        if started is not None:
            health.record_request("accounts",
                                  (time.perf_counter() - started) * 1000.0)
        self.send_response(status)
        self.send_header("X-Request-Id", self.request_id)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
        emit(
            "response",
            name=name,
            status=status,
            path=redacted_accounts_path(self.path),
            client=self.client_kind(),
            tls=self.over_tls,
            bytes=len(payload),
        )

    def _send_error_json(self, status: int, message: str, *, name: str) -> None:
        self._send_json(status, {"message": message}, name=name)

    def _unhandled(self, body: bytes = b"") -> None:
        emit(
            "unhandled-request",
            method=self.command,
            path=redacted_accounts_path(self.path),
            client=self.client_kind(),
            tls=self.over_tls,
            headers=redacted_accounts_headers(self.headers),
            body=redacted_accounts_body(body),
        )
        self._send_error_json(404, "not implemented in stage 0", name="unhandled")


    def do_GET(self) -> None:
        self._request_started = time.perf_counter()
        self._request_id = ""
        path = urlsplit(self.path).path.rstrip("/") or "/"
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        emit(
            "request",
            method="GET",
            requestId=self.request_id,
            path=redacted_accounts_path(self.path),
            client=self.client_kind(),
            tls=self.over_tls,
            agent=self.headers.get("User-Agent", ""),
        )

        if path == "/healthz":
            return self._send_json(200, health.liveness(), name="healthz")
        if path == "/readyz":
            document = health.readiness(
                getattr(self.server, "listeners", None),
                servers=getattr(self.server, "observed_servers", None),
                identity_store=getattr(self.server, "store", None),
                fut_state=getattr(self.server, "fut_state", None),
                access_list=getattr(self.server, "access", None))
            return self._send_json(200 if document["ready"] else 503,
                                   document, name="readyz")
        if path == "/metrics":
            if not self._operator_only():
                emit("operator-surface-refused", path="/metrics",
                     peer=self.client_address[0])
                return self._send_json(404, {"message": "not found"},
                                       name="metrics-refused")
            return self._metrics()
        if path == "/accounts/serverinfo":
            return self._serverinfo()
        if path == "/accounts/connect/auth":
            return self._connect_auth(query)
        if path == "/accounts/friends":
            return self._friends()
        if path == "/credits":
            return self._credits()
        if path == "/qos/qos":
            return self._qos()
        return self._unhandled()

    def do_POST(self) -> None:
        self._request_started = time.perf_counter()
        self._request_id = ""
        path = urlsplit(self.path).path.rstrip("/") or "/"
        body = self._read_body()
        if body is None:
            return
        emit(
            "request",
            method="POST",
            requestId=self.request_id,
            path=redacted_accounts_path(self.path),
            client=self.client_kind(),
            tls=self.over_tls,
            agent=self.headers.get("User-Agent", ""),
            bytes=len(body),
        )
        try:
            document = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(document, dict):
                document = {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            emit("malformed-json-body",
                 path=redacted_accounts_path(self.path), bytes=len(body))
            document = {}

        if path == "/accounts/login":
            return self._login(document)
        if path == "/accounts/validate":
            return self._validate_account(document)
        if path == "/accounts/connect/auth":
            return self._connect_auth_document(document)
        if path == "/accounts/discord":
            return self._discord(document)
        return self._unhandled(body)


    def _operator_only(self) -> bool:
        allowed = getattr(self.server, "operator_access", None)
        if allowed is None or not allowed.configured:
            return True
        return allowed.permits(self.client_address[0])

    def _metrics(self) -> None:
        server: Any = self.server
        self._send_json(
            200,
            health.snapshot(
                identity_store=self.store,
                fut_state=getattr(server, "fut_state", None),
                listeners=getattr(server, "listeners", None),
                servers=getattr(server, "observed_servers", None),
                access_list=getattr(server, "access", None),
                auth_throttle=getattr(server, "auth_throttle", None),
            ),
            name="metrics")

    def _serverinfo(self) -> None:
        fut_state = getattr(self.server, "fut_state", None)
        in_match = (fut_state.personas_in_match()
                    if fut_state is not None else ())
        presence = self.store.presence(in_match=in_match)
        self._send_json(
            200,
            {
                "playersOnline": presence["playersOnline"],
                "playersInGame": presence["playersInGame"],
                "serverVersion": SERVER_VERSION,
                "protocolVersion": getattr(self.server, "protocol_version", ""),
                "contentVersion": getattr(self.server, "content_version", ""),
                "ready": health.readiness(
                    getattr(self.server, "listeners", None),
                    servers=getattr(self.server, "observed_servers", None),
                    identity_store=getattr(self.server, "store", None),
                    fut_state=fut_state,
                    access_list=getattr(self.server, "access", None),
                )["ready"],
            },
            name="serverinfo",
        )

    def _login(self, document: dict[str, Any]) -> None:
        username = str(document.get("username", "") or "")
        password = str(document.get("password", "") or "")
        limiter = getattr(self.server, "auth_throttle", None)
        source = self.client_address[0]
        if limiter is not None and limiter.blocked(source):
            emit("login-throttled", client=self.client_kind(), peer=source)
            return self._send_error_json(
                429, "too many attempts, wait a minute", name="login-throttled")
        row = self.store.authenticate(username, password)
        if row is None:
            if limiter is not None:
                limiter.record_failure(source)
            emit("login-rejected", username=username, client=self.client_kind())
            return self._send_error_json(401, "wrong username or password", name="login-rejected")
        if limiter is not None:
            limiter.record_success(source)
        if not row["approved"]:
            return self._send_error_json(
                403, "this account is waiting for approval", name="login-unapproved"
            )
        sid = self.store.start_session(row["persona_id"])
        emit(
            "login-accepted",
            username=row["username"],
            persona_id=row["persona_id"],
            client=self.client_kind(),
        )
        self._send_json(
            200,
            {
                "sid": sid,
                "nucleusPersonaId": str(row["persona_id"]),
                "nucleusPersonaDisplayName": row["display_name"],
            },
            name="login-accepted",
        )

    def _validate_account(self, document: dict[str, Any]) -> None:
        username = str(document.get("username", "") or "")
        password = str(document.get("password", "") or "")
        limiter = getattr(self.server, "auth_throttle", None)
        source = self.client_address[0]
        if limiter is not None and limiter.blocked(source):
            emit("credential-check-throttled", client=self.client_kind(), peer=source)
            return self._send_error_json(
                429, "too many attempts, wait a minute", name="credential-check-throttled")

        row = self.store.authenticate(username, password)
        if row is None or not row["approved"]:
            if limiter is not None:
                limiter.record_failure(source)
            emit("credential-check-rejected", client=self.client_kind(), peer=source)
            return self._send_error_json(
                401, "wrong username or password", name="credential-check-rejected")

        if limiter is not None:
            limiter.record_success(source)
        emit("credential-check-accepted", client=self.client_kind(), peer=source)
        self._send_json(200, {"valid": True}, name="credential-check-accepted")

    def _discord(self, document: dict[str, Any]) -> None:
        emit("discord-attempt", has_code=bool(document.get("code")))
        self._send_error_json(
            501,
            "Discord sign-in is not enabled on this server. Use the operator password.",
            name="discord-disabled",
        )

    def _connect_auth(self, query: dict[str, list[str]]) -> None:
        sid = (query.get("access_token") or [""])[0]
        redirect = (query.get("redirect_uri") or [""])[0]
        self._issue_auth_code(sid, redirect)

    def _connect_auth_document(self, document: dict[str, Any]) -> None:
        sid = document.get("access_token", "")
        redirect = document.get("redirect_uri", "")
        self._issue_auth_code(
            sid if isinstance(sid, str) else "",
            redirect if isinstance(redirect, str) else "",
        )

    def _issue_auth_code(self, sid: str, redirect: str) -> None:
        code = self.store.mint_auth_code(sid) if sid else None
        if code is None:
            emit("auth-code-login-required", had_sid=bool(sid))
            payload = json.dumps({"error": "login_required"}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if redirect:
            location = f"{redirect}{'&' if '?' in redirect else '?'}code={code}"
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            emit("auth-code-issued", transport="302")
            return
        emit("auth-code-issued", transport="json")
        self._send_json(200, {"code": code}, name="auth-code")

    def _friends(self) -> None:
        sid = self.headers.get("X-Session-Id", "")
        row = self.store.session(sid)
        if row is None:
            return self._send_error_json(401, "no active session", name="friends-unauthenticated")
        self._send_json(200, self.store.friends(row["persona_id"]), name="friends")

    def _credits(self) -> None:
        sid = self.headers.get("X-Session-Id", "")
        row = self.store.session(sid)
        persona_id = row["persona_id"] if row is not None else 0
        fut_state = getattr(self.server, "fut_state", None)
        if persona_id and fut_state is not None:
            fut_state.ensure_persona(persona_id)
            balance = fut_state.balances(persona_id)[1]
        else:
            balance = self.store.credits(persona_id) if persona_id else 0
        emit("credits-shape-unconfirmed", persona_id=persona_id, balance=balance)
        self._send_json(
            200,
            {"credits": balance, "balance": balance, "points": balance},
            name="credits",
        )

    def _qos(self) -> None:
        emit("qos-shape-unconfirmed", path=redacted_accounts_path(self.path))
        self._send_json(200, {}, name="qos")
