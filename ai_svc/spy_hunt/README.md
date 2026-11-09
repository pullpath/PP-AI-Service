# Spy Hunt backend

A multiplayer "who is the spy" word game, served as a Flask blueprint
(`spy_hunt_bp`, mounted at `/api/spy-hunt`). State lives in SQLite; clients
receive live updates over Server-Sent Events. Bots, translation, host narration
and word generation use a DeepSeek model through `llm.call_json`.

## Endpoints

All routes except `/health` and `/guests` need `Authorization: Bearer <player_id>.<token>`
(from `POST /guests`). Errors are JSON `{"error", "message"}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/guests` | create a guest, returns `player_id` and `token` |
| POST | `/rooms` | create a room `{name, lang}` (`lang`: `en` or `zh-Hans`) |
| POST | `/rooms/<code>/join` | join `{name, lang}` |
| GET | `/rooms/<code>` | snapshot for the caller |
| PATCH | `/rooms/<code>/me` | change own name or language |
| PATCH | `/rooms/<code>/settings` | host: room settings |
| POST | `/rooms/<code>/bots` | host: `{action: add\|remove}` |
| POST | `/rooms/<code>/start` | host: start (bots fill to the minimum) |
| POST | `/rooms/<code>/statement` | `{text}` on your turn |
| POST | `/rooms/<code>/vote` | `{target_seat}` (`null` abstains) |
| POST | `/rooms/<code>/leave` | leave (a bot takes the seat mid-game) |
| POST | `/rooms/<code>/rematch` | host: new game in the same room |
| GET | `/rooms/<code>/events` | SSE stream, `?after=<seq>` or `Last-Event-ID` |
| GET | `/daily` | today's puzzle and your progress (starts your timer); 503 `no_puzzle` if none is ready |
| POST | `/daily/guess` | `{spy_seat}` (0 to 4), two tries |
| POST | `/daily/word` | `{option}` (0 to 3, or `null` to skip) |
| GET | `/daily/result` | score, answer and day stats, once finished |

## Events (SSE: `id: <seq>`, `event: <type>`, `data: <json>`)

`player_joined`, `player_left`, `player_updated`, `settings`, `roster`,
`game_started` (your own word, personal), `turn`, `phase`, `statement`
(also used for host lines, `kind: "host"`), `translation`, `vote_locked`,
`reveal`, `game_over` (winner, roles, words: the first event to contain them),
`rematch`, `state` (full snapshot when a client is too far behind).

## Environment variables

| Variable | Meaning |
|---|---|
| `DEEPSEEK_API_KEY` | model key (read from the environment or `.env`) |
| `SPY_HUNT_MODEL` | model id, default `deepseek-chat` |
| `SPY_HUNT_DB_PATH` | SQLite file; put it on a volume in Docker |
| `SPY_HUNT_FAKE_LLM=1` | use the deterministic fake transport (tests, no network) |

## Word pool

`seed/pairs_seed.json` is a small placeholder pool loaded when `pairs` is empty.
Build the real pool offline (about 300 to 400 model calls, once):

    python -m ai_svc.spy_hunt.scripts.build_pool --target 120

This writes `seed/pairs_candidate.json` and never touches the shipped seed.
Review it, then copy it over `pairs_seed.json` to load it.

## Operating notes

- **Single process only.** Room locks, the timer queue, SSE wake-ups and
  worker pools are in-process. Run one worker process (no multi-process gunicorn).
- Each room has an AI call budget (300). Host narration stops first when under
  20% remains; bots and translation keep working longest.
- Tests: `pytest ai_svc/spy_hunt/tests -v`.

## Nginx (SSE)

    location ~ ^/api/spy-hunt/rooms/[^/]+/events$ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

The server also sends `X-Accel-Buffering: no`. Other routes need no special handling.
