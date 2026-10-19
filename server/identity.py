# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import sqlite3
import threading

import health
from events import emit
import time
from contextlib import closing
from pathlib import Path
from collections.abc import Iterable
from typing import Any

SCHEMA_VERSION = 6

ENROLLMENT_SECONDS = 8 * 60 * 60
ENROLLMENT_ADDRESSES_PER_TOKEN = 3


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()

FIRST_PERSONA_ID = 1_000_001
PERSONA_ID_COUNTER = "persona_id"
SESSION_TTL_SECONDS = 24 * 60 * 60

PRESENCE_LEASE_SECONDS = 10 * 60
AUTH_CODE_TTL_SECONDS = 12 * 60 * 60
FUT_SESSION_TOKEN_BYTES = 32

PBKDF2_ITERATIONS = 200_000
DEVICE_TOKEN_BYTES = 32


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


class IdentityStore:
    def __init__(self, database: Path | str) -> None:
        self._database = str(database)
        self._lock = health.TimedLock("identity")
        Path(self._database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def health_check(self) -> tuple[bool, str]:
        if not self._lock.acquire(timeout=0.25):
            return False, "store lock did not become available"
        try:
            uri = Path(self._database).resolve().as_uri() + "?mode=rw"
            with closing(sqlite3.connect(
                    uri, uri=True, timeout=0.25)) as connection:
                row = connection.execute(
                    "SELECT version FROM schema_info").fetchone()
                if row is None or int(row[0]) != SCHEMA_VERSION:
                    return False, "schema is unavailable or outdated"
            return True, ""
        except sqlite3.Error as error:
            return False, str(error)
        finally:
            self._lock.release()

    @staticmethod
    def _stored_version(connection) -> int | None:
        tables = {row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables:
            return None
        if "schema_info" not in tables:
            return 1
        row = connection.execute("SELECT version FROM schema_info").fetchone()
        return int(row["version"]) if row is not None else 1

    def _backup_before_migration(self, from_version: int) -> Path:
        source = Path(self._database).resolve()
        target = (source.parent / "backups" /
                  ("%s-v%d-%s.sqlite3" % (source.stem, int(from_version),
                                          time.strftime("%Y%m%d-%H%M%S"))))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with (closing(sqlite3.connect(self._database)) as live,
                  closing(sqlite3.connect(target)) as backup):
                live.backup(backup)
        except (OSError, sqlite3.Error) as error:
            raise RuntimeError(
                "cannot back up %s before migrating it to schema %d: %s"
                % (self._database, SCHEMA_VERSION, error)) from error
        return target

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as reader:
            from_version = self._stored_version(reader)
        if from_version is not None and from_version < SCHEMA_VERSION:
            self._backup_before_migration(from_version)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );
                -- Monotonic id allocation. `value` is the last id handed out,
                -- so a deleted account cannot give its persona id to the next
                -- one registered.
                CREATE TABLE IF NOT EXISTS counters (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    persona_id    INTEGER PRIMARY KEY,
                    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name  TEXT NOT NULL,
                    password_hash TEXT,
                    device_token  TEXT NOT NULL UNIQUE,
                    credits       INTEGER NOT NULL DEFAULT 0,
                    approved      INTEGER NOT NULL DEFAULT 1,
                    created_at    INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    sid         TEXT PRIMARY KEY,
                    persona_id  INTEGER NOT NULL REFERENCES accounts(persona_id) ON DELETE CASCADE,
                    created_at  INTEGER NOT NULL,
                    expires_at  INTEGER NOT NULL,
                    last_seen   INTEGER NOT NULL,
                    in_game     INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code        TEXT PRIMARY KEY,
                    sid         TEXT NOT NULL REFERENCES sessions(sid) ON DELETE CASCADE,
                    persona_id  INTEGER NOT NULL,
                    created_at  INTEGER NOT NULL,
                    expires_at  INTEGER NOT NULL,
                    consumed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS fut_sessions (
                    sid         TEXT PRIMARY KEY,
                    auth_code   TEXT NOT NULL REFERENCES auth_codes(code) ON DELETE CASCADE,
                    account_sid TEXT NOT NULL REFERENCES sessions(sid) ON DELETE CASCADE,
                    persona_id  INTEGER NOT NULL REFERENCES accounts(persona_id) ON DELETE CASCADE,
                    device_id   TEXT NOT NULL DEFAULT '',
                    created_at  INTEGER NOT NULL,
                    expires_at  INTEGER NOT NULL,
                    last_seen   INTEGER NOT NULL,
                    revoked_at  INTEGER
                );
                -- Self-enrollment. `token_hash` is sha256 of the token the
                -- operator hands out; the token itself is never stored, for
                -- the same reason device tokens are not.
                CREATE TABLE IF NOT EXISTS enrollment_tokens (
                    token_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL UNIQUE,
                    token_hash  TEXT NOT NULL UNIQUE,
                    created_at  INTEGER NOT NULL,
                    revoked_at  INTEGER,
                    last_used   INTEGER
                );
                -- Addresses admitted by a knock. Durable, so a restart
                -- mid-session does not eject everyone who is playing.
                CREATE TABLE IF NOT EXISTS enrollments (
                    address     TEXT NOT NULL,
                    token_id    INTEGER NOT NULL
                                REFERENCES enrollment_tokens(token_id)
                                ON DELETE CASCADE,
                    created_at  INTEGER NOT NULL,
                    expires_at  INTEGER NOT NULL,
                    PRIMARY KEY (address, token_id)
                );
                -- Blaze connection groups. FIFA copies the id issued at
                -- login into every later GameManager request and does not log
                -- in again while its FUT session lives, so a registry that
                -- only exists in memory leaves every connected client unable
                -- to matchmake after a restart -- with no symptom but a search
                -- screen that never resolves and a cancel that is also
                -- refused. Durable, for the same reason `enrollments` is.
                CREATE TABLE IF NOT EXISTS blaze_sessions (
                    group_id     INTEGER PRIMARY KEY,
                    persona_id   INTEGER NOT NULL UNIQUE
                                 REFERENCES accounts(persona_id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    locale       INTEGER NOT NULL,
                    login_time   INTEGER NOT NULL,
                    expires_at   INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS blaze_sessions_live
                    ON blaze_sessions(expires_at);
                CREATE INDEX IF NOT EXISTS enrollments_live
                    ON enrollments(expires_at);
                CREATE INDEX IF NOT EXISTS sessions_persona ON sessions(persona_id);
                CREATE INDEX IF NOT EXISTS fut_sessions_persona
                    ON fut_sessions(persona_id, expires_at);
                CREATE INDEX IF NOT EXISTS fut_sessions_auth_device
                    ON fut_sessions(auth_code, device_id, expires_at);
                """
            )
            row = connection.execute("SELECT version FROM schema_info").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row["version"]) < SCHEMA_VERSION:
                self._migrate_versions(connection, int(row["version"]))
                connection.execute("UPDATE schema_info SET version=?", (SCHEMA_VERSION,))

    def _migrate_versions(self, connection, from_version: int) -> None:
        if from_version < 4:
            self._migrate_4_hash_device_tokens(connection)

    @staticmethod
    def _migrate_4_hash_device_tokens(connection) -> None:
        rows = connection.execute(
            "SELECT persona_id, device_token FROM accounts").fetchall()
        migrated = 0
        for row in rows:
            token = str(row["device_token"] or "")
            if not token:
                continue
            connection.execute(
                "UPDATE accounts SET device_token=? WHERE persona_id=?",
                (hash_device_token(token), int(row["persona_id"])))
            migrated += 1
        if migrated:
            emit("identity-device-tokens-hashed", accounts=migrated)


    @staticmethod
    def _allocate_persona_id(connection) -> int:
        highest = connection.execute(
            "SELECT COALESCE(MAX(persona_id), ?) AS n FROM accounts",
            (FIRST_PERSONA_ID - 1,)).fetchone()["n"]
        connection.execute(
            "INSERT OR IGNORE INTO counters(name,value) VALUES(?,?)",
            (PERSONA_ID_COUNTER, max(FIRST_PERSONA_ID - 1, int(highest))))
        row = connection.execute(
            "UPDATE counters SET value=value+1 WHERE name=? RETURNING value",
            (PERSONA_ID_COUNTER,)).fetchone()
        return int(row["value"])

    def create_account(
        self,
        username: str,
        password: str | None = None,
        *,
        display_name: str | None = None,
        approved: bool = True,
    ) -> dict[str, Any]:
        username = username.strip()
        if not username:
            raise ValueError("username must not be empty")
        now = int(time.time())
        with self._lock, closing(self._connect()) as connection, connection:
            persona_id = self._allocate_persona_id(connection)
            record = {
                "persona_id": persona_id,
                "username": username,
                "display_name": display_name or username,
                "password_hash": _hash_password(password) if password else None,
                "device_token": secrets.token_hex(DEVICE_TOKEN_BYTES),
                "credits": 0,
                "approved": 1 if approved else 0,
                "created_at": now,
            }
            stored = dict(record)
            stored["device_token"] = hash_device_token(record["device_token"])
            connection.execute(
                "INSERT INTO accounts(persona_id, username, display_name, password_hash,"
                " device_token, credits, approved, created_at)"
                " VALUES (:persona_id, :username, :display_name, :password_hash,"
                " :device_token, :credits, :approved, :created_at)",
                stored,
            )
        return record

    def create_invite_identity(
        self, username: str, password: str, *, now: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        username = str(username).strip()
        if not username:
            raise ValueError("username must not be empty")
        if not password:
            raise ValueError("password must not be empty")
        current = int(time.time()) if now is None else int(now)
        token = secrets.token_hex(DEVICE_TOKEN_BYTES)

        with self._lock, closing(self._connect()) as connection, connection:
            persona_id = self._allocate_persona_id(connection)
            record = {
                "persona_id": persona_id,
                "username": username,
                "display_name": username,
                "password_hash": _hash_password(password),
                "device_token": secrets.token_hex(DEVICE_TOKEN_BYTES),
                "credits": 0,
                "approved": 1,
                "created_at": current,
            }
            stored = dict(record)
            stored["device_token"] = hash_device_token(record["device_token"])
            connection.execute(
                "INSERT INTO accounts(persona_id, username, display_name, password_hash,"
                " device_token, credits, approved, created_at)"
                " VALUES (:persona_id, :username, :display_name, :password_hash,"
                " :device_token, :credits, :approved, :created_at)", stored)
            connection.execute(
                "INSERT INTO enrollment_tokens(name,token_hash,created_at) VALUES(?,?,?)",
                (username, hash_device_token(token), current))
        return record, token

    def reissue_invite_identity(
        self, username: str, password: str, *, now: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        username = str(username).strip()
        if not username:
            raise ValueError("username must not be empty")
        if not password:
            raise ValueError("password must not be empty")

        current = int(time.time()) if now is None else int(now)
        token = secrets.token_hex(DEVICE_TOKEN_BYTES)
        password_hash = _hash_password(password)
        device_token_hash = hash_device_token(
            secrets.token_hex(DEVICE_TOKEN_BYTES))
        enrollment_hash = hash_device_token(token)

        with self._lock, closing(self._connect()) as connection, connection:
            account = connection.execute(
                "SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
            if account is None:
                raise ValueError("account %r does not exist" % username)

            persona_id = int(account["persona_id"])
            canonical_name = str(account["username"])
            connection.execute(
                "UPDATE accounts SET password_hash=?, device_token=?"
                " WHERE persona_id=?",
                (password_hash, device_token_hash, persona_id))

            connection.execute(
                "DELETE FROM sessions WHERE persona_id=?", (persona_id,))

            existing_tokens = connection.execute(
                "SELECT token_id,name FROM enrollment_tokens"
                " WHERE name=? COLLATE NOCASE",
                (canonical_name,)).fetchall()
            if not existing_tokens:
                connection.execute(
                    "INSERT INTO enrollment_tokens(name,token_hash,created_at)"
                    " VALUES(?,?,?)",
                    (canonical_name, enrollment_hash, current))
            else:
                token_ids = [int(row["token_id"]) for row in existing_tokens]
                for token_id in token_ids:
                    connection.execute(
                        "DELETE FROM enrollments WHERE token_id=?", (token_id,))
                replacement_id = token_ids[0]
                for token_id in token_ids[1:]:
                    connection.execute(
                        "UPDATE enrollment_tokens SET revoked_at=? WHERE token_id=?",
                        (current, token_id))
                connection.execute(
                    "UPDATE enrollment_tokens"
                    " SET token_hash=?,created_at=?,revoked_at=NULL,last_used=NULL"
                    " WHERE token_id=?",
                    (enrollment_hash, current, replacement_id))

            record = {
                "persona_id": persona_id,
                "username": canonical_name,
                "display_name": str(account["display_name"]),
                "approved": int(account["approved"]),
            }

        emit("invite-reissued", username=canonical_name, persona_id=persona_id)
        return record, token


    def create_enrollment_token(self, name: str,
                                *, now: int | None = None) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError("an enrollment token needs a name")
        token = secrets.token_hex(DEVICE_TOKEN_BYTES)
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO enrollment_tokens(name,token_hash,created_at)"
                " VALUES(?,?,?)",
                (name, hash_device_token(token), current))
        return token

    def revoke_enrollment_token(self, name: str,
                                *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT token_id FROM enrollment_tokens WHERE name=?"
                " AND revoked_at IS NULL", (str(name).strip(),)).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE enrollment_tokens SET revoked_at=? WHERE token_id=?",
                (current, int(row["token_id"])))
            connection.execute("DELETE FROM enrollments WHERE token_id=?",
                               (int(row["token_id"]),))
        return True

    def enrollment_tokens(self) -> list[dict]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT token_id,name,created_at,revoked_at,last_used"
                " FROM enrollment_tokens ORDER BY token_id").fetchall()
        return [dict(row) for row in rows]

    def enroll(self, token: str, address: str, *,
               seconds: int = ENROLLMENT_SECONDS,
               now: int | None = None) -> dict | None:
        current = int(time.time()) if now is None else int(now)
        address = str(address or "").strip()
        if not address:
            return None
        try:
            ipaddress.ip_address(address)
        except ValueError:
            return None
        digest = hash_device_token(str(token or ""))
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT token_id,name FROM enrollment_tokens"
                " WHERE token_hash=? AND revoked_at IS NULL",
                (digest,)).fetchone()
            if row is None:
                return None
            token_id = int(row["token_id"])
            connection.execute("DELETE FROM enrollments WHERE expires_at<=?",
                               (current,))
            connection.execute(
                "INSERT INTO enrollments(address,token_id,created_at,expires_at)"
                " VALUES(?,?,?,?)"
                " ON CONFLICT(address,token_id) DO UPDATE SET expires_at=?",
                (address, token_id, current, current + int(seconds),
                 current + int(seconds)))
            connection.execute(
                "DELETE FROM enrollments WHERE token_id=? AND address NOT IN ("
                "  SELECT address FROM enrollments WHERE token_id=?"
                "  ORDER BY expires_at DESC LIMIT ?)",
                (token_id, token_id, ENROLLMENT_ADDRESSES_PER_TOKEN))
            connection.execute(
                "UPDATE enrollment_tokens SET last_used=? WHERE token_id=?",
                (current, token_id))
        return {"token_id": token_id, "name": str(row["name"]),
                "address": address, "expires_at": current + int(seconds)}

    def save_blaze_session(
        self,
        group_id: int,
        persona_id: int,
        display_name: str,
        locale: int,
        login_time: int,
        expires_at: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO blaze_sessions
                    (group_id, persona_id, display_name, locale,
                     login_time, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(persona_id) DO UPDATE SET
                    group_id=excluded.group_id,
                    display_name=excluded.display_name,
                    locale=excluded.locale,
                    login_time=excluded.login_time,
                    expires_at=excluded.expires_at
                """,
                (int(group_id), int(persona_id), str(display_name),
                 int(locale), int(login_time), int(expires_at)),
            )

    def blaze_sessions(self, *, now: int | None = None) -> list[dict]:
        current = int(time.time()) if now is None else int(now)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM blaze_sessions WHERE expires_at <= ?", (current,))
            rows = connection.execute(
                "SELECT group_id, persona_id, display_name, locale, "
                "login_time, expires_at FROM blaze_sessions "
                "ORDER BY login_time"
            ).fetchall()
        return [dict(row) for row in rows]

    def enrolled_addresses(self, *, now: int | None = None) -> set[str]:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT address FROM enrollments WHERE expires_at>?",
                (current,)).fetchall()
        return {str(row["address"]) for row in rows}

    def enrollments(self, *, now: int | None = None) -> list[dict]:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT e.address, e.expires_at, t.name FROM enrollments e"
                " JOIN enrollment_tokens t ON t.token_id=e.token_id"
                " WHERE e.expires_at>? ORDER BY e.expires_at DESC",
                (current,)).fetchall()
        return [{"address": str(row["address"]), "name": str(row["name"]),
                 "expiresIn": int(row["expires_at"]) - current} for row in rows]

    def account(self, username: str) -> sqlite3.Row | None:
        with self._lock, closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM accounts WHERE username = ?", (username.strip(),)
            ).fetchone()

    def account_by_persona(self, persona_id: int) -> sqlite3.Row | None:
        with self._lock, closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM accounts WHERE persona_id = ?", (int(persona_id),)
            ).fetchone()

    def authenticate(self, username: str, secret: str) -> sqlite3.Row | None:
        row = self.account(username)
        if row is None or not secret:
            return None
        if hmac.compare_digest(hash_device_token(secret), row["device_token"]):
            return row
        stored = row["password_hash"]
        if stored and _verify_password(secret, stored):
            return row
        return None


    def start_session(self, persona_id: int) -> str:
        now = int(time.time())
        sid = secrets.token_hex(16)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO sessions(sid, persona_id, created_at, expires_at, last_seen)"
                " VALUES (?, ?, ?, ?, ?)",
                (sid, int(persona_id), now, now + SESSION_TTL_SECONDS, now),
            )
        return sid

    def session(self, sid: str) -> sqlite3.Row | None:
        if not sid:
            return None
        now = int(time.time())
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE sid = ? AND expires_at > ?", (sid, now)
            ).fetchone()
            if row is not None:
                connection.execute("UPDATE sessions SET last_seen = ? WHERE sid = ?", (now, sid))
            return row


    def mint_auth_code(self, sid: str) -> str | None:
        row = self.session(sid)
        if row is None:
            return None
        now = int(time.time())
        code = secrets.token_hex(16)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM auth_codes WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO auth_codes(code, sid, persona_id, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (code, sid, row["persona_id"], now, now + AUTH_CODE_TTL_SECONDS),
            )
        return code

    def consume_auth_code(self, code: str) -> sqlite3.Row | None:
        now = int(time.time())
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM auth_codes WHERE code = ? AND expires_at > ?",
                (code, now),
            ).fetchone()
            if row is None:
                return None
            if row["consumed_at"] is None:
                connection.execute(
                    "UPDATE auth_codes SET consumed_at = ? WHERE code = ?", (now, code)
                )
                row = connection.execute(
                    "SELECT * FROM auth_codes WHERE code = ?", (code,)
                ).fetchone()
            return row


    def start_fut_session(
        self,
        code: str,
        *,
        device_id: str = "",
        now: int | None = None,
    ) -> sqlite3.Row | None:
        code = str(code or "")
        if not code:
            return None
        current = int(time.time()) if now is None else int(now)
        device_id = str(device_id or "")[:256]
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM fut_sessions WHERE expires_at<=?", (current,)
            )
            authority = connection.execute(
                "SELECT a.code,a.sid AS account_sid,a.persona_id,"
                " a.expires_at AS auth_expires,s.expires_at AS session_expires"
                " FROM auth_codes a"
                " JOIN sessions s ON s.sid=a.sid AND s.persona_id=a.persona_id"
                " JOIN accounts u ON u.persona_id=a.persona_id"
                " WHERE a.code=? AND a.expires_at>? AND s.expires_at>?"
                " AND u.approved=1",
                (code, current, current),
            ).fetchone()
            if authority is None:
                return None

            existing = connection.execute(
                "SELECT * FROM fut_sessions WHERE auth_code=? AND device_id=?"
                " AND revoked_at IS NULL AND expires_at>?"
                " ORDER BY created_at DESC LIMIT 1",
                (code, device_id, current),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    "UPDATE fut_sessions SET last_seen=? WHERE sid=?",
                    (current, existing["sid"]),
                )
                return connection.execute(
                    "SELECT * FROM fut_sessions WHERE sid=?", (existing["sid"],)
                ).fetchone()

            if connection.execute(
                    "SELECT consumed_at FROM auth_codes WHERE code=?", (code,)
            ).fetchone()["consumed_at"] is None:
                connection.execute(
                    "UPDATE auth_codes SET consumed_at=? WHERE code=?",
                    (current, code),
                )

            sid = secrets.token_hex(FUT_SESSION_TOKEN_BYTES)
            expires_at = min(
                int(authority["auth_expires"]),
                int(authority["session_expires"]),
            )
            connection.execute(
                "INSERT INTO fut_sessions(sid,auth_code,account_sid,persona_id,"
                "device_id,created_at,expires_at,last_seen) VALUES(?,?,?,?,?,?,?,?)",
                (sid, code, authority["account_sid"], int(authority["persona_id"]),
                 device_id, current, expires_at, current),
            )
            return connection.execute(
                "SELECT * FROM fut_sessions WHERE sid=?", (sid,)
            ).fetchone()

    def fut_session(self, sid: str, *, now: int | None = None) -> sqlite3.Row | None:
        sid = str(sid or "")
        if not sid:
            return None
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT f.* FROM fut_sessions f"
                " JOIN accounts a ON a.persona_id=f.persona_id"
                " JOIN sessions s ON s.sid=f.account_sid"
                " WHERE f.sid=? AND f.revoked_at IS NULL AND f.expires_at>?"
                " AND s.expires_at>? AND a.approved=1",
                (sid, current, current),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE fut_sessions SET last_seen=? WHERE sid=?", (current, sid)
            )
            return connection.execute(
                "SELECT * FROM fut_sessions WHERE sid=?", (sid,)
            ).fetchone()

    def revoke_fut_session(self, sid: str, *, now: int | None = None) -> bool:
        sid = str(sid or "")
        if not sid:
            return False
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            return connection.execute(
                "UPDATE fut_sessions SET revoked_at=?"
                " WHERE sid=? AND revoked_at IS NULL",
                (current, sid),
            ).rowcount > 0


    def friends(self, persona_id: int) -> list[dict[str, str]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT persona_id, display_name FROM accounts WHERE persona_id != ? ORDER BY persona_id",
                (int(persona_id),),
            ).fetchall()
        return [
            {"persona_id": str(row["persona_id"]), "display_name": row["display_name"]}
            for row in rows
        ]

    def credits(self, persona_id: int) -> int:
        row = self.account_by_persona(persona_id)
        return int(row["credits"]) if row is not None else 0

    def set_credits(self, persona_id: int, value: int) -> int:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE accounts SET credits = ? WHERE persona_id = ?", (int(value), int(persona_id))
            )
        return int(value)

    def presence(self, *, in_match: Iterable[int] = (),
                 now: int | None = None,
                 lease: int = PRESENCE_LEASE_SECONDS) -> dict[str, int]:
        current = int(time.time()) if now is None else int(now)
        cutoff = current - max(0, int(lease))
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT persona_id FROM fut_sessions"
                " WHERE revoked_at IS NULL AND expires_at > ? AND last_seen >= ?"
                " UNION"
                " SELECT DISTINCT persona_id FROM sessions"
                " WHERE expires_at > ? AND last_seen >= ?",
                (current, cutoff, current, cutoff),
            ).fetchall()
        online = {int(row["persona_id"]) for row in rows}
        playing = {int(persona_id) for persona_id in in_match}
        online |= playing
        return {"playersOnline": len(online), "playersInGame": len(playing)}
