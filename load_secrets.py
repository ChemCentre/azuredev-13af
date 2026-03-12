"""
PitPixie – Secret Management Module

Author: Vanessa Perera

Description:
Handles secure retrieval of configuration values and credentials from Azure
Key Vault using Azure Identity authentication. Secrets are cached locally to
reduce repeated calls to the Key Vault service.
"""

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient   
from functools import lru_cache      
import os
import time

#Connect to Azure Key Vault
load_dotenv()

VAULT_URL = os.getenv("AZURE_KEY_VAULT_URL")

#Managed Identity when deployed to Azure
try:
    credential = ManagedIdentityCredential()
    # Test if Managed Identity works
    test_token = credential.get_token("https://vault.azure.net/.default")
    print("[KeyVault] Using Managed Identity Credential.")
except Exception:
    #Fallback to DefaultAzureCredential for local development
    credential = DefaultAzureCredential()
    print("[KeyVault] Using Default Azure Credential (local dev).")

secret_client = SecretClient(vault_url=VAULT_URL, credential=credential)

#Helper function - Cached and Retry Safe 
@lru_cache(maxsize=64)
def get_secret(name: str):
    """Retrieve a secret value from Azure Key Vault.
       Cached in-memory to avoid repeated vault calls.
       Includes retry logic for transient key vault timeouts"""
    
    retries = 3
    for attempt in range(retries):
        try:
            secret = secret_client.get_secret(name)
            return secret.value
        except Exception as e:
            if attempt < retries - 1:
                wait_time = 2 *(attempt + 1)
                print(f"[KeyVault] Retry {attempt + 1}/{retries} for secret '{name}' after {wait_time} seconds due to error: {e}")
                time.sleep(wait_time)
            else:
                print(f"[KeyVault] Failed to retrieve secret '{name}': {e}")
                return None
    
    