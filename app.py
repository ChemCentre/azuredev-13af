"""
PitPixie – AI Document Analysis Tool

Author: Vanessa Perera

Description:
Main Flask application for the PitPixie system. This file handles the web
interface, chat interactions with the AI agent, document uploads, and
integration with Azure services used in the Retrieval-Augmented Generation (RAG)
pipeline.

Technologies Used:
- Flask (Python web framework)
- Azure AI Foundry Agents
- Azure Cognitive Search
- Azure Blob Storage
- Azure Content Understanding
- Azure Key Vault

This prototype was developed within the Shared Environmental Analytics
Facility (SEAF) Azure environment.
"""

import os
import threading
from flask import Flask, request, jsonify, render_template, session, redirect
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from openai import AzureOpenAI
from storage import create_chat_id, load_chat_list, save_chat_list, save_chat_message, load_chat_history, save_active_documents, load_active_documents, save_chat_thread_id, load_chat_thread_id, upload_file_to_blob, upload_page_map, load_page_map, generate_read_sas_for_blob
from content_understanding import debug_cu_printed_page_number, run_page_analyzer, build_page_map
from load_secrets import get_secret
from dotenv import load_dotenv
import tempfile
import requests
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
API_VERSION = "2024-02-01"

LOGIN_USERNAME = get_secret("Username")
LOGIN_PASSWORD = get_secret("Password")

CU_ENDPOINT = get_secret("cu-endpoint")
CU_KEY = get_secret("cu-key")
CU_ANALYZER_ID = get_secret("cu-analyzer-id")
CU_API_VERSION = "2025-05-01-preview"

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
PAGE_MAP_CACHE = {}



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

    print("[DEBUG] EMBED_ENDPOINT:", EMBED_ENDPOINT)
    print("[DEBUG] EMBED_DEPLOYMENT:", EMBED_DEPLOYMENT)
    print("[DEBUG] EMBED_API_VERSION:", API_VERSION)

    if not EMBED_ENDPOINT or "openai.azure.com" not in EMBED_ENDPOINT:
        print("[ERROR] EMBED_ENDPOINT does not look like an Azure OpenAI endpoint.")
        return None

    if not EMBED_DEPLOYMENT:
        print("[ERROR] EMBED_DEPLOYMENT is empty.")
        return None

    try:
        response = embedding_client.embeddings.create(
            model=EMBED_DEPLOYMENT,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print("[ERROR] Embedding generation failed:", e)
        return None
    
def extract_page_index_from_chunk_id(chunk_id: str) -> int|None:
    if not chunk_id:
        return None
    m = re.search(r"_pages_(\d+)", chunk_id)
    if m:
        return int(m.group(1))
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


def get_page_map_cached(title: str) -> dict:
    """Retrieve or load the page map for a document title."""
    if not title:
        return {}
    if title in PAGE_MAP_CACHE:
        return PAGE_MAP_CACHE[title]
    m = load_page_map(title)
    PAGE_MAP_CACHE[title] = m or {}
    return PAGE_MAP_CACHE[title]
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

def get_active_prefix():
    """Return the currently active document prefix for the user session."""
    return session.get("active_prefix")

def set_active_prefix(prefix):
    """Store the active document prefix in the user session."""
    session["active_prefix"] = prefix.lower()
    print(f"[DEBUG] Active document prefix set to: {prefix}")

def clear_active_prefix():
    """Clear the active document prefix """
    if "active_prefix" in session:
        print(f"[DEBUG] Cleared active prefix: {session['active_prefix']}")
        del session["active_prefix"]


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
    chat_id = request.args.get("chat_id") 
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

            mine = request.form.get("mine_name")

            if not mine:
                return jsonify({"response": "Mine folder is required."}), 400
            
            blob_path = f"{mine}/{file.filename}"

            blob_url = upload_file_to_blob(temp_file.name, blob_path)

            print("[DEBUG] Mine selected:", mine)
            print(f"[DEBUG] Uploaded file to blob: {blob_url}")

            print(f"[DEBUG] local file path", temp_file.name)
            print(f"[DEBUG] file exists:", os.path.exists(temp_file.name))
            print(f"[DEBUG] file size:", os.path.getsize(temp_file.name))
            
            sas_url = generate_read_sas_for_blob(blob_path)
            print(f"[DEBUG] Generated SAS URL for blob: {sas_url}")
            print(f"[DEBUG] Starting CU background extraction for {file.filename}")

            threading.Thread(
                target=run_cu_background, 
                args=(temp_file.name, blob_path, sas_url, file.filename),
                daemon=True
                ).start()

        save_chat_message(chat_id, "assistant", f"File uploaded: {file.filename}")

        return jsonify({
            "response": f"File uploaded successfully: {file.filename}",
            "blob_url": blob_url
        })
    except Exception as e:
        print("Upload error:", e)
        return jsonify({"response": f"Upload failed: {str(e)}"}), 500


def run_cu_background(temp_path, blob_path, sas_url, filename):
    try:
        print(f"[CU] Starting extraction: {filename}")

        cu_result = run_page_analyzer(
            sas_url, 
            CU_ENDPOINT, 
            CU_API_VERSION, 
            CU_ANALYZER_ID)
        
        debug_cu_printed_page_number(cu_result)
        page_map = build_page_map(cu_result)

        if page_map:
            upload_page_map(blob_path, page_map)

            PAGE_MAP_CACHE[blob_path] = page_map

            print(f"[CU] Page map saved: {filename} ({len(page_map)} pages)")

        else:
            print(f"[CU] Empty page map returned for {filename}")
        
    except Exception as e:
        print(f"[CU] Extraction failed for {filename}: {e}")

    finally:

        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print(f"[CU] Temporary file removed: {filename}")
        except Exception as e:
            print(f"[CU] Failed to remove temporary file for {filename}: {e}")

@app.route("/run_indexer", methods=["POST"])
@login_required
def run_indexer():

    indexer_name = "mcpdocument-rag-search-indexer"
    indexer_url = f"{SEARCH_ENDPOINT}/indexers/{indexer_name}/run?api-version=2021-04-30-Preview"
    headers = {"api-key": SEARCH_KEY}
    requests.post(indexer_url, headers=headers)
    print("[INDEXER] Indexer triggered manually.")
    return jsonify({"response": "Indexer started."})

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

        if not selected_docs:
            print("No documents are selected.")
            return ""


        if selected_docs:
            # Map filenames → parent_ids
            titles_url = (
                f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs"
                "?api-version=2023-07-01-Preview&$select=title,parent_id&$top=2000"
            )
            titles_resp = requests.get(titles_url, headers=headers)
            titles_resp.raise_for_status()

            title_docs = titles_resp.json().get("value", [])

            parent_ids = []

            for d in title_docs:
                full_title = d.get("title", "")

                if full_title in selected_docs:
                    parent_ids.append(d.get("parent_id"))

            if parent_ids:
                filter_condition = " or ".join(
                    [f"parent_id eq '{pid}'" for pid in parent_ids]
                )
                print("[DEBUG] Using checkbox filter:", filter_condition)

        # -------------------------------------------
        # Search payload 
        # -------------------------------------------
        payload = {
            "search": query,
            "queryType": "semantic",
            "semanticConfiguration": "mcpdocument-rag-search-semantic-configuration",
            "select": "chunk,title,parent_id,chunk_id",
            "top": 40,  # <-- retrieval depth
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
            title = r.get("title","")
            chunk = r.get("chunk", "")
            chunk_id = r.get("chunk_id")

            if not pid:
                continue

            page_idx = extract_page_index_from_chunk_id(chunk_id)

            printed_page = None
            if title and page_idx is not None:
                page_map = get_page_map_cached(title)

                if not page_map:
                    for key in PAGE_MAP_CACHE.keys():
                        if key.endswith(title):
                            page_map = PAGE_MAP_CACHE[key]
                            print(f"[DEBUG] Found page map for {title} by suffix match: {key}")
                            break

                printed_page = page_map.get(str(page_idx)) 

            print("[PAGE MAP DEBUG]",
                  "title=", title,
                  "chunk_id=", chunk_id,
                  "page_idx=", page_idx,
                  "printed_page=", printed_page)
            
            if printed_page:
                page_text = f"(Printed Page: {printed_page})"
            else:
                page_text = f"Printed page: not available (PDF page {page_idx})"
            
            per_doc.setdefault(pid, []).append(
                f"[{title} - {page_text}]\n{chunk}"
            )
        # -------------------------------------------
        # Build final context 
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
# Chat Endpoint - Use consistent thread, not reset every message
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

    # Low intent handling
    if normalized in LOW_INTENT:
        return jsonify({
            "response": "Hi, What would you like to know, or which document should I look at?"
        })
    
    #No docs selected
    if not selected_docs:
        return jsonify({
            "response": "Please select at least one document to assist with your query."
        })
    
    #Save User message
    chat_list = load_chat_list()
    if chat_id not in chat_list:
        chat_list.insert(0, chat_id)
        save_chat_list(chat_list)

    try:
        save_chat_message(chat_id, "user", user_message)
    except Exception as e:   
        print("Failed to save chat message error:", e)

    try:
        # Use the same thread for the session - don't reset every message
        thread_id = get_thread_for_chat(chat_id)

        retrieval_query = user_message
        context = query_azure_search(retrieval_query, chat_id)

        if not context.strip():
            return jsonify({"response": "No relevant information found in the selected documents."})
        
        clean_names = [doc.split("/")[-1] for doc in selected_docs]
        selected_list = "\n".join([f"- {doc}" for doc in clean_names])

        meta_keywords = [
            "what documents",
            "which documents",
            "selected documents",
            "what have I selected"
        ]

        is_meta_question = any(k in normalized for k in meta_keywords)

        selected_docs_prompt = f"""
Selected Documents:
The user has selected the following documents for this chat:
{selected_list}

If the user asks which documents are selected, list EXACTLY these documents names.
Do NOT add, remove, or invent any documents.
"""

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
        if is_meta_question:
            instruction_block = """
INSTRUCTIONS:

You MUST follow these formatting rules exactly.

FORMAT RULES: 
- Each document MUST be on its own line 
- Each line MUST begin with "- " 
- Show ONLY the file name (no folder path) 
- Do NOT include a References section 
- Do NOT combine multiple documents on one line 

OUTPUT EXAMPLE: 
You have selected: 
- document1.pdf 
- document2.pdf 
- document3.pdf
"""
        else:
            instruction_block = """
INSTRUCTIONS:

You MUST follow these formatting rules exactly.

RESPONSE FORMAT RULES:
- Use clear structured formatting..
- Each new point MUST start on a new line.
- Use bullet points ("- ") for lists where appropriate.
- Do NOT write everything in one paragraph.
- Leave a blank line between sections.
- Make responses easy to read.

CONTENT RULES:
You must answer using ONLY the information in CONTEXT.
If the answer is not contained in the CONTEXT, say that the information is not available in the selected documents.

REFERENCES RULES:
You must include a section titles "References" at the end.

The References section MUST:
 - Start with the word: References
 - Each reference MUST be on a new line
 - Each reference MUST begin with "- "
 - Include the document file name
 - Include printed page number if available (e.g. "Printed page: 12")

 OUTPUT EXAMPLE:
 Three pit voids will remain at closure:
 - Darlot Main Pit
 - Eldorado Pit
 - Western Deep Leads Pit

References:
- document1.pdf (Printed page: 12)
- document2.pdf (Printed page: 5)

DO NOT:
- Invent references.
- Do NOT invent page numbers.
- Mention chunk IDs or system internals.

"""

        message_text = f"""{selected_docs_prompt}{instruction_block}
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
        
        ai_response = format_agent_response(ai_response)
        
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
    try:
        from storage import main_container_client
        structure = {}

        Excluded_prefixes = [
            "labelingProjects",
            "analyzerResults",
            "analyzer",
            "contentunderstanding",
            "cu-results",
            ".labels",
            ".ocr",
        ]

        Excluded_Extensions = [
            ".labels.json",
            ".result.json"
        ]

        for blob in main_container_client.list_blobs():

            blob_name = blob.name

            if any(blob_name.startswith(prefix) for prefix in Excluded_prefixes):
                continue

            if any(blob_name.endswith(ext) for ext in Excluded_Extensions):
                continue

            if blob_name.startswith("."):
                continue

            if "/" in blob_name:
                mine, filename = blob_name.split("/", 1)
            else:
                mine = "Uncategorized"
                filename = blob_name

            if filename == ".init":
                continue
            
            structure.setdefault(mine, []).append(filename)

        return jsonify(structure)
    
    except Exception as e:
        print("Failed to retrieve document blobs error", e)
        return jsonify({})

def format_agent_response(text: str) -> str:
    """Format the agent response for better readability."""
    if not text:
        return text

    text = text.strip()
    
    #Normalize spacing
    text = text.replace("\r", "")

    #Ensure references section is on its own line
    text = re.sub(r"(?i)References:", "\n\nReferences:\n", text, flags=re.IGNORECASE)

    #Split inline bullet lists
    text = re.sub(r":\s*-\s", ":\n\n- ", text)

    #Ensure all "-" bullets start on new line
    text = re.sub(r"\s+-\s+", "\n- ", text)

    #Fix multiple bullets on same line
    text = re.sub(r"(- [^\n]+)\s+- ", r"\1\n- ", text)

    #Clean extra blank lines
    lines = [line.strip() for line in text.split("\n")]
    cleaned_lines = []
    prev_blank = False

    for line in lines:
        if line == "":
            if not prev_blank:
                cleaned_lines.append(line)
            prev_blank = True
        else:
            cleaned_lines.append(line)
            prev_blank = False
    
    formatted = "\n".join(cleaned_lines)

    return formatted.strip()

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

@app.route("/create_mine", methods=["POST"])
@login_required
def create_mine():
    data = request.json or {}
    mine_name = data.get("mine_name", "").strip()

    if not mine_name:
        return jsonify({"error": "Mine name required"}), 400
    
    from storage import main_container_client

    try:
        placeholder_blob = f"{mine_name}/.init"

        blob = main_container_client.get_blob_client(placeholder_blob)
        blob.upload_blob(b"", overwrite=True)

        return jsonify({"status": "mine created"})
    
    except Exception as e:
        print("Create mine error:", e)
        return jsonify({"error": "Failed to create mine"}), 500
    
@app.route("/get_mines", methods=["GET"])
@login_required
def get_mines():
    from storage import main_container_client

    mines = set()

    try:
        blobs = main_container_client.list_blobs()

        for blob in blobs:
            if "/" in blob.name:
                mine = blob.name.split("/")[0]
                mines.add(mine)
        
        return jsonify(sorted(list(mines)))
    
    except Exception as e:
        print("Get mines error:", e)
        return jsonify([])

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
