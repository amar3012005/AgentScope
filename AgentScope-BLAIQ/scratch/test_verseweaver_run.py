# -*- coding: utf-8 -*-
import asyncio
import logging
import json
from agentscope.message import Msg
from agentscope_blaiq.app.factory.agent_factory import AgentFactory
from agentscope_blaiq.app.factory.blueprint import AgentBlueprint

logging.basicConfig(level=logging.INFO)

async def run_verseweaver():
    print("🕯️ VerseWeaver is awakening...")
    
    # Load the blueprint we just created
    path = "/Users/amar/blaiq/AgentScope-BLAIQ/data/blueprints/verseweaver.json"
    with open(path, "r") as f:
        config = json.load(f)
    
    # Birth the poet!
    blueprint = AgentBlueprint(**config)
    poet = AgentFactory.create_agent(blueprint)
    
    # The Query
    query = "Write a high-fidelity poem about BLAIQ, the Agent Factory, and the birth of dynamic specialists. Use rich metaphors of architecture and weaving."
    
    print(f"\n✍️ Sending query to VerseWeaver: {query[:50]}...")
    
    response = await poet(Msg(name="User", content=query, role="user"))
    
    print("\n--- VERSEWEAVER'S MASTERPIECE ---")
    # Extract text from response blocks
    for block in response.content:
        if isinstance(block, dict):
            print(block.get("text", ""))
        else:
            print(getattr(block, "text", str(block)))
    print("---------------------------------")

if __name__ == "__main__":
    asyncio.run(run_verseweaver())
