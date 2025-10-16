from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from dotenv import load_dotenv
import os

load_dotenv()

endpoint = os.getenv("AZURE_ENDPOINT")
agent_id = os.getenv("AGENT_ID")

# Connect to project and agent
project = AIProjectClient(
    credential=DefaultAzureCredential(),
    endpoint=endpoint
)

agent = project.agents.get_agent(agent_id)
thread  = project.agents.threads.create()

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