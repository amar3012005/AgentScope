import asyncio
import os
import sys
from agentscope_blaiq.workflows.swarm_engine import SwarmEngine

async def run_mission():
    goal = "preprae me a pitch deck about Solvis lea product for a sales marketing pitch"
    session_id = "verification-session-" + os.urandom(4).hex()
    artifact_family = "pitch_deck"
    
    print(f"--- Starting Swarm Mission: {goal} ---")
    print(f"Session ID: {session_id}")
    
    swarm = SwarmEngine()
    
    async def publisher(role, text):
        print(f"[{role}] {text[:100]}..." if len(text) > 100 else f"[{role}] {text}")

    try:
        results = await swarm.run(
            goal=goal,
            session_id=session_id,
            artifact_family=artifact_family,
            publish=publisher
        )
        
        print("\n--- Mission Complete ---")
        for role, output in results.items():
            print(f"\n=== {role.upper()} OUTPUT (First 500 chars) ===")
            print(output[:500])
            
            # Check for Solvis keywords to verify brand alignment
            keywords = ["Solvis", "Energiesystem", "Heizung", "Visionary Partner"]
            found = [k for k in keywords if k.lower() in output.lower()]
            print(f"Keywords detected: {found}")
            
    except Exception as e:
        print(f"Mission Failed: {e}")

if __name__ == "__main__":
    # Ensure we use the local host for services since we're running locally
    os.environ["BLAIQ_SERVICE_HOST"] = "localhost"
    asyncio.run(run_mission())
