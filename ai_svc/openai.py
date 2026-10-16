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
    """去掉 base_url 末尾的斜杠，避免拼接出 //chat/completions"""
    return base_url.rstrip('/') if base_url else base_url


def get_vision_provider():
    """根据 AI_PROVIDER 返回 (base_url, api_key, model)，默认 openai。

    openai:   OPENAI_API_KEY / OPENAI_BASE_URL(兼容旧的 OPENAI_API_BASE) / OPENAI_MODEL
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
    """调用多模态模型。provider 为空时按环境变量 AI_PROVIDER 选择。

    /api/image 不传 provider，始终沿用 OpenAI；/api/see 传 None 走 AI_PROVIDER。
    """
    if provider == 'openai':
        base_url, api_key, model = (
            _join_base_url(openai_api_base), openai_api_key, 'gpt-4o-mini')
        is_openai = True
    else:
        base_url, api_key, model = get_vision_provider()
        is_openai = (os.getenv('AI_PROVIDER') or 'openai').strip().lower() == 'openai'

    # x-pp-token 只是自己 OpenAI 代理用的头，不发给 DeepSeek
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
