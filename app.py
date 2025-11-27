from flask import Flask, request, jsonify, render_template, session
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from openai import AzureOpenAI
from storage import upload_file_to_blob
from load_secrets import get_secret
from dotenv import load_dotenv
import tempfile
import requests
import time
import json
import re

load_dotenv()

# ---------------------------------------------------------------------
# Secure configuration via Azure Key Vault
# ---------------------------------------------------------------------
ENDPOINT = get_secret("azure-endpoint")
AGENT_ID = get_secret("agent-id")
SEARCH_ENDPOINT = get_secret("azure-search-endpoint")
SEARCH_INDEX = get_secret("azure-search-index")
SEARCH_KEY = get_secret("azure-search-key")
FLASK_SECRET_KEY = get_secret("flask-secret-key")
EMBED_ENDPOINT = get_secret("embedding-endpoint")
EMBED_KEY = get_secret("embedding-key")
EMBED_DEPLOYMENT = get_secret("embedding-deployment")
API_VERSION = "2023-05-15"

# ---------------------------------------------------------------------
# Flask setup
# ---------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# ---------------------------------------------------------------------
# Azure AI agent setup
# ---------------------------------------------------------------------
project = AIProjectClient(credential=DefaultAzureCredential(), endpoint=ENDPOINT)
agent = project.agents.get_agent(AGENT_ID)
embedding_client = AzureOpenAI(
    api_version=API_VERSION,
    azure_endpoint = EMBED_ENDPOINT,
    api_key=EMBED_KEY
)
LAST_CONTEXT = {}

# ---------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------
def create_clean_thread():
    """Create a fresh thread with no memory."""
    thread = project.agents.threads.create()
    print(f"[DEBUG] Created new thread: {thread.id}")
    return thread.id

def get_user_thread():
    """Get or create thread for current session."""
    if "thread_id" not in session:
        session["thread_id"] = create_clean_thread()
        session["is_new_chat"] = True  # Mark as new chat
    return session["thread_id"]

def reset_user_thread():
    """Reset thread for new chat."""
    if "thread_id" in session:
        try:
            project.agents.threads.delete(session["thread_id"])
        except Exception:
            pass
    session.clear()  # Clear entire session
    session["thread_id"] = create_clean_thread()
    session["is_new_chat"] = True
    print(f"[DEBUG] Reset thread for new chat: {session['thread_id']}")

def get_active_prefix():
    """Return the currently active document prefix for the user session"""
    return session.get("active_prefix")

def set_active_prefix(prefix):
    """Store the active document prefix in the user session."""
    session["active_prefix"] = prefix.lower()
    print(f"[DEBUG] Active prefix: {prefix}")

def clear_active_prefix():
    """Clear the active document prefix."""
    if "active_prefix" in session:
        print(f"[DEBUG] Cleared active prefix: {session['active_prefix']}")
        del session["active_prefix"]

def embed_query(text):
    """Generate embeddings for the user query using Azure AI Foundry."""
    try:
        response = embedding_client.embeddings.create(
            model=EMBED_DEPLOYMENT,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print("[ERROR] Embedding generation failed:", e)
        return None

# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.route("/")
def home():
    # Start fresh every time someone visits the home page
    reset_user_thread()
    return render_template("index.html")

@app.route("/new_chat", methods=["POST"])
def new_chat():
    """Explicit new chat endpoint."""
    reset_user_thread()
    return jsonify({"status": "New chat started"})

@app.route("/about")
def about():
    return render_template("about.html")

# ---------------------------------------------------------------------
# File Upload Endpoint
# ---------------------------------------------------------------------
@app.route("/upload_file", methods=["POST"])
def upload_file():
    thread_id = get_user_thread()
    file = request.files.get("doc_file")
    if not file:
        return jsonify({"response": "No file received."}), 400

    try:
        # save temporarily and upload to blob
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file.save(temp_file.name)
            blob_url = upload_file_to_blob(temp_file.name, file.filename)
        
        # Notify agent about the new document
        project.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=f"I have uploaded a document: {blob_url}. Please do NOT summarise it yet. Wait until I ask questions about it."
        )

        # Trigger indexer
        indexer_name = "mcpdocument-rag-search-indexer"
        indexer_url = f"{SEARCH_ENDPOINT}/indexers/{indexer_name}/run?api-version=2021-04-30-Preview"
        headers = {"api-key": SEARCH_KEY}
        resp = requests.post(indexer_url, headers=headers)
        print(f"[DEBUG] Indexer trigger: {resp.status_code}")

        return jsonify({
            "response": f"File uploaded successfully: {file.filename}",
            "blob_url": blob_url
        })
    except Exception as e:
        print("Upload error:", e)
        return jsonify({"response": f"Upload failed: {str(e)}"}), 500

# ---------------------------------------------------------------------
# Azure Cognitive Search Query
# ---------------------------------------------------------------------
def query_azure_search(query, thread_id):
    try:

        #Generate embedding for user query
        vector = embed_query(query)
        if vector is None:
            print("[ERROR] Query embedding failed.")
            return ""

        url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2024-07-01"
        headers = {"Content-Type": "application/json", "api-key": SEARCH_KEY}

        # -------------------------------------------------------------
        # Fetch document titles dynamically
        # -------------------------------------------------------------
        try:
            titles_url = (
                f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs"
                "?api-version=2023-07-01-Preview&$select=title,parent_id&$top=2000"
            )
            titles_response = requests.get(titles_url, headers=headers)
            #print(json.dumps(titles_response.json(), indent=2))
            titles_response.raise_for_status()
            title_docs = titles_response.json().get("value", [])

            titles = [d["title"] for d in title_docs]
            parents = {d["title"]: d.get("parent_id") for d in title_docs}

            known_prefixes = [t.split()[0].lower() for t in titles if t]
            #print(f"[DEBUG] Indexed document prefixes: {known_prefixes}")
        
        except Exception as e:
            print("[DEBUG] Title fetch error:", e)
            prefix_match = None

            # Detect prefix match from the user query
        prefix_match = None
        for prefix in known_prefixes:
            if prefix in query.lower():
                prefix_match = prefix
                break

        active_prefix = get_active_prefix()

        if prefix_match and prefix_match != active_prefix:
            print(f"[DEBUG] Switching document context (old: {active_prefix}, new: {prefix_match})")
            set_active_prefix(prefix_match)
        elif any(x in query.lower() for x in ["all documents", "every document", "all files"]):
            clear_active_prefix()
            print("[DEBUG] User requested search across all documents.")
        elif not prefix_match:
            prefix_match = get_active_prefix()
            if prefix_match:
                print(f"[DEBUG] Reusing active prefix: {prefix_match}")
            else:
                print("[DEBUG] No active prefix; searching all documents.")



        # -------------------------------------------------------------
        # AI behaviour: if a specific document is active, load FULL doc
        # -------------------------------------------------------------
        filter_condition = None
        if prefix_match:
            for t in titles:
                if t.lower().startswith(prefix_match):
                    parent_id = parents.get(t)
                    if parent_id:
                        filter_condition = f"parent_id eq '{parent_id}'"
                    break
        
        payload = {
            "search": query,
            "queryType": "semantic",
            "semanticConfiguration": "mcpdocument-rag-search-semantic-configuration",
            "select": "chunk,title,parent_id",
            "top": 12,
            "vectorQueries": [
                {
                    "kind": "vector",
                    "fields": "text_vector",
                    "k": 25,
                    "vector": vector
                }
            ]
        }

        if filter_condition:
            payload["filter"] = filter_condition
            print(f"[DEBUG] Using filter: {filter_condition}")
        
        url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2024-07-01"
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        results = resp.json().get("value", [])

        print(f"[DEBUG] Retrieved {len(results)} chunks from vector search.")

        if not results:
            return ""
        
        context_parts = []
        for r in results:
            title = r.get("title", "")
            chunk = r.get("chunk", "")
            context_parts.append(f"{title}\n{chunk}")
            
        full_context = "\n\n".join(context_parts)

        if len(full_context) > 180000:
            full_context = full_context[:180000] + "\n\n...[TRUNCATED]..."
            
        return full_context
    
    except Exception as e:
        print("Azure Search error:", e)
        print("status:", resp.status_code)
        print("url", url)
        print("payload sent:", json.dumps(payload, indent=2))
        print("Response:", resp.text)
        resp.raise_for_status
        return ""

# ---------------------------------------------------------------------
# Chat Endpoint - FIXED: Use consistent thread, not reset every message
# ---------------------------------------------------------------------
@app.route("/send_message", methods=["POST"])
def send_message():
    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"response": "No message provided."})

    try:
        # Use the same thread for the session - don't reset every message!
        thread_id = get_user_thread()

        context = query_azure_search(user_message, thread_id)
        if not context or not context.strip():
            return jsonify({"response": "No relevant information found in the provided documents."})

        # Build message
        MAX_CONTEXT = 180000
        if len(context) > MAX_CONTEXT:
            context = context[:MAX_CONTEXT] + "\n\n[Context truncated]"

        message_text = f"""CONTEXT:
{context}

QUESTION:
{user_message}"""

        # Send to agent
        project.agents.messages.create(
            thread_id=thread_id,
            role="user", 
            content=message_text
        )
        
        run = project.agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=agent.id
        )

        if run.status == "failed":
            return jsonify({"response": f" AI agent failed: {run.last_error}"})

        # Get response
        messages = list(project.agents.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.ASCENDING
        ))
        
        ai_response = ""
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.text_messages:
                ai_response = msg.text_messages[-1].text.value
                break
        
        return jsonify({"response": ai_response or "No response received."})

    except Exception as e:
        print("Agent error:", e)
        return jsonify({"response": f"Error: {str(e)}"})

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
