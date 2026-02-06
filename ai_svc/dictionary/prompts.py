"""
Dictionary service prompts for two-phase parallel architecture
Contains prompts for specialized agents
"""


def get_senses_discovery_prompt(word: str) -> str:
    """Generate prompt for Phase 1: Discover all word senses"""
    return f"""You are a linguistic analysis assistant focused on discovering commonly used word senses.

Analyze the word "{word}" and discover its distinct meanings/senses.

For each sense, provide a clear, concise definition.

Also provide:
- Pronunciation (IPA or simple phonetic guide)
- Headword (the word itself)

Order senses by frequency (most common first).

Output must be valid JSON matching the WordSensesDiscovery schema."""


def get_etymology_prompt(word: str) -> str:
    """Generate prompt for etymology information"""
    return f"""Provide etymology for "{word}":

1. Etymology: Origin, historical development, meaning evolution (2-3 sentences)
2. Root Analysis: Break down roots, prefixes, suffixes with meanings

Return valid JSON matching EtymologyInfo schema."""


def get_word_family_prompt(word: str) -> str:
    """Generate prompt for word family information"""
    return f"""You are a linguistic analyst specializing in word relationships.

Provide the word family for "{word}".

List 5-15 key words derived from the same root or sharing the same base.
Include:
- Direct derivatives (e.g., "happy" → "happiness", "unhappy")
- Related terms from same linguistic root
- Words in the same semantic field

IMPORTANT: Return ONLY a valid JSON object with this exact structure:
{{
    "word_family": ["word1", "word2", "word3"]
}}

Each word must be a simple string. Do not include explanations, examples, or additional formatting.
Ensure all strings are properly closed with quotes."""


def get_usage_context_prompt(word: str) -> str:
    """Generate prompt for usage context information"""
    return f"""Provide usage context for "{word}":

1. Modern Relevance: Current trends (e.g., "rising in tech", "outdated")
2. Common Confusions: Words confused with this (with brief differences)
3. Regional Variations: UK/US/AU differences

Return valid JSON matching UsageContextInfo schema."""


def get_cultural_notes_prompt(word: str) -> str:
    """Generate prompt for cultural and linguistic notes"""
    return f"""Provide cultural notes for "{word}":

Include cultural associations, historical significance, or sociolinguistic observations (2-3 sentences).

Return valid JSON matching CulturalNotesInfo schema."""


def get_frequency_prompt(word: str) -> str:
    """Generate prompt for frequency estimation"""
    return f"""Estimate frequency of "{word}" in modern English.

Choose: very_common (top 1000), common (top 5000), uncommon (top 20000), rare, or very_rare.

Return valid JSON matching FrequencyInfo schema."""


def get_enhanced_sense_prompt(word: str, sense_index: int, part_of_speech: str,
                              api_definitions: list, api_synonyms: list = [],
                              api_antonyms: list = [], api_examples: list = []) -> str:
    """Generate prompt for enhanced sense analysis (building on API data)"""
    return f""""{word}" ({part_of_speech}): {api_definitions[0] if api_definitions else ""}

Output JSON:
- definition, part_of_speech, usage_register, domain, tone, usage_notes, examples (3), collocations, word_specific_phrases, synonyms, antonyms"""


def get_detailed_sense_prompt(word: str, sense_index: int, basic_definition: str) -> str:
    """Generate prompt for detailed sense analysis (Phase 2)"""
    return f"""You are a linguistic expert analyzing specific word meanings.

Provide comprehensive analysis for sense #{sense_index + 1} of the word "{word}".

Basic definition: "{basic_definition}"

Provide detailed analysis including:
1. Refined definition for this specific sense
2. Part of speech
3. Usage register (formality level: formal, informal, colloquial, slang, archaic, literary, professional, academic, neutral)
4. Domain/field of use (e.g., biology, law, gaming, business)
5. Tone and connotations (positive, negative, neutral, humorous, derogatory, pejorative, approving)
6. Usage notes and common pitfalls for learners
7. 3-5 example sentences (include at least one corrected common learner error)
8. Common collocations (frequent word partners)
9. Related phrases/idioms built around this sense
10. Synonyms and antonyms for this specific sense

Focus on practical utility for language learners.

Output must be valid JSON matching the DetailedWordSense schema."""