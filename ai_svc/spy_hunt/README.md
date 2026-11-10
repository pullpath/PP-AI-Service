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

To grow an existing pool instead, add `--extend`: the run starts from the shipped
seed, `--target` is the total size, and the candidate file holds only the new pairs
to review and append. The generator tells the model which pairs already exist and
rejects a pair that is already in the pool (a reversed pair counts as a duplicate).

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

## Daily puzzle

One bot-vs-bot transcript per UTC day. Everyone who opens `GET /daily` that day gets
the same puzzle: read 5 players over 2 rounds, tap the spy (two tries), optionally
pick the spy's word from 4 options. Scores are computed on the server (spy found on
try 1 = 100, try 2 = 60, plus up to 20 for speed and 20 for the word) and the answer
is never sent before a player finishes. One scored attempt per guest per day.

Puzzles are generated ahead of time, never on a request. The generator
(`puzzle_gen.py`) writes the statements with the bot prompt, translates them in one
call, and rejects any puzzle where a clue names a secret word or a solver model
cannot find the spy (or finds it from round 1 alone). A day takes the oldest ready
puzzle on its first request; with none ready, `/daily` answers `503 no_puzzle`.

```
python -m ai_svc.spy_hunt.scripts.build_puzzles --count 14   # fill the queue (spends model calls)
python -m ai_svc.spy_hunt.scripts.build_puzzles --review     # list ready puzzles with the answer
python -m ai_svc.spy_hunt.scripts.build_puzzles --veto 7     # remove one from the queue
```

Keep the queue topped up with cron (about 14 model calls per puzzle):

```
0 3 * * * cd <repo> && venv/bin/python -m ai_svc.spy_hunt.scripts.build_puzzles --count 14
```

## Custom bots

A guest can make up to 3 bots (name, emoji avatar, colour, and three outfit slots:
voice, clue style, quirk). All under `/api/spy-hunt`; a guest token is required except
for the public card.

| Route | Result |
| --- | --- |
| `GET /bots/catalog` | `{voices, styles, quirks, emojis, colors}` (ids/values only) |
| `GET /bots` | `{bots: MyBot[]}`; `MyBot = {id, name, avatar, outfit, record}` |
| `POST /bots` `{name, avatar, outfit}` | 201 `MyBot` |
| `PATCH /bots/<id>` (any subset of `name`, `avatar`, `outfit`) | `MyBot`; `avatar` and `outfit` must be complete |
| `DELETE /bots/<id>` | `{ok: true}`; the public card then 404s, running rooms keep their copy |
| `GET /bots/<id>` (no token) | `{id, name, avatar, outfit, record: {games, wins, spy_games, spy_wins}}` |
| `POST /rooms/<code>/bots` `{action: "add", bot_id?}` | adds your custom bot (or a random one without `bot_id`) |
| `POST /rooms/<code>/bots` `{action: "remove", seat?}` | removes a bot; an owner may remove their own custom bot by `seat` |

Errors: `400 bad_name | bad_avatar | bad_outfit | bad_request`, `404 not_found`,
`409 bot_limit`; in rooms also `409 bot_in_room`, `403 not_allowed`.

- At most 3 bots per guest; at most one custom bot per owner per room.
- Outfits are prompt-only: the server compiles them into extra instruction text and
  they carry no game state. Scaffold rules win, then clue style, quirk, voice.
- A room copies the bot into the player row, so later edits never touch a running game.
- Records count only games that end with a winner.
- A database from before this change is migrated on start (new nullable columns).
- The public card never shows an owner; public player data carries `avatar` and `bot_id` only, never the owner or outfit.
