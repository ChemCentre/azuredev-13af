from flask import Flask, request, jsonify, render_template, session
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from storage import upload_file_to_blob
from load_secrets import get_secret
from dotenv import load_dotenv
import tempfile
import requests
import time
import json
import re

load_dotenv()

# Secure configuration via Azure Key Vault

ENDPOINT = get_secret("azure-endpoint")
AGENT_ID = get_secret("agent-id")

SEARCH_ENDPOINT = get_secret("azure-search-endpoint")
SEARCH_INDEX = get_secret("azure-search-index")
SEARCH_KEY = get_secret("azure-search-key")
FLASK_SECRET_KEY = get_secret("flask-secret-key")

# Flask setup
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Azure AI agent setup
project = AIProjectClient(credential=DefaultAzureCredential(), endpoint=ENDPOINT)
agent = project.agents.get_agent(AGENT_ID)

LAST_CONTEXT = {}
CONVERSATION_HISTORY = {}

#---------------------------------------------------------------------
#Utility Functions
#---------------------------------------------------------------------

# Per-User Thread Handling
def get_user_thread():
    """Retrieve or create a conversation thread for the user session."""
    if "thread_id" not in session:
        thread = project.agents.threads.create()
        session["thread_id"] = thread.id
        print(f"Created new thread for user: {thread.id}")
    return session["thread_id"]

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
def home():
    get_user_thread()
    return render_template("index.html")

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
        return jsonify({"response": " No file received."}), 400

    try:
        #save temporarily and upload to blob
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file.save(temp_file.name)
            blob_url = upload_file_to_blob(temp_file.name, file.filename)

        # Notify agent about the new document
        project.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=f"I have uploaded a document: {blob_url}. Please do NOT summarise it yet. Wait until I ask questions about it."
        )

        #Trigger Azure Cognitive Search indexer (instant indexing)
        indexer_name = "mcpdocument-search-indexer"
        indexer_url = f"{SEARCH_ENDPOINT}/indexers/{indexer_name}/run?api-version=2021-04-30-Preview"
        headers = {"api-key": SEARCH_KEY}

        try:
            trigger_response = requests.post(indexer_url, headers=headers)
            if trigger_response.status_code in [200, 202]:
                print(f"Indexer '{indexer_name}' triggered successfully.")
            else:
                print(f"Indexer trigger warning: {trigger_response.status_code} - {trigger_response.text}")
        except Exception as trigger_error:
            print("Failed to trigger indexer:", {trigger_error})

        return jsonify({
            "response": f" File uploaded successfully: {file.filename}",
            "blob_url": blob_url
        })

    except Exception as e:
        print("Upload error:", e)
        return jsonify({"response": f" Upload failed: {str(e)}"}), 500

# ---------------------------------------------------------------------
# Azure Cognitive Search Query
# ---------------------------------------------------------------------
def query_azure_search(query, thread_id):
    """Queries Azure Cognitive Search and returns top results."""
    
    try:
        url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2021-04-30-Preview"
        headers = {
            "Content-Type": "application/json",
            "api-key": SEARCH_KEY
        }

        prefix_match = None
        known_prefixes = []
        titles_data = []

        #Fetch document titles dynamically from the index

        try:
            titles_url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs?api-version=2021-04-30-Preview&$select=title&$top=50"
            titles_response = requests.get(titles_url, headers=headers)
            titles_response.raise_for_status()
            titles_data = [d["title"] for d in titles_response.json().get("value", [])]
            known_prefixes = [t.split()[0].lower() for t in titles_data if t]
            print(f"[DEBUG] Indexed document prefixes: {known_prefixes}")

            #Detect prefix in user query (first occurence only)
            for prefix in known_prefixes:
                if prefix.lower() in query.lower():
                    prefix_match = prefix
                    break

            active_prefix = get_active_prefix()
            if prefix_match and prefix_match != active_prefix:
                print(f"[DEBUG] Switching document - resetting verbosity context (old: {active_prefix}, new: {prefix_match}).")

                try:
                    if "thread_id" in session:
                        project.agents.threads.delete(session["thread_id"])
                    new_thread = project.agents.threads.create()
                    session["thread_id"] = new_thread.id
                    print("[DEBUG] Created new thread after prefix switch: {new_thread.id}")
                except Exception as e:
                    print("[DEBUG] Thread reset failed:", e)
                
                set_active_prefix(prefix_match)

            elif any(x in query.lower() for x in ["all documents", "every document", "all files"]):
                clear_active_prefix()
                print("[DEBUG] User requested search across all documents.")
            elif not prefix_match:
                prefix_match = get_active_prefix()
                if prefix_match:
                    print(f"[DEBUG] Reusing active prefix from session: {prefix_match}")
                else:
                    print(f"[DEBUG] No prefix active; searching all documents.")

        except Exception as e:
            print(f"[DEBUG] Could not fetch titles:", e)
            
        # Split the query intelligently
        subqueries = [q.strip() for q in re.split(r"\band\b|&|;|,|then|also", query, flags=re.IGNORECASE) if q.strip()]
        all_chunks = []
        MAX_DOC_CHARS = 60000  # Cap each document to ~60KB

        for subquery in subqueries:
            payload = {
                "search": subquery,
                "queryType": "semantic",
                "semanticConfiguration": "mcpdocument-search-semantic-configuration",
                "queryLanguage": "en-us",
                "captions": "extractive|highlight-false",
                "answers": "extractive|count-3",
                "select": "chunk,title,merged_content",
                "top":10,#Limit results
                "count": True,
                "searchMode": "all",
                "speller": "lexicon",
            }

            #Restrict to document title if prefix matched
            if prefix_match:
                matching_title = next((t for t in titles_data if t.lower().startswith(prefix_match.lower())),None)
                if matching_title:
                    escsaped_title = matching_title.replace("'", "''")
                    payload["filter"] = f"title eq '{escsaped_title}'"
                    print(f"[DEBUG] Restricting search to document: {matching_title}")

            
            #Run main search
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            
            total_matches = data.get("@odata.count", 0)
            print(f"[DEBUG] Azure search returned {total_matches} chunks for query: '{query}'")


            print(f"[DEBUG] Retrieved {len(data.get('value', []))} docs for subquery: {subquery}")
    
        # --- Fallback to keyword search if no semantic results ---
            if not data.get("value"):
                print("No semantic results, falling back to keyword search...")

                fallback_payload= {
                    "search": query,
                    "top": 10,
                    "searchMode": "all",
                    "select": "chunk,title,merged_content",
                    "queryType": "simple"
                }
                 #Apply file title filter if specific document requested
                if prefix_match:
                    fallback_payload["filter"] = payload.get("filter")

                response = requests.post(url, headers=headers, json=fallback_payload)
                response.raise_for_status()
                data = response.json()

            #Collect and Clean content
            for doc in data.get("value", []):
                title = doc.get("title", "")
                raw_content = doc.get("chunk") or doc.get("merged_content") or ""
                content = ""

                #safer content parsing
                try:
                    parsed = json.loads(raw_content)
                    if isinstance(parsed, dict) and "text" in parsed:
                        content = "\n".join(parsed["text"])
                    elif isinstance(parsed, list):
                        content = "\n".join(str(x) for x in parsed)
                    else:
                        content=str(raw_content)
                except Exception:
                    content = str(raw_content)

                if len(content.strip()) < 500 and doc.get("merged_content"):
                    content = doc.get("merged_content")

                if len(content) > MAX_DOC_CHARS:
                    content = content[:MAX_DOC_CHARS] + "\n...[TRUNCATED]..."
                all_chunks.append(f"{title}\n{content}")

        #Merge all results
        merged_context = "\n\n".join(all_chunks)
        merged_context = "\n".join(line for line in merged_context.splitlines() if len(line.strip())<=3000)

        if merged_context.strip():
            LAST_CONTEXT[thread_id] = {"query": query, "context": merged_context}

        print(f"Retrieved {len(all_chunks)} chunks from {len(subqueries)} subqueries.")
        print(f"[DEBUG] Total context length: {len(merged_context)}")
        print(f"[DEBUG] Preview: {merged_context[:400]}")

        return merged_context or "No relevant documents found."
    
    except Exception as e:
        print("Azure Search error:", e)
        return ""


# ---------------------------------------------------------------------
# Chat Endpoint
# ---------------------------------------------------------------------
@app.route("/send_message", methods=["POST"])
def send_message():
    user_message = request.json.get("message", "")
    if not user_message:
        return jsonify({"response": "No message provided."})

    try:
        #create a fresh thread per question to avoid previous context bleed.
        thread = project.agents.threads.create()
        thread_id = thread.id

        # Search Azure Cognitive Search
        context = query_azure_search(user_message, thread_id)
        if not context.strip():
            return jsonify({"response": "No relevant information found in the provided documents."})

        # Truncate total context to stay under 256k limit
        MAX_CONTEXT_CHARS = 180000
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS] + "\n\n[⚠️ Context truncated due to size limit.]"

        # Build final message
        combined_message = f"""      
        CONTEXT:
        {context}

        QUESTION:
        {user_message}
        """

        # Send to Azure Agent with retry on rate limit
        MAX_TRIES = 5
        for attempt in range(MAX_TRIES):
            try:
                project.agents.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=combined_message
                )
                time.sleep(1.2) # Small delay to prevent back-to-back throttling
                run = project.agents.runs.create_and_process(
                    thread_id=thread_id,
                    agent_id=agent.id
                )

                if run.status != "failed" or "rate_limit" not in str(run.last_error).lower():
                    break
                print(f"Rate limit hit, retrying in {5 * (attempt + 1)}s...")
                time.sleep(5 * (attempt + 1))

            except Exception as e:
                if "rate_limit" not in str(e).lower():
                    print(f"Rate limit hit, retrying in {attempt + 1}s...")
                    time.sleep(5 * (attempt + 1))
                else:
                    raise
        else:
            return jsonify({"response": " Too many retries. Please wait a moment and try again."})

        if run.status == "failed":
            return jsonify({"response": f"AI agent failed: {run.last_error}"})

        # Retrieve latest AI message
        messages = list(project.agents.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.ASCENDING
        ))

        ai_response = ""
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.text_messages:
                ai_response = msg.text_messages[-1].text.value
                break

        return jsonify({"response": ai_response or "🤖 No response received."})

    except requests.exceptions.RequestException as e:
        print("Search error:", e)
        return jsonify({"response": f"Error querying search: {str(e)}"})

    except Exception as e:
        print("Agent error:", e)
        return jsonify({"response": f"Error talking to agent: {str(e)}"})

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
