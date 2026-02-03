"""
Dictionary service prompts for two-phase parallel architecture
Contains prompts for specialized agents
"""


def get_senses_discovery_prompt(word: str) -> str:
    """Generate prompt for Phase 1: Discover all word senses"""
    return f"""You are a linguistic analysis assistant focused on discovering ALL word senses.

Analyze the word "{word}" and discover ALL its distinct meanings/senses.

For each sense, provide:
1. A clear, concise definition
2. Part of speech (noun, verb, adjective, adverb, phrasal verb, idiom, etc.)
3. Primary tone/connotation - MUST be one of these exact values: positive, negative, neutral, humorous, derogatory, pejorative, approving
   - Do NOT use "archaic/rare" or any other values for tone
   - "archaic/rare" is for frequency, NOT tone

Also provide:
- Pronunciation (IPA or simple phonetic guide)
- Frequency in modern usage (very high/high/medium/low/archaic-rare)
- Headword (the word itself)

List ALL senses, not just the most common ones. Include rare, archaic, and specialized meanings.
Order senses by frequency (most common first).

CRITICAL: The "tone" field for each sense MUST be one of: positive, negative, neutral, humorous, derogatory, pejorative, approving
Do NOT use "archaic/rare" or any other values for tone.

Output must be valid JSON matching the WordSensesDiscovery schema."""


def get_etymology_prompt(word: str) -> str:
    """Generate prompt for etymology information"""
    return f"""You are a linguistic historian specializing in word origins.

Provide detailed etymology and root analysis for the word "{word}":

1. Etymology: Narrative of the word's origin, historical development, and meaning evolution.
2. Root Analysis: Breakdown of roots, prefixes, and suffixes with their meanings and origins.

Be comprehensive but focused on linguistic history.

Output must be valid JSON matching the EtymologyInfo schema."""


def get_word_family_prompt(word: str) -> str:
    """Generate prompt for word family information"""
    return f"""You are a linguistic analyst specializing in word relationships.

Provide the word family for "{word}":

List all key words derived from the same root or sharing the same base.
Include:
- Direct derivatives (e.g., "happy" → "happiness", "unhappy")
- Related terms from same linguistic root
- Words in the same semantic field

Focus on practical relationships that help language learners understand word connections.

Output must be valid JSON matching the WordFamilyInfo schema."""


def get_usage_context_prompt(word: str) -> str:
    """Generate prompt for usage context information"""
    return f"""You are a sociolinguist analyzing word usage patterns.

Provide modern usage context for the word "{word}":

1. Modern Relevance: Current usage trends, popularity changes, domain shifts
   (e.g., "rising in tech contexts", "considered outdated", "gaining informal use")

2. Common Confusions: Words/phrases often confused with this one
   Include brief discriminators explaining the differences

3. Regional Variations: Notable differences in meaning, spelling, or usage
   between English variants (American, British, Australian, etc.)

Focus on practical guidance for language learners.

Output must be valid JSON matching the UsageContextInfo schema."""


def get_cultural_notes_prompt(word: str) -> str:
    """Generate prompt for cultural and linguistic notes"""
    return f"""You are a cultural linguist providing contextual insights.

Provide cultural and linguistic notes for the word "{word}":

Include:
- Cultural associations, connotations, or sensitivities
- Historical or literary significance
- Sociolinguistic observations
- Any additional overarching notes about the word's place in language and culture

Be insightful but concise.

Output must be valid JSON matching the CulturalNotesInfo schema."""


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