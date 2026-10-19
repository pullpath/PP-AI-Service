from unittest.mock import patch

import pytest

import app as app_module
from ai_svc.see.prompts import get_see_prompt
from ai_svc.see.routes import rate_limiter, see_service
from tests.see.test_see_endpoint import _fake_client


@pytest.fixture
def client():
    rate_limiter.reset()
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


def test_prompt_without_previous_is_unchanged():
    assert get_see_prompt("English", None) == get_see_prompt("English")
    assert "UNCHANGED" not in get_see_prompt("English")


def test_prompt_with_previous_asks_only_for_what_is_new():
    p = get_see_prompt("English", "A red mug on a desk.")
    assert "A red mug on a desk." in p
    assert "UNCHANGED" in p
    assert "only what is new" in p
    # The earlier text is data, never instructions
    assert "not instructions" in p


def test_describe_change_returns_changed_true_for_a_normal_reply(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    with patch('ai_svc.see.service.OpenAI', _fake_client({}, content='Now a person stands on your left.')):
        assert see_service.describe_change('AAAA', 'en', 'A red mug.') == ('Now a person stands on your left.', True)


def test_describe_change_detects_the_unchanged_marker(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    with patch('ai_svc.see.service.OpenAI', _fake_client({}, content='UNCHANGED')):
        text, changed = see_service.describe_change('AAAA', 'en', 'A red mug.')
    assert changed is False


def test_describe_change_sends_previous_in_the_prompt(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    captured = {}
    with patch('ai_svc.see.service.OpenAI', _fake_client(captured)):
        see_service.describe_change('AAAA', 'en', 'A red mug.')
    assert 'A red mug.' in captured['create']['messages'][0]['content'][0]['text']


def test_no_previous_keeps_the_old_response_shape(client):
    with patch.object(see_service, 'describe', return_value='A cat.') as m:
        resp = client.post('/api/see', json={"image": "AAAA"})
    assert resp.get_json() == {"text": "A cat."}
    m.assert_called_once_with("AAAA", "en")


def test_previous_returns_changed_flag(client):
    with patch.object(see_service, 'describe_change', return_value=('A dog.', True)) as m:
        resp = client.post('/api/see', json={"image": "AAAA", "previous": "A cat."})
    assert resp.get_json() == {"text": "A dog.", "changed": True}
    m.assert_called_once_with("AAAA", "en", "A cat.")


def test_unchanged_reply_has_changed_false(client):
    with patch.object(see_service, 'describe_change', return_value=('', False)):
        resp = client.post('/api/see', json={"image": "AAAA", "previous": "A cat."})
    assert resp.get_json()["changed"] is False


def test_non_string_previous_is_ignored(client):
    with patch.object(see_service, 'describe', return_value='x') as plain, \
         patch.object(see_service, 'describe_change') as change:
        resp = client.post('/api/see', json={"image": "AAAA", "previous": 123})
    assert resp.get_json() == {"text": "x"}
    plain.assert_called_once()
    change.assert_not_called()


def test_long_previous_is_truncated_to_300_chars(client):
    with patch.object(see_service, 'describe_change', return_value=('y', True)) as m:
        client.post('/api/see', json={"image": "AAAA", "previous": "z" * 10000})
    assert len(m.call_args.args[2]) == 300


def test_no_speech_is_generated_for_an_unchanged_reply(client):
    from ai_svc.tts.service import tts_service
    with patch.object(see_service, 'describe_change', return_value=('', False)), \
         patch.object(tts_service, 'synthesize', return_value=b'ID3') as tts:
        resp = client.post('/api/see', json={"image": "AAAA", "previous": "A cat.", "include_audio": True})
    tts.assert_not_called()
    assert "audio" not in resp.get_json()


def test_audio_is_generated_for_a_changed_reply(client):
    from ai_svc.tts.service import tts_service
    with patch.object(see_service, 'describe_change', return_value=('A dog.', True)), \
         patch.object(tts_service, 'synthesize', return_value=b'ID3') as tts:
        resp = client.post('/api/see', json={"image": "AAAA", "previous": "A cat.", "include_audio": True})
    tts.assert_called_once()
    assert resp.get_json()["audio_format"] == "mp3"
