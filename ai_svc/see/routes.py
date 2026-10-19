"""
Flask Blueprint for the scene description route used by Hear the Color.

POST /api/see
  { "image": "<base64 JPEG, no data: prefix>", "lang": "<optional BCP-47 tag>", "include_audio": <optional bool> }
  ->  { "text": "..." }
  with include_audio: true, the spoken description comes in the same response, so the caller can show the text
  and start the audio at the same moment:
  ->  { "text": "...", "audio": "<base64 MP3>", "audio_format": "mp3" }
  If speech fails the description is still returned, with "audio_error" instead of "audio".
"""
import base64
import logging

from flask import Blueprint, jsonify, request

from ai_svc.tts.routes import tts_service
from .language import normalize_language
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

    # Invalid or missing lang silently falls back to English
    lang = normalize_language(data.get('lang'))
    # Only a real JSON true turns it on, so "false" strings or other values never cost a TTS call
    include_audio = data.get('include_audio') is True

    try:
        text = see_service.describe(image, lang)
    except Exception as e:
        logging.error(f"[/api/see] vision call failed: {e}")
        return jsonify({"error": str(e)}), 500

    body = {"text": text}
    if include_audio:
        try:
            body["audio"] = base64.b64encode(tts_service.synthesize(text)).decode("ascii")
            body["audio_format"] = "mp3"
        except Exception as e:
            # The description is the essential part; let the caller fall back to its own voice
            logging.error(f"[/api/see] speech synthesis failed: {e}")
            body["audio_error"] = str(e)
    return jsonify(body)
