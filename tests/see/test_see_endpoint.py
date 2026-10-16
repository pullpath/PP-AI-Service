from unittest.mock import patch

import pytest

import app as app_module
from ai_svc.see import provider
from ai_svc.see.routes import rate_limiter, see_service


@pytest.fixture
def client():
    rate_limiter.reset()
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


def test_missing_image_returns_400(client):
    resp = client.post('/api/see', json={})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "missing image"}


def test_success_returns_text(client):
    with patch.object(see_service, 'describe', return_value='A fluffy orange cat') as m:
        resp = client.post('/api/see', json={"image": "AAAA"})
    assert resp.get_json() == {"text": "A fluffy orange cat"}
    m.assert_called_once_with("AAAA", "en")


def test_vision_error_returns_500(client):
    with patch.object(see_service, 'describe', side_effect=RuntimeError('boom')):
        resp = client.post('/api/see', json={"image": "AAAA"})
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "boom"}


def test_rate_limit(client):
    with patch.object(see_service, 'describe', return_value='x'):
        codes = [client.post('/api/see', json={"image": "A"}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


def test_provider_deepseek(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'k')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/')
    monkeypatch.delenv('DEEPSEEK_MODEL', raising=False)
    assert provider.get_vision_provider() == ('https://api.deepseek.com', 'k', 'deepseek-flash')


def test_provider_default_openai(monkeypatch):
    monkeypatch.delenv('AI_PROVIDER', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    assert provider.get_vision_provider()[2] == 'gpt-4o-mini'


def test_provider_unknown(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'nope')
    with pytest.raises(ValueError):
        provider.get_vision_provider()


def _fake_client(captured):
    class FakeClient:
        def __init__(self, **kwargs):
            captured['init'] = kwargs
            self.chat = type('C', (), {'completions': self})()

        def create(self, **kwargs):
            captured['create'] = kwargs
            msg = type('M', (), {'content': 'A red mug on a desk.'})()
            return type('R', (), {'choices': [type('Ch', (), {'message': msg})()]})()
    return FakeClient


def test_describe_deepseek_has_no_proxy_header(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'k')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        assert see_service.describe('AAAA') == 'A red mug on a desk.'
    assert captured['init']['default_headers'] is None
    assert captured['init']['base_url'] == 'https://api.deepseek.com'
    url = captured['create']['messages'][0]['content'][1]['image_url']['url']
    assert url == 'data:image/jpeg;base64,AAAA'


def test_describe_openai_sends_proxy_header(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('X-PP-TOKEN', 'tok')
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        see_service.describe('AAAA')
    assert captured['init']['default_headers'] == {'x-pp-token': 'tok'}
