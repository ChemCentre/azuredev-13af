import os
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

#Load environment variables from .env file
load_dotenv()

# Get connection string and container from environment
connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STR")
container_name = os.getenv("STORAGE_CONTAINER_NAME")

#Create BlobServiceClient
blob_service_client = BlobServiceClient.from_connection_string(connect_str)

#Upload doc to storage
def upload_document(file):
    try:
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=file.filename)
        blob_client.upload_blob(file, overwrite=True)
        return f"{file.filename} uploaded successfully to Azure Blob Storage."
    except Exception as e:
        return f"Error uploading file: {str(e)}"