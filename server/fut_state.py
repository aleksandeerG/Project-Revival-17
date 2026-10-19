# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import base64
import binascii
import json
import secrets
import sqlite3
import threading

import fut_economy
import health
import time
from contextlib import closing
from pathlib import Path

UNIQUE_ITEM_TYPES = frozenset({"kit", "stadium", "ball", "badge", "custom"})

FIRST_PACK_ITEM_ID = 10_000
MAX_CREDITS = fut_economy.MAX_BALANCE
TRANSFER_PILE_LIMIT = 100
MIN_LISTING_PRICE = 150
MAX_LISTING_PRICE = 15_000_000
LISTING_DURATIONS = frozenset({3600, 10_800, 21_600, 43_200, 86_400, 259_200})
FIRST_TRADE_ID = 1_000_000_000

TRADE_ID_COUNTER = "trade_id"
GAME_REPORT_ID_COUNTER = "game_report_id"

PARTICIPATION_RESULTS = ("WIN", "DRAW", "LOSS",
                         "DNF_WIN", "DNF_DRAW", "DNF_LOSS")


class SbcValidationError(ValueError):

    def __init__(self, reasons: list[str] | str):
        self.reasons = ([str(reasons)] if isinstance(reasons, str)
                        else [str(reason) for reason in reasons])
        super().__init__("; ".join(self.reasons))


def squad_id_counter(persona_id: int) -> str:
    return "squad_id:%d" % int(persona_id)


SCHEMA_VERSION = 8

SEASON_MODE_OFFLINE = "OFFLINE"
SEASON_MODE_ONLINE = "ONLINE"
SEASON_MODES = frozenset({SEASON_MODE_OFFLINE, SEASON_MODE_ONLINE})
SEASON_CONTEXT_KEY = "season:selectedMode"

MATCH_PLAYLIST_OFFLINE = "offline"
MATCH_PLAYLIST_ONLINE_SINGLE = "online_single"
MATCH_PLAYLIST_ONLINE_SEASONS = "online_seasons"
MATCH_PLAYLIST_ONLINE_DRAFT = "online_draft"
MATCH_PLAYLIST_UNRESOLVED = "unresolved"

MARKET_TAX_BPS = 500

MARKET_QUALITY_BANDS = {"bronze": (0, 64), "silver": (65, 74), "gold": (75, 99)}

MARKET_ANTI_SNIPE_SECONDS = 30

MATCH_EXPIRY_SECONDS = 5400


class FutStateStore:
    def __init__(self, database: Path | str,
                 match_expiry_seconds: int = MATCH_EXPIRY_SECONDS) -> None:
        self._database = str(database)
        self.match_expiry_seconds = max(0, int(match_expiry_seconds))
        self._lock = health.TimedLock("fut")
        self._known_personas: set[int] = set()
        self._seeded_personas: set[int] = set()
        Path(self._database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
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

    @staticmethod
    def _seed_counter(connection, name: str, value: int) -> None:
        connection.execute(
            "INSERT INTO counters(name,value) VALUES(?,?)"
            " ON CONFLICT(name) DO UPDATE SET value=MAX(value, excluded.value)",
            (str(name), int(value)))

    @staticmethod
    def _allocate_ids(connection, name: str, first: int, count: int = 1,
                      *, seed: int | None = None) -> int:
        count = max(1, int(count))
        connection.execute(
            "INSERT OR IGNORE INTO counters(name,value) VALUES(?,?)",
            (str(name), int(first) - 1 if seed is None else int(seed)))
        row = connection.execute(
            "UPDATE counters SET value=value+? WHERE name=? RETURNING value",
            (count, str(name))).fetchone()
        return int(row["value"]) - count + 1

    def _migrate_2_counters(self, connection) -> None:
        tables = {row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for name, first, table in (
                (TRADE_ID_COUNTER, FIRST_TRADE_ID, "trades"),
                ("market_trade_id", 2_000_000_000, "market_listings")):
            if table not in tables:
                continue
            row = connection.execute(
                "SELECT MAX(trade_id) AS n FROM %s" % table).fetchone()
            highest = int(row["n"]) if row and row["n"] is not None else 0
            self._seed_counter(connection, name, max(first - 1, highest))
        for row in connection.execute(
                "SELECT persona_id, MAX(squad_id) AS n FROM squads"
                " GROUP BY persona_id").fetchall():
            self._seed_counter(connection,
                               squad_id_counter(int(row["persona_id"])),
                               max(1, int(row["n"] or 1)))

    def _migrate_4_real_market(self, connection) -> None:
        columns = {row["name"] for row in
                   connection.execute("PRAGMA table_info(trades)")}
        additions = (
            ("payload", "TEXT NOT NULL DEFAULT '{}'"),
            ("bidder_persona", "INTEGER NOT NULL DEFAULT 0"),
            ("awarded_item_id", "INTEGER NOT NULL DEFAULT 0"),
            ("seller_name", "TEXT NOT NULL DEFAULT ''"),
            ("seller_established", "INTEGER NOT NULL DEFAULT 0"),
            ("resource_id", "INTEGER NOT NULL DEFAULT 0"),
            ("search_type", "TEXT NOT NULL DEFAULT ''"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("rating", "INTEGER NOT NULL DEFAULT 0"),
            ("rare_flag", "INTEGER NOT NULL DEFAULT 0"),
            ("league_id", "INTEGER NOT NULL DEFAULT 0"),
            ("nation", "INTEGER NOT NULL DEFAULT 0"),
            ("team_id", "INTEGER NOT NULL DEFAULT 0"),
            ("position", "TEXT NOT NULL DEFAULT ''"),
            ("play_style", "INTEGER NOT NULL DEFAULT 0"),
        )
        for name, ddl in additions:
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE trades ADD COLUMN {name} {ddl}")

        rows = connection.execute(
            "SELECT t.persona_id,t.trade_id,i.payload FROM trades t"
            " JOIN items i ON i.persona_id=t.persona_id"
            " AND i.item_id=t.item_id").fetchall()
        for row in rows:
            try:
                item = json.loads(row["payload"])
            except (TypeError, ValueError):
                item = {}
            fields = self._market_fields(item)
            connection.execute(
                "UPDATE trades SET payload=?,resource_id=?,search_type=?,"
                " category=?,rating=?,rare_flag=?,league_id=?,nation=?,"
                " team_id=?,position=?,play_style=?"
                " WHERE persona_id=? AND trade_id=?",
                (self._encode(item), *fields, int(row["persona_id"]),
                 int(row["trade_id"])))

        tables = {row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "market_listings" in tables:
            connection.execute("DROP TABLE market_listings")

        connection.execute(
            "CREATE INDEX IF NOT EXISTS trades_market_search"
            " ON trades(search_type,category,trade_state,expires_at)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS trades_resource_search"
            " ON trades(resource_id,trade_state)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS trades_global_id ON trades(trade_id)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS auction_watches ("
            " persona_id INTEGER NOT NULL,trade_id INTEGER NOT NULL,"
            " created_at INTEGER NOT NULL,PRIMARY KEY(persona_id,trade_id))")

    def _migrate_5_server_owned_sbc(self, connection) -> None:
        rows = connection.execute(
            "SELECT persona_id,name,payload FROM clientdata"
            " WHERE name='sbcProgress' OR name LIKE 'sbcSquad%'").fetchall()
        now = int(time.time())
        for row in rows:
            try:
                entries = json.loads(row["payload"] or "[]")
                values = {int(entry["key"]): int(entry["value"])
                          for entry in entries if isinstance(entry, dict)}
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            persona_id, name = int(row["persona_id"]), str(row["name"])
            if name == "sbcProgress":
                for challenge_id, times in values.items():
                    if challenge_id > 0 and times > 0:
                        connection.execute(
                            "INSERT OR IGNORE INTO sbc_progress"
                            "(persona_id,challenge_id,times_completed,completed_at)"
                            " VALUES(?,?,1,?)", (persona_id, challenge_id, now))
                continue
            suffix = name[len("sbcSquad"):]
            if not suffix.isdigit():
                continue
            payload = {
                "slots": {str(index): item_id for index, item_id in values.items()
                          if 0 <= index < 23 and item_id > 0},
                "rating": values.get(100, 0),
                "chemistry": values.get(101, 0),
                "formation": "",
            }
            connection.execute(
                "INSERT OR IGNORE INTO sbc_squads"
                "(persona_id,challenge_id,payload,updated_at) VALUES(?,?,?,?)",
                (persona_id, int(suffix), self._encode(payload), now))

        connection.execute(
            "DELETE FROM clientdata WHERE name='sbcProgress'"
            " OR name LIKE 'sbcSquad%'")

    def _migrate_6_sbc_rewards(self, connection) -> None:
        columns = {row["name"] for row in
                   connection.execute("PRAGMA table_info(sbc_set_rewards)")}
        if "times_granted" not in columns:
            connection.execute(
                "ALTER TABLE sbc_set_rewards ADD COLUMN times_granted "
                "INTEGER NOT NULL DEFAULT 1")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS unopened_packs ("
            " entitlement_id INTEGER PRIMARY KEY,"
            " persona_id INTEGER NOT NULL,"
            " pack_id INTEGER NOT NULL,"
            " untradeable INTEGER NOT NULL DEFAULT 0,"
            " source TEXT NOT NULL DEFAULT '',"
            " granted_at INTEGER NOT NULL)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS unopened_packs_persona "
            "ON unopened_packs(persona_id, entitlement_id)")

    def _migrate_7_season_modes(self, connection) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO season_progress("
            "persona_id,mode,season_id,division_id,round,data_version,user_data,"
            "progress_data_version,progress_data,campaign,played,won,drawn,lost,"
            "points,status,last_result,updated_at,version) "
            "SELECT persona_id,'OFFLINE',season_id,division_id,round,"
            "data_version,user_data,progress_data_version,progress_data,1,"
            "0,0,0,0,0,CASE WHEN round<=1 THEN 'active' ELSE 'legacy' END,'',"
            "updated_at,1 FROM seasons")
        match_columns = {row["name"] for row in
                         connection.execute("PRAGMA table_info(matches)")}
        if "playlist" not in match_columns:
            connection.execute(
                "ALTER TABLE matches ADD COLUMN playlist TEXT NOT NULL "
                "DEFAULT 'unresolved'")
        for name, ddl in (
                ("season_mode", "TEXT NOT NULL DEFAULT ''"),
                ("season_coins", "INTEGER NOT NULL DEFAULT 0"),
                ("season_end_result", "TEXT NOT NULL DEFAULT ''"),
                ("season_division_before", "INTEGER NOT NULL DEFAULT 0"),
                ("season_division_after", "INTEGER NOT NULL DEFAULT 0"),
                ("season_campaign", "INTEGER NOT NULL DEFAULT 0")):
            if name not in match_columns:
                connection.execute(
                    "ALTER TABLE matches ADD COLUMN %s %s" % (name, ddl))

    def _migrate_8_basic_play_styles(self, connection) -> None:
        import fut_items

        def corrected(payload: str) -> dict | None:
            try:
                item = json.loads(payload or "{}")
            except (TypeError, ValueError):
                return None
            if not isinstance(item, dict) or item.get("itemType") != "player":
                return None
            style = fut_items.valid_play_style(
                str(item.get("preferredPosition", "") or ""),
                item.get("playStyle"))
            if item.get("playStyle") == style:
                return None
            item["playStyle"] = style
            return item

        for row in connection.execute(
                "SELECT persona_id,item_id,payload FROM items"
                " WHERE item_type='player'").fetchall():
            item = corrected(row["payload"])
            if item is not None:
                connection.execute(
                    "UPDATE items SET payload=? WHERE persona_id=?"
                    " AND item_id=?",
                    (self._encode(item), int(row["persona_id"]),
                     int(row["item_id"])))
        for row in connection.execute(
                "SELECT persona_id,trade_id,payload FROM trades").fetchall():
            item = corrected(row["payload"])
            if item is not None:
                connection.execute(
                    "UPDATE trades SET payload=?,play_style=?"
                    " WHERE persona_id=? AND trade_id=?",
                    (self._encode(item), int(item["playStyle"]),
                     int(row["persona_id"]), int(row["trade_id"])))

    _MIGRATIONS = {2: _migrate_2_counters, 4: _migrate_4_real_market,
                   5: _migrate_5_server_owned_sbc,
                   6: _migrate_6_sbc_rewards,
                   7: _migrate_7_season_modes,
                   8: _migrate_8_basic_play_styles}

    def _apply_schema_migrations(self, connection,
                                 from_version: int | None) -> None:
        if from_version is None:
            reached = SCHEMA_VERSION
        else:
            reached = int(from_version)
            for version in range(reached + 1, SCHEMA_VERSION + 1):
                migration = self._MIGRATIONS.get(version)
                if migration is not None:
                    migration(self, connection)
                reached = version
        row = connection.execute("SELECT version FROM schema_info").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO schema_info(version) VALUES(?)", (reached,))
        elif int(row["version"]) != reached:
            connection.execute("UPDATE schema_info SET version=?", (reached,))

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as reader:
            from_version = self._stored_version(reader)
        if from_version is not None and from_version < SCHEMA_VERSION:
            self._backup_before_migration(from_version)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS wallets (
                    persona_id INTEGER PRIMARY KEY,
                    credits INTEGER NOT NULL,
                    points INTEGER NOT NULL,
                    -- The highest item id ever handed out. MAX(item_id) alone
                    -- falls back when the highest card is sold, and the next
                    -- pack then reuses that id.
                    high_water INTEGER NOT NULL DEFAULT 0
                );
                -- Immutable audit trail. `wallets` is the materialized balance
                -- used by hot reads; both change in the same transaction.
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    persona_id INTEGER NOT NULL,
                    currency TEXT NOT NULL CHECK(currency IN ('COINS','POINTS')),
                    requested_amount INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
                    reason TEXT NOT NULL,
                    related_type TEXT NOT NULL DEFAULT '',
                    related_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    UNIQUE (persona_id, currency, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS wallet_transactions_history
                    ON wallet_transactions(persona_id, currency, created_at,
                                           transaction_id);
                CREATE TRIGGER IF NOT EXISTS wallet_transactions_no_update
                    BEFORE UPDATE ON wallet_transactions
                    BEGIN
                        SELECT RAISE(ABORT, 'wallet ledger is immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS wallet_transactions_no_delete
                    BEFORE DELETE ON wallet_transactions
                    BEGIN
                        SELECT RAISE(ABORT, 'wallet ledger is immutable');
                    END;
                CREATE TABLE IF NOT EXISTS items (
                    persona_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    asset_id INTEGER NOT NULL,
                    pile TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    acquired_at INTEGER NOT NULL,
                    item_type TEXT NOT NULL DEFAULT 'player',
                    PRIMARY KEY (persona_id, item_id)
                );
                CREATE INDEX IF NOT EXISTS items_persona_pile
                    ON items(persona_id, pile, item_id);
                CREATE INDEX IF NOT EXISTS items_persona_asset
                    ON items(persona_id, asset_id, pile);
                CREATE TABLE IF NOT EXISTS squads (
                    persona_id INTEGER NOT NULL,
                    squad_id INTEGER NOT NULL DEFAULT 1,
                    name TEXT,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (persona_id, squad_id)
                );
                CREATE TABLE IF NOT EXISTS clientdata (
                    persona_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (persona_id, name)
                );
                -- SBC state is authoritative game state, not client scratch
                -- data. Saves, consumption, completion and rewards share the
                -- same database and transaction boundary.
                CREATE TABLE IF NOT EXISTS sbc_squads (
                    persona_id INTEGER NOT NULL,
                    challenge_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (persona_id, challenge_id)
                );
                CREATE TABLE IF NOT EXISTS sbc_progress (
                    persona_id INTEGER NOT NULL,
                    challenge_id INTEGER NOT NULL,
                    times_completed INTEGER NOT NULL CHECK(times_completed >= 0),
                    completed_at INTEGER NOT NULL,
                    PRIMARY KEY (persona_id, challenge_id)
                );
                CREATE TABLE IF NOT EXISTS sbc_set_rewards (
                    persona_id INTEGER NOT NULL,
                    set_id INTEGER NOT NULL,
                    times_granted INTEGER NOT NULL DEFAULT 1,
                    granted_at INTEGER NOT NULL,
                    PRIMARY KEY (persona_id, set_id)
                );
                CREATE TABLE IF NOT EXISTS unopened_packs (
                    entitlement_id INTEGER PRIMARY KEY,
                    persona_id INTEGER NOT NULL,
                    pack_id INTEGER NOT NULL,
                    untradeable INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT '',
                    granted_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS unopened_packs_persona
                    ON unopened_packs(persona_id, entitlement_id);
                CREATE TABLE IF NOT EXISTS sbc_tags (
                    persona_id INTEGER NOT NULL,
                    set_id INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (persona_id, set_id)
                );
                -- Versioned, persona-scoped repair jobs. A claim prevents two
                -- concurrent requests from applying the same backfill, while
                -- the lease lets a later request recover from a killed worker.
                CREATE TABLE IF NOT EXISTS persona_maintenance (
                    persona_id INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running','complete')),
                    claim_token TEXT NOT NULL,
                    claimed_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    PRIMARY KEY (persona_id, operation)
                );
                -- The schema this database was last migrated to.
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );
                -- Monotonic id allocation. `value` is the last id handed out,
                -- so a deleted row can never give its id to the next one.
                CREATE TABLE IF NOT EXISTS counters (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    persona_id INTEGER NOT NULL,
                    trade_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    starting_bid INTEGER NOT NULL,
                    buy_now_price INTEGER NOT NULL,
                    current_bid INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    trade_state TEXT NOT NULL,
                    bid_state TEXT NOT NULL DEFAULT 'none',
                    coins_processed INTEGER NOT NULL DEFAULT 0,
                    watched INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL DEFAULT '{}',
                    bidder_persona INTEGER NOT NULL DEFAULT 0,
                    awarded_item_id INTEGER NOT NULL DEFAULT 0,
                    seller_name TEXT NOT NULL DEFAULT '',
                    seller_established INTEGER NOT NULL DEFAULT 0,
                    resource_id INTEGER NOT NULL DEFAULT 0,
                    search_type TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    rating INTEGER NOT NULL DEFAULT 0,
                    rare_flag INTEGER NOT NULL DEFAULT 0,
                    league_id INTEGER NOT NULL DEFAULT 0,
                    nation INTEGER NOT NULL DEFAULT 0,
                    team_id INTEGER NOT NULL DEFAULT 0,
                    position TEXT NOT NULL DEFAULT '',
                    play_style INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (persona_id, trade_id),
                    UNIQUE (persona_id, item_id)
                );
                CREATE INDEX IF NOT EXISTS trades_persona_state
                    ON trades(persona_id, trade_state, trade_id);
                CREATE TABLE IF NOT EXISTS auction_watches (
                    persona_id INTEGER NOT NULL,
                    trade_id INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (persona_id, trade_id)
                );
                -- Single-player tournament progress.
                --
                -- The client authors its own mode state and round-trips it as
                -- text: `tournamentData` is an opaque string it hands over and
                -- expects back. CardsDLL reads it through an accessor that
                -- takes its length and allocates
                -- `FutTournamentLoadDataserverCall::TempStorageBuffer`, so the
                -- content is never interpreted here and must not be.
                --
                -- `progressData` is stored although the load response does not
                -- echo it: the client sends it, and data the client gives us
                -- is part of the contract even when we cannot yet see what
                -- reads it back.
                CREATE TABLE IF NOT EXISTS tournaments (
                    persona_id INTEGER NOT NULL,
                    tournament_id INTEGER NOT NULL,
                    round INTEGER NOT NULL DEFAULT 0,
                    data_version INTEGER NOT NULL DEFAULT 0,
                    tournament_data TEXT NOT NULL DEFAULT '',
                    progress_data_version INTEGER NOT NULL DEFAULT 0,
                    progress_data TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (persona_id, tournament_id)
                );
                -- Single-player Seasons progress. Like tournaments, FIFA owns
                -- the opaque payload; this server only persists and echoes it.
                CREATE TABLE IF NOT EXISTS seasons (
                    persona_id INTEGER PRIMARY KEY,
                    season_id INTEGER NOT NULL,
                    division_id INTEGER NOT NULL,
                    round INTEGER NOT NULL DEFAULT 1,
                    data_version INTEGER NOT NULL DEFAULT 0,
                    user_data TEXT NOT NULL DEFAULT '',
                    progress_data_version INTEGER NOT NULL DEFAULT 0,
                    progress_data TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL
                );
                -- Per-mode Seasons state. ``division_id`` is FIFA's measured
                -- inverted wire value: 1 renders as Division 10 and 10 as
                -- Division 1. Canonical counters are never decoded from or
                -- overwritten by the opaque client-authored payload.
                CREATE TABLE IF NOT EXISTS season_progress (
                    persona_id INTEGER NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('OFFLINE','ONLINE')),
                    season_id INTEGER NOT NULL DEFAULT 1,
                    division_id INTEGER NOT NULL DEFAULT 1
                        CHECK(division_id BETWEEN 1 AND 10),
                    round INTEGER NOT NULL DEFAULT 1,
                    data_version INTEGER NOT NULL DEFAULT 0,
                    user_data TEXT NOT NULL DEFAULT '',
                    progress_data_version INTEGER NOT NULL DEFAULT 0,
                    progress_data TEXT NOT NULL DEFAULT '',
                    campaign INTEGER NOT NULL DEFAULT 1 CHECK(campaign >= 1),
                    played INTEGER NOT NULL DEFAULT 0
                        CHECK(played BETWEEN 0 AND 9),
                    won INTEGER NOT NULL DEFAULT 0 CHECK(won >= 0),
                    drawn INTEGER NOT NULL DEFAULT 0 CHECK(drawn >= 0),
                    lost INTEGER NOT NULL DEFAULT 0 CHECK(lost >= 0),
                    points INTEGER NOT NULL DEFAULT 0 CHECK(points >= 0),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','legacy')),
                    last_result TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (persona_id, mode)
                );
                -- One server-owned lifecycle per match. FIFA 17 sends
                -- matchReportId=0, so the client does not provide a usable
                -- idempotency key; POST /match is the authoritative boundary.
                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY,
                    persona_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    match_type TEXT NOT NULL DEFAULT '',
                    playlist TEXT NOT NULL DEFAULT 'unresolved',
                    squad_id INTEGER NOT NULL DEFAULT 1,
                    tournament_id INTEGER NOT NULL DEFAULT 0,
                    season_id INTEGER NOT NULL DEFAULT 0,
                    division_id INTEGER NOT NULL DEFAULT 0,
                    opening_payload TEXT NOT NULL DEFAULT '{}',
                    squad_snapshot TEXT NOT NULL DEFAULT '{}',
                    lineup_saved INTEGER NOT NULL DEFAULT 0,
                    report_payload TEXT NOT NULL DEFAULT '{}',
                    end_reason TEXT NOT NULL DEFAULT '',
                    match_coins INTEGER NOT NULL DEFAULT 0,
                    participation_award INTEGER NOT NULL DEFAULT 0,
                    tournament_outcome TEXT NOT NULL DEFAULT '',
                    tournament_round_before INTEGER NOT NULL DEFAULT 0,
                    tournament_round_after INTEGER NOT NULL DEFAULT 0,
                    season_mode TEXT NOT NULL DEFAULT '',
                    season_coins INTEGER NOT NULL DEFAULT 0,
                    season_end_result TEXT NOT NULL DEFAULT '',
                    season_division_before INTEGER NOT NULL DEFAULT 0,
                    season_division_after INTEGER NOT NULL DEFAULT 0,
                    season_campaign INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    settled_at INTEGER,
                    version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS matches_persona_history
                    ON matches(persona_id, created_at, status);
                CREATE UNIQUE INDEX IF NOT EXISTS matches_one_active_persona
                    ON matches(persona_id)
                    WHERE status IN ('created','playing');
                CREATE TABLE IF NOT EXISTS game_reports (
                    report_id INTEGER PRIMARY KEY,
                    match_id TEXT NOT NULL UNIQUE,
                    persona_id INTEGER NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    received_at INTEGER NOT NULL,
                    settled_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS game_reports_persona
                    ON game_reports(persona_id, received_at);
                """
            )
            self._migrate(connection)
            self._apply_schema_migrations(connection, from_version)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS trades_market_search"
                " ON trades(search_type,category,trade_state,expires_at)")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS trades_resource_search"
                " ON trades(resource_id,trade_state)")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS trades_global_id ON trades(trade_id)")

    def _migrate(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in
                   connection.execute("PRAGMA table_info(items)")}
        if "item_type" not in columns:
            connection.execute(
                "ALTER TABLE items ADD COLUMN item_type TEXT NOT NULL"
                " DEFAULT 'player'")
            for row in connection.execute(
                    "SELECT persona_id,item_id,payload FROM items").fetchall():
                try:
                    kind = json.loads(row["payload"]).get("itemType", "player")
                except (ValueError, TypeError):
                    kind = "player"
                connection.execute(
                    "UPDATE items SET item_type=? WHERE persona_id=? AND item_id=?",
                    (str(kind), row["persona_id"], row["item_id"]))
        connection.execute(
            "CREATE INDEX IF NOT EXISTS items_persona_type"
            " ON items(persona_id, item_type, pile, item_id)")
        market_columns = {row["name"] for row in
                          connection.execute("PRAGMA table_info(market_listings)")}
        if market_columns:
            for column, ddl in (
                    ("coins_processed",
                     "ALTER TABLE market_listings ADD COLUMN coins_processed"
                     " INTEGER NOT NULL DEFAULT 0"),
                    ("watched",
                     "ALTER TABLE market_listings ADD COLUMN watched"
                     " INTEGER NOT NULL DEFAULT 0"),
                    ("awarded_item_id",
                     "ALTER TABLE market_listings ADD COLUMN awarded_item_id"
                     " INTEGER NOT NULL DEFAULT 0")):
                if column not in market_columns:
                    connection.execute(ddl)

        wallet_columns = {row["name"] for row in
                          connection.execute("PRAGMA table_info(wallets)")}
        if wallet_columns and "high_water" not in wallet_columns:
            connection.execute(
                "ALTER TABLE wallets ADD COLUMN high_water INTEGER NOT NULL"
                " DEFAULT 0")
            connection.execute(
                "UPDATE wallets SET high_water = COALESCE(("
                " SELECT MAX(item_id) FROM items"
                " WHERE items.persona_id = wallets.persona_id), 0)")

        migrated_at = int(time.time())
        for row in connection.execute(
                "SELECT persona_id,credits,points FROM wallets").fetchall():
            persona_id = int(row["persona_id"])
            if connection.execute(
                    "SELECT 1 FROM wallet_transactions WHERE persona_id=?"
                    " LIMIT 1", (persona_id,)).fetchone() is not None:
                continue
            for currency, balance in (
                    ("COINS", int(row["credits"])),
                    ("POINTS", int(row["points"]))):
                connection.execute(
                    "INSERT OR IGNORE INTO wallet_transactions("
                    "transaction_id,persona_id,currency,requested_amount,amount,"
                    "balance_after,reason,related_type,related_id,idempotency_key,"
                    "metadata,created_at) VALUES(?,?,?,?,?,?,'opening_balance',"
                    "'wallet','',?,'{}',?)",
                    (f"migration:{persona_id}:{currency.lower()}", persona_id,
                     currency, balance, balance, balance,
                     "pre-ledger-opening-v1", migrated_at),
                )

        legacy_staff = ("manager", "headCoach", "gkCoach", "GKCoach",
                        "fitnessCoach", "physio")
        placeholders = ",".join("?" for _ in legacy_staff)
        stale = connection.execute(
            "SELECT persona_id,item_id,payload FROM items"
            " WHERE item_type IN (%s)" % placeholders, legacy_staff).fetchall()
        for row in stale:
            try:
                payload = json.loads(row["payload"])
            except (ValueError, TypeError):
                payload = {}
            if isinstance(payload, dict):
                payload["itemType"] = "staff"
            connection.execute(
                "UPDATE items SET item_type='staff', payload=?"
                " WHERE persona_id=? AND item_id=?",
                (json.dumps(payload, separators=(",", ":")),
                 row["persona_id"], row["item_id"]))

        squad_columns = {row["name"] for row in
                         connection.execute("PRAGMA table_info(squads)")}
        if squad_columns and "squad_id" not in squad_columns:
            connection.execute("ALTER TABLE squads RENAME TO squads_v1")
            connection.execute(
                "CREATE TABLE squads ("
                " persona_id INTEGER NOT NULL,"
                " squad_id INTEGER NOT NULL DEFAULT 1,"
                " name TEXT,"
                " payload TEXT NOT NULL,"
                " PRIMARY KEY (persona_id, squad_id))")
            connection.execute(
                "INSERT INTO squads(persona_id, squad_id, name, payload)"
                " SELECT persona_id, 1, NULL, payload FROM squads_v1")
            connection.execute("DROP TABLE squads_v1")
        elif squad_columns and "name" not in squad_columns:
            connection.execute("ALTER TABLE squads ADD COLUMN name TEXT")
        connection.execute(
            "INSERT OR IGNORE INTO squads(persona_id,squad_id,name,payload)"
            " SELECT persona_id,1,'Local XI','{}' FROM wallets")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS clientdata ("
            " persona_id INTEGER NOT NULL, name TEXT NOT NULL,"
            " payload TEXT NOT NULL, PRIMARY KEY (persona_id, name))")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS trades ("
            " persona_id INTEGER NOT NULL, trade_id INTEGER NOT NULL,"
            " item_id INTEGER NOT NULL, starting_bid INTEGER NOT NULL,"
            " buy_now_price INTEGER NOT NULL, current_bid INTEGER NOT NULL"
            " DEFAULT 0, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,"
            " trade_state TEXT NOT NULL, bid_state TEXT NOT NULL DEFAULT 'none',"
            " coins_processed INTEGER NOT NULL DEFAULT 0, watched INTEGER NOT NULL"
            " DEFAULT 0, payload TEXT NOT NULL DEFAULT '{}',"
            " bidder_persona INTEGER NOT NULL DEFAULT 0,"
            " awarded_item_id INTEGER NOT NULL DEFAULT 0,"
            " seller_name TEXT NOT NULL DEFAULT '',"
            " seller_established INTEGER NOT NULL DEFAULT 0,"
            " resource_id INTEGER NOT NULL DEFAULT 0,"
            " search_type TEXT NOT NULL DEFAULT '',"
            " category TEXT NOT NULL DEFAULT '',"
            " rating INTEGER NOT NULL DEFAULT 0,"
            " rare_flag INTEGER NOT NULL DEFAULT 0,"
            " league_id INTEGER NOT NULL DEFAULT 0,"
            " nation INTEGER NOT NULL DEFAULT 0,"
            " team_id INTEGER NOT NULL DEFAULT 0,"
            " position TEXT NOT NULL DEFAULT '',"
            " play_style INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY (persona_id, trade_id),"
            " UNIQUE (persona_id, item_id))")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS trades_persona_state"
            " ON trades(persona_id, trade_state, trade_id)")

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict:
        return json.loads(row["payload"])

    @staticmethod
    def _encode(item: dict) -> str:
        return json.dumps(item, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _wallet_document(row: sqlite3.Row) -> dict:
        document = dict(row)
        try:
            document["metadata"] = json.loads(document["metadata"] or "{}")
        except (TypeError, ValueError):
            document["metadata"] = {}
        return document

    def _apply_wallet_delta(
            self, connection: sqlite3.Connection, persona_id: int,
            currency: str, amount: int, reason: str, related_type: str,
            related_id: object, idempotency_key: str,
            metadata: dict | None = None, now: int | None = None) -> dict:
        persona_id = int(persona_id)
        currency = str(currency or "").upper()
        column = {"COINS": "credits", "POINTS": "points"}.get(currency)
        if column is None:
            raise ValueError(f"unsupported wallet currency: {currency}")
        requested = int(amount)
        reason = str(reason or "")
        related_type = str(related_type or "")
        related_id = str(related_id or "")
        idempotency_key = str(idempotency_key or "")
        if not reason or not idempotency_key:
            raise ValueError("wallet reason and idempotency key are required")
        encoded_metadata = json.dumps(
            metadata if isinstance(metadata, dict) else {},
            separators=(",", ":"), sort_keys=True, ensure_ascii=False)

        existing = connection.execute(
            "SELECT * FROM wallet_transactions WHERE persona_id=?"
            " AND currency=? AND idempotency_key=?",
            (persona_id, currency, idempotency_key),
        ).fetchone()
        if existing is not None:
            if (int(existing["requested_amount"]) != requested
                    or str(existing["reason"]) != reason
                    or str(existing["related_type"]) != related_type
                    or str(existing["related_id"]) != related_id
                    or str(existing["metadata"]) != encoded_metadata):
                raise ValueError("wallet idempotency key conflict")
            document = self._wallet_document(existing)
            document["duplicate"] = True
            return document

        wallet = connection.execute(
            f"SELECT {column} AS balance FROM wallets WHERE persona_id=?",
            (persona_id,),
        ).fetchone()
        if wallet is None:
            raise ValueError("wallet does not exist")
        before = int(wallet["balance"])
        if requested < 0 and before + requested < 0:
            raise ValueError("insufficient wallet funds")
        after = min(MAX_CREDITS, before + requested)
        actual = after - before
        created_at = int(time.time()) if now is None else int(now)
        transaction_id = secrets.token_hex(16)
        connection.execute(
            f"UPDATE wallets SET {column}=? WHERE persona_id=?",
            (after, persona_id),
        )
        connection.execute(
            "INSERT INTO wallet_transactions(transaction_id,persona_id,currency,"
            "requested_amount,amount,balance_after,reason,related_type,related_id,"
            "idempotency_key,metadata,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (transaction_id, persona_id, currency, requested, actual, after,
             reason, related_type, related_id, idempotency_key,
             encoded_metadata, created_at),
        )
        row = connection.execute(
            "SELECT * FROM wallet_transactions WHERE transaction_id=?",
            (transaction_id,),
        ).fetchone()
        document = self._wallet_document(row)
        document["duplicate"] = False
        return document

    def wallet_transactions(self, persona_id: int,
                            currency: str | None = None) -> list[dict]:
        sql = "SELECT * FROM wallet_transactions WHERE persona_id=?"
        params: list[object] = [int(persona_id)]
        if currency is not None:
            sql += " AND currency=?"
            params.append(str(currency).upper())
        sql += " ORDER BY rowid"
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._wallet_document(row) for row in rows]


    def claim_persona_maintenance(
            self, persona_id: int, operation: str, version: str,
            *, now: int | None = None, lease_seconds: int = 300
    ) -> str | None:
        persona_id = int(persona_id)
        operation = str(operation).strip()
        version = str(version).strip()
        if not operation or not version:
            raise ValueError("maintenance operation and version are required")
        claimed_at = int(time.time()) if now is None else int(now)
        lease_seconds = max(1, int(lease_seconds))
        token = secrets.token_hex(16)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version,status,claimed_at FROM persona_maintenance"
                " WHERE persona_id=? AND operation=?",
                (persona_id, operation),
            ).fetchone()
            if row is not None:
                same_version = str(row["version"]) == version
                if same_version and str(row["status"]) == "complete":
                    return None
                if (same_version and str(row["status"]) == "running" and
                        int(row["claimed_at"]) > claimed_at - lease_seconds):
                    return None
            connection.execute(
                "INSERT INTO persona_maintenance(persona_id,operation,version,"
                "status,claim_token,claimed_at,completed_at)"
                " VALUES(?,?,?,'running',?,?,NULL)"
                " ON CONFLICT(persona_id,operation) DO UPDATE SET"
                " version=excluded.version,status='running',"
                " claim_token=excluded.claim_token,"
                " claimed_at=excluded.claimed_at,completed_at=NULL",
                (persona_id, operation, version, token, claimed_at),
            )
        return token

    def complete_persona_maintenance(
            self, persona_id: int, operation: str, version: str,
            claim_token: str, *, now: int | None = None) -> bool:
        completed_at = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            changed = connection.execute(
                "UPDATE persona_maintenance SET status='complete',completed_at=?"
                " WHERE persona_id=? AND operation=? AND version=?"
                " AND status='running' AND claim_token=?",
                (completed_at, int(persona_id), str(operation), str(version),
                 str(claim_token)),
            )
        return changed.rowcount == 1

    def abandon_persona_maintenance(
            self, persona_id: int, operation: str, version: str,
            claim_token: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            changed = connection.execute(
                "DELETE FROM persona_maintenance WHERE persona_id=?"
                " AND operation=? AND version=? AND status='running'"
                " AND claim_token=?",
                (int(persona_id), str(operation), str(version),
                 str(claim_token)),
            )
        return changed.rowcount == 1

    def persona_maintenance(self, persona_id: int,
                            operation: str) -> dict | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM persona_maintenance"
                " WHERE persona_id=? AND operation=?",
                (int(persona_id), str(operation)),
            ).fetchone()
        return dict(row) if row is not None else None

    def repair_club_items(self, persona_id: int,
                          truth_by_resource: dict | None = None) -> int:
        persona_id = int(persona_id)
        if not truth_by_resource:
            return 0
        changed = 0
        with self._lock, closing(self._connect()) as connection, connection:
            for row in connection.execute(
                    "SELECT item_id,payload FROM items WHERE persona_id=?",
                    (persona_id,)).fetchall():
                try:
                    payload = json.loads(row["payload"])
                except (ValueError, TypeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                truth = truth_by_resource.get(
                    int(payload.get("resourceId", 0) or 0))
                if not truth:
                    continue
                dirty = False
                for key, want in truth.items():
                    if int(payload.get(key, -1) or 0) != int(want):
                        payload[key] = int(want)
                        dirty = True
                if not dirty:
                    continue
                connection.execute(
                    "UPDATE items SET payload=? WHERE persona_id=? AND item_id=?",
                    (self._encode(payload), persona_id, int(row["item_id"])))
                changed += 1
        return changed

    def reconcile_special_player_items(
            self, persona_id: int,
            truth_by_resource: dict[int, dict] | None = None) -> dict[str, int]:
        persona_id = int(persona_id)
        truth_by_resource = truth_by_resource or {}
        updated = 0
        removed: set[int] = set()
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT item_id,payload FROM items WHERE persona_id=?"
                " AND item_type='player'",
                (persona_id,),
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                    rare_flag = int(payload.get("rareflag", 0) or 0)
                    resource_id = int(payload.get("resourceId", 0) or 0)
                except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if rare_flag <= 1:
                    continue
                item_id = int(row["item_id"])
                truth = truth_by_resource.get(resource_id)
                if truth is None:
                    connection.execute(
                        "DELETE FROM trades WHERE persona_id=? AND item_id=?",
                        (persona_id, item_id),
                    )
                    connection.execute(
                        "DELETE FROM items WHERE persona_id=? AND item_id=?",
                        (persona_id, item_id),
                    )
                    removed.add(item_id)
                    continue
                changed = False
                for key, wanted in truth.items():
                    if payload.get(key) != wanted:
                        payload[key] = wanted
                        changed = True
                if not changed:
                    continue
                connection.execute(
                    "UPDATE items SET asset_id=?,payload=?"
                    " WHERE persona_id=? AND item_id=?",
                    (int(payload.get("assetId", 0) or 0), self._encode(payload),
                     persona_id, item_id),
                )
                updated += 1
            self._forget_items_in_squads(connection, persona_id, removed)
        return {"updated": updated, "removed": len(removed)}

    def club_essentials_present(self, persona_id: int) -> set[str]:
        persona_id = int(persona_id)
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT DISTINCT item_type FROM items"
                " WHERE persona_id=? AND pile IN ('club','squad')",
                (persona_id,),
            ).fetchall()
        return {str(row["item_type"]) for row in rows}

    def add_club_cards(self, persona_id: int, cards: list[dict]) -> list[int]:
        persona_id = int(persona_id)
        added: list[int] = []
        if not cards:
            return added
        now = int(time.time())
        with self._lock, closing(self._connect()) as connection, connection:
            for card in cards:
                item_id = self._next_item_id(connection, persona_id)
                item = dict(card)
                item["id"] = int(item_id)
                connection.execute(
                    "INSERT INTO items(persona_id,item_id,asset_id,pile,"
                    "payload,acquired_at,item_type)"
                    " VALUES(?,?,?,'club',?,?,?)",
                    (persona_id, int(item_id), int(item.get("assetId", 0) or 0),
                     self._encode(item), now,
                     str(item.get("itemType", "custom"))),
                )
                added.append(int(item_id))
        return added

    def ensure_persona(self, persona_id: int, seed_items: list[dict] = ()) -> None:
        persona_id = int(persona_id)
        now = int(time.time())
        with self._lock:
            if (persona_id in self._known_personas and
                    (not seed_items or persona_id in self._seeded_personas)):
                return
        with self._lock, closing(self._connect()) as connection, connection:
            created = connection.execute(
                "INSERT OR IGNORE INTO wallets(persona_id,credits,points) VALUES(?,?,?)",
                (persona_id, 0, 0),
            )
            if created.rowcount:
                self._apply_wallet_delta(
                    connection, persona_id, "COINS", fut_economy.STARTING_CREDITS,
                    "starting_grant", "persona", persona_id,
                    "starting-grant-v1", now=now)
                self._apply_wallet_delta(
                    connection, persona_id, "POINTS", fut_economy.STARTING_POINTS,
                    "starting_grant", "persona", persona_id,
                    "starting-grant-v1", now=now)
            connection.execute(
                "INSERT OR IGNORE INTO squads(persona_id,squad_id,name,payload)"
                " VALUES(?,1,'Local XI','{}')", (persona_id,))
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM items WHERE persona_id=?", (persona_id,)
            ).fetchone()["n"]
            if count:
                self._known_personas.add(persona_id)
                self._seeded_personas.add(persona_id)
                return
            for item in seed_items:
                connection.execute(
                    "INSERT OR IGNORE INTO items"
                    "(persona_id,item_id,asset_id,pile,payload,acquired_at,item_type)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (persona_id, int(item["id"]), int(item["assetId"]), "club",
                     self._encode(item), now,
                     str(item.get("itemType", "player"))),
                )
            self._known_personas.add(persona_id)
            if seed_items:
                self._seeded_personas.add(persona_id)

    def has_persona(self, persona_id: int) -> bool:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM wallets WHERE persona_id=?", (int(persona_id),)
            ).fetchone()
        return row is not None

    def award_credits(self, persona_id: int, coins: int,
                      reason: str = "operator_award",
                      related_type: str = "operator",
                      related_id: object = "",
                      idempotency_key: str | None = None) -> int:
        persona_id, coins = int(persona_id), max(0, int(coins))
        self.ensure_persona(persona_id)
        key = (str(idempotency_key) if idempotency_key is not None
               else f"operator:{secrets.token_hex(16)}")
        with self._lock, closing(self._connect()) as connection, connection:
            transaction = self._apply_wallet_delta(
                connection, persona_id, "COINS", coins, reason,
                related_type, related_id, key)
        return int(transaction["balance_after"])

    def charge_credits(self, persona_id: int, coins: int, reason: str,
                       related_type: str = "", related_id: object = "",
                       idempotency_key: str | None = None) -> int:
        persona_id, cost = int(persona_id), max(0, int(coins))
        self.ensure_persona(persona_id)
        key = (str(idempotency_key) if idempotency_key is not None
               else f"charge:{secrets.token_hex(16)}")
        with self._lock, closing(self._connect()) as connection, connection:
            wallet = connection.execute(
                "SELECT credits FROM wallets WHERE persona_id=?", (persona_id,)
            ).fetchone()
            if int(wallet["credits"]) < cost:
                raise ValueError("insufficient coins")
            transaction = self._apply_wallet_delta(
                connection, persona_id, "COINS", -cost, reason,
                related_type, related_id, key)
        return int(transaction["balance_after"])


    @staticmethod
    def _match_document(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        document = dict(row)
        for name in ("opening_payload", "squad_snapshot", "report_payload"):
            try:
                document[name] = json.loads(document[name] or "{}")
            except (ValueError, TypeError):
                document[name] = {}
        snapshot = document["squad_snapshot"]
        if isinstance(snapshot, dict) and isinstance(snapshot.get("slots"), dict):
            try:
                snapshot["slots"] = {
                    int(index): int(item_id)
                    for index, item_id in snapshot["slots"].items()
                }
            except (TypeError, ValueError):
                snapshot["slots"] = {}
        return document

    def _expire_stale_matches(self, connection, now: int) -> int:
        if self.match_expiry_seconds <= 0:
            return 0
        return connection.execute(
            "UPDATE matches SET status='abandoned',end_reason='EXPIRED',"
            " updated_at=?,version=version+1"
            " WHERE status IN ('created','playing') AND updated_at<=?",
            (int(now), int(now) - self.match_expiry_seconds),
        ).rowcount

    def allocate_game_report_id(self) -> int:
        with self._lock, closing(self._connect()) as connection, connection:
            return self._allocate_ids(connection, GAME_REPORT_ID_COUNTER, 1)

    def accept_game_report(self, persona_id: int, report: dict,
                           now: int | None = None) -> dict | None:
        persona_id = int(persona_id)
        current = int(time.time()) if now is None else int(now)
        encoded = json.dumps(
            report if isinstance(report, dict) else {}, separators=(",", ":"),
            sort_keys=True, ensure_ascii=False, default=str)
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, current)
            match = connection.execute(
                "SELECT match_id FROM matches WHERE persona_id=?"
                " AND status IN ('created','playing')"
                " ORDER BY rowid DESC LIMIT 1", (persona_id,)).fetchone()
            if match is None:
                return None
            existing = connection.execute(
                "SELECT report_id,match_id,received_at FROM game_reports"
                " WHERE match_id=?", (match["match_id"],)).fetchone()
            if existing is not None:
                return {**dict(existing), "duplicate": True}
            report_id = self._allocate_ids(
                connection, GAME_REPORT_ID_COUNTER, 1)
            connection.execute(
                "INSERT INTO game_reports(report_id,match_id,persona_id,payload,"
                "received_at) VALUES(?,?,?,?,?)",
                (report_id, match["match_id"], persona_id, encoded, current))
            return {"report_id": report_id, "match_id": match["match_id"],
                    "received_at": current, "duplicate": False}

    def expire_stale_matches(self, now: int | None = None) -> int:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            return self._expire_stale_matches(connection, current)

    def match_counts(self) -> dict[str, int]:
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, int(time.time()))
            rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM matches GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    def auction_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._lock, closing(self._connect()) as connection:
            for row in connection.execute(
                    "SELECT trade_state, COUNT(*) AS n FROM trades"
                    " GROUP BY trade_state").fetchall():
                counts["market.%s" % row["trade_state"]] = int(row["n"])
        return counts

    def personas_in_match(self) -> set[int]:
        current = int(time.time())
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, current)
            rows = connection.execute(
                "SELECT DISTINCT persona_id FROM matches"
                " WHERE status IN ('created','playing')",
            ).fetchall()
        return {int(row["persona_id"]) for row in rows}

    def unfinished_matches(self, now: int | None = None) -> list[dict]:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, current)
            rows = connection.execute(
                "SELECT persona_id,match_id,match_type,tournament_id,"
                "created_at,updated_at FROM matches"
                " WHERE status IN ('created','playing')"
                " ORDER BY updated_at DESC",
            ).fetchall()
        return [{"persona_id": int(row["persona_id"]),
                 "match_id": str(row["match_id"]),
                 "match_type": str(row["match_type"]),
                 "tournament_id": int(row["tournament_id"]),
                 "created_at": int(row["created_at"]),
                 "idle_seconds": max(0, current - int(row["updated_at"]))}
                for row in rows]

    def active_match(self, persona_id: int,
                     now: int | None = None) -> dict | None:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, current)
            row = connection.execute(
                "SELECT * FROM matches WHERE persona_id=?"
                " AND status IN ('created','playing')"
                " ORDER BY rowid DESC LIMIT 1",
                (int(persona_id),),
            ).fetchone()
        return self._match_document(row)

    def start_match(self, persona_id: int, opening: dict,
                    squad_snapshot: dict | None = None,
                    now: int | None = None) -> dict:
        persona_id = int(persona_id)
        self.ensure_persona(persona_id)
        current = int(time.time()) if now is None else int(now)
        opening = dict(opening) if isinstance(opening, dict) else {}
        encoded_opening = json.dumps(
            opening, separators=(",", ":"), sort_keys=True,
            ensure_ascii=False)
        encoded_snapshot = json.dumps(
            squad_snapshot if isinstance(squad_snapshot, dict) else {},
            separators=(",", ":"), sort_keys=True, ensure_ascii=False)

        def number(name: str, fallback: int = 0) -> int:
            try:
                return int(opening.get(name, fallback) or fallback)
            except (TypeError, ValueError):
                return int(fallback)

        def playlist(connection) -> str:
            match_type = str(opening.get("type", "") or "").upper()
            if match_type != "ONLINE":
                return MATCH_PLAYLIST_OFFLINE
            if number("squadId", 1) == 900_001:
                row = connection.execute(
                    "SELECT payload FROM clientdata WHERE persona_id=?"
                    " AND name='draftRun:selectedMode'", (persona_id,)
                ).fetchone()
                try:
                    selected = {int(entry.get("key", -1)):
                                int(entry.get("value", 0))
                                for entry in json.loads(row["payload"] or "[]")}
                except (KeyError, TypeError, ValueError,
                        json.JSONDecodeError):
                    selected = {}
                return (MATCH_PLAYLIST_ONLINE_DRAFT if selected.get(0) == 1
                        else MATCH_PLAYLIST_UNRESOLVED)
            if number("seasonId") > 0 or number("divisionId") > 0:
                return MATCH_PLAYLIST_ONLINE_SEASONS
            return MATCH_PLAYLIST_ONLINE_SINGLE

        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, current)
            existing = connection.execute(
                "SELECT * FROM matches WHERE persona_id=?"
                " AND status IN ('created','playing')"
                " ORDER BY rowid DESC LIMIT 1",
                (persona_id,),
            ).fetchone()
            if (existing is not None
                    and str(existing["opening_payload"]) == encoded_opening):
                connection.execute(
                    "UPDATE matches SET updated_at=?,version=version+1"
                    " WHERE match_id=?", (current, existing["match_id"]))
                row = connection.execute(
                    "SELECT * FROM matches WHERE match_id=?",
                    (existing["match_id"],),
                ).fetchone()
                return self._match_document(row)
            if existing is not None:
                connection.execute(
                    "UPDATE matches SET status='abandoned',updated_at=?,"
                    " version=version+1 WHERE match_id=?",
                    (current, existing["match_id"]),
                )

            match_id = secrets.token_hex(16)
            match_playlist = playlist(connection)
            connection.execute(
                "INSERT INTO matches(match_id,persona_id,status,match_type,playlist,"
                "squad_id,tournament_id,season_id,division_id,opening_payload,"
                "squad_snapshot,created_at,updated_at)"
                " VALUES(?,?,'created',?,?,?,?,?,?,?,?,?,?)",
                (match_id, persona_id, str(opening.get("type", "") or ""),
                 match_playlist, max(1, number("squadId", 1)),
                 number("tournamentId"),
                 number("seasonId"), number("divisionId"), encoded_opening,
                 encoded_snapshot, current, current),
            )
            row = connection.execute(
                "SELECT * FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()
        return self._match_document(row)

    def reset_active_match(self, persona_id: int,
                           now: int | None = None) -> int:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            return connection.execute(
                "UPDATE matches SET status='abandoned',updated_at=?,"
                " version=version+1 WHERE persona_id=?"
                " AND status IN ('created','playing')",
                (current, int(persona_id)),
            ).rowcount

    def touch_active_match(self, persona_id: int,
                           now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            return connection.execute(
                "UPDATE matches SET status='playing',updated_at=?,"
                " version=version+1 WHERE persona_id=?"
                " AND status IN ('created','playing')",
                (current, int(persona_id)),
            ).rowcount > 0

    def save_match_lineup(self, persona_id: int,
                          wanted: list[int], now: int | None = None) -> dict | None:
        persona_id = int(persona_id)
        current = int(time.time()) if now is None else int(now)
        wanted = [int(item_id) for item_id in wanted]
        if len(wanted) != 11 or len(set(wanted)) != 11:
            return None
        with self._lock, closing(self._connect()) as connection, connection:
            match = connection.execute(
                "SELECT * FROM matches WHERE persona_id=?"
                " AND status IN ('created','playing')"
                " ORDER BY rowid DESC LIMIT 1",
                (persona_id,),
            ).fetchone()
            if match is None or int(match["lineup_saved"]):
                return None
            squad_id = int(match["squad_id"])
            row = connection.execute(
                "SELECT payload FROM squads WHERE persona_id=? AND squad_id=?",
                (persona_id, squad_id),
            ).fetchone()
            if row is None:
                return None
            try:
                squad = json.loads(row["payload"] or "{}")
                slots = squad.get("slots")
            except (ValueError, TypeError, AttributeError):
                return None
            if not isinstance(slots, dict):
                return None
            existing = [
                int(item_id) for index, item_id in
                sorted(((int(index), value) for index, value in slots.items()))
                if int(item_id) > 0
            ]
            wanted_set = set(wanted)
            if not wanted_set.issubset(existing):
                return None
            remaining = [item_id for item_id in existing
                         if item_id not in wanted_set]
            reordered = wanted + remaining
            squad["slots"] = {index: item_id for index, item_id
                              in enumerate(reordered[:23])}
            encoded = json.dumps(
                squad, separators=(",", ":"), sort_keys=True,
                ensure_ascii=False)
            connection.execute(
                "UPDATE squads SET payload=? WHERE persona_id=? AND squad_id=?",
                (encoded, persona_id, squad_id),
            )
            connection.execute(
                "UPDATE matches SET status='playing',lineup_saved=1,"
                " squad_snapshot=?,updated_at=?,version=version+1"
                " WHERE match_id=?",
                (encoded, current, match["match_id"]),
            )
            saved = connection.execute(
                "SELECT * FROM matches WHERE match_id=?", (match["match_id"],)
            ).fetchone()
        return self._match_document(saved)

    def _advance_season_in_transaction(
            self, connection: sqlite3.Connection, match: sqlite3.Row,
            result: str, now: int) -> dict | None:
        import fut_seasons

        canonical = fut_seasons.canonical_match_result(result)
        if canonical is None or not int(match["season_id"]):
            return None
        if str(match["playlist"]) == MATCH_PLAYLIST_ONLINE_SEASONS:
            mode = SEASON_MODE_ONLINE
        elif str(match["match_type"]).upper() == "OFFLINE":
            mode = SEASON_MODE_OFFLINE
        else:
            return None

        persona_id = int(match["persona_id"])
        progress = connection.execute(
            "SELECT * FROM season_progress WHERE persona_id=? AND mode=?",
            (persona_id, mode)).fetchone()
        if progress is None:
            division_id = int(match["division_id"] or 1)
            if not 1 <= division_id <= 10:
                division_id = 1
            connection.execute(
                "INSERT INTO season_progress("
                "persona_id,mode,season_id,division_id,round,data_version,"
                "user_data,progress_data_version,progress_data,campaign,played,"
                "won,drawn,lost,points,status,last_result,updated_at,version)"
                " VALUES(?,?,?, ?,1,0,'',0,'',1,0,0,0,0,0,'active','',?,1)",
                (persona_id, mode, int(match["season_id"]), division_id, now))
            progress = connection.execute(
                "SELECT * FROM season_progress WHERE persona_id=? AND mode=?",
                (persona_id, mode)).fetchone()
        if str(progress["status"]) != "active":
            return {"mode": mode, "advanced": False, "legacy": True,
                    "season_coins": 0, "season_end_result": "",
                    "division_before": int(progress["division_id"]),
                    "division_after": int(progress["division_id"]),
                    "campaign": int(progress["campaign"])}

        transition = fut_seasons.advance_campaign(
            int(progress["division_id"]), int(progress["campaign"]),
            int(progress["played"]), int(progress["won"]),
            int(progress["drawn"]), int(progress["lost"]),
            int(progress["points"]), canonical, mode)
        complete = bool(transition["campaign_complete"])
        opaque_reset = (
            "round=1,data_version=0,user_data='',progress_data_version=0,"
            "progress_data='',season_id=?," if complete else "")
        parameters = []
        sql = "UPDATE season_progress SET division_id=?,campaign=?,played=?,"
        sql += "won=?,drawn=?,lost=?,points=?,last_result=?,"
        if complete:
            sql += opaque_reset
        sql += "updated_at=?,version=version+1 WHERE persona_id=? AND mode=?"
        parameters.extend([
            int(transition["division_id"]), int(transition["campaign"]),
            int(transition["played"]), int(transition["won"]),
            int(transition["drawn"]), int(transition["lost"]),
            int(transition["points"]), str(transition["last_result"]),
        ])
        if complete:
            parameters.append(int(transition["division_id"]))
        parameters.extend([int(now), persona_id, mode])
        connection.execute(sql, parameters)
        transition.update({
            "mode": mode,
            "advanced": True,
            "legacy": False,
            "division_before": int(progress["division_id"]),
            "division_after": int(transition["division_id"]),
            "campaign": int(progress["campaign"]),
        })
        return transition

    def _spend_loan_games(self, connection, persona_id: int,
                          match: sqlite3.Row) -> None:
        try:
            snapshot = json.loads(match["squad_snapshot"] or "{}")
        except (ValueError, TypeError):
            snapshot = {}
        slots = snapshot.get("slots") if isinstance(snapshot, dict) else None
        if not slots:
            row = connection.execute(
                "SELECT payload FROM squads WHERE persona_id=? AND squad_id=?",
                (persona_id, int(match["squad_id"]))).fetchone()
            try:
                squad = json.loads(row["payload"] or "{}") if row else {}
            except (ValueError, TypeError):
                squad = {}
            slots = squad.get("slots") if isinstance(squad, dict) else None
        if not isinstance(slots, dict):
            return
        starters = []
        for index, item_id in slots.items():
            try:
                if 0 <= int(index) < 11 and int(item_id) > 0:
                    starters.append(int(item_id))
            except (TypeError, ValueError):
                continue
        if not starters:
            return
        marks = ",".join("?" for _ in starters)
        for row in connection.execute(
                f"SELECT item_id,payload FROM items WHERE persona_id=?"
                f" AND item_id IN ({marks})",
                [persona_id, *starters]).fetchall():
            item = self._decode(row)
            try:
                left = int(item.get("loans", 0) or 0)
            except (TypeError, ValueError):
                continue
            if left <= 0:
                continue
            item["loans"] = left - 1
            item["contract"] = left - 1
            connection.execute(
                "UPDATE items SET payload=? WHERE persona_id=? AND item_id=?",
                (self._encode(item), persona_id, int(row["item_id"])))

    def settle_active_match(
            self, persona_id: int, end_reason: str, report: dict,
            tournament_round_rewards: list[int] | None = None,
            participation_award: int = 100,
            now: int | None = None) -> dict | None:
        persona_id = int(persona_id)
        self.ensure_persona(persona_id)
        current = int(time.time()) if now is None else int(now)
        result = str(end_reason or "NO_CONTEST").upper()
        encoded_report = json.dumps(
            report if isinstance(report, dict) else {},
            separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        rewards = [max(0, int(value))
                   for value in (tournament_round_rewards or [])]

        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_stale_matches(connection, current)
            match = connection.execute(
                "SELECT * FROM matches WHERE persona_id=?"
                " AND status IN ('created','playing')"
                " ORDER BY rowid DESC LIMIT 1",
                (persona_id,),
            ).fetchone()
            if match is None:
                latest = connection.execute(
                    "SELECT * FROM matches WHERE persona_id=?"
                    " ORDER BY rowid DESC LIMIT 1", (persona_id,)
                ).fetchone()
                if latest is None or latest["status"] != "settled":
                    return None
                document = self._match_document(latest)
                document["duplicate"] = True
                wallet = connection.execute(
                    "SELECT credits FROM wallets WHERE persona_id=?",
                    (persona_id,),
                ).fetchone()
                document["balance"] = int(wallet["credits"])
                return document

            match_coins = 0
            participation = (max(0, int(participation_award))
                             if result in PARTICIPATION_RESULTS else 0)
            tournament_id = int(match["tournament_id"])
            round_before = 0
            round_after = 0
            tournament_outcome = ""
            season = self._advance_season_in_transaction(
                connection, match, result, current)
            season_coins = int((season or {}).get("season_coins", 0))
            season_end_result = str(
                (season or {}).get("season_end_result", "") or "")
            season_mode = str((season or {}).get("mode", "") or "")
            season_division_before = int(
                (season or {}).get("division_before", 0))
            season_division_after = int(
                (season or {}).get("division_after", 0))
            season_campaign = int((season or {}).get("campaign", 0))
            progress = None
            if tournament_id:
                progress = connection.execute(
                    "SELECT * FROM tournaments WHERE persona_id=?"
                    " AND tournament_id=?",
                    (persona_id, tournament_id),
                ).fetchone()
                if progress is None:
                    progress = connection.execute(
                        "SELECT * FROM tournaments WHERE persona_id=?"
                        " AND tournament_id=?",
                        (persona_id, self.CURRENT_TOURNAMENT),
                    ).fetchone()
                round_before = max(
                    1, int(progress["round"] if progress is not None else 0))
                if rewards and result in ("WIN", "DRAW", "LOSS"):
                    match_coins = rewards[min(round_before, len(rewards)) - 1]
                    if result != "WIN":
                        match_coins //= 2

                if result == "WIN":
                    tournament_outcome = (
                        "won" if round_before >= max(1, len(rewards))
                        else "advanced")
                    round_after = (1 if tournament_outcome == "won"
                                   else round_before + 1)
                elif result in self.TOURNAMENT_ELIMINATING:
                    tournament_outcome, round_after = "eliminated", 1
                elif result == "DRAW":
                    tournament_outcome, round_after = "replay", round_before

                if tournament_outcome and tournament_outcome != "replay":
                    connection.execute(
                        "INSERT INTO tournaments(persona_id,tournament_id,round,"
                        "data_version,tournament_data,progress_data_version,"
                        "progress_data,updated_at) VALUES(?,?,?,0,'',0,'',?)"
                        " ON CONFLICT(persona_id,tournament_id) DO UPDATE SET"
                        " round=excluded.round,data_version=0,tournament_data='',"
                        " progress_data_version=0,progress_data='',"
                        " updated_at=excluded.updated_at",
                        (persona_id, tournament_id, round_after, current),
                    )

            if result in PARTICIPATION_RESULTS:
                self._spend_loan_games(connection, persona_id, match)

            total = int(match_coins) + int(participation) + int(season_coins)
            wallet_transaction = self._apply_wallet_delta(
                connection, persona_id, "COINS", total, "match_reward",
                "match", match["match_id"],
                f"match:{match['match_id']}:settlement",
                metadata={"end_reason": result,
                          "match_coins": int(match_coins),
                          "participation_award": int(participation),
                          "season_coins": int(season_coins),
                          "season_end_result": season_end_result},
                now=current)
            connection.execute(
                "UPDATE matches SET status='settled',report_payload=?,"
                " end_reason=?,match_coins=?,participation_award=?,"
                " tournament_outcome=?,tournament_round_before=?,"
                " tournament_round_after=?,season_mode=?,season_coins=?,"
                " season_end_result=?,season_division_before=?,"
                " season_division_after=?,season_campaign=?,"
                " updated_at=?,settled_at=?,"
                " version=version+1 WHERE match_id=?",
                (encoded_report, result, int(match_coins), int(participation),
                 tournament_outcome, round_before, round_after, season_mode,
                 season_coins, season_end_result, season_division_before,
                 season_division_after, season_campaign, current, current,
                 match["match_id"]),
            )
            connection.execute(
                "UPDATE game_reports SET settled_at=? WHERE match_id=?",
                (current, match["match_id"]),
            )
            settled = connection.execute(
                "SELECT * FROM matches WHERE match_id=?", (match["match_id"],)
            ).fetchone()
            linked_report = connection.execute(
                "SELECT report_id FROM game_reports WHERE match_id=?",
                (match["match_id"],),
            ).fetchone()
        document = self._match_document(settled)
        document["duplicate"] = False
        document["balance"] = int(wallet_transaction["balance_after"])
        document["gameReportId"] = (
            int(linked_report["report_id"]) if linked_report is not None else 0)
        return document

    ACTIVE_SQUAD_KEY = "activeSquadId"

    TRANSIENT_SQUAD_IDS = frozenset({900_001})

    def set_active_squad(self, persona_id: int, squad_id: int) -> None:
        if int(squad_id) in self.TRANSIENT_SQUAD_IDS:
            return
        self.save_clientdata(int(persona_id), self.ACTIVE_SQUAD_KEY,
                             [{"key": 0, "value": int(squad_id)}])

    def active_squad_id(self, persona_id: int, fallback: int = 1) -> int:
        entries = self.load_clientdata(int(persona_id), self.ACTIVE_SQUAD_KEY)
        for entry in entries or []:
            try:
                value = int(entry.get("value", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            if value > 0 and value not in self.TRANSIENT_SQUAD_IDS:
                return value
        return int(fallback)

    def item_high_water(self, persona_id: int) -> int:
        self.ensure_persona(persona_id)
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT high_water FROM wallets WHERE persona_id=?",
                (int(persona_id),),
            ).fetchone()
        return int(row["high_water"]) if row is not None else 0

    def balances(self, persona_id: int) -> tuple[int, int]:
        self.ensure_persona(persona_id)
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT credits,points FROM wallets WHERE persona_id=?",
                (int(persona_id),),
            ).fetchone()
        return int(row["credits"]), int(row["points"])

    def list_items(self, persona_id: int, pile: str | None = None,
                   offset: int = 0, count: int | None = None,
                   item_type: str | None = None) -> list[dict]:
        sql = "SELECT payload FROM items WHERE persona_id=?"
        params: list[object] = [int(persona_id)]
        if pile is not None:
            sql += " AND pile=?"
            params.append(str(pile))
        if item_type is not None:
            sql += " AND item_type=?"
            params.append(str(item_type))
        sql += " ORDER BY item_id"
        if count is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend((max(0, int(count)), max(0, int(offset))))
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._decode(row) for row in rows]

    def items_by_ids(self, persona_id: int, item_ids: list[int]) -> list[dict]:
        wanted = []
        for value in item_ids:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id not in wanted:
                wanted.append(item_id)
        if not wanted:
            return []
        marks = ",".join("?" for _ in wanted)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT item_id,payload FROM items WHERE persona_id=? AND item_id IN ({marks})",
                [int(persona_id), *wanted],
            ).fetchall()
        by_id = {int(row["item_id"]): self._decode(row) for row in rows}
        return [by_id[item_id] for item_id in wanted if item_id in by_id]

    def owned_by_resource(self, persona_id: int) -> dict[int, int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT asset_id,item_id,payload FROM items WHERE persona_id=?"
                " AND pile IN ('club','squad') ORDER BY item_id",
                (int(persona_id),),
            ).fetchall()
        owned: dict[int, int] = {}
        for row in rows:
            try:
                payload = self._decode(row)
                resource_id = int(payload.get("resourceId", row["asset_id"]))
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                resource_id = int(row["asset_id"])
            owned.setdefault(resource_id, int(row["item_id"]))
        return owned

    def purchase_pack(self, persona_id: int, price: int, items: list[dict],
                      currency: str = "COINS",
                      pack_id: object = "") -> tuple[list[dict], int, int]:
        persona_id = int(persona_id)
        self.ensure_persona(persona_id)
        now = int(time.time())
        currency = str(currency).upper()
        with self._lock, closing(self._connect()) as connection, connection:
            wallet = connection.execute(
                "SELECT credits,points FROM wallets WHERE persona_id=?", (persona_id,)
            ).fetchone()
            credits, points = int(wallet["credits"]), int(wallet["points"])
            cost = max(0, int(price))
            if currency == "POINTS":
                if points < cost:
                    raise ValueError("insufficient FIFA Points")
            else:
                if credits < cost:
                    raise ValueError("insufficient coins")
            top = connection.execute(
                "SELECT MAX(m) AS top FROM ("
                " SELECT MAX(item_id) AS m FROM items WHERE persona_id=?"
                " UNION ALL"
                " SELECT high_water AS m FROM wallets WHERE persona_id=?)",
                (persona_id, persona_id)
            ).fetchone()["top"]
            next_id = max(FIRST_PACK_ITEM_ID, int(top or 0) + 1)
            item_ids = list(range(next_id, next_id + len(items)))
            purchase_key = f"pack:{next_id}:purchase"
            self._apply_wallet_delta(
                connection, persona_id, currency, -cost, "pack_purchase",
                "pack", pack_id, purchase_key,
                metadata={"item_ids": item_ids, "pack_id": str(pack_id or "")},
                now=now)
            stored = []
            for source in items:
                item = dict(source)
                item["id"] = next_id
                next_id += 1
                connection.execute(
                    "INSERT INTO items(persona_id,item_id,asset_id,pile,payload,"
                    "acquired_at,item_type) VALUES(?,?,?,?,?,?,?)",
                    (persona_id, int(item["id"]), int(item["assetId"]),
                     "unassigned", self._encode(item), now,
                     str(item.get("itemType", "player"))),
                )
                stored.append(item)
            connection.execute(
                "UPDATE wallets SET high_water=MAX(high_water,?) WHERE persona_id=?",
                (next_id - 1, persona_id),
            )
            wallet = connection.execute(
                "SELECT credits,points FROM wallets WHERE persona_id=?",
                (persona_id,),
            ).fetchone()
            credits, points = int(wallet["credits"]), int(wallet["points"])
        return stored, credits, points

    ACTIVE_SLOT_STATES = {100: "activeBadge", 101: "activeHomeKit",
                          102: "activeAwayKit", 103: "activeBall",
                          104: "activeStadium"}

    def activate_item(self, persona_id: int, item_id: int,
                      slot: int) -> tuple[bool, str]:
        persona_id, item_id, slot = int(persona_id), int(item_id), int(slot)
        state_name = self.ACTIVE_SLOT_STATES.get(slot)
        if state_name is None:
            return False, "Invalid Slot"
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT payload FROM items WHERE persona_id=? AND item_id=?",
                (persona_id, item_id),
            ).fetchone()
            if row is None:
                return False, "Item Not Found"
            for other in connection.execute(
                    "SELECT item_id,payload FROM items WHERE persona_id=?",
                    (persona_id,)).fetchall():
                try:
                    payload = json.loads(other["payload"])
                except (ValueError, TypeError):
                    continue
                if str(payload.get("itemState", "")) != state_name:
                    continue
                payload["itemState"] = "free"
                connection.execute(
                    "UPDATE items SET payload=? WHERE persona_id=? AND item_id=?",
                    (self._encode(payload), persona_id, int(other["item_id"])))
            try:
                payload = json.loads(row["payload"])
            except (ValueError, TypeError):
                payload = {}
            payload["itemState"] = state_name
            connection.execute(
                "UPDATE items SET payload=? WHERE persona_id=? AND item_id=?",
                (self._encode(payload), persona_id, item_id))
        return True, ""

    def active_slot_items(self, persona_id: int) -> dict:
        persona_id = int(persona_id)
        names = set(self.ACTIVE_SLOT_STATES.values())
        out = {}
        with self._lock, closing(self._connect()) as connection, connection:
            for row in connection.execute(
                    "SELECT item_id,payload FROM items WHERE persona_id=?",
                    (persona_id,)).fetchall():
                try:
                    payload = json.loads(row["payload"])
                except (ValueError, TypeError):
                    continue
                name = str(payload.get("itemState", ""))
                if name in names:
                    out[name] = int(row["item_id"])
        return out

    def move_items(self, persona_id: int, requests: list[dict]) -> list[dict]:
        persona_id = int(persona_id)
        results = []
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_trades(connection, persona_id, int(time.time()))
            for request in requests:
                try:
                    item_id = int(request["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                pile = str(request.get("pile", "club"))
                if pile == "purchased":
                    pile = "unassigned"
                row = connection.execute(
                    "SELECT asset_id,item_type,pile,payload FROM items"
                    " WHERE persona_id=? AND item_id=?",
                    (persona_id, item_id),
                ).fetchone()
                success, reason = row is not None, ""
                trade = None
                if success:
                    trade = connection.execute(
                        "SELECT trade_id,trade_state FROM trades"
                        " WHERE persona_id=? AND item_id=? LIMIT 1",
                        (persona_id, item_id),
                    ).fetchone()
                active = (trade if trade is not None and
                          str(trade["trade_state"]) == "active" else None)
                if success and active is not None and pile != "trade":
                    success, reason = False, "Item Listed"
                item_type = str(row["item_type"]) if row is not None else ""
                duplicate = None
                if success and pile in ("club", "squad"):
                    if item_type == "player" or item_type in UNIQUE_ITEM_TYPES:
                        try:
                            incoming = self._decode(row)
                            resource_id = int(incoming.get(
                                "resourceId", row["asset_id"]))
                        except (AttributeError, TypeError, ValueError,
                                json.JSONDecodeError):
                            resource_id = int(row["asset_id"])
                        candidates = connection.execute(
                            "SELECT item_id,asset_id,payload FROM items"
                            " WHERE persona_id=? AND item_type=?"
                            " AND pile IN ('club','squad') AND item_id<>?"
                            " ORDER BY item_id",
                            (persona_id, item_type, item_id),
                        ).fetchall()
                        for candidate in candidates:
                            try:
                                held = self._decode(candidate)
                                held_resource = int(held.get(
                                    "resourceId", candidate["asset_id"]))
                            except (AttributeError, TypeError, ValueError,
                                    json.JSONDecodeError):
                                held_resource = int(candidate["asset_id"])
                            if held_resource == resource_id:
                                duplicate = candidate
                                break
                    if duplicate is not None:
                        success, reason = False, "Duplicate Item Type"
                if success and pile == "trade" and str(row["pile"]) != "trade":
                    transfer_count = connection.execute(
                        "SELECT COUNT(*) AS n FROM items"
                        " WHERE persona_id=? AND pile='trade'",
                        (persona_id,),
                    ).fetchone()["n"]
                    if int(transfer_count) >= TRANSFER_PILE_LIMIT:
                        success, reason = False, "Trade Pile Full"
                if success:
                    try:
                        payload = self._decode(row)
                    except (ValueError, TypeError):
                        payload = {}
                    if isinstance(payload, dict):
                        held = str(payload.get("itemState", ""))
                        if held not in self.ACTIVE_SLOT_STATES.values():
                            payload["itemState"] = (
                                "forSale" if active is not None else "free")
                    connection.execute(
                        "UPDATE items SET pile=?,payload=?"
                        " WHERE persona_id=? AND item_id=?",
                        (pile, self._encode(payload), persona_id, item_id),
                    )
                    if (pile != "trade" and trade is not None and
                            str(trade["trade_state"]) in ("expired", "inactive")):
                        connection.execute(
                            "UPDATE trades SET trade_state='cancelled'"
                            " WHERE persona_id=? AND trade_id=?",
                            (persona_id, int(trade["trade_id"])),
                        )
                    if pile == "trade":
                        self._forget_items_in_squads(
                            connection, persona_id, {item_id})
                result = {"id": item_id, "pile": pile, "success": success}
                if reason:
                    result["reason"] = reason
                results.append(result)
        return results

    def _forget_items_in_squads(self, connection, persona_id: int,
                                gone: set) -> None:
        if not gone:
            return
        gone = {int(item_id) for item_id in gone}

        def _id(value) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        for row in connection.execute(
                "SELECT squad_id, payload FROM squads WHERE persona_id=?",
                (int(persona_id),)).fetchall():
            try:
                squad = json.loads(row["payload"])
            except (ValueError, TypeError):
                continue
            if not isinstance(squad, dict):
                continue
            changed = False
            slots = squad.get("slots")
            if isinstance(slots, dict):
                kept = {index: item for index, item in slots.items()
                        if _id(item) not in gone}
                if len(kept) != len(slots):
                    squad["slots"] = kept
                    changed = True
            manager = squad.get("manager")
            if isinstance(manager, list) and any(
                    isinstance(entry, dict) and _id(entry.get("id")) in gone
                    for entry in manager):
                squad["manager"] = [{"id": 0, "dream": False}]
                changed = True
            if _id(squad.get("captain")) in gone:
                del squad["captain"]
                changed = True
            kicktakers = squad.get("kicktakers")
            if isinstance(kicktakers, list) and any(
                    isinstance(entry, dict) and _id(entry.get("id")) in gone
                    for entry in kicktakers):
                del squad["kicktakers"]
                changed = True
            if not changed:
                continue
            connection.execute(
                "UPDATE squads SET payload=? WHERE persona_id=? AND squad_id=?",
                (json.dumps(squad, separators=(",", ":")),
                 int(persona_id), int(row["squad_id"])))

    def discard_items(self, persona_id: int, item_ids: list[int]) -> tuple[int, list[dict]]:
        persona_id = int(persona_id)
        self.ensure_persona(persona_id)
        sold = []
        with self._lock, closing(self._connect()) as connection, connection:
            wallet = connection.execute(
                "SELECT credits FROM wallets WHERE persona_id=?", (persona_id,)
            ).fetchone()
            credits = int(wallet["credits"])
            for raw_id in dict.fromkeys(item_ids):
                try:
                    item_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                row = connection.execute(
                    "SELECT payload FROM items WHERE persona_id=? AND item_id=?",
                    (persona_id, item_id),
                ).fetchone()
                if row is None:
                    continue
                listed = connection.execute(
                    "SELECT trade_id FROM trades WHERE persona_id=? AND item_id=?"
                    " AND trade_state IN ('active','sold') LIMIT 1",
                    (persona_id, item_id),
                ).fetchone()
                if listed is not None:
                    continue
                item = self._decode(row)
                gain = max(0, int(item.get("discardValue", 0) or 0))
                connection.execute(
                    "DELETE FROM items WHERE persona_id=? AND item_id=?",
                    (persona_id, item_id),
                )
                transaction = self._apply_wallet_delta(
                    connection, persona_id, "COINS", gain, "quick_sell",
                    "item", item_id, f"quick-sell:{item_id}",
                    metadata={
                        "asset_id": int(item.get("assetId", 0) or 0),
                        "resource_id": int(item.get("resourceId", 0) or 0),
                        "discard_value": gain,
                    })
                credits = int(transaction["balance_after"])
                sold.append({"id": item_id, "itemId": item_id,
                             "discardValue": gain})
            self._forget_items_in_squads(
                connection, persona_id, {int(s["id"]) for s in sold})
        return credits, sold

    @staticmethod
    def _valid_market_price(value: int) -> bool:
        value = int(value)
        if value < MIN_LISTING_PRICE or value > MAX_LISTING_PRICE:
            return False
        if value <= 1_000:
            step = 50
        elif value <= 10_000:
            step = 100
        elif value <= 50_000:
            step = 250
        elif value <= 100_000:
            step = 500
        else:
            step = 1_000
        return value % step == 0

    @staticmethod
    def _market_fields(item: dict) -> tuple:
        import fut_cards

        item = item if isinstance(item, dict) else {}
        item_type = str(item.get("itemType", "") or "")
        resource_id = int(item.get("resourceId", 0) or 0)
        family = str(fut_cards.family_by_resource().get(resource_id, "") or "")
        if item_type == "player":
            search_type, category = "player", ""
        elif item_type == "staff":
            search_type = "staff"
            category = "GKCoach" if family == "gkCoach" else family
        elif item_type == "training":
            search_type = "training"
            category = {
                "trainingPlayer": "playerTraining",
                "trainingGk": "GKTraining",
                "leagueModifier": "managerLeagueModifier",
            }.get(family, family)
        elif item_type == "development":
            search_type = "development"
            if family == "healing":
                category = ("fitness" if int(item.get("cardassetid", 0) or 0)
                            == 10 else "healing")
            else:
                category = family
        elif item_type in ("kit", "custom"):
            search_type = "clubInfo"
            category = "kit" if item_type == "kit" else "badge"
        elif item_type in ("stadium", "ball"):
            search_type, category = item_type, ""
        else:
            search_type, category = item_type, family
        return (
            resource_id,
            search_type,
            category,
            int(item.get("rating", 0) or 0),
            int(item.get("rareflag", 0) or 0),
            int(item.get("leagueId", 0) or 0),
            int(item.get("nation", 0) or 0),
            int(item.get("teamid", 0) or 0),
            str(item.get("preferredPosition", "") or ""),
            int(item.get("playStyle", 0) or 0),
        )

    @staticmethod
    def _trade_document(row: sqlite3.Row) -> dict:
        document = dict(row)
        document["itemData"] = json.loads(row["payload"])
        document.pop("payload", None)
        return document

    def _expire_trades(self, connection: sqlite3.Connection, persona_id: int,
                       now: int) -> None:
        self._settle_elapsed_trades(connection, int(now), int(persona_id))

    def _settle_real_trade(self, connection: sqlite3.Connection,
                           row: sqlite3.Row, now: int) -> None:
        seller = int(row["persona_id"])
        bidder = int(row["bidder_persona"])
        price = int(row["current_bid"])
        trade_id = int(row["trade_id"])
        item_id = int(row["item_id"])
        item_row = connection.execute(
            "SELECT * FROM items WHERE persona_id=? AND item_id=?",
            (seller, item_id)).fetchone()

        if bidder <= 0 or price <= 0:
            connection.execute(
                "UPDATE trades SET trade_state='expired'"
                " WHERE persona_id=? AND trade_id=?", (seller, trade_id))
            if item_row is not None:
                try:
                    item = json.loads(item_row["payload"])
                except (TypeError, ValueError):
                    item = {}
                if isinstance(item, dict):
                    item["itemState"] = "free"
                connection.execute(
                    "UPDATE items SET payload=? WHERE persona_id=? AND item_id=?",
                    (self._encode(item), seller, item_id))
            return

        try:
            item = json.loads(item_row["payload"] if item_row is not None
                              else row["payload"])
        except (TypeError, ValueError):
            item = {}
        resource_id = int(row["resource_id"] or item.get("resourceId", 0) or 0)
        duplicate = (str(item.get("itemType", "")) in UNIQUE_ITEM_TYPES
                     and self._owns_resource(connection, bidder, resource_id))
        if item_row is None or duplicate:
            reason = ("market_duplicate_refund" if duplicate
                      else "market_missing_item_refund")
            self._apply_wallet_delta(
                connection, bidder, "COINS", price, reason, "trade", trade_id,
                f"market:{trade_id}:settlement-refund:{bidder}:{price}",
                metadata={"seller_persona": seller,
                          "resource_id": resource_id}, now=now)
            connection.execute(
                "UPDATE trades SET trade_state='expired',current_bid=0,"
                " bidder_persona=0,bid_state='none',coins_processed=0"
                " WHERE persona_id=? AND trade_id=?", (seller, trade_id))
            if item_row is not None:
                item["itemState"] = "free"
                connection.execute(
                    "UPDATE items SET payload=? WHERE persona_id=? AND item_id=?",
                    (self._encode(item), seller, item_id))
            return

        awarded_id = self._next_item_id(connection, bidder)
        item["id"] = awarded_id
        item["itemState"] = "free"
        item["owners"] = max(1, int(item.get("owners", 1) or 1)) + 1
        item["lastSalePrice"] = price
        item["timestamp"] = int(now)
        connection.execute(
            "DELETE FROM items WHERE persona_id=? AND item_id=?",
            (seller, item_id))
        connection.execute(
            "INSERT INTO items(persona_id,item_id,asset_id,pile,payload,"
            "acquired_at,item_type) VALUES(?,?,?,'unassigned',?,?,?)",
            (bidder, awarded_id, int(item.get("assetId", 0) or 0),
             self._encode(item), int(now),
             str(item.get("itemType", "player") or "player")))

        fee = price * MARKET_TAX_BPS // 10_000
        proceeds = price - fee
        self._apply_wallet_delta(
            connection, seller, "COINS", proceeds, "market_sale_proceeds",
            "trade", trade_id, f"market:{trade_id}:seller-proceeds",
            metadata={"buyer_persona": bidder, "gross": price,
                      "tax": fee, "tax_bps": MARKET_TAX_BPS}, now=now)
        connection.execute(
            "UPDATE trades SET trade_state='sold',coins_processed=1,"
            " awarded_item_id=? WHERE persona_id=? AND trade_id=?",
            (awarded_id, seller, trade_id))

    def _settle_elapsed_trades(self, connection: sqlite3.Connection, now: int,
                               persona_id: int | None = None) -> int:
        params: list[int] = [int(now)]
        owner = ""
        if persona_id is not None:
            owner = " AND persona_id=?"
            params.append(int(persona_id))
        rows = connection.execute(
            "SELECT * FROM trades WHERE trade_state='active'"
            " AND expires_at<=?" + owner + " ORDER BY trade_id", params
        ).fetchall()
        for row in rows:
            self._settle_real_trade(connection, row, int(now))
        return len(rows)

    def _reconcile_unlisted_trade_identities(
            self, connection: sqlite3.Connection, persona_id: int,
            now: int) -> None:
        rows = connection.execute(
            "SELECT i.item_id,t.trade_id,t.trade_state,t.starting_bid,"
            " t.buy_now_price,t.created_at,t.expires_at FROM items i"
            " LEFT JOIN trades t ON t.persona_id=i.persona_id"
            " AND t.item_id=i.item_id"
            " WHERE i.persona_id=? AND i.pile='trade'"
            " AND (t.trade_id IS NULL"
            " OR t.trade_state IN ('cancelled','inactive')"
            " OR (t.trade_state='expired' AND t.created_at=t.expires_at))"
            " ORDER BY i.item_id",
            (int(persona_id),),
        ).fetchall()
        if not rows:
            return
        wanted = sum(1 for row in rows if row["trade_id"] is None)
        next_trade_id = (self._allocate_ids(connection, TRADE_ID_COUNTER,
                                            FIRST_TRADE_ID, wanted)
                         if wanted else 0)
        for row in rows:
            if row["trade_id"] is None:
                connection.execute(
                    "INSERT INTO trades(persona_id,trade_id,item_id,starting_bid,"
                    "buy_now_price,current_bid,created_at,expires_at,trade_state,"
                    "bid_state,coins_processed,watched)"
                    " VALUES(?,?,?,0,0,0,?,?,'inactive','none',0,0)",
                    (int(persona_id), next_trade_id, int(row["item_id"]),
                     int(now), int(now)),
                )
                next_trade_id += 1
            else:
                connection.execute(
                    "UPDATE trades SET starting_bid=0,buy_now_price=0,"
                    " current_bid=0,created_at=?,expires_at=?,"
                    " trade_state='inactive',bid_state='none',"
                    " coins_processed=0,watched=0"
                    " WHERE persona_id=? AND trade_id=?",
                    (int(now), int(now), int(persona_id),
                     int(row["trade_id"])),
                )

    def list_trades(self, persona_id: int, now: int | None = None) -> list[dict]:
        persona_id = int(persona_id)
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_trades(connection, persona_id, current)
            self._reconcile_unlisted_trade_identities(
                connection, persona_id, current)
            rows = connection.execute(
                "SELECT t.*,COALESCE(i.payload,t.payload) AS listing_payload"
                " FROM trades t LEFT JOIN items i"
                " ON i.persona_id=t.persona_id AND i.item_id=t.item_id"
                " WHERE t.persona_id=?"
                " AND t.trade_state IN ('inactive','active','expired','sold')"
                " ORDER BY t.trade_id",
                (persona_id,),
            ).fetchall()
        documents = []
        for row in rows:
            document = dict(row)
            document["itemData"] = json.loads(row["listing_payload"])
            document.pop("payload", None)
            document.pop("listing_payload", None)
            documents.append(document)
        return documents

    def create_trade(self, persona_id: int, item_id: int, starting_bid: int,
                     buy_now_price: int, duration: int,
                     now: int | None = None, *, seller_name: str = "",
                     seller_established: int = 0) -> tuple[dict | None, str]:
        persona_id = int(persona_id)
        item_id = int(item_id)
        starting_bid = int(starting_bid)
        buy_now_price = int(buy_now_price)
        duration = int(duration)
        current = int(time.time()) if now is None else int(now)
        self.ensure_persona(persona_id)
        if not self._valid_market_price(starting_bid):
            return None, "INVALID_STARTING_BID"
        if (buy_now_price != 0 and
                (buy_now_price < starting_bid or
                 not self._valid_market_price(buy_now_price))):
            return None, "INVALID_BUY_NOW_PRICE"
        if duration not in LISTING_DURATIONS:
            return None, "INVALID_DURATION"

        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_trades(connection, persona_id, current)
            item_row = connection.execute(
                "SELECT pile,payload FROM items WHERE persona_id=? AND item_id=?",
                (persona_id, item_id),
            ).fetchone()
            if item_row is None:
                return None, "ITEM_NOT_FOUND"
            if str(item_row["pile"]) not in ("club", "trade"):
                return None, "INVALID_PILE"
            try:
                item = json.loads(item_row["payload"])
            except (ValueError, TypeError):
                item = {}
            if not isinstance(item, dict) or bool(item.get("untradeable", False)):
                return None, "UNTRADEABLE_ITEM"

            existing = connection.execute(
                "SELECT * FROM trades WHERE persona_id=? AND item_id=?",
                (persona_id, item_id),
            ).fetchone()
            if existing is not None and str(existing["trade_state"]) == "active":
                row = connection.execute(
                    "SELECT t.*,i.payload AS listing_payload FROM trades t"
                    " JOIN items i ON i.persona_id=t.persona_id"
                    " AND i.item_id=t.item_id"
                    " WHERE t.persona_id=? AND t.trade_id=?",
                    (persona_id, int(existing["trade_id"])),
                ).fetchone()
                document = dict(row)
                document["itemData"] = json.loads(row["listing_payload"])
                document.pop("payload", None)
                document.pop("listing_payload", None)
                return document, ""
            if existing is not None and str(existing["trade_state"]) == "sold":
                return None, "ITEM_ALREADY_SOLD"

            if str(item_row["pile"]) != "trade":
                pile_count = connection.execute(
                    "SELECT COUNT(*) AS n FROM items"
                    " WHERE persona_id=? AND pile='trade'",
                    (persona_id,),
                ).fetchone()["n"]
                if int(pile_count) >= TRANSFER_PILE_LIMIT:
                    return None, "TRADE_PILE_FULL"

            item["itemState"] = "forSale"
            connection.execute(
                "UPDATE items SET pile='trade',payload=?"
                " WHERE persona_id=? AND item_id=?",
                (self._encode(item), persona_id, item_id),
            )
            self._forget_items_in_squads(connection, persona_id, {item_id})
            expires_at = current + duration
            fields = self._market_fields(item)
            snapshot = self._encode(item)
            if existing is None:
                trade_id = self._allocate_ids(
                    connection, TRADE_ID_COUNTER, FIRST_TRADE_ID)
                connection.execute(
                    "INSERT INTO trades(persona_id,trade_id,item_id,starting_bid,"
                    "buy_now_price,current_bid,created_at,expires_at,trade_state,"
                    "bid_state,coins_processed,watched,payload,bidder_persona,"
                    "awarded_item_id,seller_name,seller_established,resource_id,"
                    "search_type,category,rating,rare_flag,league_id,nation,"
                    "team_id,position,play_style)"
                    " VALUES(?,?,?,?,?,0,?,?,'active','none',0,0,?,0,0,?,?,"
                    "?,?,?,?,?,?,?,?,?,?)",
                    (persona_id, trade_id, item_id, starting_bid,
                     buy_now_price, current, expires_at, snapshot,
                     str(seller_name), int(seller_established), *fields),
                )
            else:
                trade_id = int(existing["trade_id"])
                connection.execute(
                    "UPDATE trades SET starting_bid=?,buy_now_price=?,current_bid=0,"
                    " created_at=?,expires_at=?,trade_state='active',"
                    " bid_state='none',coins_processed=0,watched=0"
                    ",payload=?,bidder_persona=0,awarded_item_id=0,"
                    "seller_name=?,seller_established=?,resource_id=?,"
                    "search_type=?,category=?,rating=?,rare_flag=?,league_id=?,"
                    "nation=?,team_id=?,position=?,play_style=?"
                    " WHERE persona_id=? AND trade_id=?",
                    (starting_bid, buy_now_price, current, expires_at,
                     snapshot, str(seller_name), int(seller_established),
                     *fields, persona_id, trade_id),
                )
            row = connection.execute(
                "SELECT t.*,i.payload AS listing_payload FROM trades t"
                " JOIN items i ON i.persona_id=t.persona_id"
                " AND i.item_id=t.item_id"
                " WHERE t.persona_id=? AND t.trade_id=?",
                (persona_id, trade_id),
            ).fetchone()
            document = dict(row)
            document["itemData"] = json.loads(row["listing_payload"])
            document.pop("payload", None)
            document.pop("listing_payload", None)
            return document, ""

    def cancel_trade(self, persona_id: int, trade_id: int) -> bool:
        persona_id = int(persona_id)
        trade_id = int(trade_id)
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_trades(connection, persona_id, int(time.time()))
            row = connection.execute(
                "SELECT item_id,trade_state,current_bid FROM trades"
                " WHERE persona_id=? AND trade_id=?",
                (persona_id, trade_id),
            ).fetchone()
            if row is not None and str(row["trade_state"]) == "sold":
                connection.execute(
                    "DELETE FROM trades WHERE persona_id=? AND trade_id=?"
                    " AND coins_processed=1", (persona_id, trade_id))
                return True
            if row is None or str(row["trade_state"]) not in ("active", "expired"):
                return False
            if int(row["current_bid"] or 0) > 0:
                return False
            item_id = int(row["item_id"])
            item_row = connection.execute(
                "SELECT payload FROM items WHERE persona_id=? AND item_id=?",
                (persona_id, item_id),
            ).fetchone()
            if item_row is None:
                return False
            try:
                item = json.loads(item_row["payload"])
            except (ValueError, TypeError):
                item = {}
            if isinstance(item, dict):
                item["itemState"] = "free"
            connection.execute(
                "UPDATE trades SET trade_state='cancelled'"
                " WHERE persona_id=? AND trade_id=?",
                (persona_id, trade_id),
            )
            connection.execute(
                "UPDATE items SET pile='club',payload=?"
                " WHERE persona_id=? AND item_id=?",
                (self._encode(item), persona_id, item_id),
            )
        return True

    def relist_trade(self, persona_id: int, trade_id: int, duration: int = 3600,
                     now: int | None = None) -> tuple[dict | None, str]:
        persona_id = int(persona_id)
        trade_id = int(trade_id)
        current = int(time.time()) if now is None else int(now)
        if int(duration) not in LISTING_DURATIONS:
            return None, "INVALID_DURATION"
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_trades(connection, persona_id, current)
            row = connection.execute(
                "SELECT item_id,starting_bid,buy_now_price,trade_state,"
                "seller_name,seller_established FROM trades"
                " WHERE persona_id=? AND trade_id=?",
                (persona_id, trade_id),
            ).fetchone()
            if row is None or str(row["trade_state"]) != "expired":
                return None, "TRADE_NOT_EXPIRED"
        return self.create_trade(
            persona_id, int(row["item_id"]), int(row["starting_bid"]),
            int(row["buy_now_price"]), int(duration), now=current,
            seller_name=str(row["seller_name"] or ""),
            seller_established=int(row["seller_established"] or 0))

    def relist_expired_trades(self, persona_id: int,
                              now: int | None = None) -> tuple[list[dict], int]:
        persona_id = int(persona_id)
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._expire_trades(connection, persona_id, current)
            rows = connection.execute(
                "SELECT trade_id,created_at,expires_at FROM trades"
                " WHERE persona_id=? AND trade_state='expired'"
                " ORDER BY trade_id",
                (persona_id,),
            ).fetchall()
            pending = [(int(row["trade_id"]),
                        int(row["expires_at"]) - int(row["created_at"]))
                       for row in rows]

        relisted: list[dict] = []
        failed = 0
        for trade_id, span in pending:
            duration = span if span in LISTING_DURATIONS else min(LISTING_DURATIONS)
            trade, _reason = self.relist_trade(
                persona_id, trade_id, duration, now=current)
            if trade is None:
                failed += 1
            else:
                relisted.append(trade)
        return relisted, failed

    def _real_market_document(self, connection: sqlite3.Connection,
                              row: sqlite3.Row, viewer: int | None = None) -> dict:
        document = dict(row)
        try:
            item = json.loads(document.pop("payload"))
        except (TypeError, ValueError):
            item = {}
        viewer_id = int(viewer or 0)
        awarded = int(document.get("awarded_item_id") or 0)
        bidder = int(document.get("bidder_persona") or 0)
        if awarded and viewer_id == bidder:
            awarded_row = connection.execute(
                "SELECT payload FROM items WHERE persona_id=? AND item_id=?",
                (bidder, awarded)).fetchone()
            if awarded_row is not None:
                try:
                    item = json.loads(awarded_row["payload"])
                except (TypeError, ValueError):
                    pass
        document["itemData"] = item
        document["seller_name"] = (str(document.get("seller_name") or "")
                                   or f"Persona {document['persona_id']}")
        watched = False
        if viewer_id:
            watched = connection.execute(
                "SELECT 1 FROM auction_watches WHERE persona_id=?"
                " AND trade_id=?", (viewer_id, int(document["trade_id"])))
            watched = watched is not None
            if bidder == viewer_id:
                pass
            elif watched and int(document.get("current_bid") or 0) > 0:
                document["bid_state"] = self.BID_OUTBID
            else:
                document["bid_state"] = self.BID_NONE
        document["watched"] = bool(watched)
        return document

    @staticmethod
    def _market_query_number(query: dict, name: str) -> int | None:
        raw = query.get(name)
        if raw in (None, "", "-1", "any"):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _search_real_market(self, query: dict, now: int,
                            viewer: int | None = None) -> tuple[list[dict], int]:
        number = lambda name: self._market_query_number(query, name)
        search_type = str(query.get("type", "") or "").strip()
        category = str(query.get("cat", "") or "").strip()
        start = max(0, number("start") or 0)
        count = max(1, min(number("num") or 12, 50))

        where = ["trade_state='active'", "search_type=?"]
        params: list = [search_type]
        if category:
            where.append("category=?")
            params.append(category)
        if viewer:
            where.append("persona_id!=?")
            params.append(int(viewer))

        definition_id = 0
        for alias in ("definitionId", "defId", "defid", "maskedDefId",
                      "resourceId"):
            definition_id = number(alias) or 0
            if definition_id:
                break
        if definition_id:
            where.append("resource_id=?")
            params.append(definition_id)

        level = str(query.get("lev", "") or "").strip().lower()
        band = MARKET_QUALITY_BANDS.get(level)
        if band:
            where.append("rating BETWEEN ? AND ?")
            params.extend(band)
        elif level == "rare":
            where.append("rare_flag>=1")
        elif level in ("sp", "special"):
            where.append("resource_id>16777215")

        position = str(query.get("pos", "") or "").strip().upper()
        if position and position not in ("ANY", "ALL", "-1"):
            where.append("position=?")
            params.append(position)
        for column, name in (("nation", "nat"), ("league_id", "leag"),
                             ("team_id", "team"),
                             ("play_style", "playStyle")):
            value = number(name)
            if value is not None:
                where.append(f"{column}=?")
                params.append(value)

        asking = "(CASE WHEN current_bid>0 THEN current_bid ELSE starting_bid END)"
        for column, name, operator in ((asking, "micr", ">="),
                                       (asking, "macr", "<="),
                                       ("buy_now_price", "minb", ">="),
                                       ("buy_now_price", "maxb", "<=")):
            value = number(name)
            if value is not None:
                where.append(f"{column}{operator}?")
                params.append(value)

        clause = " AND ".join(where)
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, int(now))
            total = int(connection.execute(
                f"SELECT COUNT(*) AS n FROM trades WHERE {clause}", params
            ).fetchone()["n"])
            rows = connection.execute(
                f"SELECT * FROM trades WHERE {clause}"
                " ORDER BY expires_at,trade_id LIMIT ? OFFSET ?",
                (*params, count, start)).fetchall()
            return ([self._real_market_document(connection, row, viewer)
                     for row in rows], total)

    def _real_market_for_resource(self, resource_id: int, limit: int, now: int,
                                  viewer: int | None = None) -> list[dict]:
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, int(now))
            params: list = [int(resource_id)]
            owner = ""
            if viewer:
                owner = " AND persona_id!=?"
                params.append(int(viewer))
            rows = connection.execute(
                "SELECT * FROM trades WHERE resource_id=?"
                " AND trade_state='active'" + owner +
                " ORDER BY (CASE WHEN current_bid>0 THEN current_bid"
                " ELSE starting_bid END),trade_id LIMIT ?",
                (*params, int(limit))).fetchall()
            return [self._real_market_document(connection, row, viewer)
                    for row in rows]

    def _place_real_offer(self, persona_id: int, trade_id: int, bid: int,
                          now: int) -> tuple[dict | None, str]:
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, int(now))
            listing = connection.execute(
                "SELECT * FROM trades WHERE trade_id=? ORDER BY persona_id"
                " LIMIT 1", (int(trade_id),)).fetchone()
            if listing is None:
                return None, "NO_SUCH_TRADE"
            if int(listing["persona_id"]) == int(persona_id):
                return None, "CANNOT_BID_ON_OWN_TRADE"
            if str(listing["trade_state"]) != "active":
                return None, "AUCTION_CLOSED"
            try:
                item = json.loads(listing["payload"])
            except (TypeError, ValueError):
                item = {}
            if (str(item.get("itemType", "")) in UNIQUE_ITEM_TYPES
                    and self._owns_resource(connection, persona_id,
                                            int(listing["resource_id"]))):
                return None, "DUPLICATE_ITEM_TYPE"

            buy_now = int(listing["buy_now_price"])
            standing = int(listing["current_bid"])
            holder = int(listing["bidder_persona"])
            already_held = standing if holder == int(persona_id) else 0
            if int(bid) < self.minimum_bid(dict(listing)):
                return None, "BID_TOO_LOW"
            if buy_now > 0 and int(bid) > buy_now:
                bid = buy_now
            if not self._valid_market_price(int(bid)):
                return None, "INVALID_BID"
            wallet = connection.execute(
                "SELECT credits FROM wallets WHERE persona_id=?",
                (int(persona_id),)).fetchone()
            if int(bid) - already_held > int(wallet["credits"] if wallet else 0):
                return None, "INSUFFICIENT_FUNDS"

            if holder > 0 and holder != int(persona_id) and standing > 0:
                self._apply_wallet_delta(
                    connection, holder, "COINS", standing,
                    "market_outbid_refund", "trade", trade_id,
                    f"market:{trade_id}:outbid:{holder}:{standing}",
                    metadata={"new_bidder": int(persona_id),
                              "new_bid": int(bid)}, now=now)
            self._apply_wallet_delta(
                connection, int(persona_id), "COINS", -(int(bid) - already_held),
                "market_bid_hold", "trade", trade_id,
                f"market:{trade_id}:hold:{persona_id}:{bid}",
                metadata={"bid": int(bid), "previously_held": already_held,
                          "seller_persona": int(listing["persona_id"])}, now=now)
            connection.execute(
                "INSERT OR IGNORE INTO auction_watches(persona_id,trade_id,created_at)"
                " VALUES(?,?,?)", (int(persona_id), int(trade_id), int(now)))

            if buy_now > 0 and int(bid) >= buy_now:
                connection.execute(
                    "UPDATE trades SET current_bid=?,bidder_persona=?,"
                    "bid_state=?,expires_at=? WHERE persona_id=? AND trade_id=?",
                    (int(bid), int(persona_id), self.BID_BUY_NOW, int(now),
                     int(listing["persona_id"]), int(trade_id)))
                changed = connection.execute(
                    "SELECT * FROM trades WHERE persona_id=? AND trade_id=?",
                    (int(listing["persona_id"]), int(trade_id))).fetchone()
                self._settle_real_trade(connection, changed, int(now))
                outcome = "bought"
            else:
                expires_at = int(listing["expires_at"])
                if expires_at - int(now) < MARKET_ANTI_SNIPE_SECONDS:
                    expires_at = int(now) + MARKET_ANTI_SNIPE_SECONDS
                connection.execute(
                    "UPDATE trades SET current_bid=?,bidder_persona=?,"
                    "bid_state=?,expires_at=? WHERE persona_id=? AND trade_id=?",
                    (int(bid), int(persona_id), self.BID_HIGHEST, expires_at,
                     int(listing["persona_id"]), int(trade_id)))
                outcome = "bid"
            final = connection.execute(
                "SELECT * FROM trades WHERE persona_id=? AND trade_id=?",
                (int(listing["persona_id"]), int(trade_id))).fetchone()
            document = self._real_market_document(connection, final, persona_id)
            document["outcome"] = outcome
            return document, ""

    def watch_trade(self, persona_id: int, trade_id: int,
                    now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, current)
            row = connection.execute(
                "SELECT persona_id,trade_state FROM trades WHERE trade_id=?"
                " LIMIT 1", (int(trade_id),)).fetchone()
            if (row is None or str(row["trade_state"]) != "active"
                    or int(row["persona_id"]) == int(persona_id)):
                return False
            connection.execute(
                "INSERT OR IGNORE INTO auction_watches(persona_id,trade_id,created_at)"
                " VALUES(?,?,?)", (int(persona_id), int(trade_id), current))
            return True

    def unwatch_trade(self, persona_id: int, trade_id: int) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            return connection.execute(
                "DELETE FROM auction_watches WHERE persona_id=? AND trade_id=?",
                (int(persona_id), int(trade_id))).rowcount > 0

    def remove_sold_trades(self, persona_id: int) -> int:
        with self._lock, closing(self._connect()) as connection, connection:
            return connection.execute(
                "DELETE FROM trades WHERE persona_id=? AND trade_state='sold'"
                " AND coins_processed=1", (int(persona_id),)).rowcount


    BID_NONE = "none"
    BID_HIGHEST = "highest"
    BID_OUTBID = "outbid"
    BID_BUY_NOW = "buyNow"

    @staticmethod
    def _bid_increment(current: int) -> int:
        current = int(current)
        if current < 1_000:
            return 50
        if current < 10_000:
            return 100
        if current < 50_000:
            return 250
        if current < 100_000:
            return 500
        return 1_000

    def minimum_bid(self, listing: dict) -> int:
        current = int(listing["current_bid"])
        if current <= 0:
            return int(listing["starting_bid"])
        return current + self._bid_increment(current)

    def _owns_resource(self, connection: sqlite3.Connection, persona_id: int,
                       resource_id: int) -> bool:
        row = connection.execute(
            "SELECT 1 FROM items WHERE persona_id=? AND pile!='trade'"
            " AND json_extract(payload,'$.resourceId')=? LIMIT 1",
            (int(persona_id), int(resource_id))).fetchone()
        return row is not None

    def _next_item_id(self, connection: sqlite3.Connection,
                      persona_id: int) -> int:
        top = connection.execute(
            "SELECT MAX(m) AS top FROM ("
            " SELECT MAX(item_id) AS m FROM items WHERE persona_id=?"
            " UNION ALL"
            " SELECT high_water AS m FROM wallets WHERE persona_id=?)",
            (int(persona_id), int(persona_id))).fetchone()["top"]
        next_id = max(FIRST_PACK_ITEM_ID, int(top or 0) + 1)
        connection.execute(
            "UPDATE wallets SET high_water=MAX(high_water,?) WHERE persona_id=?",
            (next_id, int(persona_id)))
        return next_id

    def search_market(self, query: dict, now: int | None = None,
                      persona_id: int | None = None) -> tuple[list[dict], int]:
        current = int(time.time()) if now is None else int(now)
        return self._search_real_market(query, current, persona_id)

    def market_listings_for_resource(self, resource_id: int, limit: int = 20,
                                     now: int | None = None,
                                     persona_id: int | None = None) -> list[dict]:
        current = int(time.time()) if now is None else int(now)
        return self._real_market_for_resource(
            resource_id, limit, current, persona_id)

    def settle_market(self, persona_id: int, now: int | None = None) -> int:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            return self._settle_elapsed_trades(connection, current)

    def place_offer(self, persona_id: int, trade_id: int, bid: int,
                    now: int | None = None) -> tuple[dict | None, str]:
        persona_id = int(persona_id)
        current = int(time.time()) if now is None else int(now)
        self.ensure_persona(persona_id)
        return self._place_real_offer(persona_id, int(trade_id), int(bid), current)

    def bid_listings(self, persona_id: int,
                     now: int | None = None) -> list[dict]:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, current)
            rows = connection.execute(
                "SELECT t.* FROM trades t JOIN auction_watches w"
                " ON w.trade_id=t.trade_id WHERE w.persona_id=?"
                " AND (t.trade_state='active'"
                " OR (t.trade_state='sold' AND t.bidder_persona=?"
                " AND t.awarded_item_id IN (SELECT item_id FROM items"
                " WHERE persona_id=? AND pile='unassigned'))"
                " OR (t.trade_state IN ('expired','sold')"
                " AND t.bidder_persona!=?)) ORDER BY t.trade_id",
                (int(persona_id), int(persona_id), int(persona_id),
                 int(persona_id))).fetchall()
            return [self._real_market_document(connection, row, persona_id)
                    for row in rows]

    def live_auction_count(self, persona_id: int,
                           now: int | None = None) -> int:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, current)
            return int(connection.execute(
                "SELECT COUNT(*) AS n FROM trades WHERE trade_state='active'"
            ).fetchone()["n"])

    def market_listing(self, trade_id: int, persona_id: int | None = None,
                       now: int | None = None) -> dict | None:
        current = int(time.time()) if now is None else int(now)
        with self._lock, closing(self._connect()) as connection, connection:
            self._settle_elapsed_trades(connection, current)
            row = connection.execute(
                "SELECT * FROM trades WHERE trade_id=? ORDER BY persona_id LIMIT 1",
                (int(trade_id),)).fetchone()
            return (self._real_market_document(connection, row, persona_id)
                    if row is not None else None)


    CURRENT_TOURNAMENT = 0

    def save_tournament_progress(self, persona_id: int, round_number: int,
                                 data_version: int, tournament_data: str,
                                 progress_data_version: int = 0,
                                 progress_data: str = "",
                                 tournament_id: int | None = None,
                                 now: int | None = None) -> dict:
        persona_id = int(persona_id)
        slot = (self.CURRENT_TOURNAMENT if tournament_id is None
                else int(tournament_id))
        current = int(time.time()) if now is None else int(now)
        self.ensure_persona(persona_id)
        with self._lock, closing(self._connect()) as connection, connection:
            if slot != self.CURRENT_TOURNAMENT:
                settled = connection.execute(
                    "SELECT * FROM matches WHERE persona_id=?"
                    " AND tournament_id=? AND status='settled'"
                    " ORDER BY rowid DESC LIMIT 1",
                    (persona_id, slot),
                ).fetchone()
                canonical = connection.execute(
                    "SELECT * FROM tournaments WHERE persona_id=?"
                    " AND tournament_id=?", (persona_id, slot)
                ).fetchone()
                if (settled is not None and canonical is not None
                        and settled["tournament_outcome"] not in ("", "replay")
                        and int(canonical["updated_at"])
                            <= int(settled["settled_at"] or 0)
                        and int(round_number)
                            == int(settled["tournament_round_before"])
                        and self.tournament_is_resumable(
                            int(round_number), str(progress_data))):
                    retained = dict(canonical)
                    retained["settlement_rollback_rejected"] = True
                    return retained
            connection.execute(
                "INSERT INTO tournaments(persona_id,tournament_id,round,"
                "data_version,tournament_data,progress_data_version,"
                "progress_data,updated_at) VALUES(?,?,?,?,?,?,?,?)"
                " ON CONFLICT(persona_id,tournament_id) DO UPDATE SET"
                " round=excluded.round,data_version=excluded.data_version,"
                " tournament_data=excluded.tournament_data,"
                " progress_data_version=excluded.progress_data_version,"
                " progress_data=excluded.progress_data,"
                " updated_at=excluded.updated_at",
                (persona_id, slot, int(round_number), int(data_version),
                 str(tournament_data), int(progress_data_version),
                 str(progress_data), current),
            )
        return self.load_tournament_progress(persona_id, slot)

    @staticmethod
    def tournament_is_resumable(round_value: int, progress_data: str) -> bool:
        if int(round_value or 0) > 1:
            return True
        blob = str(progress_data or "")
        if not blob:
            return False
        try:
            return any(base64.b64decode(blob, validate=True))
        except (ValueError, binascii.Error):
            return True

    TOURNAMENT_ELIMINATING = ("LOSS", "DNF", "QUIT", "FORFEIT")

    def settle_tournament(self, persona_id: int, tournament_id: int,
                          end_reason: str, rounds: int) -> dict:
        persona_id, tournament_id = int(persona_id), int(tournament_id)
        rounds = max(1, int(rounds))
        result = str(end_reason or "").upper()
        record = self.load_tournament_progress(persona_id, tournament_id) or {}
        played = max(1, int(record.get("round", 0) or 0))

        if result == "WIN":
            outcome = "won" if played >= rounds else "advanced"
            nxt = 1 if played >= rounds else played + 1
        elif result in self.TOURNAMENT_ELIMINATING:
            outcome, nxt = "eliminated", 1
        else:
            return {"tournamentId": tournament_id, "round": played,
                    "outcome": "replay"}

        self.save_tournament_progress(
            persona_id, round_number=nxt, data_version=0, tournament_data="",
            progress_data_version=0, progress_data="",
            tournament_id=tournament_id)
        return {"tournamentId": tournament_id, "round": nxt,
                "previousRound": played, "outcome": outcome}

    def resumable_tournament_ids(self, persona_id: int) -> list[int]:
        persona_id = int(persona_id)
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT tournament_id,round,progress_data FROM tournaments"
                " WHERE persona_id=? ORDER BY tournament_id",
                (persona_id,),
            ).fetchall()
        return [int(row["tournament_id"]) for row in rows
                if int(row["tournament_id"]) != self.CURRENT_TOURNAMENT
                and self.tournament_is_resumable(row["round"],
                                                 row["progress_data"])]

    def load_tournament_progress(self, persona_id: int,
                                 tournament_id: int | None = None) -> dict:
        persona_id = int(persona_id)
        slot = (self.CURRENT_TOURNAMENT if tournament_id is None
                else int(tournament_id))
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM tournaments WHERE persona_id=? AND tournament_id=?",
                (persona_id, slot),
            ).fetchone()
            if row is None and slot != self.CURRENT_TOURNAMENT:
                row = connection.execute(
                    "SELECT * FROM tournaments WHERE persona_id=? AND tournament_id=?",
                    (persona_id, self.CURRENT_TOURNAMENT),
                ).fetchone()
        if row is None:
            return {"tournament_id": slot, "round": 0, "data_version": 0,
                    "tournament_data": "", "progress_data_version": 0,
                    "progress_data": ""}
        return dict(row)

    def clear_tournament_progress(self, persona_id: int,
                                  tournament_id: int | None = None) -> int:
        persona_id = int(persona_id)
        with self._lock, closing(self._connect()) as connection, connection:
            if tournament_id is None:
                return connection.execute(
                    "DELETE FROM tournaments WHERE persona_id=?",
                    (persona_id,)).rowcount
            return connection.execute(
                "DELETE FROM tournaments WHERE persona_id=? AND tournament_id=?",
                (persona_id, int(tournament_id))).rowcount


    @staticmethod
    def _season_mode(mode: str) -> str:
        value = str(mode or "").strip().upper()
        if value not in SEASON_MODES:
            raise ValueError("unknown season mode: %s" % mode)
        return value

    def ensure_season_progress(self, persona_id: int, mode: str,
                               *, season_id: int = 1,
                               division_id: int = 1,
                               now: int | None = None) -> dict:
        persona_id = int(persona_id)
        season_mode = self._season_mode(mode)
        division_id = int(division_id)
        if not 1 <= division_id <= 10:
            raise ValueError("division id is outside 1..10")
        current = int(time.time()) if now is None else int(now)
        self.ensure_persona(persona_id)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO season_progress("
                "persona_id,mode,season_id,division_id,round,data_version,"
                "user_data,progress_data_version,progress_data,campaign,played,"
                "won,drawn,lost,points,status,last_result,updated_at,version)"
                " VALUES(?,?,?, ?,1,0,'',0,'',1,0,0,0,0,0,'active','',?,1)",
                (persona_id, season_mode, int(season_id), division_id,
                 current))
            row = connection.execute(
                "SELECT * FROM season_progress WHERE persona_id=? AND mode=?",
                (persona_id, season_mode)).fetchone()
        return dict(row)

    def select_season_mode(self, persona_id: int, mode: str) -> str:
        season_mode = self._season_mode(mode)
        self.save_clientdata(
            int(persona_id), SEASON_CONTEXT_KEY,
            [{"key": 0,
              "value": 1 if season_mode == SEASON_MODE_ONLINE else 0}])
        return season_mode

    def current_season_mode(self, persona_id: int) -> str:
        for entry in self.load_clientdata(
                int(persona_id), SEASON_CONTEXT_KEY) or []:
            try:
                if int(entry.get("key", -1)) == 0:
                    return (SEASON_MODE_ONLINE
                            if int(entry.get("value", 0)) else
                            SEASON_MODE_OFFLINE)
            except (AttributeError, TypeError, ValueError):
                continue
        return SEASON_MODE_OFFLINE

    def save_season_progress(self, persona_id: int, season_id: int,
                             division_id: int, round_number: int,
                             data_version: int, user_data: str,
                             progress_data_version: int = 0,
                             progress_data: str = "",
                             mode: str = SEASON_MODE_OFFLINE) -> dict:
        season_mode = self._season_mode(mode)
        division_id = int(division_id)
        if not 1 <= division_id <= 10:
            raise ValueError("division id is outside 1..10")
        with self._lock, closing(self._connect()) as connection, connection:
            current = connection.execute(
                "SELECT * FROM season_progress WHERE persona_id=? AND mode=?",
                (int(persona_id), season_mode)).fetchone()
            if (current is not None
                    and int(current["season_id"]) == int(season_id)
                    and int(current["division_id"]) == division_id
                    and int(round_number) < int(current["round"])):
                return dict(current)
            if (current is not None and str(current["status"]) == "active"
                    and (int(current["season_id"]) != int(season_id)
                         or int(current["division_id"]) != division_id)):
                return dict(current)
            if (current is not None and str(current["status"]) == "active"
                    and int(current["campaign"]) > 1
                    and int(current["played"]) == 0
                    and int(current["round"]) == 1
                    and int(round_number) > 1):
                return dict(current)
            connection.execute(
                "INSERT INTO season_progress(persona_id,mode,season_id,"
                "division_id,round,"
                " data_version,user_data,progress_data_version,progress_data,"
                " campaign,played,won,drawn,lost,points,status,last_result,"
                " updated_at,version) VALUES(?,?,?,?,?,?,?,?,?,1,0,0,0,0,0,"
                " CASE WHEN ?<=1 THEN 'active' ELSE 'legacy' END,'',?,1)"
                " ON CONFLICT(persona_id,mode) DO UPDATE SET"
                " season_id=CASE WHEN season_progress.status='legacy'"
                " THEN excluded.season_id ELSE season_progress.season_id END,"
                " division_id=CASE WHEN season_progress.status='legacy'"
                " THEN excluded.division_id ELSE season_progress.division_id END,"
                " round=excluded.round,"
                " data_version=excluded.data_version,"
                " user_data=excluded.user_data,"
                " progress_data_version=excluded.progress_data_version,"
                " progress_data=excluded.progress_data,"
                " status=CASE"
                " WHEN season_progress.status='legacy'"
                "  AND excluded.round>1 THEN 'legacy'"
                " WHEN excluded.round<=1 THEN 'active'"
                " ELSE season_progress.status END,"
                " updated_at=excluded.updated_at,version=season_progress.version+1",
                (int(persona_id), season_mode, int(season_id), division_id,
                 max(1, int(round_number)), int(data_version), str(user_data),
                 int(progress_data_version), str(progress_data),
                 max(1, int(round_number)), int(time.time())))
        return self.load_season_progress(persona_id, season_mode) or {}

    def load_season_progress(
            self, persona_id: int,
            mode: str = SEASON_MODE_OFFLINE) -> dict | None:
        season_mode = self._season_mode(mode)
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM season_progress WHERE persona_id=? AND mode=?",
                (int(persona_id), season_mode)).fetchone()
        return dict(row) if row is not None else None

    def season_divisions(self, persona_id: int) -> tuple[int, int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT mode,division_id FROM season_progress"
                " WHERE persona_id=?", (int(persona_id),)).fetchall()
        values = {str(row["mode"]): int(row["division_id"]) for row in rows}
        return (values.get(SEASON_MODE_OFFLINE, 1),
                values.get(SEASON_MODE_ONLINE, 1))

    def save_squad(self, persona_id: int, squad: dict, squad_id: int = 1) -> None:
        name = squad.get("squadName")
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO squads(persona_id,squad_id,name,payload)"
                " VALUES(?,?,?,?)"
                " ON CONFLICT(persona_id,squad_id) DO UPDATE SET"
                "  payload=excluded.payload,"
                "  name=COALESCE(NULLIF(excluded.name,''), squads.name)",
                (int(persona_id), int(squad_id),
                 str(name) if name else None,
                 json.dumps(squad, separators=(",", ":"))),
            )

    def rename_squad(self, persona_id: int, squad_id: int, name: str) -> bool:
        if not name:
            return False
        with self._lock, closing(self._connect()) as connection, connection:
            changed = connection.execute(
                "UPDATE squads SET name=? WHERE persona_id=? AND squad_id=?",
                (str(name), int(persona_id), int(squad_id))).rowcount
            if not changed:
                connection.execute(
                    "INSERT INTO squads(persona_id,squad_id,name,payload)"
                    " VALUES(?,?,?,'{}')",
                    (int(persona_id), int(squad_id), str(name)))
        return True

    def squad_ids(self, persona_id: int) -> list:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT squad_id FROM squads WHERE persona_id=?"
                " ORDER BY squad_id", (int(persona_id),)).fetchall()
        return [int(row["squad_id"]) for row in rows]

    def squad_name(self, persona_id: int, squad_id: int):
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT name FROM squads WHERE persona_id=? AND squad_id=?",
                (int(persona_id), int(squad_id))).fetchone()
        return row["name"] if row and row["name"] else None

    def create_squad(self, persona_id: int, name: str = "") -> int:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(squad_id),1) AS n FROM squads"
                " WHERE persona_id=?", (int(persona_id),)).fetchone()
            squad_id = self._allocate_ids(
                connection, squad_id_counter(persona_id), 2,
                seed=max(1, int(row["n"])))
            connection.execute(
                "INSERT OR REPLACE INTO squads(persona_id,squad_id,name,payload)"
                " VALUES(?,?,?,'{}')",
                (int(persona_id), squad_id, str(name) if name else None))
        return squad_id

    def delete_squad(self, persona_id: int, squad_id: int) -> bool:
        if int(squad_id) <= 1:
            return False
        with self._lock, closing(self._connect()) as connection, connection:
            return connection.execute(
                "DELETE FROM squads WHERE persona_id=? AND squad_id=?",
                (int(persona_id), int(squad_id))).rowcount > 0

    def load_squad(self, persona_id: int, squad_id: int = 1) -> dict | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM squads WHERE persona_id=? AND squad_id=?",
                (int(persona_id), int(squad_id))
            ).fetchone()
        if row is None:
            return None
        squad = json.loads(row["payload"])
        if isinstance(squad.get("slots"), dict):
            squad["slots"] = {int(index): int(item_id)
                              for index, item_id in squad["slots"].items()}
        return squad


    @staticmethod
    def _normalise_sbc_squad(parsed: dict | None) -> dict:
        parsed = parsed if isinstance(parsed, dict) else {}
        slots = {}
        for raw_index, raw_item_id in (parsed.get("slots") or {}).items():
            try:
                index, item_id = int(raw_index), int(raw_item_id)
            except (TypeError, ValueError):
                continue
            if 0 <= index < 23 and item_id > 0:
                slots[index] = item_id
        return {
            "slots": slots,
            "rating": int(parsed.get("rating", 0) or 0),
            "chemistry": int(parsed.get("chemistry", 0) or 0),
            "formation": str(parsed.get("formation", "") or ""),
        }

    def save_sbc_squad(self, persona_id: int, challenge_id: int,
                       parsed: dict, repeatable: bool = False) -> None:
        persona_id, challenge_id = int(persona_id), int(challenge_id)
        self.ensure_persona(persona_id)
        squad = self._normalise_sbc_squad(parsed)
        item_ids = list(squad["slots"].values())
        if len(item_ids) != len(set(item_ids)):
            raise SbcValidationError("duplicate item id")
        with self._lock, closing(self._connect()) as connection, connection:
            if not repeatable and connection.execute(
                    "SELECT 1 FROM sbc_progress WHERE persona_id=?"
                    " AND challenge_id=?", (persona_id, challenge_id)).fetchone():
                raise SbcValidationError("challenge is already complete")
            if item_ids:
                marks = ",".join("?" for _ in item_ids)
                rows = connection.execute(
                    f"SELECT item_id,pile,item_type FROM items WHERE persona_id=?"
                    f" AND item_id IN ({marks})", [persona_id, *item_ids]).fetchall()
                found = {int(row["item_id"]): row for row in rows}
                missing = [item_id for item_id in item_ids if item_id not in found]
                if missing:
                    raise SbcValidationError("item is not owned")
                if any(str(found[item_id]["item_type"]) != "player"
                       for item_id in item_ids):
                    raise SbcValidationError("non-player item")
                if any(str(found[item_id]["pile"]) not in ("club", "squad")
                       for item_id in item_ids):
                    raise SbcValidationError("item is unavailable")
                listed = connection.execute(
                    f"SELECT 1 FROM trades WHERE persona_id=?"
                    f" AND item_id IN ({marks})"
                    " AND trade_state IN ('active','sold') LIMIT 1",
                    [persona_id, *item_ids]).fetchone()
                if listed is not None:
                    raise SbcValidationError("listed item")
            connection.execute(
                "INSERT INTO sbc_squads(persona_id,challenge_id,payload,updated_at)"
                " VALUES(?,?,?,?) ON CONFLICT(persona_id,challenge_id) DO UPDATE"
                " SET payload=excluded.payload,updated_at=excluded.updated_at",
                (persona_id, challenge_id, self._encode(squad), int(time.time())))

    def load_sbc_squad(self, persona_id: int, challenge_id: int) -> dict | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM sbc_squads WHERE persona_id=?"
                " AND challenge_id=?", (int(persona_id), int(challenge_id))
            ).fetchone()
        if row is None:
            return None
        try:
            return self._normalise_sbc_squad(json.loads(row["payload"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._normalise_sbc_squad({})

    def sbc_in_progress(self, persona_id: int) -> set[int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT challenge_id,payload FROM sbc_squads WHERE persona_id=?"
                " ORDER BY challenge_id", (int(persona_id),)).fetchall()
        started = set()
        for row in rows:
            try:
                squad = self._normalise_sbc_squad(json.loads(row["payload"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if squad["slots"]:
                started.add(int(row["challenge_id"]))
        return started

    def sbc_progress(self, persona_id: int) -> dict[int, int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT challenge_id,times_completed FROM sbc_progress"
                " WHERE persona_id=? ORDER BY challenge_id",
                (int(persona_id),)).fetchall()
        return {int(row["challenge_id"]): int(row["times_completed"])
                for row in rows}

    def sbc_tagged_sets(self, persona_id: int) -> set[int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT set_id FROM sbc_tags WHERE persona_id=?",
                (int(persona_id),)).fetchall()
        return {int(row["set_id"]) for row in rows}

    def set_sbc_tag(self, persona_id: int, set_id: int, tagged: bool) -> None:
        self.ensure_persona(int(persona_id))
        with self._lock, closing(self._connect()) as connection, connection:
            if tagged:
                connection.execute(
                    "INSERT INTO sbc_tags(persona_id,set_id,updated_at) VALUES(?,?,?)"
                    " ON CONFLICT(persona_id,set_id) DO UPDATE"
                    " SET updated_at=excluded.updated_at",
                    (int(persona_id), int(set_id), int(time.time())))
            else:
                connection.execute(
                    "DELETE FROM sbc_tags WHERE persona_id=? AND set_id=?",
                    (int(persona_id), int(set_id)))

    def unopened_pack_ids(self, persona_id: int) -> list[int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT pack_id FROM unopened_packs WHERE persona_id=?"
                " ORDER BY entitlement_id", (int(persona_id),)).fetchall()
        return [int(row["pack_id"]) for row in rows]

    def unopened_pack_count(self, persona_id: int, pack_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) FROM unopened_packs WHERE persona_id=?"
        params: list[object] = [int(persona_id)]
        if pack_id is not None:
            sql += " AND pack_id=?"
            params.append(int(pack_id))
        with self._lock, closing(self._connect()) as connection:
            return int(connection.execute(sql, params).fetchone()[0])

    def open_unopened_pack(self, persona_id: int, pack_id: int,
                           items: list[dict]) -> list[dict] | None:
        persona_id, pack_id = int(persona_id), int(pack_id)
        self.ensure_persona(persona_id)
        with self._lock, closing(self._connect()) as connection, connection:
            entitlement = connection.execute(
                "SELECT entitlement_id,untradeable FROM unopened_packs"
                " WHERE persona_id=? AND pack_id=? ORDER BY entitlement_id LIMIT 1",
                (persona_id, pack_id)).fetchone()
            if entitlement is None:
                return None
            if connection.execute(
                    "SELECT 1 FROM items WHERE persona_id=? AND pile='unassigned'"
                    " LIMIT 1", (persona_id,)).fetchone():
                raise ValueError("unassigned items must be resolved first")
            top = connection.execute(
                "SELECT MAX(m) AS top FROM ("
                " SELECT MAX(item_id) AS m FROM items WHERE persona_id=?"
                " UNION ALL SELECT high_water AS m FROM wallets WHERE persona_id=?)",
                (persona_id, persona_id)).fetchone()["top"]
            next_id = max(FIRST_PACK_ITEM_ID, int(top or 0) + 1)
            stored = []
            for source in items:
                item = dict(source)
                item["id"] = next_id
                next_id += 1
                if bool(entitlement["untradeable"]):
                    item["untradeable"] = True
                    item["discardValue"] = 0
                connection.execute(
                    "INSERT INTO items(persona_id,item_id,asset_id,pile,payload,"
                    "acquired_at,item_type) VALUES(?,?,?,?,?,?,?)",
                    (persona_id, int(item["id"]), int(item["assetId"]),
                     "unassigned", self._encode(item), int(time.time()),
                     str(item.get("itemType", "player"))))
                stored.append(item)
            connection.execute(
                "DELETE FROM unopened_packs WHERE entitlement_id=?",
                (int(entitlement["entitlement_id"]),))
            if stored:
                connection.execute(
                    "UPDATE wallets SET high_water=MAX(high_water,?) WHERE persona_id=?",
                    (next_id - 1, persona_id))
            return stored

    def _forget_items_in_sbc_squads(self, connection, persona_id: int,
                                    gone: set[int]) -> None:
        for row in connection.execute(
                "SELECT challenge_id,payload FROM sbc_squads WHERE persona_id=?",
                (int(persona_id),)).fetchall():
            try:
                squad = self._normalise_sbc_squad(json.loads(row["payload"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            kept = {index: item_id for index, item_id in squad["slots"].items()
                    if item_id not in gone}
            if len(kept) == len(squad["slots"]):
                continue
            squad["slots"] = kept
            connection.execute(
                "UPDATE sbc_squads SET payload=?,updated_at=?"
                " WHERE persona_id=? AND challenge_id=?",
                (self._encode(squad), int(time.time()), int(persona_id),
                 int(row["challenge_id"])))

    def complete_sbc(self, persona_id: int, definition: dict,
                     validator, rewards: dict | None = None) -> dict:
        persona_id = int(persona_id)
        challenge_id, set_id = (int(definition["id"]),
                                int(definition["setId"]))
        self.ensure_persona(persona_id)
        rewards = rewards if isinstance(rewards, dict) else {}
        repeatable = bool(definition.get("repeatable", False))
        with self._lock, closing(self._connect()) as connection, connection:
            prior = connection.execute(
                "SELECT times_completed FROM sbc_progress WHERE persona_id=?"
                " AND challenge_id=?", (persona_id, challenge_id)).fetchone()
            if prior is not None and not repeatable:
                balance = connection.execute(
                    "SELECT credits FROM wallets WHERE persona_id=?",
                    (persona_id,)).fetchone()
                return {"repeat": True, "timesCompleted": int(prior[0]),
                        "balance": int(balance[0]), "challengeCoins": 0,
                        "setCoins": 0, "setCompleted": False}

            saved = connection.execute(
                "SELECT payload FROM sbc_squads WHERE persona_id=?"
                " AND challenge_id=?", (persona_id, challenge_id)).fetchone()
            if saved is None:
                if prior is not None and repeatable:
                    balance = connection.execute(
                        "SELECT credits FROM wallets WHERE persona_id=?",
                        (persona_id,)).fetchone()
                    return {"repeat": True,
                            "timesCompleted": int(prior["times_completed"]),
                            "balance": int(balance[0]), "challengeCoins": 0,
                            "setCoins": 0, "setCompleted": False}
                raise SbcValidationError("no saved squad")
            try:
                squad = self._normalise_sbc_squad(json.loads(saved["payload"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise SbcValidationError("invalid saved squad")
            slots = squad["slots"]
            wanted = max(1, min(11, int(definition.get("players", 11))))
            if not set(range(wanted)) <= set(slots):
                raise SbcValidationError(
                    f"starting XI must contain exactly {wanted} players")
            item_ids = [slots[index] for index in range(wanted)]
            if len(set(item_ids)) != wanted:
                raise SbcValidationError("duplicate item id")
            marks = ",".join("?" for _ in item_ids)
            rows = connection.execute(
                f"SELECT item_id,pile,item_type,payload FROM items"
                f" WHERE persona_id=? AND item_id IN ({marks})",
                [persona_id, *item_ids]).fetchall()
            by_id = {int(row["item_id"]): row for row in rows}
            if len(by_id) != wanted:
                raise SbcValidationError("item is not owned")
            if any(str(by_id[item_id]["item_type"]) != "player"
                   for item_id in item_ids):
                raise SbcValidationError("non-player item")
            if any(str(by_id[item_id]["pile"]) not in ("club", "squad")
                   for item_id in item_ids):
                raise SbcValidationError("item is unavailable")
            if connection.execute(
                    f"SELECT 1 FROM trades WHERE persona_id=?"
                    f" AND item_id IN ({marks})"
                    " AND trade_state IN ('active','sold') LIMIT 1",
                    [persona_id, *item_ids]).fetchone() is not None:
                raise SbcValidationError("listed item")

            items_by_slot = {index: self._decode(by_id[slots[index]])
                             for index in range(wanted)}
            reported = {"rating": int(squad.get("rating", 0) or 0),
                        "chemistry": int(squad.get("chemistry", 0) or 0)}
            failures = list(validator(items_by_slot, reported) or [])
            if failures:
                raise SbcValidationError(failures)

            connection.execute(
                f"DELETE FROM items WHERE persona_id=? AND item_id IN ({marks})",
                [persona_id, *item_ids])
            gone = set(item_ids)
            self._forget_items_in_squads(connection, persona_id, gone)
            self._forget_items_in_sbc_squads(connection, persona_id, gone)
            connection.execute(
                "DELETE FROM sbc_squads WHERE persona_id=? AND challenge_id=?",
                (persona_id, challenge_id))
            now = int(time.time())
            times_completed = int(prior["times_completed"]) + 1 if prior else 1
            connection.execute(
                "INSERT INTO sbc_progress(persona_id,challenge_id,"
                "times_completed,completed_at) VALUES(?,?,?,?)"
                " ON CONFLICT(persona_id,challenge_id) DO UPDATE SET"
                " times_completed=excluded.times_completed,"
                " completed_at=excluded.completed_at",
                (persona_id, challenge_id, times_completed, now))

            challenge_coins = max(0, int(definition.get("rewardCoins", 0)))
            set_ids = [int(value) for value in definition["setChallengeIds"]]
            set_counts = []
            for value in set_ids:
                row = connection.execute(
                    "SELECT times_completed FROM sbc_progress WHERE persona_id=?"
                    " AND challenge_id=?", (persona_id, value)).fetchone()
                set_counts.append(int(row["times_completed"]) if row else 0)
            complete_cycles = min(set_counts, default=0)
            rewarded = connection.execute(
                "SELECT times_granted FROM sbc_set_rewards WHERE persona_id=?"
                " AND set_id=?", (persona_id, set_id)).fetchone()
            rewarded_cycles = int(rewarded["times_granted"]) if rewarded else 0
            grant_set = complete_cycles > rewarded_cycles
            set_coins = 0
            if grant_set:
                connection.execute(
                    "INSERT INTO sbc_set_rewards"
                    "(persona_id,set_id,times_granted,granted_at) VALUES(?,?,?,?)"
                    " ON CONFLICT(persona_id,set_id) DO UPDATE SET"
                    " times_granted=excluded.times_granted,"
                    " granted_at=excluded.granted_at",
                    (persona_id, set_id, complete_cycles, now))
                set_coins = max(0, int(definition.get("setRewardCoins", 0)))

            reward_items = list(rewards.get("challengeItems") or [])
            if grant_set:
                reward_items += list(rewards.get("setItems") or [])
            if reward_items:
                top = connection.execute(
                    "SELECT MAX(m) AS top FROM ("
                    " SELECT MAX(item_id) AS m FROM items WHERE persona_id=?"
                    " UNION ALL SELECT high_water AS m FROM wallets WHERE persona_id=?)",
                    (persona_id, persona_id)).fetchone()["top"]
                next_id = max(FIRST_PACK_ITEM_ID, int(top or 0) + 1)
                for source in reward_items:
                    item = dict(source)
                    item["id"] = next_id
                    next_id += 1
                    connection.execute(
                        "INSERT INTO items(persona_id,item_id,asset_id,pile,payload,"
                        "acquired_at,item_type) VALUES(?,?,?,?,?,?,?)",
                        (persona_id, int(item["id"]), int(item["assetId"]),
                         "unassigned", self._encode(item), now,
                         str(item.get("itemType", "player"))))
                connection.execute(
                    "UPDATE wallets SET high_water=MAX(high_water,?) WHERE persona_id=?",
                    (next_id - 1, persona_id))

            pack_rewards = list(rewards.get("challengePacks") or [])
            if grant_set:
                pack_rewards += list(rewards.get("setPacks") or [])
            if pack_rewards:
                first = self._allocate_ids(connection, "unopened_pack_id", 1,
                                           len(pack_rewards))
                for offset, pack in enumerate(pack_rewards):
                    if isinstance(pack, dict):
                        pack_id = int(pack["packId"])
                        untradeable = bool(pack.get("untradeable", False))
                    else:
                        pack_id, untradeable = int(pack), False
                    connection.execute(
                        "INSERT INTO unopened_packs(entitlement_id,persona_id,"
                        "pack_id,untradeable,source,granted_at) VALUES(?,?,?,?,?,?)",
                        (first + offset, persona_id, pack_id, int(untradeable),
                         "sbc", now))
            total = challenge_coins + set_coins
            transaction = self._apply_wallet_delta(
                connection, persona_id, "COINS", total,
                "sbc-challenge-complete", "sbc", challenge_id,
                f"sbc:{challenge_id}:completion:{times_completed}",
                metadata={"set_id": set_id,
                          "challenge_coins": challenge_coins,
                          "set_coins": set_coins,
                          "consumed_item_ids": item_ids})
            return {"repeat": False, "timesCompleted": times_completed,
                    "balance": int(transaction["balance_after"]),
                    "challengeCoins": challenge_coins,
                    "setCoins": set_coins, "setCompleted": bool(grant_set),
                    "consumedItemIds": item_ids}

    def save_clientdata(self, persona_id: int, name: str, entries: list) -> None:
        pairs = [{"key": int(entry.get("key", 0) or 0),
                  "value": int(entry.get("value", 0) or 0)}
                 for entry in entries or []
                 if isinstance(entry, dict)]
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO clientdata(persona_id,name,payload) VALUES(?,?,?)"
                " ON CONFLICT(persona_id,name)"
                " DO UPDATE SET payload=excluded.payload",
                (int(persona_id), str(name),
                 json.dumps(pairs, separators=(",", ":"))),
            )

    def load_clientdata(self, persona_id: int, name: str) -> list:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM clientdata WHERE persona_id=? AND name=?",
                (int(persona_id), str(name)),
            ).fetchone()
        return json.loads(row["payload"]) if row else []
