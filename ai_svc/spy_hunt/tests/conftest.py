from __future__ import annotations

import pytest
from flask import Flask

from ai_svc.spy_hunt import db
from ai_svc.spy_hunt import spy_hunt_bp


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = str(tmp_path / "test_spy_hunt.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.close_conn()
    db.init_db()
    yield path
    db.close_conn()


@pytest.fixture
def conn(temp_db):
    return db.get_conn()


@pytest.fixture
def client(temp_db):
    app = Flask(__name__)
    app.register_blueprint(spy_hunt_bp)
    app.testing = True
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_timers(monkeypatch):
    """No real timer thread in tests (one test opts in); clean scheduler state."""
    from ai_svc.spy_hunt import timers
    timers.reset()
    monkeypatch.setattr(timers, "THREAD_ENABLED", False)
    yield
    timers.reset()


@pytest.fixture(autouse=True)
def _reset_ratelimits():
    from ai_svc.spy_hunt import ratelimits
    ratelimits.reset_all()
    yield
    ratelimits.reset_all()


@pytest.fixture(autouse=True)
def _reset_translation(monkeypatch):
    """No real worker threads or network in tests: workers run inline, the fake
    LLM transport is on (no task registered -> LlmError), translation is unhooked."""
    from ai_svc.spy_hunt import fake_llm, game, workers
    monkeypatch.setenv("SPY_HUNT_FAKE_LLM", "1")
    fake_llm.reset()
    workers.reset()
    workers.set_synchronous(True)
    yield
    workers.reset()
    fake_llm.reset()
    game.set_on_message(None)
    try:
        from ai_svc.spy_hunt import translation
        translation.reset()
    except ImportError:
        pass
