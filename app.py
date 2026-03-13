from flask import Flask, jsonify, request, render_template, redirect, url_for
from werkzeug.utils import secure_filename
from flask_cors import CORS
import os
from ai_svc import tool, openai
import sys
import logging
from dotenv import load_dotenv
import base64
from typing import List

load_dotenv()

def configure_logging():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configure logging to output to sys.stdout
configure_logging()

from ai_svc.dictionary import dictionary_service
from ai_svc.dictionary.cache_service import cache_service
from ai_svc.dictionary.cache_routes import cache_bp
from ai_svc.dictionary.suggest_service import suggestion_service
from ai_svc.dictionary.video_task_service import video_task_service

app = Flask(__name__)
CORS(app)

from flask_caching import Cache
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Register cache management blueprint
app.register_blueprint(cache_bp)


@app.route('/')
def index():
    return render_template('index.html')

@app.errorhandler(404)
def page_not_found(error):
    return redirect(url_for('index'))

@app.route('/cache-manager')
def cache_manager():
    """Cache management UI"""
    return app.send_static_file('cache_manager.html')
@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    data = request.files
    audio = data.get("audio")
    if audio:
        saved_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads', secure_filename(audio.filename))
        logging.info('save audio file to: ' + saved_path)
        audio.save(saved_path)
        text = openai.audio_to_text(saved_path)
    else:
        text = None
    if os.path.exists(saved_path):
        logging.info('delete file: ' + saved_path)
        os.remove(saved_path)
    else:
        logging.info("The file does not exist")
    return jsonify({"text": text}) if text else (jsonify({"error": "No audio provided"}), 400)

@app.route('/api/image', methods=['POST'])
def image():
    prompt_text = request.form.get('prompt')
    if not prompt_text:
        return jsonify({"error": "No prompt provided"}), 400

    data = request.files
    if 'images' not in data:
        return jsonify({"error": "No images part in the request"}), 400

    images = data.getlist('images')

    # If no files are selected
    if len(images) == 0:
        return jsonify({"error": "No selected files"}), 400
    
     # Dictionary to store the base64 images
    base64_images: List[str] = []

    for idx, file in enumerate(images):
        # Read the image file and encode it in base64
        image_data = file.read()

        # Detect image type using python-magic
        image_type = tool.detect_image_type(image_data)
        if not image_type:
            return jsonify({"error": f"File '{file.filename}' is not a valid image"}), 400

        b64 = base64.b64encode(image_data).decode('utf-8')
        base64_images.append(f"data:image/{image_type};base64,{b64}")

    result = openai.vision(images=base64_images, prompt_text=prompt_text)

    return jsonify({"content": result})

@app.route('/api/dictionary', methods=['POST'])
def dictionary_lookup():
    """
    Dictionary lookup endpoint - section-based with entry-level awareness
    
    Request body:
    {
        "word": "hello",          # Required
        "section": "etymology",   # Required: specific section to fetch
        "index": 0,               # Optional: DEPRECATED - use entry_index + sense_index
        "entry_index": 0,         # Optional: for entry-specific sections
        "sense_index": 0,         # Optional: for 'detailed_sense' section (0-based within entry)
        "phrase": "hello world"   # Optional: required for 'bilibili_videos' and 'ai_generated_phrase_video' sections
    }
    
    Valid sections:
    - "basic": Entry-level structure with counts (fast, no AI)
    - "common_phrases": Common phrases for the word (AI-generated, 1-6 phrases)
    - "etymology": Word origin (requires entry_index for multi-entry words)
    - "word_family": Related words (requires entry_index for multi-entry words)
    - "usage_context": Modern usage trends (requires entry_index for multi-entry words)
    - "cultural_notes": Cultural notes (requires entry_index for multi-entry words)
    - "frequency": Word frequency (requires entry_index for multi-entry words)
    - "detailed_sense": Single sense detail (requires entry_index + sense_index)
    - "bilibili_videos": Videos for specific phrase (requires phrase parameter)
    - "ai_generated_phrase_video": AI-generated educational video for phrase (requires phrase parameter)
    
    Example requests:
    - {"word": "scrub", "section": "basic"}  # Get entry structure
    - {"word": "scrub", "section": "common_phrases"}  # Get common phrases
    - {"word": "scrub", "section": "etymology", "entry_index": 0}  # Get etymology for entry 0
    - {"word": "scrub", "section": "etymology", "entry_index": 1}  # Get etymology for entry 1
    - {"word": "scrub", "section": "detailed_sense", "entry_index": 1, "sense_index": 0}  # Entry 1, first sense
    - {"word": "scrub", "section": "bilibili_videos", "phrase": "scrub away"}  # Videos for phrase
    - {"word": "scrub", "section": "ai_generated_phrase_video", "phrase": "scrub away"}  # AI-generated video
    - {"word": "scrub", "section": "detailed_sense", "index": 14}  # DEPRECATED flat indexing
    """
    try:
        data = request.get_json()
        if not data or 'word' not in data:
            return jsonify({
                "error": "Missing 'word' parameter in request body",
                "success": False
            }), 400
        
        if 'section' not in data:
            return jsonify({
                "error": "Missing 'section' parameter in request body. Valid sections: basic, common_phrases, etymology, word_family, usage_context, cultural_notes, frequency, detailed_sense, bilibili_videos",
                "success": False
            }), 400
        
        word = data['word'].strip()
        if not word:
            return jsonify({
                "error": "Word cannot be empty",
                "success": False
            }), 400
        
        section = data['section'].strip()
        if not section:
            return jsonify({
                "error": "Section cannot be empty",
                "success": False
            }), 400
        
        entry_index = data.get('entry_index', None)
        sense_index = data.get('sense_index', None)
        phrase = data.get('phrase', None)
        task_id = data.get('task_id', None)
        
        if section == 'video_status':
            if not task_id:
                return jsonify({
                    "error": "video_status section requires 'task_id' parameter",
                    "success": False
                }), 400
            result = dictionary_service.get_video_status(task_id)
            status_code = 200 if result.get('success') else 404
            return jsonify(result), status_code
        
        # Auto-default entry_index for entry-level sections
        # Most entry-level sections are not entry-specific, so default to 0
        if entry_index is None and section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
            entry_index = 0
            logging.debug(f"[{word}] Auto-defaulting entry_index to 0 for {section}")
        
        # --- Cache orchestration (delegated to cache_service) ---
        def fetch_from_service():
            """Fetch function for cache miss"""
            return dictionary_service.lookup_section(word, section, sense_index, entry_index, phrase)
        
        result, status_code = cache_service.lookup_with_cache(
            word=word,
            section=section,
            entry_index=entry_index,
            sense_index=sense_index,
            phrase=phrase,
            fetch_func=fetch_from_service
        )
        
        return jsonify(result), status_code
    except Exception as e:
        logging.error(f"Error in dictionary lookup: {str(e)}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500

@app.route('/api/dictionary/test', methods=['GET'])
def dictionary_test():
    """
    Simple test endpoint to verify the dictionary agent API is working
    """
    return jsonify({
        "message": "Dictionary agent API is working!",
        "endpoints": {
            "POST /api/dictionary": "Look up a word (requires JSON body with 'word' field)",
            "GET /api/dictionary/test": "This test endpoint",
            "GET /api/dictionary/suggest": "Get word suggestions (requires 'q' query param)"
        },
        "status": "ok"
    }), 200

@app.route('/api/dictionary/suggest', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def dictionary_suggest():
    """
    Word suggestion endpoint for autocomplete
    
    Query params:
        q: Search query (min 2 chars)
        limit: Max suggestions (default 10, max 20)
    
    Returns:
        {
            "query": str,
            "suggestions": List[str],
            "source": "datamuse" | "local" | "cache",
            "success": bool
        }
    """
    try:
        query = request.args.get('q', '').strip()
        limit = min(int(request.args.get('limit', 10)), 20)
        
        if not query:
            return jsonify({
                "error": "Missing 'q' query parameter",
                "success": False
            }), 400
        
        if len(query) < 2:
            return jsonify({
                "query": query,
                "suggestions": [],
                "source": "none",
                "success": True
            }), 200
        
        result = suggestion_service.suggest(query, limit=limit)
        return jsonify(result), 200
        
    except ValueError:
        return jsonify({
            "error": "Invalid 'limit' parameter (must be integer)",
            "success": False
        }), 400
    except Exception as e:
        logging.error(f"Error in dictionary suggest: {str(e)}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500

@app.route('/api/ai_phrase_videos', methods=['GET'])
def get_ai_phrase_videos():
    """
    List all AI-generated phrase videos for a given phrase
    
    Query params:
        word: Word being looked up (required)
        phrase: Phrase to find videos for (required)
        status: Filter by status (optional) - "pending", "processing", "completed", "failed"
    
    Returns:
        {
            "word": str,
            "phrase": str,
            "videos": [
                {
                    "task_id": str,
                    "video_url": str | None,
                    "status": str,
                    "style": str,
                    "duration": int,
                    "resolution": str,
                    "ratio": str,
                    "created_at": str,
                    "completed_at": str | None
                }
            ],
            "count": int,
            "success": bool
        }
    """
    try:
        word = request.args.get('word', '').strip()
        phrase = request.args.get('phrase', '').strip()
        status = request.args.get('status', '').strip()
        
        if not word or not phrase:
            return jsonify({
                "error": "Missing 'word' and/or 'phrase' query parameters",
                "success": False
            }), 400
        
        status_filter = [status] if status else None
        videos = cache_service.list_ai_phrase_videos(word, phrase, status_filter)
        
        return jsonify({
            "word": word,
            "phrase": phrase,
            "videos": videos,
            "count": len(videos),
            "success": True
        }), 200
        
    except Exception as e:
        logging.error(f"Error in get_ai_phrase_videos: {str(e)}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500

@app.route('/api/search', methods=['GET'])
def search():
    result = tool.google_search(request.args.get('keyword'))
    return jsonify({"status": "ok", "result": result})

@app.route('/api/scrape', methods=['GET'])
def scrape():
    result = tool.web_scraping(request.args.get('objective'), request.args.get('url'))
    return jsonify({"status": "ok", "result": result})

if __name__ == '__main__':
    env = os.getenv('FLASK_ENV', 'development')
    if env == 'production':
        app.run(debug=False, host='0.0.0.0', port=8000)
    else:
        app.run(debug=True, host='0.0.0.0', port=8000)