"""
Standalone translation service.
Translates arbitrary text into a target language using DeepSeek LLM.
"""
import os
import time
import logging
from typing import Dict, Any

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from dotenv import load_dotenv

from .prompts import get_translation_prompt

load_dotenv()
logger = logging.getLogger(__name__)


class TranslationService:
    """Translates arbitrary text into a target language via DeepSeek."""

    def __init__(self):
        deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        no_thinking = {"thinking": {"type": "disabled"}}

        translation_model = DeepSeek(
            id="deepseek-v4-flash",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=1024,
            timeout=45.0,
            max_retries=0,
            extra_body=no_thinking,
        )

        self.agent = Agent(
            name="TranslationAgent",
            model=translation_model,
            description="Translates text into a target language",
        )

    def translate(self, text: str, target_lang: str) -> Dict[str, Any]:
        """Translate text into target_lang.

        Args:
            text: The text to translate.
            target_lang: BCP-47 language tag (e.g. "zh-cn", "ja", "es").

        Returns:
            {"success": True, "translation": "<translated text>"}
            or {"success": False, "error": "<message>"}
        """
        start = time.time()
        try:
            prompt = get_translation_prompt(text, target_lang)
            response = self.agent.run(prompt)
            # Extract plain-text content from the agent response
            translation = response.content
            if isinstance(translation, list):
                # agno may return a list of content blocks
                translation = "".join(
                    block.text if hasattr(block, "text") else str(block)
                    for block in translation
                )
            translation = translation.strip()
            logger.info(
                f"[translate] '{target_lang}' in {time.time() - start:.2f}s "
                f"({len(text)} chars → {len(translation)} chars)"
            )
            return {"success": True, "translation": translation}
        except Exception as e:
            logger.warning(f"[translate] Failed for target_lang='{target_lang}': {e}")
            return {"success": False, "error": str(e)}
