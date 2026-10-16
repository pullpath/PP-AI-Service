from unittest.mock import patch

import pytest

import app as app_module
from ai_svc import openai as ai_openai


@pytest.fixture
def client():
    app_module._see_hits.clear()
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


def test_missing_image_returns_400(client):
    resp = client.post('/api/see', json={})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "missing image"}


def test_success_builds_data_url(client):
    with patch.object(app_module.openai, 'vision', return_value='一只橘猫') as m:
        resp = client.post('/api/see', json={"image": "AAAA"})
    assert resp.get_json() == {"text": "一只橘猫"}
    assert m.call_args.kwargs['images'] == ["data:image/jpeg;base64,AAAA"]


def test_vision_error_returns_500(client):
    with patch.object(app_module.openai, 'vision', side_effect=RuntimeError('boom')):
        resp = client.post('/api/see', json={"image": "AAAA"})
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "boom"}


def test_rate_limit(client):
    with patch.object(app_module.openai, 'vision', return_value='x'):
        codes = [client.post('/api/see', json={"image": "A"}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


def test_provider_deepseek(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'k')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/')
    monkeypatch.delenv('DEEPSEEK_MODEL', raising=False)
    assert ai_openai.get_vision_provider() == ('https://api.deepseek.com', 'k', 'deepseek-flash')


def test_provider_default_openai(monkeypatch):
    monkeypatch.delenv('AI_PROVIDER', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    assert ai_openai.get_vision_provider()[2] == 'gpt-4o-mini'


def test_provider_unknown(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'nope')
    with pytest.raises(ValueError):
        ai_openai.get_vision_provider()
