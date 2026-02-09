"""
Dictionary service prompts for two-phase parallel architecture
Contains prompts for specialized agents
"""
from typing import List


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


# 4-Agent Parallel Execution Prompts for DetailedWordSense
# These prompts split detailed sense generation into 4 concurrent tasks for optimal performance
def get_sense_core_metadata_prompt(word: str, sense_index: int, basic_definition: str) -> str:
    """Generate prompt for core metadata (Agent 1) - parallel execution"""
    return f"""You are a linguistic expert analyzing word meanings.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"

Provide:
1. **definition**: Refined, clear definition for this specific sense
2. **part_of_speech**: e.g., noun, verb, phrasal verb, adjective, idiom, etc.
3. **usage_register**: List of appropriate contexts (formal, informal, colloquial, slang, archaic, literary, professional, academic, neutral)
4. **domain**: Specific fields of use (e.g., biology, law, gaming, business) - can be empty list
5. **tone**: Primary connotation (positive, negative, neutral, humorous, derogatory, pejorative, approving)

Focus on accuracy and clarity for language learners.

Output must be valid JSON matching the SenseCoreMetadata schema."""


def get_sense_usage_examples_prompt(word: str, sense_index: int, basic_definition: str, 
                                   api_examples=None) -> str:
    """Generate prompt for examples and collocations (Agent 2) - parallel execution"""
    api_examples = api_examples or []
    examples_context = f"\n\nAPI provided examples: {api_examples}" if api_examples else ""
    
    return f"""You are a linguistic expert specializing in language usage and examples.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"{examples_context}

Provide:
1. **examples**: Exactly 3 example sentences showing this sense in natural context
2. **collocations**: Exactly 3 most frequent word partners (e.g., "strong evidence", "gather evidence")

Focus on practical, real-world usage for language learners.

Output must be valid JSON matching the SenseUsageExamples schema."""


def get_sense_related_words_prompt(word: str, sense_index: int, basic_definition: str,
                                   api_synonyms=None, api_antonyms=None) -> str:
    """Generate prompt for related words and phrases (Agent 3) - parallel execution"""
    api_synonyms = api_synonyms or []
    api_antonyms = api_antonyms or []
    synonyms_context = f"\n\nAPI provided synonyms: {api_synonyms}" if api_synonyms else ""
    antonyms_context = f"\n\nAPI provided antonyms: {api_antonyms}" if api_antonyms else ""
    
    return f"""You are a linguistic expert specializing in word relationships.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"{synonyms_context}{antonyms_context}

Provide:
1. **synonyms**: Exactly 3 most common synonyms for this specific sense
2. **antonyms**: Exactly 3 most common antonyms for this specific sense (can be empty list if none exist)
3. **word_specific_phrases**: Exactly 3 most common fixed expressions, phrasal verbs, or idioms built around this sense (e.g., "run up a bill", "in the long run")

Focus on the most useful words/phrases that help learners expand vocabulary.

Output must be valid JSON matching the SenseRelatedWords schema."""


def get_sense_usage_notes_prompt(word: str, sense_index: int, basic_definition: str) -> str:
    """Generate prompt for usage notes and guidance (Agent 4) - parallel execution"""
    return f"""You are a linguistic expert specializing in usage guidance for language learners.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"

Provide:
1. **usage_notes**: Critical guidance on when/how to use this sense and common pitfalls for learners (2-3 sentences)

Focus on practical advice that helps learners avoid mistakes.

Output must be valid JSON matching the SenseUsageNotes schema."""