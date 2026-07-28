"""
Translation service prompts
"""


def get_translation_prompt(text: str, target_lang: str) -> str:
    """Build a prompt that asks the LLM to translate text into the target language.

    Args:
        text: The text to translate.
        target_lang: BCP-47 language tag (e.g. "zh-cn", "ja", "es", "fr").

    Returns:
        Prompt string for the translation agent.
    """
    return (
        f"Translate the following text into the language identified by BCP-47 tag \"{target_lang}\".\n"
        "Return ONLY the translated text — no explanations, no quotes, no markdown, no extra punctuation.\n"
        "Preserve the original meaning and tone exactly.\n\n"
        f"Text to translate:\n{text}"
    )
