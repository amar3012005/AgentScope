import asyncio
import json
from agentscope_blaiq.app.services.text_buddy_v2 import TextBuddy
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings

async def main():
    resolver = LiteLLMModelResolver.from_settings(settings)
    tb = TextBuddy(resolver)
    print("Testing TextBuddy skill selection...")
    async for msg in tb.generate_artifact(
        request_text="Review the iPhone 15 Pro using product_review_pro.", 
        artifact_type="report"
    ):
        print(f"[{msg.name}] {msg.content[:200]}...")

if __name__ == "__main__":
    asyncio.run(main())
