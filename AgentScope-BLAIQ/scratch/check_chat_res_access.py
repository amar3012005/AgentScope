from agentscope.model import ChatResponse
import json

# Let's mock a ChatResponse if possible or see how it's constructed
# In AgentScope, ModelResponse usually has 'text' in its __dict__ if it's a dataclass, 
# or it's a dict with 'text'.

res = ChatResponse(text="Hello", embedding=None, logprobs=None)
print(f"Text via attr: {getattr(res, 'text', 'MISSING')}")
print(f"Text via dict: {res.get('text', 'MISSING')}")
print(f"Keys: {res.keys()}")
