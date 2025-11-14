from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from load_secrets import get_secret
from dotenv import load_dotenv

load_dotenv()

# Retrieve endpoint and agent ID from Azure Key Vault
endpoint = get_secret("azure-endpoint")
agent_id = get_secret("agent-id")

# Connect securely to Azure AI Project
project = AIProjectClient(
    credential=DefaultAzureCredential(),
    endpoint=endpoint
)
#Fetch the agent
agent = project.agents.get_agent(agent_id)

#Create a conversation thread
thread  = project.agents.threads.create()

# Use the thread ID from session
#thread_id = session["thread_id"]
#print(f"[DEBUG] Using thread ID: {thread_id}")

# Send a message to the agent
message = project.agents.messages.create(
    thread_id=thread.id,
    role="user",
    content="Hi Agent812"
)

# Process the agent's response
run = project.agents.runs.create_and_process(
    thread_id=thread.id,
    agent_id=agent.id
)

# Prints all messages in the thread
messages = project.agents.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
for message in messages:
    if message.text_messages:
        print(f"{message.role}: {message.text_messages[-1].text.value}")