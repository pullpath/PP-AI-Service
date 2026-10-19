"""
Text-to-speech service for Hear the Color.
Turns a short description into natural-sounding speech with OpenAI's speech API.

Configuration:
  OPENAI_API_KEY        required
  OPENAI_BASE_URL       optional, e.g. a proxy when OpenAI is not reachable directly; default is the official
                        endpoint
  OPENAI_TTS_MODEL      optional, default gpt-4o-mini-tts
  OPENAI_TTS_VOICE      optional, default nova
It is independent of the vision provider (AI_PROVIDER) and ignores the legacy OPENAI_API_BASE / X-PP-TOKEN
proxy settings used by other routes.
"""
import logging
import os
from typing import Iterator

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "nova"
MAX_TEXT_LENGTH = 400
# Small chunks so the first audio reaches the browser as soon as OpenAI produces it
CHUNK_SIZE = 4096
# Only gpt-4o-* TTS models accept style instructions; tts-1 rejects the parameter
INSTRUCTIONS = "Speak warmly and calmly, like a kind guide describing a scene to a friend."


class TtsService:
    def __init__(self):
        load_dotenv()

    def stream(self, text: str) -> Iterator[bytes]:
        """Yield MP3 chunks for text as OpenAI generates them.

        MP3 is kept on purpose: it plays progressively in every browser (WAV/PCM are 5-10x larger and stream
        poorly in Safari). Provider errors are raised when the generator is first advanced.
        """
        model = os.getenv("OPENAI_TTS_MODEL") or DEFAULT_MODEL
        base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or DEFAULT_BASE_URL
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url)
        kwargs = {}
        if model.startswith("gpt-4o"):
            kwargs["instructions"] = INSTRUCTIONS
        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=os.getenv("OPENAI_TTS_VOICE") or DEFAULT_VOICE,
            input=text,
            response_format="mp3",
            **kwargs,
        ) as response:
            yield from response.iter_bytes(CHUNK_SIZE)
