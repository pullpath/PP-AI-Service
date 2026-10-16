# `POST /api/see`

Scene description for the [Hear the Color](../../hear-the-color) frontend (a vision assistant for visually
impaired users). Design background: [`hear-the-color/docs/DESIGN.md`](../../hear-the-color/docs/DESIGN.md).

## Request

```http
POST /api/see
Content-Type: application/json

{ "image": "<base64 JPEG, WITHOUT the data:image/jpeg;base64, prefix>" }
```

## Responses

| Status | Body | When |
| --- | --- | --- |
| 200 | `{ "text": "A fluffy orange cat sleeps on a sunlit blue sofa." }` | Success |
| 400 | `{ "error": "missing image" }` | `image` absent, empty or not a string |
| 429 | `{ "error": "too many requests" }` | More than 20 requests/minute from one IP |
| 500 | `{ "error": "<message>" }` | Model call failed (logged) |

Rate limiting is in memory, per process, keyed by `X-Real-IP` (set by Nginx) or the socket address.

## Provider configuration

Selected with `AI_PROVIDER` in `.env`; restart Flask after changing it.

| Variable | Default |
| --- | --- |
| `AI_PROVIDER` | `openai` (or `deepseek`) |
| `OPENAI_API_KEY` | none |
| `OPENAI_BASE_URL` | falls back to legacy `OPENAI_API_BASE` |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `DEEPSEEK_API_KEY` | none |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-flash` |

The model must accept image input. `/api/image` ignores `AI_PROVIDER` and always uses OpenAI. The
`x-pp-token` proxy header is sent only to OpenAI. Implementation: `get_vision_provider()` and `vision()` in
`ai_svc/openai.py`, route in `app.py`, tests in `tests/test_see_endpoint.py`.

## Try it

```bash
curl -s -X POST http://localhost:8000/api/see -H 'Content-Type: application/json' \
  -d "{\"image\": \"$(base64 < photo.jpg | tr -d '\n')\"}"
```
