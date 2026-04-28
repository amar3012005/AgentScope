# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, Optional
from agentscope.message import Msg
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient

logger = logging.getLogger(__name__)

def hitl_research_verification_hook(
    self: Any,
    kwargs: Dict[str, Any],
    output: Any
) -> Any:
    """
    POST-REPLY Hook for Research Agent.
    Flags for review if:
    1. 'review_mode' is strict.
    2. 'injection_sources' were used (Audit requirement).
    """
    msg = output
    if not isinstance(msg, Msg): return output

    has_injection = "injection_sources" in msg.metadata
    is_strict = msg.metadata.get("review_mode") == "strict"

    if has_injection or is_strict:
        logger.info(f"Research Verification Hook triggered for {self.name} (Injection: {has_injection})")
        msg.metadata["requires_hitl_approval"] = True
        msg.metadata["hitl_reason"] = "Audit required for custom injection sources." if has_injection else "Strict review mode enabled."
    
    return msg

def pre_flight_variable_check_hook(
    self: Any,
    kwargs: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    PRE-REPLY Hook for any agent.
    Checks for missing mandatory fields in the message metadata.
    """
    msg = kwargs.get("msg")
    # Ignore pre-flight checks for the Master Orchestrator to prevent planning loops
    if self.name == "StrategistV2": return kwargs
    
    mandatory_fields = getattr(self, "metadata", {}).get("mandatory_fields", [])
    missing = [f for f in mandatory_fields if not msg.metadata.get(f)]
    
    if missing:
        logger.warning(f"Pre-flight check failed for {self.name}. Missing: {missing}")
        # We can't easily 'suspend' inside a pre-hook without returning modified kwargs
        # So we inject a 'missing_data' flag for the agent's system prompt to see.
        msg.metadata["missing_data"] = missing
        
    return kwargs
