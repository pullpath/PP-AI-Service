from __future__ import annotations

import json
import threading

import pytest

from ai_svc.spy_hunt import puzzles
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.tests.puzzle_fixtures import sample_puzzle


def add(n=1):
    ids = []
    for i in range(n):
        public, answer = sample_puzzle()
        ids.append(puzzles.insert_ready(public, answer, 2, f"p-{i}"))
    return ids


def test_schema_has_puzzle_tables(temp_db):
    names = {r["name"] for r in get_conn().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"puzzles", "puzzle_results"} <= names


def test_utc_day_formats_the_date(temp_db):
    assert puzzles.utc_day(1794211514302) == "2026-11-09"
    assert puzzles.utc_day(0) == "1970-01-01"


def test_publish_assigns_oldest_ready_puzzle_once(temp_db):
    a, b = add(2)
    row = puzzles.publish_today("2026-11-10")
    assert row["id"] == a and row["number"] == 1
    assert puzzles.publish_today("2026-11-10")["id"] == a
    assert puzzles.ready_count() == 1
    nxt = puzzles.publish_today("2026-11-11")
    assert nxt["id"] == b and nxt["number"] == 2


def test_publish_returns_none_when_queue_empty(temp_db):
    assert puzzles.publish_today("2026-11-10") is None


def test_publish_skips_vetoed(temp_db):
    a, b = add(2)
    assert puzzles.veto(a) is True
    assert puzzles.publish_today("2026-11-10")["id"] == b


def test_veto_only_ready(temp_db):
    (a,) = add(1)
    puzzles.publish_today("2026-11-10")
    assert puzzles.veto(a) is False


def test_list_ready(temp_db):
    a, b = add(2)
    puzzles.veto(a)
    rows = puzzles.list_ready()
    assert [r["id"] for r in rows] == [b]
    assert {"id", "pair_id", "difficulty", "created_at"} <= set(rows[0])


def test_public_payload_has_no_answer(temp_db):
    add(1)
    payload = puzzles.public_payload(puzzles.publish_today("2026-11-10"))
    text = json.dumps(payload)
    for key in ("spy_seat", "option_index", "spy_word"):
        assert key not in text
    assert payload["number"] == 1 and payload["day"] == "2026-11-10"
    assert payload["difficulty"] == 2 and len(payload["statements"]) == 10


def test_concurrent_first_publish_assigns_one_puzzle(temp_db):
    add(3)
    out, errs = [], []

    def go():
        try:
            out.append(puzzles.publish_today("2026-11-10")["id"])
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errs and len(set(out)) == 1
    assert get_conn().execute(
        "SELECT COUNT(*) c FROM puzzles WHERE day='2026-11-10'").fetchone()["c"] == 1
