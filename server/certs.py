# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import datetime
import hashlib
import ipaddress
import os
import secrets
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

DEFAULT_VALID_DAYS = 3650


def _san_entries(hostname: str,
                 extra_addresses: tuple[str, ...] = ()) -> list[x509.GeneralName]:
    try:
        primary_address = ipaddress.ip_address(hostname)
    except ValueError:
        entries: list[x509.GeneralName] = [x509.DNSName(hostname)]
    else:
        entries = [x509.IPAddress(primary_address)]
    if hostname != "localhost":
        entries.append(x509.DNSName("localhost"))
    seen = {"127.0.0.1", hostname}
    entries.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
    for address in extra_addresses:
        if address in seen:
            continue
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            entries.append(x509.DNSName(address))
        else:
            entries.append(x509.IPAddress(parsed))
        seen.add(address)
    return entries


def _certificate_stem(hostname: str) -> str:
    if all(character not in '<>:"/\\|?*' for character in hostname):
        return hostname
    digest = hashlib.sha256(hostname.encode("ascii")).hexdigest()[:20]
    return f"host-{digest}"


def _covers(cert_path: Path, addresses: tuple[str, ...]) -> bool:
    if not addresses:
        return True
    try:
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    present = {str(name) for name in san.get_values_for_type(x509.DNSName)}
    present |= {str(address) for address
                in san.get_values_for_type(x509.IPAddress)}
    return all(address in present for address in addresses)


def _pair_matches(cert_path: Path, key_path: Path) -> bool:
    try:
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=None)
        certificate_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        private_key = key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        return certificate_key == private_key
    except (OSError, ValueError, TypeError):
        return False


def _stage(path: Path, payload: bytes, mode: int) -> Path:
    staged = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def create_self_signed(
    hostname: str,
    directory: Path,
    *,
    force: bool = False,
    valid_days: int = DEFAULT_VALID_DAYS,
    extra_addresses: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = _certificate_stem(hostname)
    cert_path = directory / f"{stem}.crt"
    key_path = directory / f"{stem}.key"
    if (cert_path.exists() and key_path.exists() and not force
            and _covers(cert_path, extra_addresses)
            and _pair_matches(cert_path, key_path)):
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=valid_days))
        .add_extension(
            x509.SubjectAlternativeName(
                _san_entries(hostname, tuple(extra_addresses))),
            critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption())
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    staged_key: Path | None = None
    staged_cert: Path | None = None
    try:
        staged_key = _stage(key_path, key_bytes, 0o600)
        staged_cert = _stage(cert_path, cert_bytes, 0o644)
        os.replace(staged_key, key_path)
        os.replace(staged_cert, cert_path)
    finally:
        if staged_key is not None:
            staged_key.unlink(missing_ok=True)
        if staged_cert is not None:
            staged_cert.unlink(missing_ok=True)
    return cert_path, key_path


def der_sha256(cert_path: Path) -> str:
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    der = certificate.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest().upper()


def legacy_server_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    try:
        context.minimum_version = ssl.TLSVersion.TLSv1
    except (ValueError, OSError):
        pass
    for ciphers in ("DEFAULT:@SECLEVEL=0", "ALL:@SECLEVEL=0", "DEFAULT"):
        try:
            context.set_ciphers(ciphers)
            break
        except ssl.SSLError:
            continue
    return context
