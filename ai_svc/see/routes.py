"""
Flask Blueprint for the scene description route used by Hear the Color.

POST /api/see  { "image": "<base64 JPEG, no data: prefix>" }  ->  { "text": "..." }
"""
import logging

from flask import Blueprint, jsonify, request

from .rate_limit import RateLimiter
from .service import SeeService

see_bp = Blueprint('see', __name__)

see_service = SeeService()
rate_limiter = RateLimiter(max_requests=20, window_seconds=60)


@see_bp.route('/api/see', methods=['POST'])
def see():
    # Behind Nginx, the real client IP is in X-Real-IP
    ip = request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'
    if rate_limiter.is_limited(ip):
        return jsonify({"error": "too many requests"}), 429

    data = request.get_json(silent=True) or {}
    image = data.get('image')
    if not image or not isinstance(image, str):
        return jsonify({"error": "missing image"}), 400

    try:
        return jsonify({"text": see_service.describe(image)})
    except Exception as e:
        logging.error(f"[/api/see] vision call failed: {e}")
        return jsonify({"error": str(e)}), 500
