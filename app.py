from flask import Flask, jsonify, request, render_template, redirect, url_for
from werkzeug.utils import secure_filename
from flask_cors import CORS
import os
from ai_svc import tool, openai
from ai_svc.dictionary import dictionary_service
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

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.errorhandler(404)
def page_not_found(error):
    return redirect(url_for('index'))

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
    Dictionary lookup endpoint - section-based only (no full lookup)
    
    Request body:
    {
        "word": "hello",         # Required
        "section": "etymology",  # Required: specific section to fetch
        "index": 0               # Optional: for 'detailed_sense' section only
    }
    
    Valid sections:
    - "basic": pronunciation, total_senses (fast, no AI)
    - "etymology": word origin and root analysis
    - "word_family": related words
    - "usage_context": modern usage trends
    - "cultural_notes": cultural and linguistic notes
    - "frequency": word frequency estimation
    - "detailed_sense": single sense detail (requires index, fast ~2-3s)
    
    Example requests:
    - {"word": "run", "section": "basic"}  # Get basic info
    - {"word": "run", "section": "etymology"}  # Get etymology only
    - {"word": "run", "section": "detailed_sense", "index": 0}  # Get first sense
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
                "error": "Missing 'section' parameter in request body. Valid sections: basic, etymology, word_family, usage_context, cultural_notes, frequency, detailed_sense",
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
        
        index = data.get('index', None)
        
        # Service layer handles all business logic
        result = dictionary_service.lookup_section(word, section, index)
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({
            "error": f"Internal server error: {str(e)}",
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
            "GET /api/dictionary/test": "This test endpoint"
        },
        "status": "ok"
    }), 200
    
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