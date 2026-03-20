import asyncio
import json
import logging
import uuid
import sys

import httpx
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
logger = logging.getLogger("test_content_agent")

async def test_agent():
    url = "http://localhost:6080/orchestrate"
    
    payload = {
        "task": "Build Pitch Deck for Da'Vinci AI",
        "target_agent": "blaiq-content-agent",
        "payload": {
            "session_id": f"test-deck-{uuid.uuid4()}"
        },
        "protocol": "ws"
    }

    logger.info(f"Sending request to orchestrator: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            logger.info("Response received:")
            print(json.dumps(res.json(), indent=2))
        except Exception as e:
            logger.error(f"Failed: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response body: {e.response.text}")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_agent())
