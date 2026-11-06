from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, g, jsonify, request

from ai_svc.spy_hunt import auth, ratelimits, store, visibility

spy_hunt_bp = Blueprint("spy_hunt", __name__, url_prefix="/api/spy-hunt")


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
    store.update_me(room["id"], g.player_id, name=body.get("name"), lang=body.get("lang"))
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
