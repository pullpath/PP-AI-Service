"""
Flask Blueprint for the speech route used by Hear the Color.

GET  /api/speak?text=...   ->  audio/mpeg, streamed (used by the frontend: an <audio src> starts playing on
                                the first chunk instead of waiting for the whole file)
POST /api/speak {"text"}   ->  the same stream
"""
import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context

from ai_svc.see.rate_limit import RateLimiter
from .service import MAX_TEXT_LENGTH, TtsService

tts_bp = Blueprint('tts', __name__)

tts_service = TtsService()
# One description per cycle, so this is generous; it mainly caps cost if the route is abused
rate_limiter = RateLimiter(max_requests=30, window_seconds=60)


@tts_bp.route('/api/speak', methods=['GET', 'POST'])
def speak():
    ip = request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'
    if rate_limiter.is_limited(ip):
        return jsonify({"error": "too many requests"}), 429

    if request.method == 'GET':
        text = request.args.get('text')
    else:
        text = (request.get_json(silent=True) or {}).get('text')
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "missing text"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": f"text too long (max {MAX_TEXT_LENGTH} characters)"}), 400

    # Pull the first chunk before answering, so provider errors still become a proper 500 instead of a
    # 200 with a broken audio stream
    chunks = tts_service.stream(text.strip())
    try:
        first = next(chunks)
    except StopIteration:
        logging.error("[/api/speak] provider returned no audio")
        return jsonify({"error": "empty audio"}), 500
    except Exception as e:
        logging.error(f"[/api/speak] speech synthesis failed: {e}")
        return jsonify({"error": str(e)}), 500

    def body():
        try:
            yield first
            yield from chunks
        finally:
            chunks.close()

    return Response(
        stream_with_context(body()),
        mimetype='audio/mpeg',
        # X-Accel-Buffering: no stops Nginx from holding the stream back, without any Nginx config change
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
    )
