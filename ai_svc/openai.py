from openai import OpenAI
from dotenv import load_dotenv
import os
from typing import List

load_dotenv()

openai_api_key = os.getenv('OPENAI_API_KEY')
openai_api_base = os.getenv('OPENAI_API_BASE')
openai_proxy_token = os.getenv('X-PP-TOKEN')

def audio_to_text(audio):
    client = OpenAI(
        api_key=openai_api_key, 
        base_url=openai_api_base, 
        default_headers={"x-pp-token": openai_proxy_token}
    )
    audio_file= open(audio, "rb")
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )
    return transcription.text

def _join_base_url(base_url):
    """Strip trailing slashes from base_url to avoid //chat/completions"""
    return base_url.rstrip('/') if base_url else base_url


def get_vision_provider():
    """Return (base_url, api_key, model) for AI_PROVIDER (default: openai).

    openai:   OPENAI_API_KEY / OPENAI_BASE_URL(falls back to the legacy OPENAI_API_BASE) / OPENAI_MODEL
    deepseek: DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
    """
    provider = (os.getenv('AI_PROVIDER') or 'openai').strip().lower()
    if provider == 'deepseek':
        return (
            _join_base_url(os.getenv('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com'),
            os.getenv('DEEPSEEK_API_KEY'),
            os.getenv('DEEPSEEK_MODEL') or 'deepseek-flash',
        )
    if provider != 'openai':
        raise ValueError(f"Unsupported AI_PROVIDER '{provider}', expected 'openai' or 'deepseek'")
    return (
        _join_base_url(os.getenv('OPENAI_BASE_URL') or openai_api_base),
        os.getenv('OPENAI_API_KEY') or openai_api_key,
        os.getenv('OPENAI_MODEL') or 'gpt-4o-mini',
    )


def vision(images: List[str], prompt_text: str, max_tokens: int = 500, provider: str = None):
    """Call a multimodal model. If provider is None, AI_PROVIDER decides.

    /api/image pins provider='openai'; /api/see passes None and follows AI_PROVIDER.
    """
    if provider == 'openai':
        base_url, api_key, model = (
            _join_base_url(openai_api_base), openai_api_key, 'gpt-4o-mini')
        is_openai = True
    else:
        base_url, api_key, model = get_vision_provider()
        is_openai = (os.getenv('AI_PROVIDER') or 'openai').strip().lower() == 'openai'

    # x-pp-token is only for our own OpenAI proxy; don't send it to DeepSeek
    headers = {"x-pp-token": openai_proxy_token} if is_openai else None
    client = OpenAI(api_key=api_key, base_url=base_url, default_headers=headers)

    PROMPT_MESSAGES = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                *map(lambda x: {"type": "image_url", "image_url": {"url": x}}, images)
            ],
        },
    ]

    result = client.chat.completions.create(
        messages=PROMPT_MESSAGES,
        model=model,
        max_tokens=max_tokens,
    )
    return result.choices[0].message.content
