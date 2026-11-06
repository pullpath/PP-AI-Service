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
