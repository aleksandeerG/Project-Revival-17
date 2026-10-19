# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import re
import socket
import threading
import time
from ipaddress import AddressValueError, IPv4Address, ip_address
from typing import Any
from xml.etree import ElementTree

from accounts import BoundedHTTPRequestHandler, DualProtocolHTTPServer, read_limited_body
from events import emit

GET_SERVER_INSTANCE_PATH = "/redirector/getServerInstance"

CLIENT_VERSION_MEMBER = "clientversion"
_CLIENT_VERSION_PATTERN = re.compile(
    rf"<\s*{CLIENT_VERSION_MEMBER}\b[^>]*>(.*?)<\s*/\s*{CLIENT_VERSION_MEMBER}\s*>",
    re.IGNORECASE | re.DOTALL,
)


def parse_client_version(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        root = None
    if root is not None:
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag.lower() == CLIENT_VERSION_MEMBER:
                return (element.text or "").strip()
        return ""
    match = _CLIENT_VERSION_PATTERN.search(text)
    return match.group(1).strip() if match else ""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


_RESOLVED: dict[str, tuple[str, float]] = {}
_RESOLVED_LOCK = threading.Lock()
_RESOLVE_TTL_SECONDS = 60.0


def resolve_ipv4(host: str, *, fallback: str = "") -> str:
    literal = host.strip()
    try:
        return str(IPv4Address(literal))
    except (AddressValueError, ValueError):
        pass
    with _RESOLVED_LOCK:
        cached = _RESOLVED.get(literal)
    now = time.monotonic()
    if cached is not None and now - cached[1] < _RESOLVE_TTL_SECONDS:
        return cached[0]
    try:
        resolved = socket.gethostbyname(literal)
    except OSError as error:
        stale = cached[0] if cached is not None else ""
        emit("redirector-resolve-failed", host=literal, error=str(error),
             using=stale or fallback)
        return stale or fallback or literal
    if cached is None or cached[0] != resolved:
        emit("redirector-resolved", host=literal, address=resolved)
    with _RESOLVED_LOCK:
        _RESOLVED[literal] = (resolved, now)
    return resolved


def _is_private(address: str) -> bool:
    try:
        return ip_address(address).is_private
    except ValueError:
        return False


def blaze_host_for(peer: str, advertised: str, reached_on: str) -> str:
    if _is_private(peer) and reached_on:
        return reached_on
    return advertised


def build_serverinstanceinfo(
    host: str, port: int, *, secure: bool = False,
    client_versions: tuple[str, ...] = (), address_fallback: str = ""
) -> bytes:
    ip = int(IPv4Address(resolve_ipv4(host, fallback=address_fallback)))
    versions_xml = ""
    if client_versions:
        entries = "".join(f"    <value>{_escape(v)}</value>\n" for v in client_versions)
        versions_xml = (
            f"  <compatibleClientVersions>\n{entries}  </compatibleClientVersions>\n"
            "  <incompatibleClientVersions/>\n"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<serverinstanceinfo>\n"
        '  <address member="0">\n'
        "    <valu>\n"
        f"      <hostname>{host}</hostname>\n"
        f"      <ip>{ip}</ip>\n"
        f"      <port>{port}</port>\n"
        "    </valu>\n"
        "  </address>\n"
        f"  <secure>{1 if secure else 0}</secure>\n"
        + versions_xml
        + "  <default>1</default>\n"
        "</serverinstanceinfo>\n"
    )
    return xml.encode("utf-8")


class RedirectorHttpHandler(BoundedHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Redirector"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def _read_body(self) -> bytes | None:
        return read_limited_body(self, self.path)

    def _respond(self, status: int, payload: bytes, *, content_type: str, name: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        emit("redirector-response", name=name, status=status, path=self.path, bytes=len(payload))

    def do_POST(self) -> None:
        server: Any = self.server
        body = self._read_body()
        if body is None:
            return
        emit(
            "redirector-request",
            method="POST",
            path=self.path,
            agent=self.headers.get("User-Agent", ""),
            body=body.decode("utf-8", "replace"),
        )
        if self.path.split("?", 1)[0] == GET_SERVER_INSTANCE_PATH:
            client_versions: tuple[str, ...] = ()
            if getattr(server, "echo_client_versions", False):
                client_version = parse_client_version(body)
                client_versions = (client_version,) if client_version else ()
            try:
                reached_on = self.connection.getsockname()[0]
            except OSError:
                reached_on = ""
            blaze_host = blaze_host_for(
                self.client_address[0], server.blaze_host, reached_on)
            payload = build_serverinstanceinfo(
                blaze_host, server.blaze_port,
                secure=getattr(server, "blaze_secure", False),
                client_versions=client_versions, address_fallback=reached_on
            )
            self._respond(200, payload, content_type="application/xml", name="serverinstanceinfo")
            emit(
                "redirector-reply",
                blaze_host=blaze_host,
                peer=self.client_address[0],
                blaze_port=server.blaze_port,
                secure=getattr(server, "blaze_secure", False),
                client_versions=list(client_versions),
                xml=payload.decode("utf-8"),
            )
            return
        emit("redirector-unhandled", method="POST", path=self.path)
        self._respond(404, b"", content_type="text/plain", name="unhandled")

    def do_GET(self) -> None:
        emit("redirector-request", method="GET", path=self.path,
             agent=self.headers.get("User-Agent", ""))
        emit("redirector-unhandled", method="GET", path=self.path)
        self._respond(404, b"", content_type="text/plain", name="unhandled")


class RedirectorServer(DualProtocolHTTPServer):

    def __init__(
        self,
        server_address,
        ssl_context,
        blaze_host: str,
        blaze_port: int,
        echo_client_versions: bool = False,
        blaze_secure: bool = False,
    ) -> None:
        self.blaze_host = blaze_host
        self.blaze_port = blaze_port
        self.echo_client_versions = echo_client_versions
        self.blaze_secure = bool(blaze_secure)
        super().__init__(server_address, RedirectorHttpHandler, ssl_context)
