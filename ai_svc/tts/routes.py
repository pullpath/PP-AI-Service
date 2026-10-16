"""
Flask Blueprint for the speech route used by Hear the Color.

POST /api/speak  { "text": "..." }  ->  audio/mpeg
"""
import logging

from flask import Blueprint, Response, jsonify, request

from ai_svc.see.rate_limit import RateLimiter
from .service import MAX_TEXT_LENGTH, TtsService

tts_bp = Blueprint('tts', __name__)

tts_service = TtsService()
# One description per cycle, so this is generous; it mainly caps cost if the route is abused
rate_limiter = RateLimiter(max_requests=30, window_seconds=60)


@tts_bp.route('/api/speak', methods=['POST'])
def speak():
    ip = request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'
    if rate_limiter.is_limited(ip):
        return jsonify({"error": "too many requests"}), 429

    data = request.get_json(silent=True) or {}
    text = data.get('text')
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "missing text"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": f"text too long (max {MAX_TEXT_LENGTH} characters)"}), 400

    try:
        audio = tts_service.synthesize(text.strip())
    except Exception as e:
        logging.error(f"[/api/speak] speech synthesis failed: {e}")
        return jsonify({"error": str(e)}), 500
    return Response(audio, mimetype='audio/mpeg', headers={'Cache-Control': 'no-store'})
