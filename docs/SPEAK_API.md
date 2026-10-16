# `POST /api/speak`

Natural-sounding speech for the [Hear the Color](../../hear-the-color) frontend, using OpenAI's speech API.
The frontend falls back to the browser voice if this route fails.

```http
POST /api/speak
Content-Type: application/json

{ "text": "A bright red mug rests on a sunny wooden desk." }
```

| Status | Body | When |
| --- | --- | --- |
| 200 | MP3 audio (`audio/mpeg`) | Success |
| 400 | `{ "error": "missing text" }` / `{ "error": "text too long (max 400 characters)" }` | Bad input |
| 429 | `{ "error": "too many requests" }` | More than 30 requests/minute from one IP |
| 500 | `{ "error": "<message>" }` | OpenAI call failed (logged) |

## Configuration

| Variable | Default |
| --- | --- |
| `OPENAI_API_KEY` | required |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` (style instructions are sent only to `gpt-4o*` models) |
| `OPENAI_TTS_VOICE` | `nova` |

It always calls the official `https://api.openai.com/v1` endpoint and ignores `OPENAI_API_BASE`,
`OPENAI_BASE_URL` and `X-PP-TOKEN`, so the server must be able to reach OpenAI directly. This is independent of
`AI_PROVIDER`, which only chooses the vision model for `/api/see`.

Code: `ai_svc/tts/` (`routes.py`, `service.py`), registered in `app.py` as a blueprint. Tests: `tests/tts/`.
