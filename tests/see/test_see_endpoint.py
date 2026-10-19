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


def test_provider_default_is_deepseek(monkeypatch):
    monkeypatch.delenv('AI_PROVIDER', raising=False)
    monkeypatch.delenv('DEEPSEEK_MODEL', raising=False)
    monkeypatch.delenv('DEEPSEEK_BASE_URL', raising=False)
    assert provider.get_vision_provider()[0] == 'https://api.deepseek.com'
    assert provider.get_vision_provider()[2] == 'deepseek-flash'


def test_openai_ignores_legacy_proxy_settings(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('OPENAI_API_BASE', 'https://proxy.example.com/v1')
    monkeypatch.delenv('OPENAI_BASE_URL', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    base_url, _, model = provider.get_vision_provider()
    assert base_url is None and model == 'gpt-4o-mini'


def test_provider_unknown(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'nope')
    with pytest.raises(ValueError):
        provider.get_vision_provider()


def _fake_client(captured, content='A red mug on a desk.'):
    class FakeClient:
        def __init__(self, **kwargs):
            captured['init'] = kwargs
            self.chat = type('C', (), {'completions': self})()

        def create(self, **kwargs):
            captured['create'] = kwargs
            msg = type('M', (), {'content': content})()
            return type('R', (), {'choices': [type('Ch', (), {'message': msg, 'finish_reason': 'length'})()]})()
    return FakeClient


def test_describe_deepseek_has_no_proxy_header(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'k')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        assert see_service.describe('AAAA') == 'A red mug on a desk.'
    assert 'default_headers' not in captured['init']
    assert captured['init']['base_url'] == 'https://api.deepseek.com'
    url = captured['create']['messages'][0]['content'][1]['image_url']['url']
    assert url == 'data:image/jpeg;base64,AAAA'


def test_describe_never_sends_proxy_header(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('X-PP-TOKEN', 'tok')
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        see_service.describe('AAAA')
    assert 'default_headers' not in captured['init']

def test_deepseek_disables_thinking(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'k')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        see_service.describe('AAAA')
    assert captured['create']['extra_body'] == {"thinking": {"type": "disabled"}}


def test_openai_has_no_extra_body(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        see_service.describe('AAAA')
    assert captured['create']['extra_body'] is None


def test_empty_model_reply_is_an_error(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    with patch('ai_svc.see.service.OpenAI', _fake_client({}, content='')):
        with pytest.raises(RuntimeError):
            see_service.describe('AAAA')



def test_include_audio_returns_text_and_audio(client):
    from ai_svc.tts.routes import tts_service
    with patch.object(see_service, 'describe', return_value='A red mug.'), \
         patch.object(tts_service, 'synthesize', return_value=b'ID3mp3') as tts:
        resp = client.post('/api/see', json={"image": "AAAA", "include_audio": True})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["text"] == 'A red mug.' and body["audio_format"] == 'mp3'
    import base64
    assert base64.b64decode(body["audio"]) == b'ID3mp3'
    tts.assert_called_once_with('A red mug.')


@pytest.mark.parametrize("flag", [None, False, "true", 1, "yes"])
def test_audio_only_for_json_true(client, flag):
    from ai_svc.tts.routes import tts_service
    payload = {"image": "AAAA"}
    if flag is not None:
        payload["include_audio"] = flag
    with patch.object(see_service, 'describe', return_value='x'), \
         patch.object(tts_service, 'synthesize') as tts:
        body = client.post('/api/see', json=payload).get_json()
    assert body == {"text": "x"}
    tts.assert_not_called()


def test_tts_failure_still_returns_text(client):
    from ai_svc.tts.routes import tts_service
    with patch.object(see_service, 'describe', return_value='A red mug.'), \
         patch.object(tts_service, 'synthesize', side_effect=RuntimeError('tts down')):
        resp = client.post('/api/see', json={"image": "AAAA", "include_audio": True})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body == {"text": "A red mug.", "audio_error": "tts down"}


def test_vision_failure_skips_tts(client):
    from ai_svc.tts.routes import tts_service
    with patch.object(see_service, 'describe', side_effect=RuntimeError('boom')), \
         patch.object(tts_service, 'synthesize') as tts:
        resp = client.post('/api/see', json={"image": "AAAA", "include_audio": True})
    assert resp.status_code == 500
    tts.assert_not_called()
