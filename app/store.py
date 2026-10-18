"""Database-queries. Elke schrijfactie verhoogt ``calendars.version`` en logt wie wat deed."""

from __future__ import annotations

import sqlite3
from collections import defaultdict


# --- gebruikers -------------------------------------------------------------

def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users ORDER BY name").fetchall()


def get_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_or_create_user(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    with conn:
        conn.execute("INSERT OR IGNORE INTO users (name) VALUES (?)", (name,))
    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()


# --- kalenders --------------------------------------------------------------

def list_calendars(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT c.*, u.name AS created_by_name
           FROM calendars c LEFT JOIN users u ON u.id = c.created_by
           ORDER BY c.created_at DESC, c.id DESC"""
    ).fetchall()


def get_calendar(conn: sqlite3.Connection, calendar_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT c.*, u.name AS created_by_name
           FROM calendars c LEFT JOIN users u ON u.id = c.created_by
           WHERE c.id = ?""",
        (calendar_id,),
    ).fetchone()


def create_calendar(
    conn: sqlite3.Connection, ruleset_code: str, label: str, serial: str | None, user_id: int
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO calendars (ruleset_code, label, serial, created_by) VALUES (?, ?, ?, ?)",
            (ruleset_code, label, serial or None, user_id),
        )
        _log(conn, cur.lastrowid, user_id, "Kalender aangemaakt")
    return cur.lastrowid


def delete_calendar(conn: sqlite3.Connection, calendar_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM calendars WHERE id = ?", (calendar_id,))


def _touch(conn: sqlite3.Connection, calendar_id: int) -> None:
    conn.execute(
        "UPDATE calendars SET version = version + 1, updated_at = datetime('now') WHERE id = ?",
        (calendar_id,),
    )


def _log(conn: sqlite3.Connection, calendar_id: int, user_id: int | None, message: str) -> None:
    conn.execute(
        "INSERT INTO activity_log (calendar_id, user_id, message) VALUES (?, ?, ?)",
        (calendar_id, user_id, message),
    )


def set_paid_out(conn: sqlite3.Connection, calendar_id: int, paid: bool, user_id: int) -> None:
    with conn:
        conn.execute("UPDATE calendars SET paid_out = ? WHERE id = ?", (int(paid), calendar_id))
        _touch(conn, calendar_id)
        _log(conn, calendar_id, user_id, "Gemarkeerd als uitbetaald" if paid else "Uitbetaald-markering verwijderd")


def reset_calendar(conn: sqlite3.Connection, calendar_id: int, user_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM boxes WHERE calendar_id = ?", (calendar_id,))
        conn.execute("DELETE FROM game_amounts WHERE calendar_id = ?", (calendar_id,))
        conn.execute("UPDATE calendars SET paid_out = 0 WHERE id = ?", (calendar_id,))
        _touch(conn, calendar_id)
        _log(conn, calendar_id, user_id, "Kalender gereset (alle vakjes en spellen gewist)")


# --- vakjes en spellen ------------------------------------------------------

def get_boxes(conn: sqlite3.Connection, calendar_id: int) -> dict[int, str]:
    rows = conn.execute(
        "SELECT day, symbol_key FROM boxes WHERE calendar_id = ?", (calendar_id,)
    ).fetchall()
    return {r["day"]: r["symbol_key"] for r in rows}


def set_box(
    conn: sqlite3.Connection,
    calendar_id: int,
    day: int,
    symbol_key: str | None,
    user_id: int,
    message: str,
) -> None:
    with conn:
        if symbol_key is None:
            conn.execute("DELETE FROM boxes WHERE calendar_id = ? AND day = ?", (calendar_id, day))
        else:
            conn.execute(
                """INSERT INTO boxes (calendar_id, day, symbol_key, updated_by) VALUES (?, ?, ?, ?)
                   ON CONFLICT (calendar_id, day) DO UPDATE SET
                     symbol_key = excluded.symbol_key,
                     updated_by = excluded.updated_by,
                     updated_at = datetime('now')""",
                (calendar_id, day, symbol_key, user_id),
            )
        _touch(conn, calendar_id)
        _log(conn, calendar_id, user_id, message)


def get_amounts(conn: sqlite3.Connection, calendar_id: int, kind: str) -> dict[int, dict[int, int]]:
    rows = conn.execute(
        "SELECT game, slot, amount_cents FROM game_amounts WHERE calendar_id = ? AND kind = ?",
        (calendar_id, kind),
    ).fetchall()
    result: dict[int, dict[int, int]] = defaultdict(dict)
    for r in rows:
        result[r["game"]][r["slot"]] = r["amount_cents"]
    return dict(result)


def set_game_amounts(
    conn: sqlite3.Connection,
    calendar_id: int,
    kind: str,
    game: int,
    amounts: list[int | None],
    user_id: int,
    message: str,
) -> None:
    with conn:
        conn.execute(
            "DELETE FROM game_amounts WHERE calendar_id = ? AND kind = ? AND game = ?",
            (calendar_id, kind, game),
        )
        conn.executemany(
            "INSERT INTO game_amounts (calendar_id, kind, game, slot, amount_cents) VALUES (?, ?, ?, ?, ?)",
            [(calendar_id, kind, game, slot, a) for slot, a in enumerate(amounts) if a is not None],
        )
        _touch(conn, calendar_id)
        _log(conn, calendar_id, user_id, message)


# --- logboek ----------------------------------------------------------------

def get_log(conn: sqlite3.Connection, calendar_id: int, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT l.*, u.name AS user_name
           FROM activity_log l LEFT JOIN users u ON u.id = l.user_id
           WHERE l.calendar_id = ? ORDER BY l.id DESC LIMIT ?""",
        (calendar_id, limit),
    ).fetchall()


def clear_log(conn: sqlite3.Connection, calendar_id: int, user_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM activity_log WHERE calendar_id = ?", (calendar_id,))
        _log(conn, calendar_id, user_id, "Logboek gewist")


# --- export -----------------------------------------------------------------

def export_all(conn: sqlite3.Connection) -> dict:
    tables = ["users", "calendars", "boxes", "game_amounts", "activity_log"]
    return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tables}
