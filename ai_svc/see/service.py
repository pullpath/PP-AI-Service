"""
Scene description service for Hear the Color.
Sends one camera frame to a multimodal LLM (OpenAI or DeepSeek) and returns a short description.
"""
import logging

from dotenv import load_dotenv
from openai import OpenAI

from .language import language_name, normalize_language
from .prompts import UNCHANGED_MARKER, get_see_prompt
from .provider import get_provider_name, get_vision_provider

logger = logging.getLogger(__name__)


class SeeService:
    """Describes a JPEG frame in one sentence via the provider selected by AI_PROVIDER."""

    def __init__(self):
        load_dotenv()

    def describe(self, image_b64: str, lang: str = "en") -> str:
        """Describe a base64 JPEG (WITHOUT the data: prefix) in the language of the BCP-47 tag lang.

        Raises on provider errors.
        """
        return self._ask(image_b64, lang, None)

    def describe_change(self, image_b64: str, lang: str, previous: str) -> tuple[str, bool]:
        """Describe only what is new compared to the earlier description `previous`.

        Returns (text, changed). changed is False when the model reports that nothing meaningful changed;
        the text is then empty. Raises on provider errors.
        """
        text = self._ask(image_b64, lang, previous)
        if text.strip().strip('."\'').upper() == UNCHANGED_MARKER:
            return "", False
        return text, True

    def _ask(self, image_b64: str, lang: str, previous: str | None) -> str:
        prompt = get_see_prompt(language_name(normalize_language(lang)), previous)
        base_url, api_key, model = get_vision_provider()
        # DeepSeek models reason by default, and the hidden reasoning tokens count against max_tokens, so a
        # small cap leaves an empty answer (finish_reason "length"). Turn thinking off, as the translation
        # service does; a one-sentence description doesn't need it.
        extra_body = {"thinking": {"type": "disabled"}} if get_provider_name() == "deepseek" else None

        client = OpenAI(api_key=api_key, base_url=base_url)
        result = client.chat.completions.create(
            model=model,
            max_tokens=300,
            extra_body=extra_body,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
        )
        choice = result.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            # Never return an empty description as a success
            raise RuntimeError(f"Model returned an empty description (finish_reason={choice.finish_reason})")
        return text
