import asyncio
from agentscope.model import OpenAIChatModel
import os

async def test():
    # We don't need a real API key just to check the return type if it errors out before call, 
    # but let's see what the signature says.
    model = OpenAIChatModel(model_name="test", api_key="test")
    print(f"Model call type: {type(model)}")
    # Check if it has a specific response class
    import agentscope.model
    print(f"Model response classes: {[name for name in dir(agentscope.model) if 'Response' in name]}")

if __name__ == "__main__":
    asyncio.run(test())
