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
| GET | `/daily/streak` | `{streak, best, played_today}` computed from your finished daily puzzles |
| POST | `/register` | `{email, password}`; attaches credentials to your current guest (guest token required) |
| POST | `/login` | `{email, password}`; no token needed, returns `{player_id, token, email}` |
| POST | `/logout` | removes only the calling device's token (guest token required) |
| GET | `/me` | `{email}`, `null` when the guest has no account |

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

## Accounts

Registration is optional and never blocks guest play. Four routes:

- `POST /register` (guest token required) sets an email and password on the caller's existing guest identity. There is no merge step: `player_id` never changes, so bots, remixes and history stay put. Email is trimmed and lowercased; the password must be at least 8 characters. An already-registered guest, or an email already in use, gets `409 conflict`. Hashing uses `werkzeug.security`.
- `POST /login` (no token) checks email and password and mints a new token for that account's `player_id`. A wrong email or password gives the same `401`. It is rate limited per IP (20/min).
- `POST /logout` (guest token required) deletes only the token it was called with.
- `GET /me` (guest token required) returns `{"email": ...}`, or `{"email": null}` for a plain guest.

The `sessions` table holds many tokens per guest, so logging in on a second device does not sign out the first, and logout only affects the calling device. `init_db()` backfills tokens issued before this table existed, so old guests stay signed in. There is no email verification and no password reset in this version.

`GET /daily`, `GET /daily/result` and `GET /daily/streak` return `streak`, `best` and `played_today`, computed from `puzzle_results` rather than client storage. A streak survives one unplayed day before it shows as 0.

## Custom bots

A guest can make up to 3 bots (name, emoji avatar, colour, and three outfit slots:
voice, clue style, quirk). All under `/api/spy-hunt`; a guest token is required except
for the public card.

| Route | Result |
| --- | --- |
| `GET /bots/catalog` | `{voices, styles, quirks, emojis, colors, triggers, actions, max_rules}` (ids/values only) |
| `GET /bots` | `{bots: MyBot[]}`; `MyBot = {id, name, avatar, outfit, record}` |
| `POST /bots` `{name, avatar, outfit, remix_of?, listed?}` | 201 `MyBot`; `remix_of` is a bot id to credit, `listed` (default true) shows the bot on the board |
| `PATCH /bots/<id>` (any subset of `name`, `avatar`, `outfit`, `listed`) | `MyBot`; `avatar` and `outfit` must be complete |
| `DELETE /bots/<id>` | `{ok: true}`; the public card then 404s, running rooms keep their copy |
| `GET /bots/top?kind=winners\|spies` (no token) | `{kind, bots: [{rank, id, name, avatar, rate, games, remixes}]}`, at most 10; `kind` defaults to `winners`, other values `400 bad_request` |
| `GET /bots/<id>` (no token) | `{id, name, avatar, outfit, record: {games, wins, spy_games, spy_wins}, remix_of, remixes, remixable, ranked: {games, wins, spy_games, spy_wins}, listed}`; `remix_of` is `{id, name}` or null |
| `POST /rooms/<code>/bots` `{action: "add", bot_id?}` | adds your custom bot (or a random one without `bot_id`) |
| `POST /rooms/<code>/bots` `{action: "remove", seat?}` | removes a bot; an owner may remove their own custom bot by `seat` |

### Ranked record and board

A game updates a bot's ranked record only if it ends with a winner and has at least 3 humans
(non-bot players). The board lists bots with at least 10 ranked games (`winners`) or 5 ranked
spy games (`spies`), ordered by win rate, then more games, then older bot; top 10 only.
Changing a bot's outfit resets its ranked record. A bot with `listed: false` is hidden from the
board but still remixable; a blocked bot is off the board and not remixable. Block from the
server: `python -m ai_svc.spy_hunt.scripts.block_bot <id> [--unblock]`.

### Rule cards

`outfit` also carries `rules: [{when, do}]` (max 3, no duplicate pair, missing means `[]`; violations are `400 bad_outfit`).
Conditions (`when`) read public state only: `accused`, `first_to_speak`, `last_to_speak`, `after_elimination`, `late_game`.
Actions (`do`): statement actions `counter_accuse`, `copy_previous`, `go_vague` add a sentence to the prompt;
vote actions `vote_accuser`, `vote_leader` pick the target directly and skip the model call (if none applies, the normal model vote runs).
Vote rules never choose an illegal target. Rule text names players by seat number only, never by name.
A stored rule that is broken or unknown is ignored.

Errors: `400 bad_name | bad_avatar | bad_outfit | bad_request`, `404 not_found`,
`409 bot_limit`; in rooms also `409 bot_in_room`, `403 not_allowed`.

- At most 3 bots per guest; at most one custom bot per owner per room.
- Outfits are prompt-only: the server compiles them into extra instruction text and
  they carry no game state. Scaffold rules win, then clue style, quirk, voice.
- A room copies the bot into the player row, so later edits never touch a running game.
- Records count only games that end with a winner.
- A database from before this change is migrated on start (new nullable columns).
- The public card never shows an owner; public player data carries `avatar` and `bot_id` only, never the owner or outfit.

## Living bot (arena)

Custom bots play on their own: once a day a cron job runs bot-only matches and each
owner gets a recap. Run from the repo root, once a day:

    python -m ai_svc.spy_hunt.scripts.arena_night [--matches N] [--dry-run]

`--matches` overrides the match count (default 20); `--dry-run` only prints the planned
groups and calls no model. A match costs about 24 model calls, so about 480 a day at the defaults.

Rules:
- Who plays: bots with `arena` on (default true), not blocked, and active in the last 14 days
  (any create/update/list by the owner counts; `GET /bots/recaps` does not). Seats per match: 5.
- Each bot plays at most once a day.
- A match with too many fallback (non-model) moves is discarded; a bot whose own fallback share is
  at least half gets no entry or record for that match.
- Arena games never touch the ranked record or the board. Matches and entries are pruned after 14 days.

Routes (under `/api/spy-hunt`):

| Route | Result |
| --- | --- |
| `GET /bots/recaps` (guest token) | `{recaps: Recap[], unseen}`, newest first, at most 10, only your own bots; `Recap = {match_id, bot_id, bot_name, avatar, day, lang, role, won, accused, out_round, quote, seen}`; `unseen` counts all unseen entries |
| `POST /bots/recaps/seen` (guest token) | `{ok: true}`; marks all your recaps seen |
| `GET /arena/matches/<id>` (no token) | `{id, day, lang, players: [{seat, name, avatar, bot_id, role, is_custom}], rounds, words, winner}`; no owner info; unknown or pruned id is `404 not_found` |

`POST`/`PATCH /bots` accept `arena` (boolean, default true) to opt a bot in or out. The bot card
and `MyBot` carry the arena fields (`arena` and the arena record).
