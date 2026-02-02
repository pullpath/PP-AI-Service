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

def vision(images: List[str], prompt_text: str):
    client = OpenAI(
        api_key=openai_api_key, 
        base_url=openai_api_base, 
        default_headers={"x-pp-token": openai_proxy_token}
    )
    PROMPT_MESSAGES = [
        {
            "role": "user",
            "content": [
                prompt_text,
                *map(lambda x: {"type": "image_url", "image_url": {"url": x}}, images)
            ],
        },
    ]

    result = client.chat.completions.create(
        messages=PROMPT_MESSAGES,
        model="gpt-4o-mini",
        max_tokens=500,
    )
    return result.choices[0].message.content