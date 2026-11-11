from __future__ import annotations

from ai_svc.spy_hunt import db

TABLES = {"guests", "rooms", "players", "messages", "translations", "votes",
          "events", "pairs", "room_pairs", "guest_recent_pairs"}


def test_tables_created(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_indexes_created(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_events_room_seq", "idx_messages_room_id", "idx_rooms_status_active"} <= names


def test_wal(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_init_twice(conn):
    db.init_db()
    db.init_db()


def test_row_factory_and_per_thread(conn):
    import threading
    assert db.get_conn() is conn
    other = []
    t = threading.Thread(target=lambda: other.append(db.get_conn()))
    t.start(); t.join()
    assert other[0] is not conn


def test_sessions_table_and_guest_columns_exist(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert cols == {"token_hash", "player_id", "created_at"}
    guest_cols = {r["name"] for r in conn.execute("PRAGMA table_info(guests)")}
    assert {"email", "password_hash"} <= guest_cols


def test_old_guest_tokens_are_backfilled_into_sessions(conn):
    conn.execute(
        "INSERT INTO guests(player_id, token_hash, created_at) VALUES('p1','h1',0)"
    )
    conn.commit()
    db.init_db()
    row = conn.execute("SELECT player_id FROM sessions WHERE token_hash='h1'").fetchone()
    assert row["player_id"] == "p1"
