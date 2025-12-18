from flask import Flask, request, jsonify, render_template, session, redirect
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from storage import upload_file_to_blob, save_chat_message,load_chat_history,create_chat_id,load_chat_list,save_chat_list,save_chat_prefix
from load_secrets import get_secret
from dotenv import load_dotenv
import tempfile
import requests
import uuid
import time
import json
import os
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

#LOGIN_USERNAME = get_secret("login-username")
#LOGIN_PASSWORD = get_secret("login-password")
LOGIN_USERNAME = "admin"
LOGIN_PASSWORD = "admin123"

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

    #session.clear()  # Clear entire session
    session["thread_id"] = create_clean_thread()
    session["is_new_chat"] = True
    session.pop("active_prefix", None)
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
    
""" def get_chat_id():
    if "chat_id" not in session:
        session["chat_id"] = create_chat_id()
    return session["chat_id"] """

def get_chat_id():
    """
    Returns the current chat id for this session.
    If none yet, creates one and ensures it's in the global chat list.
    """
    chat_id = session.get("chat_id")
    if not chat_id:
        chat_id = create_chat_id()
        session["chat_id"] = chat_id

        # Ensure chat list contains this chat
        chat_list = load_chat_list()
        if chat_id not in chat_list:
            chat_list.insert(0, chat_id)  # newest first
            save_chat_list(chat_list)

        print(f"[CHAT] New chat_id created and saved: {chat_id}")
    return chat_id


#---------------------------------------------------------------------
# Authentication decorator
#---------------------------------------------------------------------

def login_required(route_function):
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"error": "Authentication required"}), 401
            return redirect("/login")
        return route_function(*args, **kwargs)
    wrapper.__name__ = route_function.__name__
    return wrapper

#---------------------------------------------------------------------
# Login route
#---------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Render login page and handle authentication."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
            session["authenticated"] = True
            return redirect("/")
        else:
            return render_template("login.html", error="Invalid credentials. Please try again.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    """Log out the user by clearing the session."""
    session.clear()
    return redirect("/login")

# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.route("/")
@login_required
def home():
    # Start fresh every time someone visits the home page
    if "thread_id" not in session:
        session["thread_id"] = create_clean_thread()
        #reset_user_thread()
    #chat_history = load_chat_history(get_chat_id())
    return render_template("index.html")
    #return render_template("index.html")

@app.route("/new_chat", methods=["POST"])
@login_required
def new_chat():
    """Explicit new chat endpoint."""
    reset_user_thread()
    session.pop("active_prefix", None)
    chat_id = create_chat_id()

    chat_list = load_chat_list()
    chat_list.append(chat_id)
    save_chat_list(chat_list)

    #session.pop("chat_id", None)  # Clear chat ID for new chat
    return jsonify({"status": "New chat started", "chat_id": chat_id})

@app.route("/get_chat_list", methods=["GET"])
@login_required
def list_chats():
    """Endpoint to list all chats."""
    chat_list = load_chat_list()
    return jsonify([{"chat_id": cid} for cid in chat_list])

@app.route("/chat/<chat_id>", methods=["GET"])
@login_required
def get_chat(chat_id):
     """Endpoint to load a specific chat by ID."""
     chat_history = load_chat_history(chat_id)
     return jsonify({"chat_history": chat_history})

@app.route("/about")
@login_required
def about():
    return render_template("about.html")

# ---------------------------------------------------------------------
# File Upload Endpoint
# ---------------------------------------------------------------------
@app.route("/upload_file", methods=["POST"])
@login_required
def upload_file():
    thread_id = get_user_thread()
    file = request.files.get("doc_file")
    chat_id = request.form.get("chat_id")
    if not file:
        return jsonify({"response": "No file received."}), 400

    if not chat_id:
        chat_id = get_chat_id()

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
def query_azure_search(query, thread_id, chat_id):
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

            try:
                save_chat_prefix(chat_id, prefix_match)
                print(f"[DEBUG] Saved chat prefix: {prefix_match} for chat: {chat_id}")
            except Exception as e:
                print("Failed to save chat prefix error:", e)

        elif any(x in query.lower() for x in ["all documents", "every document", "all files"]):
            clear_active_prefix()

            try:
                save_chat_prefix(chat_id, None)
                print(f"[DEBUG] Cleared chat prefix for chat: {chat_id}")
            except Exception as e:
                print("Failed to clear chat prefix error:", e)

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
@login_required
def send_message():
    user_message = request.json.get("message", "").strip()

    if not user_message:
        return jsonify({"response": "No message provided."})
    
    chat_id = request.json.get("chat_id")

    if not chat_id:
        chat_id = get_chat_id()

    chat_list = load_chat_list()
    if chat_id not in chat_list:
        chat_list.insert(0, chat_id)
        save_chat_list(chat_list)

    try:
        save_chat_message(chat_id, "user", user_message)
    except Exception as e:   
        print("Failed to save chat message error:", e)

    try:
        # Use the same thread for the session - don't reset every message!
        thread_id = get_user_thread()

        context = query_azure_search(user_message, thread_id, chat_id)

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
        
        # Save chat to blob history
        try:
            save_chat_message(chat_id, "assistant", ai_response)
        except Exception as e:   
            print("Failed to save AI chat message error:", e)
        
        return jsonify({"response": ai_response or "No response received."})

    except Exception as e:
        print("Agent error:", e)
        return jsonify({"response": f"Error: {str(e)}"})

@app.route("/get_chat_history", methods=["GET"])
@login_required
def get_chat_history():
    """Endpoint to retrieve chat history."""
    chat_id = request.args.get("chat_id") #or get_chat_id()
    if not chat_id:
        return jsonify({"chat_history": []})
    try:
        chat_history = load_chat_history(chat_id)
        # Restore prefix
        prefix = load_chat_history("chat_id")
        session["active_prefix"] = prefix

        return jsonify({
            "chat_history": chat_history,
            "active_prefix": prefix
            })
    except Exception as e:
        print("Failed to load chat history error:", e)
        return jsonify({"chat_history": []})

@app.route("/delete_chat", methods=["DELETE"])
@login_required
def delete_chat():

    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "No chat_id provided."}), 400

    print(f"[DELETE] Deleting chat_id: {chat_id}")   

    # Delete chat history blob
    try:
        from storage import chat_container_client
        blob_name = f"{chat_id}.json"
        blob_client = chat_container_client.get_blob_client(blob_name)

        if blob_client.exists():
            blob_client.delete_blob()
            print(f"[DELETE] Deleted blob file: {blob_name}") 
        else:
            print(f"[DELETE] Blob file not found: {blob_name}")
    
    except Exception as e:
        print("Failed to delete chat blob error:", e)
        return jsonify({"error": f"Failed to delete chat file"}), 500
    
    # Remove from chat list
    try:
        chat_list = load_chat_list()

        if chat_id in chat_list:
            chat_list.remove(chat_id)
            save_chat_list(chat_list)
            print(f"[DELETE] Removed chat_id from chat list: {chat_id}")
        else:
            print(f"[DELETE] chat_id not found in chat list: {chat_id}")

    except Exception as e:
        print("Failed to update chat list error:", e)
        return jsonify({"error": "Failed to update chat list"}), 500
    
    if session.get("chat_id") == chat_id:
        session.pop("chat_id", None)
        print(f"[DELETE] Cleared chat_id from session: {chat_id}")
    
    return jsonify({"status": "Chat deleted successfully."})

@app.route("/get_documents", methods=["GET"])
@login_required
def get_documents():
    """Return list of documents for filtering."""
    try:
        headers = {"Content-Type": "application/json", "api-key": SEARCH_KEY}
        url = (f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs""?api-version=2023-07-01-Preview&$select=title,parent_id&$top=2000" )
        resp = requests.get(url, headers=headers)
        resp.raise_for_status() 
        docs = resp.json().get("value", [])

        seen = {}
        for d in docs:
            pid = d.get("parent_id")
            title = d.get("title")
            if pid and title and pid not in seen:
                seen[pid] = {
                    "parent_id": pid,
                    "title": title
                }
        return jsonify({"documents": list(seen.values())})
    except Exception as e:
        print("Failed to retrieve documents error:", e)
        return jsonify({"documents": []})

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
