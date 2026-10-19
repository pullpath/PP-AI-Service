from unittest.mock import patch

import pytest

import app as app_module
from ai_svc.tts.routes import rate_limiter, tts_service


@pytest.fixture(autouse=True)
def fresh_client():
    # The service caches its OpenAI client; drop it so each test sees its own fake
    tts_service._client = None


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


def _stream(*chunks):
    def gen(_text):
        yield from chunks
    return gen


@pytest.mark.parametrize("method", ["get", "post"])
def test_success_streams_audio(client, method):
    calls = []
    def gen(text):
        calls.append(text)
        yield b'ID3'
        yield b'audio'
    with patch.object(tts_service, 'stream', side_effect=gen):
        if method == "get":
            resp = client.get('/api/speak', query_string={"text": " Hello there. "})
        else:
            resp = client.post('/api/speak', json={"text": " Hello there. "})
        data = resp.get_data()
    assert resp.status_code == 200 and resp.mimetype == 'audio/mpeg'
    assert resp.headers['X-Accel-Buffering'] == 'no'
    assert data == b'ID3audio' and calls == ["Hello there."]


def test_get_missing_text_returns_400(client):
    assert client.get('/api/speak').status_code == 400


def test_provider_error_returns_500(client):
    def gen(_text):
        raise RuntimeError('boom')
        yield b''
    with patch.object(tts_service, 'stream', side_effect=gen):
        resp = client.post('/api/speak', json={"text": "hi"})
    assert resp.status_code == 500 and resp.get_json() == {"error": "boom"}


def test_empty_audio_returns_500(client):
    with patch.object(tts_service, 'stream', side_effect=_stream()):
        resp = client.post('/api/speak', json={"text": "hi"})
    assert resp.status_code == 500 and resp.get_json() == {"error": "empty audio"}


def test_rate_limit(client):
    with patch.object(tts_service, 'stream', side_effect=_stream(b'x')):
        codes = [client.post('/api/speak', json={"text": "hi"}).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def _fake_client(captured):
    class Streamed:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_bytes(self, _size):
            yield b'mp'
            yield b'3'

    class Fake:
        def __init__(self, **kwargs):
            captured['init'] = kwargs
            self.audio = type('A', (), {'speech': type('S', (), {'with_streaming_response': self})()})()

        def create(self, **kwargs):
            captured['create'] = kwargs
            return Streamed()
    return Fake


def test_service_uses_official_endpoint_and_ignores_proxy_settings(monkeypatch):
    for k in ('OPENAI_BASE_URL', 'OPENAI_TTS_MODEL', 'OPENAI_TTS_VOICE'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('OPENAI_API_BASE', 'https://legacy-proxy.example.com')
    monkeypatch.setenv('X-PP-TOKEN', 'legacy')
    captured = {}
    with patch('ai_svc.tts.service.OpenAI', _fake_client(captured)):
        assert b''.join(tts_service.stream('hi')) == b'mp3'
    assert captured['init']['base_url'] == 'https://api.openai.com/v1'
    assert 'default_headers' not in captured['init']
    assert captured['create']['model'] == 'gpt-4o-mini-tts'
    assert captured['create']['voice'] == 'nova'
    assert 'instructions' in captured['create']


def test_tts1_has_no_instructions(monkeypatch):
    monkeypatch.setenv('OPENAI_TTS_MODEL', 'tts-1')
    captured = {}
    with patch('ai_svc.tts.service.OpenAI', _fake_client(captured)):
        b''.join(tts_service.stream('hi'))
    assert 'instructions' not in captured['create']


@pytest.mark.parametrize("value,expected", [
    ("https://proxy.example.com/v1", "https://proxy.example.com/v1"),
    ("https://proxy.example.com/v1/", "https://proxy.example.com/v1"),
    ("  ", "https://api.openai.com/v1"),
    ("", "https://api.openai.com/v1"),
])
def test_tts_base_url_override(monkeypatch, value, expected):
    monkeypatch.setenv('OPENAI_BASE_URL', value)
    captured = {}
    with patch('ai_svc.tts.service.OpenAI', _fake_client(captured)):
        b''.join(tts_service.stream('hi'))
    assert captured['init']['base_url'] == expected


def test_client_is_reused_and_rebuilt_on_config_change(monkeypatch):
    monkeypatch.delenv('OPENAI_BASE_URL', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'k1')
    created = []
    real = _fake_client({})
    def counting(**kwargs):
        created.append(kwargs)
        return real(**kwargs)
    with patch('ai_svc.tts.service.OpenAI', side_effect=counting):
        b''.join(tts_service.stream('a'))
        b''.join(tts_service.stream('b'))
        assert len(created) == 1
        monkeypatch.setenv('OPENAI_BASE_URL', 'https://proxy.example.com/v1')
        b''.join(tts_service.stream('c'))
    assert len(created) == 2 and created[1]['base_url'] == 'https://proxy.example.com/v1'


def test_synthesize_joins_stream_and_rejects_empty(monkeypatch):
    with patch.object(tts_service, 'stream', side_effect=_stream(b'ab', b'cd')):
        assert tts_service.synthesize('hi') == b'abcd'
    with patch.object(tts_service, 'stream', side_effect=_stream()):
        with pytest.raises(RuntimeError):
            tts_service.synthesize('hi')
