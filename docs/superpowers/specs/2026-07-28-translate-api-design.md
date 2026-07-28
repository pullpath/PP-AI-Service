# Design: Standalone Translation API

**Date:** 2026-07-28  
**Status:** Approved

## Problem

The WOTD frontend (and other consumers) need to translate arbitrary example sentences into a target language. The dictionary service's existing translation layer is tightly coupled to word lookup data structures and is not suitable for general-purpose sentence translation. No standalone translation endpoint exists today.

## Goal

Add a `POST /api/translate` endpoint that accepts a text string and a target language code, and returns the translated text using the DeepSeek LLM.

## Architecture

### New module: `ai_svc/translation/`

Two files following the same pattern as `ai_svc/dictionary/`:

| File | Responsibility |
|------|----------------|
| `ai_svc/translation/service.py` | `TranslationService` class — DeepSeek agent instantiated once at startup, `translate()` method called per request |
| `ai_svc/translation/prompts.py` | `get_translation_prompt(text, target_lang)` — builds the LLM prompt |

### Flask route in `app.py`

- `TranslationService` instantiated at app startup alongside `dictionary_service`
- `POST /api/translate` handler validates input, calls `translation_service.translate()`, returns JSON

## API Contract

### Request

```
POST /api/translate
Content-Type: application/json
```

```json
{
  "text": "She scrubbed the floor until it gleamed.",
  "target_lang": "zh-cn"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | yes | The text to translate. May be a word, phrase, or sentence. |
| `target_lang` | string | yes | BCP-47 language tag for the target language (e.g. `zh-cn`, `ja`, `es`, `fr`, `de`). |

### Response (success, HTTP 200)

```json
{
  "text": "She scrubbed the floor until it gleamed.",
  "target_lang": "zh-cn",
  "translation": "她把地板擦得闪闪发光。",
  "execution_time": 1.23,
  "success": true
}
```

### Response (validation error, HTTP 400)

```json
{
  "error": "Missing 'text' parameter in request body",
  "success": false
}
```

### Response (translation failure, HTTP 500)

```json
{
  "error": "Translation failed: <reason>",
  "success": false
}
```

## Data Flow

```
POST /api/translate
  → app.py: validate (text, target_lang present, non-empty)
  → TranslationService.translate(text, target_lang)
      → build prompt via get_translation_prompt()
      → DeepSeek agent.run(prompt)
      → parse plain-text response
  → return JSON response
```

## TranslationService

```python
class TranslationService:
    def __init__(self):
        self.agent = Agent(
            model=DeepSeek(id="deepseek-chat", api_key=...),
            # no response_model — translation is free-form text
        )

    def translate(self, text: str, target_lang: str) -> Dict[str, Any]:
        # returns {"success": True, "translation": "..."} or {"success": False, "error": "..."}
```

- Agent uses no `response_model` (translation output is a plain string, not structured JSON)
- Agent response content is extracted and returned as `translation`
- Exceptions are caught and returned as `{"success": False, "error": str(e)}`

## Prompt Design

The prompt instructs the model to:
1. Translate the given text into the specified target language
2. Return **only** the translated text — no explanations, no markdown, no quotes
3. Preserve the original meaning and tone

## Error Handling

| Condition | HTTP status | Response |
|-----------|-------------|----------|
| Missing `text` | 400 | `{"error": "Missing 'text' parameter", "success": false}` |
| Missing `target_lang` | 400 | `{"error": "Missing 'target_lang' parameter", "success": false}` |
| Empty `text` after strip | 400 | `{"error": "text cannot be empty", "success": false}` |
| Empty `target_lang` after strip | 400 | `{"error": "target_lang cannot be empty", "success": false}` |
| LLM exception | 500 | `{"error": "Translation failed: <msg>", "success": false}` |

## File Map

| File | Change |
|------|--------|
| `ai_svc/translation/__init__.py` | Create (empty, makes it a package) |
| `ai_svc/translation/service.py` | Create — `TranslationService` class |
| `ai_svc/translation/prompts.py` | Create — `get_translation_prompt()` |
| `app.py` | Add import, instantiate `translation_service`, add route `POST /api/translate` |

## Out of Scope

- Caching translations
- Batch translation (multiple texts in one request)
- Source language detection or `source_lang` parameter
- Any UI changes
