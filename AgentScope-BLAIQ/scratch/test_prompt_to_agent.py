# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from agentscope.message import Msg
from agentscope_blaiq.app.factory.spawner import spawn_specialist_agent
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logging.basicConfig(level=logging.INFO)

async def test_prompt_to_agent():
    print("🪄 PHASE 1: Architecting the Agent from a Prompt")
    
    resolver = LiteLLMModelResolver.from_settings()
    
    # We ask the LLM to design a blueprint for a specific task
    user_need = "I need an expert to audit a SaaS pricing page and suggest 3 psychological 'nudges' to increase conversion."
    
    architect_prompt = f"""
    Design a JSON blueprint for a specialist agent to solve this: "{user_need}"
    
    The JSON must follow this structure:
    {{
      "name": "string",
      "description": "string",
      "model": "gpt-4o",
      "system": "Detailed system prompt for this specific expertise",
      "tools": []
    }}
    Return ONLY the JSON.
    """
    
    response = await resolver.acompletion(
        role="strategic", 
        messages=[{"role": "user", "content": architect_prompt}],
        max_tokens=2000,
        response_format={"type": "json_object"}
    )
    response_text = resolver.extract_text(response)
    print(f"\n--- RAW ARCHITECT RESPONSE ---\n{response_text}\n------------------------------")
    blueprint_data = resolver.safe_json_loads(response_text)
    
    print(f"\n✅ Blueprint Created: {blueprint_data['name']}")
    
    print("\n🚀 PHASE 2: Spawning the Worker via Factory")
    
    # Now we spawn it!
    worker_task = f"Audit this pricing page: 'Starter: $10/mo, Pro: $50/mo, Enterprise: Contact Us'. Focus on the 'Pro' tier."
    
    result = await spawn_specialist_agent(
        task_description=worker_task,
        blueprint_json=json.dumps(blueprint_data)
    )
    
    print("\n--- WORKER OUTPUT ---")
    # Content is a list of TextBlocks or dicts
    for block in result.content:
        if isinstance(block, dict):
            print(block.get("text", ""))
        else:
            print(getattr(block, "text", str(block)))
    print("----------------------")

if __name__ == "__main__":
    asyncio.run(test_prompt_to_agent())
