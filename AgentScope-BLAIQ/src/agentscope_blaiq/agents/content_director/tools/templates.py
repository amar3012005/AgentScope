from __future__ import annotations

import json

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from agentscope_blaiq.agents.content_director.planning import template_name_for_family


async def template_selection(
    artifact_spec: dict | None = None,
) -> ToolResponse:
    """Select a template direction for the renderer.

    Args:
        artifact_spec (dict): Artifact family and audience spec.
    """
    family = (artifact_spec or {}).get("family", "custom")
    template_name = template_name_for_family(family)
    payload = {"template_name": template_name}
    return ToolResponse(content=[TextBlock(type="text", text=json.dumps(payload))])
