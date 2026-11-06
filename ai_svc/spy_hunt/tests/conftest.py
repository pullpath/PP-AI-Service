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
