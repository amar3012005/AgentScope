# -*- coding: utf-8 -*-
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, AliasChoices

class ToolConfig(BaseModel):
    name: str
    enabled: bool = True
    config: Optional[Dict[str, Any]] = None

class AgentToolset(BaseModel):
    type: str = "agent_toolset_20260401"
    default_config: Dict[str, Any] = {"enabled": True}
    configs: List[ToolConfig] = []

class AgentBlueprint(BaseModel):
    # Use validation_alias to support common LLM naming hallucinations
    name: str = Field(validation_alias=AliasChoices("name", "role", "agent_name"))
    description: str = Field(validation_alias=AliasChoices("description", "specialty", "goal"))
    model: str = Field(default="gpt-4o", validation_alias=AliasChoices("model", "engine", "model_name"))
    system: str = Field(validation_alias=AliasChoices("system", "sys_prompt", "prompt", "instructions"))
    
    mcp_servers: List[str] = []
    tools: List[Any] = []
    skills: List[Any] = []
    output_schema: Optional[Dict[str, Any]] = None
    
    model_config = {
        "extra": "allow",
        "populate_by_name": True
    }
