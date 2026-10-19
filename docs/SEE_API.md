# `POST /api/see`

Scene description for the [Hear the Color](../../hear-the-color) frontend (a vision assistant for visually
impaired users). Design background: [`hear-the-color/docs/DESIGN.md`](../../hear-the-color/docs/DESIGN.md).

## Request

```http
POST /api/see
Content-Type: application/json

{ "image": "<base64 JPEG, WITHOUT the data:image/jpeg;base64, prefix>", "lang": "zh-CN" }
```

`lang` is optional: a BCP-47 tag for the language of the description. It is validated (letters and digits only,
short subtags) and mapped to a language name before it is put in the prompt; a missing or malformed value
falls back to English. Error bodies stay English; the frontend shows its own translated messages.

### Optional: `include_audio`

```json
{ "image": "...", "lang": "en", "include_audio": true }
```

With `"include_audio": true` (a JSON boolean; anything else is ignored) the backend also speaks the description
with OpenAI TTS (same voice and settings as [`/api/speak`](SPEAK_API.md)) and returns it in the same response:

```json
{ "text": "A bright red mug rests on a sunny wooden desk.", "audio": "<base64 MP3>", "audio_format": "mp3" }
```

This saves a second round trip and lets a client show the text and start the voice at the same moment. The
description is the essential part: if speech fails, the request still succeeds with `audio_error` instead of
`audio`, and the client can fall back to `/api/speak` or its own voice. Without the flag the response is
unchanged (`{ "text": "..." }`) and no TTS call is made, so other clients aren't affected.

## Responses

| Status | Body | When |
| --- | --- | --- |
| 200 | `{ "text": "A fluffy orange cat sleeps on a sunlit blue sofa." }` (plus `audio` / `audio_format` or `audio_error` with `include_audio`) | Success |
| 400 | `{ "error": "missing image" }` | `image` absent, empty or not a string |
| 429 | `{ "error": "too many requests" }` | More than 20 requests/minute from one IP |
| 500 | `{ "error": "<message>" }` | Model call failed (logged) |

Rate limiting is in memory, per process, keyed by `X-Real-IP` (set by Nginx) or the socket address.

## Provider configuration

Selected with `AI_PROVIDER` in `.env`; restart Flask after changing it.

| Variable | Default |
| --- | --- |
| `AI_PROVIDER` | `deepseek` (or `openai`) |
| `OPENAI_API_KEY` | none |
| `OPENAI_BASE_URL` | official OpenAI endpoint |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `DEEPSEEK_API_KEY` | none |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-flash` |

The model must accept image input. DeepSeek is the default. For DeepSeek, thinking is turned off in the request:
reasoning tokens would otherwise eat the small `max_tokens` budget and leave an empty description.

This module is independent of the proxy setup used elsewhere: it never reads `OPENAI_API_BASE` or `X-PP-TOKEN`,
and sends no custom headers. Existing routes, including `/api/image`, are untouched and keep using
`ai_svc/openai.py`.

## Code layout

Self-contained module `ai_svc/see/`, registered in `app.py` as a blueprint (like `ai_svc/dictionary`):

| File | Role |
| --- | --- |
| `routes.py` | `see_bp` blueprint, `POST /api/see` |
| `service.py` | `SeeService.describe()`: builds the request and calls the model |
| `provider.py` | `get_vision_provider()` -> `(base_url, api_key, model)` from `AI_PROVIDER` |
| `prompts.py` | `SEE_PROMPT_TEMPLATE` / `get_see_prompt(language)` |
| `language.py` | `normalize_language()` (validation) and `language_name()` (tag to prompt language) |
| `../rate_limit.py` | In-memory sliding-window `RateLimiter` (shared with `ai_svc/tts`) |

Tests: `tests/see/`.

## Try it

```bash
curl -s -X POST http://localhost:8000/api/see -H 'Content-Type: application/json' \
  -d "{\"image\": \"$(base64 < photo.jpg | tr -d '\n')\"}"
```
