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

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "nova"
MAX_TEXT_LENGTH = 400
# Only gpt-4o-* TTS models accept style instructions; tts-1 rejects the parameter
INSTRUCTIONS = "Speak warmly and calmly, like a kind guide describing a scene to a friend."


class TtsService:
    def __init__(self):
        load_dotenv()

    def synthesize(self, text: str) -> bytes:
        """Return MP3 bytes for text. Raises on provider errors."""
        model = os.getenv("OPENAI_TTS_MODEL") or DEFAULT_MODEL
        base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or DEFAULT_BASE_URL
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url)
        kwargs = {}
        if model.startswith("gpt-4o"):
            kwargs["instructions"] = INSTRUCTIONS
        result = client.audio.speech.create(
            model=model,
            voice=os.getenv("OPENAI_TTS_VOICE") or DEFAULT_VOICE,
            input=text,
            response_format="mp3",
            **kwargs,
        )
        return result.content
