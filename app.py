from flask import Flask, jsonify, request, render_template, redirect, url_for
from langchain_svc.openai import OpenAIIntegration

app = Flask(__name__)
openai_integration = OpenAIIntegration()

# @app.route('/')
# def index():
#     return render_template('index.html')

@app.route('/api/translate', methods=['POST'])
def translate():
    data = request.json
    text = data.get("text")
    if text:
        response = openai_integration.generate_text(text)
        print(response)
        return jsonify({"response": response})
    else:
        return jsonify({"error": "No text provided"}), 400
    
# @app.errorhandler(404)
# def page_not_found(error):
#     return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=9900)