import os
import requests
from dotenv import load_dotenv

load_dotenv()

endpoint = os.getenv("AZURE_ENDPOINT")
api_key = os.getenv("AZURE_API_KEY")
agent_id = os.getenv("AZURE_AGENT_ID")

url=f"{endpoint}/agents/{agent_id}/invoke"

headers={
    "Authorization":f"Bearer {api_key}",
    "Content-Type":"application/json"
}

data = {
    "input": "Hello Agent, I am connecting from VS Code!"
}

response = requests.post(url, headers=headers, json=data)

print("Status Code:", response.status_code)
try:
    print("Response:", response.json())
except:
    print("Raw Response:", response.text)