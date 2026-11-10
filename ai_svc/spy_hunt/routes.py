from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, Response, g, jsonify, request

from ai_svc.spy_hunt import auth, custombots, events, game, host, outfits, puzzles, ratelimits, store, timers, translation, visibility, words, workers
from ai_svc.spy_hunt import bots as bots_module

log = logging.getLogger(__name__)

spy_hunt_bp = Blueprint("spy_hunt", __name__, url_prefix="/api/spy-hunt")


@spy_hunt_bp.before_request
def _start_timers():
    # Lazy (impl spec §3): the debug reloader's parent imports the app but never
    # serves a request, so it never starts a timer thread.
    for step in (timers.ensure_started, translation.install, bots_module.install, host.install, words.install):  # independent: one failing
        try:                                                  # must not skip the other
            step()
        except Exception:
            log.exception("before_request %s failed", getattr(step, "__name__", step))


@spy_hunt_bp.errorhandler(store.StoreError)
def _store_error(e: store.StoreError):
    return jsonify({"error": e.code, "message": e.message}), e.status


def _json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise store.StoreError(400, "bad_json", "Body must be a JSON object.")
    return body


def _room_or_404(code: str) -> Dict[str, Any]:
    room = store.get_room_by_code(code)
    if room is None:
        raise store.StoreError(404, "not_found", "No such room.")
    return room


def _snapshot(room_id: str) -> Dict[str, Any]:
    try:
        return visibility.build_snapshot(room_id, g.player_id)
    except LookupError:
        raise store.StoreError(403, "not_member", "You are not in this room.")


@spy_hunt_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@spy_hunt_bp.route("/guests", methods=["POST"])
@ratelimits.limit("guest_create")
def create_guest():
    player_id, token = auth.create_guest()
    return jsonify({"player_id": player_id, "token": token})


# Room routes: `flood` (per IP) runs first, before auth, so unauthenticated
# floods are counted too. Per-guest limits sit BELOW @require_guest because
# they need g.player_id.

@spy_hunt_bp.route("/rooms", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("room_create")
def create_room():
    body = _json_body()
    room = store.create_room(g.player_id, body.get("name"), body.get("lang"))
    return jsonify(_snapshot(room["id"])), 201


@spy_hunt_bp.route("/rooms/<code>/join", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def join_room(code: str):
    body = _json_body()
    room = _room_or_404(code)
    store.add_player(room["id"], g.player_id, body.get("name"), body.get("lang"))
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>", methods=["GET"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("read")
def get_room(code: str):
    room = _room_or_404(code)
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>/me", methods=["PATCH"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def update_me(code: str):
    body = _json_body()
    room = _room_or_404(code)
    changed = store.update_me(room["id"], g.player_id, name=body.get("name"),
                              lang=body.get("lang"))
    if changed:  # backfill runs in a worker: never a model call in the request thread
        workers.submit(translation.backfill_room, room["id"], body["lang"])
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>/settings", methods=["PATCH"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def update_settings(code: str):
    body = _json_body()
    room = _room_or_404(code)
    store.update_settings(room["id"], g.player_id,
                          main_lang=body.get("main_lang"), bot_fill=body.get("bot_fill"))
    return jsonify(_snapshot(room["id"]))


# ---- game flow ----

@spy_hunt_bp.route("/rooms/<code>/start", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def start_game(code: str):
    room = _room_or_404(code)
    game.start_game(room["id"], g.player_id)
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>/statement", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def post_statement(code: str):
    body = _json_body()
    room = _room_or_404(code)
    text = body.get("text")
    if not isinstance(text, str):
        raise store.StoreError(400, "bad_text", "text must be a string.")
    game.submit_statement(room["id"], g.player_id, text)
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>/vote", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def post_vote(code: str):
    body = _json_body()
    room = _room_or_404(code)
    if "target_seat" not in body:
        raise store.StoreError(400, "bad_target", "target_seat is required (null to abstain).")
    game.submit_vote(room["id"], g.player_id, body["target_seat"])
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>/leave", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def leave_room(code: str):
    room = _room_or_404(code)
    game.leave(room["id"], g.player_id)
    return jsonify({"ok": True})


@spy_hunt_bp.route("/rooms/<code>/rematch", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def rematch_room(code: str):
    room = _room_or_404(code)
    game.rematch(room["id"], g.player_id)
    return jsonify(_snapshot(room["id"]))


@spy_hunt_bp.route("/rooms/<code>/bots", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def bots(code: str):
    body = _json_body()
    action = body.get("action")
    if action not in ("add", "remove"):
        raise store.StoreError(400, "bad_request", "action must be add or remove.")
    bot_id, seat = body.get("bot_id"), body.get("seat")
    if bot_id is not None and not isinstance(bot_id, str):
        raise store.StoreError(400, "bad_request", "bot_id must be a string.")
    if seat is not None and (not isinstance(seat, int) or isinstance(seat, bool)):
        raise store.StoreError(400, "bad_request", "seat must be an integer.")
    room = _room_or_404(code)
    if action == "add":
        game.add_bot(room["id"], g.player_id, bot_id)
    else:
        game.remove_bot(room["id"], g.player_id, seat)
    return jsonify(_snapshot(room["id"]))


# ---- daily puzzle ----

@spy_hunt_bp.route("/daily", methods=["GET"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("read")
def get_daily():
    return jsonify(puzzles.get_today(g.player_id))


@spy_hunt_bp.route("/daily/guess", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def daily_guess():
    body = _json_body()
    return jsonify(puzzles.guess_spy(g.player_id, body.get("spy_seat"),
                                     puzzles.check_day(body.get("day"))))


@spy_hunt_bp.route("/daily/word", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def daily_word():
    body = _json_body()
    if "option" not in body:
        raise store.StoreError(400, "bad_option", "option is required (null to skip).")
    return jsonify(puzzles.guess_word(g.player_id, body["option"],
                                      puzzles.check_day(body.get("day"))))


@spy_hunt_bp.route("/daily/result", methods=["GET"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("read")
def daily_result():
    return jsonify(puzzles.result(g.player_id, puzzles.check_day(request.args.get("day"))))


# ---- SSE stream (impl spec §7.1) ----
# No rate-limit decorator on purpose: reconnect storms must never 429. The
# stream caps (events.acquire_slot) bound the cost instead. Auth is the
# Authorization header only; a token in the URL is never accepted.

@spy_hunt_bp.route("/rooms/<code>/events", methods=["GET"])
@auth.require_guest
def room_events(code: str):
    room = _room_or_404(code)
    if store.seat_of(room["id"], g.player_id) is None:
        raise store.StoreError(403, "not_member", "You are not in this room.")
    after = events.parse_cursor(request.args.get("after"), request.headers.get("Last-Event-ID"))
    release = events.acquire_slot(g.player_id)
    if release is None:
        return jsonify({"error": "too_many_streams",
                        "message": "Too many open streams, close one and retry."}), 429
    try:
        body = events.Body(events.stream(room["id"], g.player_id, after, release), release)
    except BaseException:
        release()
        raise
    # Connection: keep-alive is a hop-by-hop header; WSGI apps must not set it.
    return Response(body, status=200, headers={
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ---- custom bots ----

@spy_hunt_bp.route("/bots/catalog", methods=["GET"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("read")
def bot_catalog():
    return jsonify(outfits.catalog())


@spy_hunt_bp.route("/bots", methods=["GET"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("read")
def list_bots():
    return jsonify({"bots": custombots.list_for(g.player_id)})


@spy_hunt_bp.route("/bots", methods=["POST"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def create_bot():
    body = _json_body()
    bot = custombots.create(g.player_id, body.get("name"), body.get("avatar"), body.get("outfit"),
                            body.get("remix_of"), body.get("listed", True))
    return jsonify(bot), 201


@spy_hunt_bp.route("/bots/<bot_id>", methods=["PATCH"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def update_bot(bot_id: str):
    return jsonify(custombots.update(g.player_id, bot_id, _json_body()))


@spy_hunt_bp.route("/bots/<bot_id>", methods=["DELETE"])
@ratelimits.limit("flood")
@auth.require_guest
@ratelimits.limit("action")
def delete_bot(bot_id: str):
    custombots.delete(g.player_id, bot_id)
    return jsonify({"ok": True})


@spy_hunt_bp.route("/bots/<bot_id>", methods=["GET"])
@ratelimits.limit("flood")
def get_bot_card(bot_id: str):
    card = custombots.get_card(bot_id)
    if card is None:
        raise store.StoreError(404, "not_found", "No such bot.")
    return jsonify(card)
