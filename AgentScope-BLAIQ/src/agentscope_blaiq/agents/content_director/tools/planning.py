from __future__ import annotations

import json
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


async def content_distribution(
    artifact_spec: dict | None = None,
    requirements: dict | None = None,
) -> ToolResponse:
    """Decide how content should be distributed across sections.

    Args:
        artifact_spec (dict): Artifact family and audience spec.
        requirements (dict): Checklist of content requirements.
    """
    payload = {
        "artifact_spec": artifact_spec or {},
        "requirements": requirements or {},
        "distribution": "Match sections to the required narrative and evidence hierarchy.",
    }
    return ToolResponse(content=[TextBlock(type="text", text=json.dumps(payload))])


async def section_planning(
    section_plan: list | None = None,
) -> ToolResponse:
    """Produce a section-by-section plan from requirements and evidence.

    Args:
        section_plan (list): List of section dicts with title, objective, evidence_refs.
    """
    payload = {"section_plan": section_plan or []}
    return ToolResponse(content=[TextBlock(type="text", text=json.dumps(payload))])
