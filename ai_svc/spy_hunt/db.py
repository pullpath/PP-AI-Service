from __future__ import annotations

import os
import sqlite3
import threading

DB_PATH = os.environ.get("SPY_HUNT_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "spy_hunt.db"
)

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS guests(
  player_id TEXT PRIMARY KEY, token_hash TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS rooms(
  id TEXT PRIMARY KEY, code TEXT UNIQUE, host_player_id TEXT, main_lang TEXT,
  config_json TEXT, status TEXT,
  phase TEXT, phase_deadline INTEGER, round INTEGER,
  pair_id TEXT, civ_is_a INTEGER, ai_calls INTEGER DEFAULT 0,
  game_no INTEGER DEFAULT 1,
  phase_seq INTEGER DEFAULT 0,
  winner TEXT, last_active INTEGER, created_at INTEGER, version INTEGER);
CREATE TABLE IF NOT EXISTS players(
  room_id TEXT, player_id TEXT, seat INTEGER, name TEXT, lang TEXT, is_bot INTEGER,
  bot_persona TEXT, role TEXT,
  alive INTEGER, connected INTEGER, joined_at INTEGER, PRIMARY KEY(room_id, seat));
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, game_no INTEGER, round INTEGER,
  stage INTEGER, seat INTEGER NULL,
  kind TEXT CHECK(kind IN ('statement','skipped','host')),
  text TEXT, lang TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS translations(
  message_id INTEGER, target_lang TEXT, text TEXT, PRIMARY KEY(message_id, target_lang));
CREATE TABLE IF NOT EXISTS votes(
  room_id TEXT, game_no INTEGER, round INTEGER, stage INTEGER, voter_seat INTEGER,
  target_seat INTEGER NULL,
  PRIMARY KEY(room_id, game_no, round, stage, voter_seat));
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, type TEXT, payload_json TEXT,
  audience TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS pairs(
  id TEXT PRIMARY KEY, concept_a TEXT, concept_b TEXT, difficulty INTEGER, theme TEXT,
  words_json TEXT, active INTEGER, plays INTEGER, spy_wins INTEGER);
CREATE TABLE IF NOT EXISTS room_pairs(room_id TEXT, pair_id TEXT);
CREATE TABLE IF NOT EXISTS guest_recent_pairs(player_id TEXT, pair_id TEXT, played_at INTEGER);
CREATE INDEX IF NOT EXISTS idx_events_room_seq ON events(room_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_room_id ON messages(room_id, id);
CREATE INDEX IF NOT EXISTS idx_rooms_status_active ON rooms(status, last_active);
"""


def get_conn() -> sqlite3.Connection:
    """Return this thread's connection, (re)opening it if DB_PATH changed."""
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == DB_PATH:
        return conn
    if conn is not None:
        conn.close()
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    _local.conn = conn
    _local.path = DB_PATH
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.path = None


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
