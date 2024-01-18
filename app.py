from flask import Flask, jsonify, request, render_template, redirect, url_for
from ai_svc.openai import OpenAIIntegration
from werkzeug.utils import secure_filename
from flask_cors import CORS
import os
from ai_svc import tool

app = Flask(__name__)
CORS(app)
openai_integration = OpenAIIntegration()

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
        saved_path = os.path.join('static/uploads', secure_filename(audio.filename))
        audio.save(saved_path)
        text = openai_integration.audio_to_text(saved_path)
        return jsonify({"text": text})
    else:
        return jsonify({"error": "No audio provided"}), 400
    
@app.route('/api/search', methods=['GET'])
def search():
    result = tool.google_search(request.args.get('keyword'))
    return jsonify({"status": "ok", "result": result})

@app.route('/api/scrape', methods=['GET'])
def scrape():
    result = tool.web_scraping(request.args.get('objective'), request.args.get('url'))
    return jsonify({"status": "ok", "result": result})

if __name__ == '__main__':
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        app.run(debug=False, host='0.0.0.0', port=8000)
    else:
        app.run(debug=True, host='0.0.0.0', port=8000)