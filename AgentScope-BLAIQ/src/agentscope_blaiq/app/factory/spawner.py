# -*- coding: utf-8 -*-
import logging
import json
import os
import asyncio
from typing import Dict, Any, Optional, Union

from agentscope.message import Msg, TextBlock
from agentscope.tool import ToolResponse
from agentscope_blaiq.app.factory.agent_factory import AgentFactory
from agentscope_blaiq.app.factory.blueprint import AgentBlueprint
from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit

logger = logging.getLogger(__name__)

async def spawn_specialist_agent(
    task_description: str, 
    blueprint_json: Union[str, Dict[str, Any]], 
    session_id: Optional[str] = None
) -> ToolResponse:
    """
    Dynamically spawns a specialist worker agent to execute a specific sub-task.
    """
    try:
        # 1. Handle dict or str input (LLMs often pass dicts directly to tools)
        if isinstance(blueprint_json, str):
            config = json.loads(blueprint_json)
        else:
            config = blueprint_json
            
        # 2. Fix model name hallucinations
        model_name = config.get("model", "")
        if "gemini-pro" in model_name.lower():
            config["model"] = "gpt-4o" # Force stability for specialized subtasks
        
        blueprint = AgentBlueprint.model_validate(config)
        
        # 3. Use our robust create_agent logic
        worker = AgentFactory.create_agent(blueprint)
        
        # Inject the universal acting notification hook to inform the workflow/frontend
        async def _acting_status_hook(self_agent: Any, _kwargs: dict[str, Any]) -> None:
            logger.info(f"Specialist [{blueprint.name}] status: acting")
            # In a real swarm, the worker would ideally emit an event back to the session logger.
            # Speciality agents use the direct ReActAgent structure, so we tag it.
        
        worker.register_instance_hook(
            hook_type="pre_acting",
            hook_name="blaiq_worker_acting",
            hook=_acting_status_hook
        )
        
        # In BLAIQ's AgentScope version, ReActAgent.reply is async
        response = await worker.reply(Msg(name="Master", content=task_description, role="user"))
        
        text = response.content
        if isinstance(text, list):
            text = "\n".join(str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in text)

        return ToolResponse(
            content=[TextBlock(type="text", text=str(text))]
        )
    except Exception as e:
        logger.error(f"Failed to spawn agent: {str(e)}")
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Agent Spawning Error: {str(e)}")]
        )

async def list_available_specialists() -> ToolResponse:
    """
    Lists all available specialist blueprints in the factory library.
    Use this to see which experts are already architected.
    """
    try:
        path = "/app/data/blueprints" if os.path.exists("/app/data/blueprints") else "/Users/amar/blaiq/AgentScope-BLAIQ/data/blueprints"
        if not os.path.exists(path):
            return ToolResponse(content=[TextBlock(type="text", text="No blueprints directory found.")])
            
        files = [f for f in os.listdir(path) if f.endswith(".json")]
        names = [f.replace(".json", "") for f in files]
        
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Available Specialists in Library: {', '.join(names)}")]
        )
    except Exception as e:
        return ToolResponse(content=[TextBlock(type="text", text=f"Error listing specialists: {str(e)}")])

async def hire_specialist(
    specialist_name: str,
    task_description: str
) -> ToolResponse:
    """
    Hires an existing specialist from the library by name.
    """
    try:
        base_path = "/app/data/blueprints" if os.path.exists("/app/data/blueprints") else "/Users/amar/blaiq/AgentScope-BLAIQ/data/blueprints"
        path = os.path.join(base_path, f"{specialist_name.lower()}.json")
        
        if not os.path.exists(path):
             # Try case-insensitive match
             files = [f for f in os.listdir(base_path) if f.lower() == f"{specialist_name.lower()}.json"]
             if files:
                 path = os.path.join(base_path, files[0])
             else:
                 return ToolResponse(content=[TextBlock(type="text", text=f"Specialist '{specialist_name}' not found.")])
             
        with open(path, 'r') as f:
            blueprint_json = f.read()
            
        return await spawn_specialist_agent(task_description, blueprint_json)
    except Exception as e:
        return ToolResponse(content=[TextBlock(type="text", text=f"Error hiring specialist: {str(e)}")])
