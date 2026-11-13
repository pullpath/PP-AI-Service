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


def test_guest_preferred_lang_column_exists(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(guests)")}
    assert "preferred_lang" in cols


def test_room_results_tables_and_index_created(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"room_results", "room_result_players"} <= names
    idx = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_room_result_players_player" in idx


def test_room_results_schema_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(room_results)")}
    assert cols == {"room_id", "game_no", "finished_at", "winner", "lang", "roles_json", "words_json"}
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(room_result_players)")}
    assert cols == {"room_id", "game_no", "player_id", "seat", "role", "won", "credits_earned", "credit_parts"}


def test_old_guest_tokens_are_backfilled_into_sessions(conn):
    conn.execute(
        "INSERT INTO guests(player_id, token_hash, created_at) VALUES('p1','h1',0)"
    )
    conn.commit()
    db.init_db()
    row = conn.execute("SELECT player_id FROM sessions WHERE token_hash='h1'").fetchone()
    assert row["player_id"] == "p1"


def test_a_real_pre_migration_database_keeps_its_guests_signed_in(tmp_path, monkeypatch):
    """Build the old schema by hand (no sessions table, no email columns), then upgrade it."""
    import sqlite3
    from flask import Flask
    from ai_svc.spy_hunt import auth, spy_hunt_bp

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE guests(player_id TEXT PRIMARY KEY, token_hash TEXT, created_at INTEGER)")
    old.execute("INSERT INTO guests VALUES('legacy-pid', ?, 0)", (auth.hash_token("legacy-token"),))
    old.commit()
    old.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    db.close_conn()
    db.init_db()
    try:
        cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(guests)")}
        assert {"email", "password_hash"} <= cols
        app = Flask(__name__)
        app.register_blueprint(spy_hunt_bp)
        r = app.test_client().get("/api/spy-hunt/me", headers={"Authorization": "Bearer legacy-pid.legacy-token"})
        assert r.status_code == 200 and r.get_json() == {"email": None}
    finally:
        db.close_conn()
