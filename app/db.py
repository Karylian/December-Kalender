"""SQLite-persistentie: één bestand, schema-migraties via ``PRAGMA user_version``."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("DK_DB_PATH", "data/december-kalender.db"))

# Elke entry is één migratie; voeg nieuwe alleen achteraan toe.
MIGRATIONS = [
    """
    CREATE TABLE users (
        id         INTEGER PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE calendars (
        id           INTEGER PRIMARY KEY,
        ruleset_code TEXT NOT NULL,
        label        TEXT NOT NULL,
        serial       TEXT,
        created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
        version      INTEGER NOT NULL DEFAULT 0,
        paid_out     INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE boxes (
        calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        day         INTEGER NOT NULL,
        symbol_key  TEXT NOT NULL,
        updated_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (calendar_id, day)
    );

    -- Bedragen van feestdagspellen (day = 5/25/26/31) en extra spellen (day = NULL, game >= 1).
    CREATE TABLE game_amounts (
        calendar_id  INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        kind         TEXT NOT NULL CHECK (kind IN ('holiday', 'extra')),
        game         INTEGER NOT NULL,
        slot         INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL,
        PRIMARY KEY (calendar_id, kind, game, slot)
    );

    CREATE TABLE activity_log (
        id          INTEGER PRIMARY KEY,
        calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        message     TEXT NOT NULL
    );
    CREATE INDEX activity_log_calendar ON activity_log (calendar_id, id);
    """,
    # 2: afronden zonder symbolen (alleen het resultaat) en zoeken op serienummer
    """
    ALTER TABLE calendars ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'done'));
    ALTER TABLE calendars ADD COLUMN done_total_cents INTEGER;
    ALTER TABLE calendars ADD COLUMN done_at TEXT;
    ALTER TABLE calendars ADD COLUMN done_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
    CREATE INDEX calendars_serial ON calendars (ruleset_code, serial);
    """,
]


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
