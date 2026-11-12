from __future__ import annotations

import threading

import pytest
from flask import Flask

from ai_svc.spy_hunt import admin, puzzles
from ai_svc.spy_hunt.tests.puzzle_fixtures import sample_puzzle


def _seed(n):
    for i in range(n):
        puzzles.insert_ready(*sample_puzzle(), 2, f"p-{i}")


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secret-xyz")
    return "secret-xyz"


def _app_with(view):
    app = Flask(__name__)
    app.add_url_rule("/x", "x", admin.require_admin(view))
    app.testing = True
    return app


def test_require_admin_rejects_missing_header(temp_db, token):
    app = _app_with(lambda: ("ok", 200))
    assert app.test_client().get("/x").status_code == 401


def test_require_admin_rejects_wrong_token(temp_db, token):
    app = _app_with(lambda: ("ok", 200))
    assert app.test_client().get("/x", headers={"X-Admin-Token": "nope"}).status_code == 401


def test_require_admin_rejects_empty_token(temp_db, token):
    app = _app_with(lambda: ("ok", 200))
    assert app.test_client().get("/x", headers={"X-Admin-Token": ""}).status_code == 401


def test_require_admin_rejects_non_ascii_token(temp_db, token):
    # Werkzeug decodes header values as latin-1, so a client can send a non-ASCII
    # byte. hmac.compare_digest on str raises on non-ASCII; must 401, not 500.
    app = _app_with(lambda: ("ok", 200))
    assert app.test_client().get("/x", headers={"X-Admin-Token": "\xe9"}).status_code == 401


def test_require_admin_allows_correct_token(temp_db, token):
    app = _app_with(lambda: ("ok", 200))
    r = app.test_client().get("/x", headers={"X-Admin-Token": "secret-xyz"})
    assert r.status_code == 200 and r.get_data(as_text=True) == "ok"


def test_status_reports_counts(temp_db, token):
    _seed(2)
    out = admin.admin_status()
    assert out == {"ready_count": 2, "total_count": 2, "refilling": False}


def test_start_refill_runs_fill_queue(temp_db, token, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(admin.puzzle_gen, "fill_queue",
                        lambda **k: calls.__setitem__("n", calls["n"] + 1) or 1)
    assert admin.start_refill() == {"started": True}
    assert calls["n"] == 1           # ran inline (workers synchronous in tests)
    assert admin.admin_status()["refilling"] is False  # flag cleared after


def test_double_refill_does_not_double_run(temp_db, token, monkeypatch):
    # fill_queue blocks until released; with the pool async, the flag is
    # observably set when the 2nd call lands.
    started, release = threading.Event(), threading.Event()

    def slow(**k):
        started.set()
        release.wait(2)
        return 0

    monkeypatch.setattr(admin.puzzle_gen, "fill_queue", slow)
    admin.workers.set_synchronous(False)  # real background thread
    try:
        r1 = admin.start_refill()
        assert started.wait(2)
        r2 = admin.start_refill()
    finally:
        release.set()
    assert r1 == {"started": True}
    assert r2 == {"started": False, "refilling": True}


def test_flag_cleared_when_fill_queue_raises(temp_db, token, monkeypatch):
    def boom(**k):
        raise RuntimeError("x")

    monkeypatch.setattr(admin.puzzle_gen, "fill_queue", boom)
    admin.start_refill()
    assert admin.admin_status()["refilling"] is False


HDR = {"X-Admin-Token": "secret-xyz"}


def test_status_route_requires_token(client, token):
    assert client.get("/api/spy-hunt/admin/status").status_code == 401


def test_status_route_returns_counts(client, token):
    _seed(1)
    r = client.get("/api/spy-hunt/admin/status", headers=HDR)
    assert r.status_code == 200 and r.get_json()["ready_count"] == 1


def test_refill_route_starts(client, token, monkeypatch):
    monkeypatch.setattr(admin.puzzle_gen, "fill_queue", lambda **k: 0)
    r = client.post("/api/spy-hunt/admin/refill", headers=HDR)
    assert r.status_code == 200 and r.get_json() == {"started": True}


def test_refill_route_requires_token(client, token):
    assert client.post("/api/spy-hunt/admin/refill").status_code == 401
