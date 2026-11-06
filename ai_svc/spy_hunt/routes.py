from __future__ import annotations

from flask import Blueprint, jsonify

spy_hunt_bp = Blueprint("spy_hunt", __name__, url_prefix="/api/spy-hunt")


@spy_hunt_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})
