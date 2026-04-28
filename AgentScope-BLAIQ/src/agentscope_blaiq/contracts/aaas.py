from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum

class NodeRole(str, Enum):
    RESEARCH = "research"
    PLANNING = "planning"
    COMPOSITION = "composition"
    REFINEMENT = "refinement"
    GOVERNANCE = "governance"
    VISUAL = "visual"

class MissionNode(BaseModel):
    node_id: str
    role: NodeRole
    service_endpoint: str
    purpose: str
    inputs: Dict[str, Any] = {}
    depends_on: List[str] = []

class MissionPlan(BaseModel):
    mission_id: str
    title: str
    artifact_type: str
    topology: List[MissionNode]
    success_criteria: List[str]
    notes: List[str] = []
    
class AgentRequest(BaseModel):
    query: str
    session_id: str
    user_context: Optional[Dict[str, Any]] = None
    stream: bool = True
