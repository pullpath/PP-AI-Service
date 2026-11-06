from __future__ import annotations


def test_health(client):
    r = client.get("/api/spy-hunt/health")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
