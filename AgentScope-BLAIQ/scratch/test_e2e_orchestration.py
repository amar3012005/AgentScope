# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from agentscope.message import Msg
from agentscope_blaiq.agents.strategic.agent import StrategicAgent

logging.basicConfig(level=logging.INFO)

# Simulation of a Custom Specialist Blueprint from the DB
MAILCHIMP_AUDITOR_BLUEPRINT = {
  "name": "Mailchimp Auditor",
  "description": "Audits campaigns for open rates and segment health.",
  "model": "gpt-4o",
  "system": "You are a Mailchimp expert. Analyze campaign data and propose 3 concrete fixes.",
  "tools": []
}

async def test_strategist_orchestration():
    print("🎯 Testing Strategist as Master Orchestrator")
    
    # Initialize the Master
    master = StrategicAgent()
    
    # User query that requires a specialist
    user_query = f"I need a deep audit of my recent Mailchimp campaign. Use this blueprint for the specialist: {json.dumps(MAILCHIMP_AUDITOR_BLUEPRINT)}"
    
    # Run the Master
    # The Master should see the 'spawn_specialist_agent' tool and use it
    response = await master(Msg(name="User", content=user_query, role="user"))
    
    print("\n--- MASTER'S FINAL RESPONSE ---")
    print(response.content)
    print("-------------------------------")

if __name__ == "__main__":
    asyncio.run(test_strategist_orchestration())
