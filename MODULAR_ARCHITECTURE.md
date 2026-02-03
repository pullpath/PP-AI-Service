# Modular Architecture Documentation

## Overview

The AI service has been refactored into a modular architecture with separate modules for schemas and prompts. This design improves maintainability, extensibility, and code organization.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     AI Service (app.py)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    │
│  │  Schemas    │    │   Prompts   │    │   Agents    │    │
│  │   Module    │◄──►│   Module    │◄──►│   Module    │    │
│  │             │    │             │    │             │    │
│  └─────────────┘    └─────────────┘    └─────────────┘    │
│         │                     │                     │      │
│         ▼                     ▼                     ▼      │
│  ┌─────────────────────────────────────────────────────┐  │
│  │                Agno Framework (LLM)                 │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Module Structure

### 1. Schemas Module (`ai_svc/schemas.py`)

Contains all Pydantic models for structured AI responses.

#### Key Models:

**DictionaryEntry** - Comprehensive dictionary entry
- `headword`: The requested word or phrase
- `pronunciation`: IPA transcription and phonetic guide
- `senses`: List of WordSense objects (multiple meanings)
- `etymology`: Word origin and history
- `frequency`: Usage frequency (FrequencyEnum)
- `modern_relevance`: Current usage trends
- `common_confusions`: Words often confused with this one
- `visual_mnemonic`: Memory aid suggestion
- `regional_variations`: Differences between English variants

**WordSense** - Individual word meaning
- `definition`: Core definition for this specific meaning
- `part_of_speech`: Noun, verb, adjective, etc.
- `usage_register`: Contexts (formal, informal, slang, etc.)
- `domain`: Fields of use (biology, law, gaming, etc.)
- `tone`: Emotional charge (ToneEnum)
- `usage_notes`: Guidance on when/how to use
- `examples`: 3-5 example sentences
- `collocations`: Frequent word partners
- `word_specific_phrases`: Fixed expressions and idioms
- `synonyms`: Close synonyms for this sense
- `antonyms`: Close antonyms for this sense

**Enums**:
- `ToneEnum`: POSITIVE, NEGATIVE, NEUTRAL, HUMOROUS, DEROGATORY, PEJORATIVE, APPROVING
- `FrequencyEnum`: VERY_HIGH, HIGH, MEDIUM, LOW, ARCHAIC_RARE

**Supporting Models**:
- `APIResponse`: Standard API response wrapper
- `SimpleDefinition`: Basic definition schema for simple use cases

### 2. Prompts Module (`ai_svc/prompts.py`)

Contains reusable prompt templates for different AI tasks.

#### Key Prompt Templates:

**DICTIONARY_PROMPT_TEMPLATE** - Comprehensive dictionary analysis
- Provides detailed instructions for lexicographers
- Requests structured JSON output matching DictionaryEntry schema
- Includes examples and formatting guidelines

**SIMPLE_DICTIONARY_PROMPT** - Basic dictionary lookup
- Simplified version for quick definitions
- Returns SimpleDefinition schema

**CHAT_PROMPT_TEMPLATE** - General chat conversations
- Flexible template for various chat scenarios

**OpenAI-Specific Prompts**:
- `AUDIO_TRANSCRIPTION_PROMPT`: Instructions for audio transcription
- `VISION_ANALYSIS_PROMPT`: Instructions for image analysis

#### Helper Functions:
- `get_dictionary_prompt(word)`: Formats dictionary prompt with word
- `get_simple_dictionary_prompt(word)`: Formats simple dictionary prompt
- `get_chat_prompt(user_message)`: Formats chat prompt

### 3. Agents Module (`ai_svc/dictionary_agent.py`)

Contains AI agents that use the schemas and prompts.

#### DictionaryAgent Features:
- Uses Agno framework with DeepSeek LLM
- Configured with `use_json_mode=True` for structured output
- `output_schema=DictionaryEntry` ensures type-safe responses
- Global instance `dictionary_agent` for easy access
- Backward compatible `lookup_word_sync()` method

## Benefits of Modular Architecture

### 1. **Maintainability**
- Centralized schemas: Update data structures in one place
- Centralized prompts: Modify AI instructions consistently
- Clear separation of concerns

### 2. **Extensibility**
- Easy to add new agent types using the same pattern
- New schemas can be added without modifying existing code
- Prompt templates can be extended for new use cases

### 3. **Type Safety**
- Pydantic models provide runtime validation
- IDE support with autocomplete and type hints
- Structured responses reduce parsing errors

### 4. **Consistency**
- Standardized prompt formatting
- Consistent response structures across endpoints
- Reusable components reduce code duplication

## Usage Examples

### Using the Dictionary Agent

```python
from ai_svc.dictionary_agent import dictionary_agent

# Look up a word
result = dictionary_agent.lookup_word("example")

if result.get("success"):
    # Access structured data
    headword = result.get("headword")
    pronunciation = result.get("pronunciation")
    senses = result.get("senses", [])
    
    for sense in senses:
        print(f"Definition: {sense.get('definition')}")
        print(f"Part of speech: {sense.get('part_of_speech')}")
        print(f"Examples: {sense.get('examples')}")
```

### Creating New Agents

```python
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from .schemas import YourSchema
from .prompts import get_your_prompt

class YourAgent:
    def __init__(self):
        self.agent = Agent(
            model=DeepSeek(id="deepseek-chat", api_key=api_key),
            use_json_mode=True,
            output_schema=YourSchema
        )
    
    def process(self, input_data):
        prompt = get_your_prompt(input_data)
        response = self.agent.run(prompt)
        return response.content.model_dump()
```

## API Endpoints

### Dictionary Endpoints
- `GET /api/dictionary/test` - Test endpoint
- `POST /api/dictionary` - Look up a word (requires JSON with "word" field)

### OpenAI Endpoints
- `GET /api/transcribe` - Audio transcription form
- `POST /api/transcribe` - Transcribe audio file
- `GET /api/vision` - Vision analysis form
- `POST /api/vision` - Analyze image file

## Testing

Run comprehensive tests:
```bash
source venv/bin/activate
python test_all_features.py
```

Test individual endpoint:
```bash
source venv/bin/activate
python test_endpoint.py
```

## Future Extensions

### Potential New Modules:
1. **Cache Module**: For caching frequent word lookups
2. **Rate Limiter Module**: For API rate limiting
3. **Metrics Module**: For tracking usage statistics
4. **Logging Module**: For structured logging

### Potential New Agents:
1. **GrammarAgent**: For grammar correction and analysis
2. **TranslationAgent**: For language translation
3. **SummarizationAgent**: For text summarization
4. **SentimentAgent**: For sentiment analysis

## Dependencies

- **Agno Framework**: Agent-driven LLM interactions
- **DeepSeek**: Primary LLM provider via Agno
- **OpenAI**: For audio transcription and vision analysis
- **Flask**: Web framework for API endpoints
- **Pydantic**: Data validation and serialization

## Configuration

Required environment variables:
- `DEEPSEEK_API_KEY`: DeepSeek API key
- `OPENAI_API_KEY`: OpenAI API key (for audio/vision)

## Conclusion

The modular architecture provides a solid foundation for building and extending AI services. The separation of schemas, prompts, and agents allows for clean code organization, easy maintenance, and straightforward extension for new features.