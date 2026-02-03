"""
Prompts module for AI service
Contains prompt templates for different AI tasks
"""

# Dictionary Agent Prompt Template
DICTIONARY_PROMPT_TEMPLATE = """
**Task:** Create a comprehensive "Word Context Mastery Guide" for the given word or phrase.

**Objective:** Generate a structured JSON output containing all the linguistic and contextual information outlined below. Focus on clarity, accuracy, and practical utility for language learners.

**Output Instructions:**
1.  **Populate all fields.** If information for a non-essential field is genuinely unavailable or inapplicable (e.g., `regional_variations` for a very standard word), use an empty list `[]` or an empty string `""`.
2.  **List Format:** For fields like `senses`, `word_family`, `collocations`, etc., provide ordered lists, with the most common/relevant items first.
3.  **Tone & Style:** Write explanations in clear, instructive English. Be prescriptive about usage (e.g., "This is typically used in...", "Avoid using this in formal writing because...").
4.  **Multiple Senses:** If the word has multiple distinct meanings, create a separate object for each within the `senses` list. Each sense should have its own `definition`, `part_of_speech`, `usage_register`, `tone`, `examples`, etc. Top-level fields (like `etymology`, `pronunciation`) apply to the word as a whole, unless a sense has a *different* etymology (e.g., "bank" of a river vs. "bank" financial institution), in which case note it in that sense's `notes` field.
5.  **Output Strictly:** You must output only a valid JSON object that conforms to the provided schema. Do not include any introductory text, explanations, or markdown formatting outside the JSON.

**Word/Phrase to Analyze: {user_query}**
"""


# Simple Dictionary Prompt (for basic lookups)
SIMPLE_DICTIONARY_PROMPT = """
Provide clear, concise definitions for words.

Always respond in valid JSON format with the following structure:
{{
    "word": "[the word being defined]",
    "definition": "[clear definition]",
    "examples": ["[example 1]", "[example 2]"],
    "synonyms": ["[synonym 1]", "[synonym 2]"],
    "antonyms": ["[antonym 1]", "[antonym 2]"],
    "etymology": "[brief etymology if known]",
    "part_of_speech": "[noun/verb/adjective/etc]"
}}

Word to define: {word}
"""


# Audio Transcription Prompt
AUDIO_TRANSCRIPTION_PROMPT = """
Please transcribe the following audio content accurately.
Include timestamps if available and note any unclear sections.
"""


# Vision Analysis Prompt
VISION_ANALYSIS_PROMPT = """
Analyze the provided image(s) and describe what you see.
Be detailed and objective in your description.
"""


# Chat Completion Prompt Template
CHAT_PROMPT_TEMPLATE = """
Respond to the user's query in a clear, informative, and helpful manner.

User query: {query}
"""


def get_dictionary_prompt(word: str) -> str:
    """Get formatted dictionary prompt for a specific word"""
    return DICTIONARY_PROMPT_TEMPLATE.format(user_query=word)


def get_simple_dictionary_prompt(word: str) -> str:
    """Get simple dictionary prompt for basic lookups"""
    return SIMPLE_DICTIONARY_PROMPT.format(word=word)


def get_chat_prompt(query: str) -> str:
    """Get formatted chat prompt for a specific query"""
    return CHAT_PROMPT_TEMPLATE.format(query=query)