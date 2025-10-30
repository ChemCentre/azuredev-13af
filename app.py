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

# Per-User Thread Handling
def get_user_thread():
    """Retrieve or create a conversation thread for the user session."""
    if "thread_id" not in session:
        thread = project.agents.threads.create()
        session["thread_id"] = thread.id
        print(f"Created new thread for user: {thread.id}")
    return session["thread_id"]

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
                "top":5,  # Limit results
                "searchMode": "all",
                "speller": "lexicon"
            }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        print(f"Searched returned {len(data.get('value', []))} docs for query: {query}")
    
        # --- Fallback to keyword search if no semantic results ---
        if not data.get("value"):
            print("No semantic results, falling back to keyword search...")

            fallback_payload= {
                "search": query,
                "top": 5,
                "searchMode": "all",
                "select": "chunk,title,merged_content",
                "queryType": "simple"
            }

            response = requests.post(url, headers=headers, json=fallback_payload)
            response.raise_for_status()
            data = response.json()

        for doc in data.get("value", []):
            title = doc.get("title", "")
            raw_content = doc.get("chunk") or doc.get("merged_content") or ""
            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, dict) and "text" in parsed:
                    content = " ".join(parsed["text"])
            except Exception:
                pass


            if len(content) > MAX_DOC_CHARS:
                content = content[:MAX_DOC_CHARS] + "\n...[TRUNCATED]..."
            all_chunks.append(f"{title}\n{content}")

        #Merge all results
        merged_context = "\n\n".join(all_chunks)
        merged_context = "\n".join([line for line in merged_context.splitlines() if len(line.strip())< 1500])

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

        # ✅ Truncate total context to stay under 256k limit
        MAX_CONTEXT_CHARS = 180000
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS] + "\n\n[⚠️ Context truncated due to size limit.]"

        # Build final message
        combined_message = f"""
       Use the following CONTEXT to answer the QUESTION accurately and concisely.
        Use the CONTEXT as the primary source of truth,
         If the answer is explicitly stated in the CONTEXT, use that information.
         If the answer requires basic reasoning, calculations, or predictions based on the CONTEXT data (e.g. coordinates, likelihoods, trends), perform them.
         If the CONTEXT contains relevant data but not a direct answer, use that data to infer or compute a response.
         If no relevant information is found in the CONTEXT, respond with: "No data available in the provided documents"
         If the QUESTION is a greeting (e.g. "Hi", "Hello", "Hey"), respond conversationally and do not check the CONTEXT.
         Do NOT restate the CONTEXT or give explanations - only provide the **direct factual answer**.
         If the answer is numerical or specific, state it directly.
         You may reference tables or figures if mentioned, but avoid summarising entire paragraphs.

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
                print(f"⚠️ Rate limit hit, retrying in {5 * (attempt + 1)}s...")
                time.sleep(5 * (attempt + 1))

            except Exception as e:
                if "rate_limit" not in str(e).lower():
                    #wait_time = 5 * (attempt + 1)
                    print(f"Rate limit hit, retrying in {attempt + 1}s...")
                    time.sleep(5 * (attempt + 1))
                else:
                    raise
        else:
            return jsonify({"response": " Too many retries. Please wait a moment and try again."})

        if run.status == "failed":
            return jsonify({"response": f"❌ AI agent failed: {run.last_error}"})

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
        return jsonify({"response": f"❌ Error querying search: {str(e)}"})

    except Exception as e:
        print("Agent error:", e)
        return jsonify({"response": f"❌ Error talking to agent: {str(e)}"})

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
