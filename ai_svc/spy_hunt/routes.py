from __future__ import annotations

from flask import Blueprint, jsonify

from ai_svc.spy_hunt import auth, ratelimits

spy_hunt_bp = Blueprint("spy_hunt", __name__, url_prefix="/api/spy-hunt")


@spy_hunt_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@spy_hunt_bp.route("/guests", methods=["POST"])
@ratelimits.limit("guest_create")
def create_guest():
    player_id, token = auth.create_guest()
    return jsonify({"player_id": player_id, "token": token})
