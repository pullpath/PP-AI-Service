# `POST /api/speak`

Natural-sounding speech for the [Hear the Color](../../hear-the-color) frontend, using OpenAI's speech API.
The frontend falls back to the browser voice if this route fails.

```http
GET /api/speak?text=A%20bright%20red%20mug%20rests%20on%20a%20sunny%20wooden%20desk.
```

`POST /api/speak` with `{ "text": "..." }` works the same. The frontend uses GET so an `<audio>` element can
play the URL directly.

The MP3 is **streamed** as OpenAI generates it (chunked, `X-Accel-Buffering: no` so Nginx passes it through
without buffering and without any config change), so playback can start before generation has finished.
The first chunk is fetched before the response starts, so a provider failure is still a proper 500.

| Status | Body | When |
| --- | --- | --- |
| 200 | MP3 audio (`audio/mpeg`), streamed | Success |
| 400 | `{ "error": "missing text" }` / `{ "error": "text too long (max 400 characters)" }` | Bad input |
| 429 | `{ "error": "too many requests" }` | More than 30 requests/minute from one IP |
| 500 | `{ "error": "<message>" }` | OpenAI call failed (logged) |

## Configuration

| Variable | Default |
| --- | --- |
| `OPENAI_API_KEY` | required |
| `OPENAI_BASE_URL` | official `https://api.openai.com/v1`; set it to use a proxy (trailing slash is stripped). Shared with the OpenAI option of `/api/see` |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` (style instructions are sent only to `gpt-4o*` models) |
| `OPENAI_TTS_VOICE` | `nova` |

Without `OPENAI_BASE_URL` it calls the official endpoint directly. It never reads the legacy `OPENAI_API_BASE`
or `X-PP-TOKEN` and sends no custom headers, so a proxy must accept a plain
`Authorization: Bearer <OPENAI_API_KEY>` request.

Note: `load_dotenv()` does not override variables already set in the environment, so an `OPENAI_BASE_URL`
exported by your shell (e.g. in `~/.bash_profile`) wins over the one in `.env`. This is independent of
`AI_PROVIDER`, which only chooses the vision model for `/api/see`.

Code: `ai_svc/tts/` (`routes.py`, `service.py`), registered in `app.py` as a blueprint. Tests: `tests/tts/`.
