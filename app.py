from flask import Flask, request, jsonify, render_template, session, redirect
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from storage import create_chat_id, load_chat_list, save_chat_list, save_chat_message, load_chat_history, save_active_documents, load_active_documents, clear_active_documents, save_chat_thread_id, load_chat_thread_id, upload_file_to_blob
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

LOGIN_USERNAME = get_secret("Username")
LOGIN_PASSWORD = get_secret("Password")

LOW_INTENT = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}

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

def get_thread_for_chat(chat_id: str) -> str:
    """Get or create thread ID associated with chat ID."""

    threads_map = session.get("threads_by_chat", {})
    if chat_id in threads_map:
        return threads_map[chat_id]
    
    persisted = load_chat_thread_id(chat_id)
    if persisted:
        threads_map[chat_id] = persisted
        session["threads_by_chat"] = threads_map
        print(f"[DEBUG] Loaded persisted thread for chat {chat_id}: {persisted}")
        return persisted
    
    new_thread = create_clean_thread()
    save_chat_thread_id(chat_id, new_thread)
    threads_map[chat_id] = new_thread
    session["threads_by_chat"] = threads_map
    return new_thread

def embed_query(text: str):
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
    return render_template("index.html")

@app.route("/new_chat", methods=["POST"])
@login_required
def new_chat():
    """Explicit new chat endpoint."""
    chat_id = create_chat_id()

    chat_list = load_chat_list()
    if chat_id not in chat_list:
        chat_list.insert(0, chat_id)
        save_chat_list(chat_list)
    
    #create a new thread for this chat
    thread_id = create_clean_thread()
    save_chat_thread_id(chat_id, thread_id)

    # Cache in session
    threads_map = session.get("threads_by_chat", {})
    threads_map[chat_id] = thread_id
    session["threads_by_chat"] = threads_map

    #session.pop("chat_id", None)  # Clear chat ID for new chat
    return jsonify({"status": "New chat started", "chat_id": chat_id})

@app.route("/get_chat_list", methods=["GET"])
@login_required
def list_chats():
    """Endpoint to list all chats."""
    chat_list = load_chat_list()
    return jsonify([{"chat_id": cid} for cid in chat_list])

@app.route("/get_chat_history", methods=["GET"])
@login_required
def get_chat_history():
    """Endpoint to retrieve chat history."""
    chat_id = request.args.get("chat_id") #or get_chat_id()
    if not chat_id:
        return jsonify({"chat_history": [], "active_documents": []})
    try:
        chat_history = load_chat_history(chat_id)
        # Restore prefix
        active_docs = load_active_documents(chat_id)

        return jsonify({
            "chat_history": chat_history,
            "active_documents": active_docs
            })
    except Exception as e:
        print("Failed to load chat history error:", e)
        return jsonify({"chat_history": [], "active_documents": []})

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
    
    file = request.files.get("doc_file")
    chat_id = request.form.get("chat_id")
    if not file:
        return jsonify({"response": "No file received."}), 400

    if not chat_id:
        return jsonify({"response": "chat_id is required."}), 400

    try:
        # save temporarily and upload to blob
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file.save(temp_file.name)
            blob_url = upload_file_to_blob(temp_file.name, file.filename)

        # Trigger indexer
        indexer_name = "mcpdocument-rag-search-indexer"
        indexer_url = f"{SEARCH_ENDPOINT}/indexers/{indexer_name}/run?api-version=2021-04-30-Preview"
        headers = {"api-key": SEARCH_KEY}
        resp = requests.post(indexer_url, headers=headers)
        print(f"[DEBUG] Indexer trigger: {resp.status_code}")

        save_chat_message(chat_id, "assistant", f"File uploaded: {file.filename}")

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

def query_azure_search(query: str, chat_id: str): 
    try:
        vector = embed_query(query)
        if not vector:
            return ""

        headers = {
            "Content-Type": "application/json",
            "api-key": SEARCH_KEY
        }

        # -------------------------------------------
        # Load checkbox-selected documents for chat
        # -------------------------------------------
        selected_docs = load_active_documents(chat_id)  # <-- storage.py
        print("[DEBUG] Checkbox filters active:", selected_docs)

        filter_condition = None
        if selected_docs:
            # Map filenames → parent_ids
            titles_url = (
                f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs"
                "?api-version=2023-07-01-Preview&$select=title,parent_id&$top=2000"
            )
            titles_resp = requests.get(titles_url, headers=headers)
            titles_resp.raise_for_status()

            title_docs = titles_resp.json().get("value", [])
            parent_ids = [
                d["parent_id"]
                for d in title_docs
                if d["title"] in selected_docs
            ]

            if parent_ids:
                filter_condition = " or ".join(
                    [f"parent_id eq '{pid}'" for pid in parent_ids]
                )
                print("[DEBUG] Using checkbox filter:", filter_condition)

        # -------------------------------------------
        # Search payload (IMPORTANT CHANGES HERE)
        # -------------------------------------------
        payload = {
            "search": query,
            "queryType": "semantic",
            "semanticConfiguration": "mcpdocument-rag-search-semantic-configuration",
            "select": "chunk,title,parent_id",
            "top": 40,  # <-- increase retrieval depth
            "vectorQueries": [{
                "kind": "vector",
                "fields": "text_vector",
                "k": 40,
                "vector": vector
            }]
        }

        if filter_condition:
            payload["filter"] = filter_condition

        resp = requests.post(
            f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2024-07-01",
            headers=headers,
            json=payload
        )
        resp.raise_for_status()

        results = resp.json().get("value", [])
        print(f"[DEBUG] Retrieved {len(results)} chunks")

        if not results:
            return ""

        # -------------------------------------------
        # Aggregate by document
        # -------------------------------------------
        per_doc = {}
        for r in results:
            pid = r.get("parent_id")
            per_doc.setdefault(pid, []).append(
                f"{r.get('title','')}\n{r.get('chunk','')}"
            )

        # -------------------------------------------
        # Build final context (balanced across docs)
        # -------------------------------------------
        context_parts = []
        for pid, chunks in per_doc.items():
            context_parts.extend(chunks[:5])  # limit dominance per doc

        full_context = "\n\n".join(context_parts)

        return full_context[:180000]

    except Exception as e:
        print("Azure Search error:", e)
        return ""



def build_retrieval_query(chat_id: str, user_message: str, max_turns: int = 4) -> str:

    history = load_chat_history(chat_id)
    recent = history[-max_turns:] if history else []
    parts = []

    for m in recent:
        role = m.get("role", "")
        msg = (m.get("message", "") or "").strip()
        if not msg:
            continue

        if len(msg) > 400:
            msg = msg[:400] + "..."
        parts.append(f"{role.upper()}: {msg}")

    convo = "\n".join(parts)
    if convo:
        return f"{convo}\n\nUSER: {user_message}"
    return user_message


# ---------------------------------------------------------------------
# Chat Endpoint - FIXED: Use consistent thread, not reset every message
# ---------------------------------------------------------------------
@app.route("/send_message", methods=["POST"])
@login_required
def send_message():
    user_message = request.json.get("message", "").strip()
    chat_id = request.json.get("chat_id")

    if not user_message:
        return jsonify({"response": "No message provided."})
    
    if not chat_id:
        return jsonify({"response": "chat_id is required."})
    
    normalized = user_message.lower()
    selected_docs = load_active_documents(chat_id)

    if normalized in LOW_INTENT:
        return jsonify({
            "response": "Hi, What would you like to know, or which document should I look at?"
        })
    
    if not selected_docs and len(normalized.split()) < 3:
        return jsonify({
            "response": "Please select at least one document to assist with your query."
        })

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
        thread_id = get_thread_for_chat(chat_id)

        #retrieval_query = build_retrieval_query(chat_id, user_message, max_turns=4)
        retrieval_query = user_message
        context = query_azure_search(retrieval_query, chat_id)


        if not context.strip():
            return jsonify({"response": "No relevant information found in the selected documents."})
        
        #Add a small recent chat snippet for pronoun resolution
        recent = load_chat_history(chat_id)[-6:]
        recent_lines = []
        for m in recent:
            role = m.get("role", "")
            msg = (m.get("message", "") or "").strip()
            if len(msg) > 250:
                msg = msg[:250] + "..."
            recent_lines.append(f"{role.upper()}: {msg}")
        recent_block = "\n".join(recent_lines)

        system_note = ""
        if not selected_docs:
            system_note = (
                "SYSTEM NOTE: \n"
                "No document filters were selected. Context was retrived from all documents.\n\n "
            )

        instruction_block = """
INSTRUCTIONS:
You must answer using ONLY the information in CONTEXT.
You must include a section titled "References" after the answer.
Each reference must contain the document title.
Include a section identifier ONLY if it appears explicitly in the CONTEXT text.
Do NOT invent page numbers.
Do NOT invent section numbers.
Do NOT reference chunk IDs.
Do NOT mention system internals."""

        message_text = f"""{system_note}{instruction_block}
RECENT CHAT:    
{recent_block}

CONTEXT:
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


@app.route("/delete_chat", methods=["DELETE"])
@login_required
def delete_chat():

    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "No chat_id provided."}), 400

    print(f"[DELETE] Deleting chat_id: {chat_id}")   

    thread_id = load_chat_thread_id(chat_id)

    from storage import chat_container_client

    blobs_to_delete = [
        f"{chat_id}.json",
        f"{chat_id}_documents.json",
        f"{chat_id}_thread.json"
    ]

    for blob_name in blobs_to_delete:
        try:
            blob = chat_container_client.get_blob_client(blob_name)
            if blob.exists():
                blob.delete_blob()
                print(f"[DELETE] Deleted blob file: {blob_name}")
        except Exception as e:
            print(f"Failed to delete blob {blob_name} error:", e)

    
    #Remove from chat list
    chat_list = load_chat_list()
    if chat_id in chat_list:
        chat_list.remove(chat_id)
        save_chat_list(chat_list)
        print(f"[DELETE] Removed chat_id {chat_id} from chat list.")    

    #Remove from session cache
    threads_map = session.get("threads_by_chat", {})
    if chat_id in threads_map:
        threads_map.pop(chat_id, None)
        session["threads_by_chat"] = threads_map
        print(f"[DELETE] Removed chat_id {chat_id} from session cache.")

    #Delete agent thread
    if thread_id:
        try:
            project.agents.threads.delete(thread_id)
            print(f"[DELETE] Deleted agent thread: {thread_id}")
        except Exception as e:
            print(f"Failed to delete agent thread {thread_id} error:", e)

    return jsonify({"status": "Chat deleted.", })
    

@app.route("/get_filterdocuments", methods=["GET"])
@login_required
def get_filterdocuments():
    """Return list of documents for filtering."""
    try:
        blobs = []
        from storage import main_container_client
        for blob in main_container_client.list_blobs():
            blobs.append(blob.name)
        return jsonify(blobs)
    except Exception as e:
        print("Failed to retrieve document blobs error:", e)
        return jsonify([])


@app.route("/set_active_documents", methods=["POST"])
@login_required
def set_active_documents():
    data = request.json or {}
    chat_id = data.get("chat_id")
    documents = data.get("documents", [])

    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400

    # Store per-chat selection
    save_active_documents(chat_id, documents)

    print(f"[FILTER] Chat {chat_id} documents set to: {documents}")
    return jsonify({"status": "ok", "active_documents": documents})

""" @app.route("/update_chat_filters", methods=["POST"])
@login_required
def update_chat_filters():
    data = request.json
    chat_id = data["chat_id"]
    filters = data["filters"]

    save_chat_filters(chat_id, filters)
    return jsonify({"status": "ok"}) """

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
