import os
import requests
from openai import AzureOpenAI
from dotenv import load_dotenv


load_dotenv()

import os
import requests
from dotenv import load_dotenv

load_dotenv()

import os
import requests
from dotenv import load_dotenv

load_dotenv()

class FoundryClient:
    def __init__(self, api_key: str, endpoint: str, system_prompt: str = None):
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.system_prompt = system_prompt or "You are an AI assistant."

    def _call_api(self, user_prompt: str):
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": 1024,
        }
        response = requests.post(self.endpoint, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    def get_response(self, user_prompt: str):
        result = self._call_api(user_prompt)
        return result["choices"][0]["message"]["content"].strip()

# Load credentials
endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
api_key = os.getenv("AZURE_FOUNDRY_KEY")

# Initialize client
client = FoundryClient(api_key=api_key, endpoint=endpoint)

# Test prompt
prompt = input("Enter your prompt: ")
response = client.get_response(prompt)
print("\nAgent Response:\n", response)



""" # ---------- 1. Azure OpenAI (raw model call) ----------
print("=== Testing Azure OpenAI (raw deployment) ===")

openai_client = AzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
)

try:
    response = openai_client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello from VS Code using OpenAI endpoint."},
        ],
        max_completion_tokens=200
    )
    print("OpenAI Response:", response.choices[0].message.content)
except Exception as e:
    print("OpenAI Error:", e)


# ---------- 2. Azure AI Foundry Agent ----------
print("\n=== Testing Azure AI Foundry Agent ===")

foundry_endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT")
foundry_key = os.getenv("AZURE_FOUNDRY_KEY")
agent_id = os.getenv("AZURE_AGENT_ID")

url = f"{foundry_endpoint}/agents/{agent_id}/invoke"

headers = {
    "api-key": foundry_key,
    "Content-Type": "application/json"
}

data = {
    "input": "Hello Agent, are you receiving this from VS Code?"
}

try:
    resp = requests.post(url, headers=headers, json=data)
    print("Status Code:", resp.status_code)
    if resp.status_code == 200:
        print("Agent Response:", resp.json())
    else:
        print("Agent Raw Response:", resp.text)
except Exception as e:
    print("Agent Error:", e) """




#deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
#api_version = os.getenv("AZURE_OPENAI_API_VERSION")

#client = AzureOpenAI(
#    api_version=api_version,
#    azure_endpoint=endpoint,
#    api_key=api_key,
#)

#response = client.chat.completions.create(
#    messages=[
#        {"role": "system", "content": "You are a helpful assistant."},
#        {"role": "user", "content": "Hello, are you connected to VS Code now?"},
#    ],
#    max_completion_tokens=500,
#    temperature=0.7,
#    top_p=1.0,
#    model=deployment
#)

#print("Response:", response.choices[0].message.content)

