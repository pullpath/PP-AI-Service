"""
Scene description service for Hear the Color.
Sends one camera frame to a multimodal LLM (OpenAI or DeepSeek) and returns a short description.
"""
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

from .prompts import SEE_PROMPT
from .provider import get_provider_name, get_vision_provider

logger = logging.getLogger(__name__)


class SeeService:
    """Describes a JPEG frame in one sentence via the provider selected by AI_PROVIDER."""

    def __init__(self):
        load_dotenv()

    def describe(self, image_b64: str) -> str:
        """Describe a base64 JPEG (WITHOUT the data: prefix). Raises on provider errors."""
        base_url, api_key, model = get_vision_provider()
        # x-pp-token is only for our own OpenAI proxy; don't send it to DeepSeek
        headers = None
        if get_provider_name() == "openai":
            headers = {"x-pp-token": os.getenv("X-PP-TOKEN")}

        client = OpenAI(api_key=api_key, base_url=base_url, default_headers=headers)
        result = client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": SEE_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
        )
        return result.choices[0].message.content
