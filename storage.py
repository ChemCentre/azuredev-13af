""" from azure.storage.blob import BlobServiceClient
from load_secrets import get_secret
from dotenv import load_dotenv
import json
import time
import uuid
import os

load_dotenv()

ACCOUNT_NAME = get_secret("azure-storage-account")
ACCOUNT_KEY = get_secret("azure-storage-key")
CONTAINER_NAME = get_secret("azure-storage-container")
CHAT_CONTAINER_NAME = "chathistory"

connection_string = f"DefaultEndpointsProtocol=https;AccountName={ACCOUNT_NAME};AccountKey={ACCOUNT_KEY};EndpointSuffix=core.windows.net"
blob_service_client = BlobServiceClient.from_connection_string(connection_string)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)
chat_container_client = blob_service_client.get_container_client(CHAT_CONTAINER_NAME)

try:
    chat_container_client.create_container()
    print("[storage] Chat history container created.")
except Exception as e:
    print("[storage] Chat history container already exists.")

def upload_file_to_blob(file_path, blob_name):
    Uploads a file to Azure Blob Storage and returns the blob URL.
    with open(file_path, "rb") as data:
        container_client.upload_blob(name=blob_name, data=data, overwrite=True)
    blob_url = f"https://{ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{blob_name}"
    return blob_url

def create_chat_id():
    Generates a unique chat ID.
    return str(uuid.uuid4())

CHAT_LIST_BLOB = "chats.json"

def load_chat_list():
    Returns list of all that chats stored in blob.
    blob_client = container_client.get_blob_client(CHAT_LIST_BLOB)

    if not blob_client.exists():
        print("[storage] No chat list found")
        return []
    
    try:
        data = json.loads(blob_client.download_blob().readall())
        print(f"[storage] Chat list loaded: {CHAT_LIST_BLOB} | Total chats: {len(data)}")
        return data
    except Exception as e:
        print("Chat list blob load error:", e)
        return []
    
def save_chat_list(chat_list):
    Saves the list of all chats to blob.
    blob_client = container_client.get_blob_client(CHAT_LIST_BLOB)

    try:
        blob_client.upload_blob(json.dumps(chat_list, indent=2), overwrite=True)
        print(f"[storage] Chat list saved to blob: {CHAT_LIST_BLOB} | Total chats: {len(chat_list)}")
    except Exception as e:
        print("Chat list blob save error:", e)


def save_chat_message(chat_id, role, message):
    blob_name = f"{chat_id}.json"
    blob_client = chat_container_client.get_blob_client(blob_name)

    try:
        #Load existing history
        if blob_client.exists():
            data = json.loads(blob_client.download_blob().readall())
        else:
            data = []
        
        data.append({"role": role, "message": message, "timestamp": time.time()})
        blob_client.upload_blob(json.dumps(data, indent=2), overwrite=True)
        print(f"[storage] Chat saved to blob: {blob_name} | Total messages: {len(data)}")
    
    except Exception as e:
        print("Chat blob save error:", e)


def load_chat_history(chat_id):
    blob_name = f"{chat_id}.json"
    blob_client = chat_container_client.get_blob_client(blob_name)

    if not blob_client.exists():
        print("[storage] No chat history found")
        return []
    
    try:
        data = json.loads(blob_client.download_blob().readall())
        print(f"[storage] Chat history loaded: {blob_name} | Total messages: {len(data)}")
        return data
    except Exception as e:
        print("Chat blob load error:", e)
        return []
    

 """

from azure.storage.blob import BlobServiceClient
from load_secrets import get_secret
from dotenv import load_dotenv
import json
import time
import uuid
import os

load_dotenv()

ACCOUNT_NAME = get_secret("azure-storage-account")
ACCOUNT_KEY = get_secret("azure-storage-key")
MAIN_CONTAINER = get_secret("azure-storage-container")
CHAT_CONTAINER = "chathistory"

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

# Ensure chat container exists
try:
    chat_container_client.create_container()
    print("[storage] Chat history container created.")
except Exception:
    print("[storage] Chat history container already exists.")

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

def save_chat_prefix(chat_id, prefix):
    """Saves the chat prefix to a separate blob."""
    blob_name = f"{chat_id}_prefix.json"
    data = {"active_prefix": prefix}

    blob = chat_container_client.get_blob_client(blob_name)
    try:
        blob.upload_blob(json.dumps(data), overwrite=True)
        print(f"[storage] Saved prefix for {chat_id}")
    except Exception as e:
        print("[storage] Chat prefix save error:", e)

def load_chat_prefix(chat_id):
    """Loads the chat prefix from a separate blob."""
    blob_name = f"{chat_id}_prefix.json"
    try:
        blob_client = chat_container_client.get_blob_client(blob_name)
        content = blob_client.download_blob().readall()
        data = json.loads(content)
        return data.get("active_prefix")
    except Exception:
        return None