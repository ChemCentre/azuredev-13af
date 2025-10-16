from flask import Flask, request, jsonify, render_template
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from storage import upload_file_to_blob
import tempfile
from dotenv import load_dotenv
import os

# Load .env variables
load_dotenv()
ENDPOINT = os.getenv("AZURE_ENDPOINT")
AGENT_ID = os.getenv("AGENT_ID")

# Flask app
app = Flask(__name__)

# Azure AI project and agent
project = AIProjectClient(credential=DefaultAzureCredential(), endpoint=ENDPOINT)
agent = project.agents.get_agent(AGENT_ID)

# Single thread for simplicity
thread = project.agents.threads.create()

# Serve the frontend
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

# 📁 Handle file upload from frontend
@app.route("/upload_file", methods=["POST"])
def upload_file():
    file = request.files.get("doc_file")

    if not file:
        return jsonify({"response": "❌ No file received."}), 400

    try:
        # Save the uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file.save(temp_file.name)
            blob_url = upload_file_to_blob(temp_file.name, file.filename)

        # Send message to agent to acknowledge the new document
        project.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content=f"I have uploaded a document: {blob_url}. Please do NOT summarise it yet. Wait until I ask questions about it."
        )

        return jsonify({
            "response": f"✅ File uploaded successfully: {file.filename}",
            "blob_url": blob_url
        })

    except Exception as e:
        print("Upload error:", e)
        return jsonify({"response": f"❌ Upload failed: {str(e)}"}), 500


# API endpoint for the frontend
@app.route("/send_message", methods=["POST"])
def send_message():
    user_message = request.json.get("message", "")
    if not user_message:
        return jsonify({"response": "❌ No message provided."})

    try:
        # Send user message to agent
        project.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_message
        )

        # Process response
        run = project.agents.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent.id
        )

        if run.status == "failed":
            return jsonify({"response": f"❌ AI agent failed: {run.last_error}"})

        # Get latest AI message
        messages = list(project.agents.messages.list(
            thread_id=thread.id,
            order=ListSortOrder.ASCENDING
        ))

        ai_response = ""
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.text_messages:
                ai_response = msg.text_messages[-1].text.value
                break

        return jsonify({"response": ai_response or "🤖 No response received."})

    except Exception as e:
        print("Error:", e)
        return jsonify({"response": f"❌ Error talking to agent: {str(e)}"})

if __name__ == "__main__":
    app.run(debug=True)
