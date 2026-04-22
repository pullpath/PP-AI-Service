"""
Dictionary service prompts for specialized agents
"""
from typing import List


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


def get_usage_context_skeleton_prompt(word: str) -> str:
    return f"""Provide usage context for "{word}":

1. Modern Relevance: Current trends (e.g., "rising in tech", "outdated")
2. Common Confusions: Return ONLY the bare word names commonly confused with "{word}" — no explanations, no parentheses, no sentences. Example: ["effect", "impact"]. Return 1-4 words maximum.
3. Regional Variations: Return a JSON object mapping region to usage, e.g. {{"US": "used broadly for any size", "UK": "typically a small mat", "AU": "similar to UK"}}. Only include regions with meaningful differences.

Return valid JSON matching UsageContextInfo schema."""


def get_confusion_meta_prompt(searched_word: str, confused_word: str) -> str:
    return f"""Classify the confusion between "{searched_word}" and "{confused_word}" for an English learner.

Return JSON matching ConfusionMeta schema:
confusion_type: near_homophone|semantic_overlap|spelling_similarity|false_friend|register_mismatch
quick_rule: short memorable rule (e.g. "Affect=verb, Effect=noun")
key_differentiator: one sentence most important distinction
difficulty: low|medium|high"""


def get_confusion_profiles_prompt(searched_word: str, confused_word: str) -> str:
    return f"""Generate side-by-side linguistic profiles for "{searched_word}" and "{confused_word}" to help learners distinguish them.

Return a JSON object with EXACTLY this structure (all fields required):
{{
  "searched_word": {{
    "core_meaning": "one-sentence essential meaning in the context of this confusion",
    "part_of_speech": "primary POS, e.g. noun / verb / adjective",
    "typical_domains": ["domain1", "domain2"],
    "collocations": ["collocation1", "collocation2"],
    "grammar_note": "key grammar constraint, or empty string if none"
  }},
  "confused_word": {{
    "core_meaning": "one-sentence essential meaning in the context of this confusion",
    "part_of_speech": "primary POS, e.g. noun / verb / adjective",
    "typical_domains": ["domain1", "domain2"],
    "collocations": ["collocation1", "collocation2"],
    "grammar_note": "key grammar constraint, or empty string if none"
  }}
}}

Fill in the values for "{searched_word}" (searched_word) and "{confused_word}" (confused_word).
Do NOT omit any field. part_of_speech is required for both."""


def get_confusion_examples_prompt(searched_word: str, confused_word: str) -> str:
    return f"""Provide usage examples and guidance for "{searched_word}" and "{confused_word}" to help learners use them correctly.

Return JSON matching ConfusionExamples schema with searched_word and confused_word each containing:
- example_sentences: 2 natural example sentences showing typical usage
- usage_note: 1-2 sentences of practical guidance on when and how to use this word correctly"""


def get_cultural_notes_prompt(word: str) -> str:
    """Generate prompt for cultural and linguistic notes"""
    return f"""Provide cultural notes for "{word}":

1. **historical_context**: Historical origin, evolution, and development of the word's cultural usage (1-2 sentences)
2. **cultural_associations**: List of 2-4 modern cultural contexts, media associations, or social domains where this word appears (e.g., "social media humor", "professional settings", "sitcoms and TV shows")
3. **social_perceptions**: List of 2-3 ways the word is perceived or interpreted in different contexts (e.g., "conveys intelligence", "may be perceived as rude", "shows wit and sarcasm")

Focus on helping learners understand the cultural and social dimensions of this word.

Return valid JSON matching CulturalNotesInfo schema."""


def get_frequency_prompt(word: str) -> str:
    """Generate prompt for frequency estimation"""
    return f"""Estimate frequency of "{word}" in modern English.

Choose: very_common (top 1000), common (top 5000), uncommon (top 20000), rare, or very_rare.

Return valid JSON matching FrequencyInfo schema."""


# 2-Agent Parallel Execution Prompts for DetailedWordSense
# These prompts split detailed sense generation into 2 concurrent tasks for optimal performance
def get_sense_core_metadata_prompt(word: str, sense_index: int, basic_definition: str) -> str:
    """Generate prompt for core metadata (Agent 1) - parallel execution
    
    Note: API always provides definition (not generated by AI)
    """
    return f"""You are a linguistic expert analyzing word meanings.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"

The definition is already provided by the API. Provide ONLY metadata analysis:

1. **part_of_speech**: e.g., noun, verb, phrasal verb, adjective, idiom, etc.
2. **usage_register**: List of appropriate contexts (formal, informal, colloquial, slang, archaic, literary, professional, academic, neutral)
3. **domain**: Specific fields of use (e.g., biology, law, gaming, business) - can be empty list
4. **tone**: Primary connotation (positive, negative, neutral, humorous, derogatory, pejorative, approving)

Focus on accuracy and clarity for language learners.

Output must be valid JSON matching the SenseCoreMetadata schema."""


def get_sense_usage_examples_prompt(word: str, sense_index: int, basic_definition: str,
                                   api_examples=None, examples_needed: int = 2, 
                                   collocations_needed: int = 3) -> str:
    """Generate prompt for examples and collocations (Agent 2) - parallel execution
    
    Dynamic counts based on API data availability:
    - examples_needed: Number of additional examples to generate (0-2)
    - collocations_needed: Number of collocations to generate (0-3)
    """
    api_examples = api_examples or []
    
    # Build dynamic context
    if api_examples:
        examples_context = f"\n\nAPI already provided {len(api_examples)} example(s): {api_examples}"
    else:
        examples_context = ""
    
    # Build dynamic instructions
    if examples_needed > 0:
        examples_instruction = f"1. **examples**: Exactly {examples_needed} additional example sentence(s) showing this sense in natural context"
    else:
        examples_instruction = "1. **examples**: Empty list (API already provided sufficient examples)"
    
    if collocations_needed > 0:
        collocations_instruction = f"2. **collocations**: Exactly {collocations_needed} most frequent word partner(s) (e.g., \"strong evidence\", \"gather evidence\")"
    else:
        collocations_instruction = "2. **collocations**: Empty list (not needed)"
    
    return f"""You are a linguistic expert specializing in language usage and examples.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"{examples_context}

Provide:
{examples_instruction}
{collocations_instruction}

Focus on practical, real-world usage for language learners.

Output must be valid JSON matching the SenseUsageExamples schema."""


def get_sense_related_words_prompt(word: str, sense_index: int, basic_definition: str,
                                   api_synonyms=None, api_antonyms=None,
                                   synonyms_needed: int = 3, antonyms_needed: int = 3,
                                   phrases_needed: int = 3) -> str:
    """Generate prompt for related words and phrases (Agent 3) - parallel execution
    
    Dynamic counts based on API data availability:
    - synonyms_needed: Number of additional synonyms to generate (0-3)
    - antonyms_needed: Number of additional antonyms to generate (0-3)
    - phrases_needed: Number of phrases to generate (0-3)
    """
    api_synonyms = api_synonyms or []
    api_antonyms = api_antonyms or []
    
    if api_synonyms:
        synonyms_context = f"\n\nAPI already provided {len(api_synonyms)} synonym(s): {api_synonyms}"
    else:
        synonyms_context = ""
    
    if api_antonyms:
        antonyms_context = f"\n\nAPI already provided {len(api_antonyms)} antonym(s): {api_antonyms}"
    else:
        antonyms_context = ""
    
    if synonyms_needed > 0:
        synonyms_instruction = f"1. **synonyms**: Exactly {synonyms_needed} additional most common synonym(s) for this specific sense"
    else:
        synonyms_instruction = "1. **synonyms**: Empty list (API already provided sufficient synonyms)"
    
    if antonyms_needed > 0:
        antonyms_instruction = f"2. **antonyms**: Exactly {antonyms_needed} additional most common antonym(s) for this specific sense (can be empty if none exist)"
    else:
        antonyms_instruction = "2. **antonyms**: Empty list (API already provided sufficient antonyms)"
    
    if phrases_needed > 0:
        phrases_instruction = f"3. **word_specific_phrases**: Exactly {phrases_needed} most common fixed expression(s), phrasal verb(s), or idiom(s) built around this sense (e.g., \"run up a bill\", \"in the long run\")"
    else:
        phrases_instruction = "3. **word_specific_phrases**: Empty list (not needed)"
    
    return f"""You are a linguistic expert specializing in word relationships.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"{synonyms_context}{antonyms_context}

Provide:
{synonyms_instruction}
{antonyms_instruction}
{phrases_instruction}

Focus on the most useful words/phrases that help learners expand vocabulary.

Output must be valid JSON matching the SenseRelatedWords schema."""


def get_common_phrases_prompt(word: str) -> str:
    """Generate prompt for common phrases - return 1-6 phrases"""
    return f"""You are a linguistic expert. For the word "{word}", return the 1-6 MOST COMMON phrases or collocations that native English speakers actually use.

CRITICAL RULES:
1. Each phrase MUST contain the exact word "{word}"
2. ONLY include phrases that are frequently used in real English
3. Prioritize: phrasal verbs > idioms > common collocations > standalone word

Good examples:
- For "run": ["run", "run out of", "in the long run", "run into", "run away", "run over"]
- For "take": ["take", "take care of", "take place", "take a look", "take advantage", "take time"]
- For "hello": ["hello"] (standalone, rarely in phrases)
- For "cat": ["cat"] (standalone, rarely in phrases)

Bad examples (NEVER do this):
- For "run": ["jogging", "sprint"] (synonyms, not phrases with "run")
- For "hello": ["hi there", "greetings"] (doesn't contain "hello")

Strategy:
1. If word is rarely used in phrases (like "hello", "cat", "table"), return just ["{word}"]
2. If word has common phrasal verbs or idioms, return up to 6 most frequent ones
3. Always include the standalone word as the first phrase

Return valid JSON: {{"phrases": ["phrase1", "phrase2", ...]}}"""


def get_sense_usage_notes_prompt(word: str, sense_index: int, basic_definition: str) -> str:
    return f"""You are a linguistic expert specializing in usage guidance for language learners.

Analyze sense #{sense_index + 1} of "{word}": "{basic_definition}"

Provide:
1. **usage_notes**: Critical guidance on when/how to use this sense and common pitfalls for learners (2-3 sentences)

Focus on practical advice that helps learners avoid mistakes.

Output must be valid JSON matching the SenseUsageNotes schema."""


def get_conversation_script_prompt(phrase: str, style: str = "kids_cartoon") -> str:
    style_contexts = {
        "kids_cartoon": {
            "setting": "bright, friendly children's environment (playground, home, school)",
            "characters": "2-3 cute cartoon characters (like Peppa Pig style)",
            "tone": "cheerful, simple, age-appropriate for 5-8 year olds",
            "complexity": "very simple vocabulary and short sentences"
        },
        "business_professional": {
            "setting": "professional workplace (office, meeting room, conference)",
            "characters": "2-3 business professionals in work attire",
            "tone": "professional, clear, suitable for workplace",
            "complexity": "professional vocabulary and complete sentences"
        },
        "realistic": {
            "setting": "everyday real-world location (cafe, park, home)",
            "characters": "2-3 people in casual daily situations",
            "tone": "natural, conversational, relatable",
            "complexity": "everyday vocabulary and natural speech patterns"
        },
        "anime": {
            "setting": "dynamic anime-style environment",
            "characters": "2-3 anime-style characters with expressive personalities",
            "tone": "engaging, energetic, expressive",
            "complexity": "varied vocabulary with emotion and expression"
        }
    }
    
    context = style_contexts.get(style, style_contexts["kids_cartoon"])
    
    return f"""You are an expert in educational content design and English language teaching.

Your task: Create a short, natural conversation that demonstrates the English phrase "{phrase}" in a clear, memorable context.

STYLE REQUIREMENTS:
- Setting: {context['setting']}
- Characters: {context['characters']}
- Tone: {context['tone']}
- Language complexity: {context['complexity']}

CRITICAL RULES:
1. The conversation MUST include the exact phrase "{phrase}" used naturally by one of the characters
2. The scenario should make the phrase's meaning obvious through context
3. Keep dialogue realistic and natural - avoid forced or artificial usage
4. 2-4 dialogue exchanges (each character speaks 1-2 times)
5. Each line should be short (1-2 sentences maximum)
6. The situation should be relatable and easy to visualize
7. Ensure the phrase is used correctly and appropriately for the style

OUTPUT FORMAT:
- scenario: 1-2 sentence description of the setting and situation
- dialogue: Array of {{character, text}} objects (2-6 lines total)
- phrase_explanation: 1 sentence explaining how the phrase is used in this context

EXAMPLES:

Phrase: "pipe down"
Style: kids_cartoon
{{
  "scenario": "At Peppa's playroom. George is being too loud while Daddy Pig is working.",
  "dialogue": [
    {{"character": "Daddy Pig", "text": "George, could you pipe down a bit? I'm trying to concentrate."}},
    {{"character": "George", "text": "Okay, Daddy. I'll play quietly."}},
    {{"character": "Peppa", "text": "Come on George, let's do a puzzle instead!"}}
  ],
  "phrase_explanation": "Pipe down means to be quiet or make less noise, used when someone is being too loud."
}}

Phrase: "break the ice"
Style: business_professional
{{
  "scenario": "First day at the office. Sarah joins a new team meeting.",
  "dialogue": [
    {{"character": "Manager", "text": "Welcome Sarah! Let's break the ice with a quick round of introductions."}},
    {{"character": "Sarah", "text": "Thank you! I'm excited to meet everyone."}},
    {{"character": "Colleague", "text": "I'll start - I'm Mike from the design team."}}
  ],
  "phrase_explanation": "Break the ice means to make people feel more comfortable in an awkward or formal situation."
}}

Now generate a conversation script for the phrase "{phrase}" in {style} style.

Output must be valid JSON matching the ConversationScript schema."""