from __future__ import annotations

import pytest
from flask import Flask

from ai_svc.spy_hunt import admin


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


def test_require_admin_allows_correct_token(temp_db, token):
    app = _app_with(lambda: ("ok", 200))
    r = app.test_client().get("/x", headers={"X-Admin-Token": "secret-xyz"})
    assert r.status_code == 200 and r.get_data(as_text=True) == "ok"
