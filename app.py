from flask import Flask, request, render_template
from storage import upload_document
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__, static_folder='Client', template_folder='Client')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('doc_file')
    message = request.form.get('message')

    if file:
        result = upload_document(file)
    else:
        result = "No file uploaded."

    return f"{result} | Message: {message}" 

if __name__ == '__main__':
    app.run(debug=True)