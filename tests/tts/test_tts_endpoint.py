from unittest.mock import patch

import pytest

import app as app_module
from ai_svc.tts.routes import rate_limiter, tts_service


@pytest.fixture
def client():
    rate_limiter.reset()
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   "}, {"text": 5}])
def test_missing_text_returns_400(client, body):
    assert client.post('/api/speak', json=body).status_code == 400


def test_too_long_text_returns_400(client):
    assert client.post('/api/speak', json={"text": "a" * 401}).status_code == 400


def test_success_returns_audio(client):
    with patch.object(tts_service, 'synthesize', return_value=b'ID3audio') as m:
        resp = client.post('/api/speak', json={"text": " Hello there. "})
    assert resp.status_code == 200
    assert resp.mimetype == 'audio/mpeg'
    assert resp.data == b'ID3audio'
    m.assert_called_once_with("Hello there.")


def test_provider_error_returns_500(client):
    with patch.object(tts_service, 'synthesize', side_effect=RuntimeError('boom')):
        resp = client.post('/api/speak', json={"text": "hi"})
    assert resp.status_code == 500 and resp.get_json() == {"error": "boom"}


def test_rate_limit(client):
    with patch.object(tts_service, 'synthesize', return_value=b'x'):
        codes = [client.post('/api/speak', json={"text": "hi"}).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def _fake_client(captured):
    class Fake:
        def __init__(self, **kwargs):
            captured['init'] = kwargs
            self.audio = type('A', (), {'speech': self})()

        def create(self, **kwargs):
            captured['create'] = kwargs
            return type('R', (), {'content': b'mp3'})()
    return Fake


def test_service_uses_official_endpoint_and_ignores_proxy_settings(monkeypatch):
    for k in ('OPENAI_TTS_MODEL', 'OPENAI_TTS_VOICE'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('OPENAI_API_BASE', 'https://legacy-proxy.example.com')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://another-proxy.example.com')
    monkeypatch.setenv('X-PP-TOKEN', 'legacy')
    captured = {}
    with patch('ai_svc.tts.service.OpenAI', _fake_client(captured)):
        assert tts_service.synthesize('hi') == b'mp3'
    assert captured['init']['base_url'] == 'https://api.openai.com/v1'
    assert 'default_headers' not in captured['init']
    assert captured['create']['model'] == 'gpt-4o-mini-tts'
    assert captured['create']['voice'] == 'nova'
    assert 'instructions' in captured['create']


def test_tts1_has_no_instructions(monkeypatch):
    monkeypatch.setenv('OPENAI_TTS_MODEL', 'tts-1')
    captured = {}
    with patch('ai_svc.tts.service.OpenAI', _fake_client(captured)):
        tts_service.synthesize('hi')
    assert 'instructions' not in captured['create']
