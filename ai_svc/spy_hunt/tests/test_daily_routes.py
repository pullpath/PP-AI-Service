from __future__ import annotations

import json

import pytest

from ai_svc.spy_hunt import puzzles
from ai_svc.spy_hunt.tests.puzzle_fixtures import sample_puzzle


def guest(client):
    g = client.post("/api/spy-hunt/guests").get_json()
    return {"Authorization": f"Bearer {g['player_id']}.{g['token']}"}


def seed():
    public, answer = sample_puzzle(2)
    puzzles.insert_ready(public, answer, 2, "p-x")


def test_daily_requires_guest_token(client):
    seed()
    for method, path in (("get", "/daily"), ("post", "/daily/guess"), ("post", "/daily/word"),
                         ("get", "/daily/result")):
        r = getattr(client, method)("/api/spy-hunt" + path)
        assert r.status_code == 401, path


def test_get_daily_returns_puzzle_without_answer(client):
    seed()
    h = guest(client)
    body = client.get("/api/spy-hunt/daily", headers=h).get_json()
    options = body["puzzle"].pop("options")
    text = json.dumps(body, ensure_ascii=False)
    for needle in ("spy_seat", "spy_word", "option_index", "organ", "风琴"):
        assert needle not in text, needle
    assert len(options) == 4 and body["me"]["stage"] == "spy"


def test_wrong_guess_response_has_no_answer(client):
    seed()
    h = guest(client)
    client.get("/api/spy-hunt/daily", headers=h)
    r = client.post("/api/spy-hunt/daily/guess", json={"spy_seat": 0}, headers=h)
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    for needle in ("organ", "风琴", "option_index", "spy_word"):
        assert needle not in text
    assert r.get_json()["correct"] is False


def test_full_happy_path(client):
    seed()
    h = guest(client)
    client.get("/api/spy-hunt/daily", headers=h)
    g = client.post("/api/spy-hunt/daily/guess", json={"spy_seat": 2}, headers=h).get_json()
    assert g["correct"] is True and g["stage"] == "word"
    w = client.post("/api/spy-hunt/daily/word", json={"option": 0}, headers=h).get_json()
    assert w == {"correct": True, "stage": "done"}
    r = client.get("/api/spy-hunt/daily/result", headers=h).get_json()
    assert r["solved"] is True and r["word_correct"] is True and r["score"] >= 120


def test_no_ready_puzzle_is_503_with_error_code(client):
    h = guest(client)
    r = client.get("/api/spy-hunt/daily", headers=h)
    assert r.status_code == 503 and r.get_json()["error"] == "no_puzzle"


@pytest.mark.parametrize("path,code", [("/daily/guess", "bad_seat"), ("/daily/word", "bad_option")])
def test_missing_key_is_400(client, path, code):
    seed()
    h = guest(client)
    client.get("/api/spy-hunt/daily", headers=h)
    client.post("/api/spy-hunt/daily/guess", json={"spy_seat": 2}, headers=h)
    r = client.post("/api/spy-hunt" + path, json={}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == code


def test_result_before_finish_is_409(client):
    seed()
    h = guest(client)
    client.get("/api/spy-hunt/daily", headers=h)
    r = client.get("/api/spy-hunt/daily/result", headers=h)
    assert r.status_code == 409 and r.get_json()["error"] == "not_finished"
