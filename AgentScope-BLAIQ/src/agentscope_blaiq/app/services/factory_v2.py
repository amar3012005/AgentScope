# -*- coding: utf-8 -*-
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from agentscope_blaiq.app.factory.agent_factory import AgentFactory
from agentscope_blaiq.app.factory.spawner import spawn_specialist_agent

# Standard BLAIQ AaaS schemas
class AgentRequest(BaseModel):
    input: str
    session_id: str
    user_id: str
    metadata: Optional[Dict[str, Any]] = {}

class CreateAgentRequest(BaseModel):
    prompt: str

app = FastAPI(title="BLAIQ Agent Factory Service")
logger = logging.getLogger("factory-service")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "factory"}

@app.post("/create")
async def create_agent_blueprint(req: CreateAgentRequest):
    """Architects and saves a new agent blueprint."""
    try:
        blueprint = await AgentFactory.generate_blueprint(req.prompt)
        path = AgentFactory.save_blueprint(blueprint)
        return {
            "status": "success",
            "blueprint": blueprint.model_dump(),
            "path": path
        }
    except Exception as e:
        logger.error(f"Failed to create agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/spawn")
async def spawn_agent_execution(req: AgentRequest):
    """Spawns and executes a specialist based on a blueprint in metadata."""
    try:
        blueprint_json = req.metadata.get("blueprint_json")
        if not blueprint_json:
            raise HTTPException(status_code=400, detail="Missing blueprint_json in metadata")
            
        response = await spawn_specialist_agent(
            task_description=req.input,
            blueprint_json=blueprint_json,
            session_id=req.session_id
        )
        
        return {
            "status": "success",
            "output": [block.model_dump() if hasattr(block, "model_dump") else block for block in response.content]
        }
    except Exception as e:
        logger.error(f"Failed to spawn agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
