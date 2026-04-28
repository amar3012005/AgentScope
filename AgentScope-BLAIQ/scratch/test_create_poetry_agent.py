# -*- coding: utf-8 -*-
import asyncio
import logging
from agentscope_blaiq.app.factory.agent_factory import AgentFactory

logging.basicConfig(level=logging.INFO)

async def test_create_poetry_agent():
    print("🎭 Command Received: /create-agent 'i want u to create a poetry writer agent'")
    
    prompt = "i want u to create a poetry writer agent"
    
    print("\n🏗️ Architecting specialized Poetry Agent...")
    blueprint = await AgentFactory.generate_blueprint(prompt)
    
    print(f"\n✨ Specialized Agent Designed: {blueprint.name}")
    print(f"📝 Description: {blueprint.description}")
    
    print("\n💾 Saving to Library...")
    path = AgentFactory.save_blueprint(blueprint)
    
    print(f"\n✅ SUCCESS! Your new agent is ready at: {path}")
    print("\n--- BLUEPRINT PREVIEW ---")
    print(blueprint.system[:300] + "...")
    print("-------------------------")

if __name__ == "__main__":
    asyncio.run(test_create_poetry_agent())
