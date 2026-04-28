import httpx
import json
import asyncio
import sys

async def test_aaas_node(name: str, url: str, query: str):
    print(f"\n🚀 Testing {name} at {url}...")
    print("-" * 50)
    
    payload = {
        "query": query,
        "session_id": "test-session-123",
        "user_id": "test-user-amar",
        "stream": True
    }
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{url}/query", json=payload) as response:
                if response.status_code != 200:
                    print(f"❌ Error: Received status code {response.status_code}")
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        
                        # Handle different message types from AgentApp
                        if "message" in data:
                            msg = data["message"]
                            kind = data.get("kind", "thought")
                            print(f"[{kind.upper()}] {msg}")
                        elif "error" in data:
                            print(f"❌ NODE ERROR: {data['error']}")
                        else:
                            # Standard AgentScope message format
                            content = data.get("content", "")
                            if content:
                                print(content, end="", flush=True)

    except Exception as e:
        print(f"❌ Connection Error: {str(e)}")

async def main():
    # 1. Test Strategist
    await test_aaas_node(
        "Strategist V2", 
        "http://localhost:8095", 
        "Plan a research mission about the impact of AI on renewable energy for an investor report."
    )
    
    # 2. Test Research
    await test_aaas_node(
        "Deep Research V2", 
        "http://localhost:8096", 
        "What are the latest breakthroughs in perovskite solar cells in 2026?"
    )

if __name__ == "__main__":
    asyncio.run(main())
