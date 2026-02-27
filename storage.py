from azure.storage.blob import BlobServiceClient, ContentSettings
from load_secrets import get_secret
from dotenv import load_dotenv
from datetime import datetime, timedelta
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from urllib.parse import quote
import json
import time
import uuid
import os

load_dotenv()

ACCOUNT_NAME = get_secret("azure-storage-account")
ACCOUNT_KEY = get_secret("azure-storage-key")
MAIN_CONTAINER = get_secret("azure-storage-container")
CHAT_CONTAINER = "chathistory"

PAGE_MAP_CONTAINER = "pagemaps"


connection_string = (
    f"DefaultEndpointsProtocol=https;"
    f"AccountName={ACCOUNT_NAME};"
    f"AccountKey={ACCOUNT_KEY};"
    f"EndpointSuffix=core.windows.net"
)

blob_service = BlobServiceClient.from_connection_string(connection_string)

# Main document upload container
main_container_client = blob_service.get_container_client(MAIN_CONTAINER)

# Chat history + chat list container
chat_container_client = blob_service.get_container_client(CHAT_CONTAINER)

page_map_container = blob_service.get_container_client(PAGE_MAP_CONTAINER)

# Ensure chat container exists
try:
    chat_container_client.create_container()
    print("[storage] Chat history container created.")
except Exception:
    print("[storage] Chat history container already exists.")

#Ensure page map container exists
try:
    page_map_container.create_container()
    print("[storage] Page map container created.")
except Exception:
    print("[storage] Page map container already exists.")

# -------------------------------
# Document Upload (unchanged)
# -------------------------------
def upload_file_to_blob(file_path, blob_name):
    with open(file_path, "rb") as data:
        main_container_client.upload_blob(blob_name, data, overwrite=True)
    return f"https://{ACCOUNT_NAME}.blob.core.windows.net/{MAIN_CONTAINER}/{blob_name}"

# -------------------------------
# Chat ID Management
# -------------------------------
def create_chat_id():
    return str(uuid.uuid4())

# -------------------------------
# CHAT LIST STORAGE (FIXED)
# -------------------------------
CHAT_LIST_BLOB = "chats.json"

def load_chat_list():
    blob = chat_container_client.get_blob_client(CHAT_LIST_BLOB)

    if not blob.exists():
        print("[storage] No chat list found")
        return []

    try:
        data = blob.download_blob().readall()
        chat_ids = json.loads(data)
        print(f"[storage] Loaded chat list ({len(chat_ids)} chats)")
        return chat_ids
    except Exception as e:
        print("[storage] Chat list load error:", e)
        return []


def save_chat_list(chat_list):
    blob = chat_container_client.get_blob_client(CHAT_LIST_BLOB)
    try:
        blob.upload_blob(json.dumps(chat_list, indent=2), overwrite=True)
        print(f"[storage] Saved chat list ({len(chat_list)} chats)")
    except Exception as e:
        print("[storage] Chat list save error:", e)

# -------------------------------
# CHAT HISTORY STORAGE
# -------------------------------
def save_chat_message(chat_id, role, message):
    blob_name = f"{chat_id}.json"
    blob = chat_container_client.get_blob_client(blob_name)

    try:
        if blob.exists():
            messages = json.loads(blob.download_blob().readall())
        else:
            messages = []

        messages.append({
            "role": role,
            "message": message,
            "timestamp": time.time()
        })

        blob.upload_blob(json.dumps(messages, indent=2), overwrite=True)
        print(f"[storage] Saved message to {blob_name} ({len(messages)} msgs)")

    except Exception as e:
        print("[storage] Chat save error:", e)


def load_chat_history(chat_id):
    blob_name = f"{chat_id}.json"
    blob = chat_container_client.get_blob_client(blob_name)

    if not blob.exists():
        #print(f"[storage] No history for {chat_id}")
        return []

    try:
        messages = json.loads(blob.download_blob().readall())
        print(f"[storage] Loaded chat {chat_id} ({len(messages)} msgs)")
        return messages
    except Exception as e:
        print("[storage] Chat load error:", e)
        return []
    
# -------------------------------
# Per chat active documents (checkbox filters)

def save_active_documents(chat_id, documents):
    """Saves the active documents for a chat."""
    if documents is None:
        documents = []

    if isinstance(documents, str):
        documents = [documents]
    
    if not isinstance(documents, list):
        documents = []
    
    blob_name = f"{chat_id}_documents.json"
    blob = chat_container_client.get_blob_client(blob_name)
    data = {"active_documents": documents}

    try:
        blob.upload_blob(json.dumps(data, indent=2), overwrite=True)
        print(f"[storage] Saved active documents for {chat_id}: {documents}")
    except Exception as e:
        print("[storage] Active documents save error:", e)


def load_active_documents(chat_id):
    """Loads the active documents for a chat."""
    blob_name = f"{chat_id}_documents.json"
    blob = chat_container_client.get_blob_client(blob_name)
    try:
        if not blob.exists():
            return []
        
        data = json.loads(blob.download_blob().readall())
        return data.get("active_documents", [])
    
        if docs is None:
            return []
        
        if isinstance(docs, str):
            return [docs]
        
        if not isinstance(docs, list):
            return []
        
        return docs
    except Exception as e:
        return []
    
def clear_active_documents(chat_id):
    """Clears the active documents for a chat."""
    save_active_documents(chat_id, [])


# -------------------------------
#Per chat thread id (agent memory per chat)
#-------------------------------

def save_chat_thread_id(chat_id, thread_id):
    """Saves the chat thread ID to a separate blob."""
    blob_name = f"{chat_id}_thread.json"
    data = {"thread_id": thread_id}

    blob = chat_container_client.get_blob_client(blob_name)
    try:
        blob.upload_blob(json.dumps(data), overwrite=True)
        print(f"[storage] Saved thread ID for {chat_id}: {thread_id}")
    except Exception as e:
        print("[storage] Chat thread ID save error:", e)

def load_chat_thread_id(chat_id):
    """Loads the chat thread ID from a separate blob."""
    blob_name = f"{chat_id}_thread.json"
    blob_client = chat_container_client.get_blob_client(blob_name)
    try:
        if not blob_client.exists():
            return None
        content = blob_client.download_blob().readall()
        data = json.loads(content)
        return data.get("thread_id")
    except Exception:
        return None
    

def upload_page_map(filename: str, page_map: dict):     
    """Uploads a page number map as a JSON blob to the PAGE_MAP_CONTAINER."""

    if not page_map:
        raise ValueError("Page map is empty")
    
    blob_name = f"{filename}.pagemap.json"
    blob = page_map_container.get_blob_client(blob_name)

    blob.upload_blob(
        json.dumps(page_map,ensure_ascii=False, indent=2),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )
    print(f"[storage] Uploaded page map -> pagemaps/{blob_name}")

def load_page_map(filename: str) -> dict:
    try:
        blob_name = f"{filename}.pagemap.json"
        blob = page_map_container.get_blob_client(blob_name)
        raw = blob.download_blob().readall()
        return json.loads(raw)
    except Exception as e:
        print(f"[storage] No page map found for {filename}: {e}")
        return {}
    
def generate_read_sas_for_blob(blob_name: str, expiry_minutes: int = 60) -> str:
    """Generates a read-only SAS URL for a blob valid for a specified number of minutes."""
    sas_token = generate_blob_sas(
        account_name=ACCOUNT_NAME,
        container_name=MAIN_CONTAINER,
        blob_name=blob_name,
        account_key=ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(minutes=expiry_minutes)
    )

    encoded_blob_name = quote(blob_name, safe="/")

    url = (
        f"https://{ACCOUNT_NAME}.blob.core.windows.net/"
        f"{MAIN_CONTAINER}/"
        f"{encoded_blob_name}"
        f"?{sas_token}"
    )

    return url
