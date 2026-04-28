# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from agentscope_blaiq.app.factory.spawner import spawn_specialist_agent

logging.basicConfig(level=logging.INFO)

API_DESIGNER_JSON = {
  "name": "API Designer",
  "description": "Designs intuitive, scalable API architectures.",
  "model": "gpt-4o", # Using a common model name for test
  "system": "You are a senior API designer. Deliver complete OpenAPI specs for any request.",
  "tools": [
    {
      "type": "agent_toolset_20260401",
      "default_config": {"enabled": True},
      "configs": [{"name": "web_search", "enabled": True}]
    }
  ]
}

async def test_inflation():
    print("🚀 Starting Agent Factory Test: API Designer Inflation")
    
    task = "Design a REST API for a sustainable heating company like Solvis. Include endpoints for SolvisMax monitoring."
    
    # We call our spawner tool directly for the test
    # In the real system, this would be registered in the Master's toolkit
    response = await spawn_specialist_agent(
        task_description=task,
        blueprint_json=json.dumps(API_DESIGNER_JSON)
    )
    
    print("\n--- WORKER RESPONSE ---")
    print(response.content)
    print("------------------------")

if __name__ == "__main__":
    asyncio.run(test_inflation())
