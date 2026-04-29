from __future__ import annotations

import json

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from agentscope_blaiq.contracts.brief import ArtifactBrief


async def render_brief_generation(
    brief_data: dict | None = None,
) -> ToolResponse:
    """Generate the renderer handoff brief and validate it against ArtifactBrief contract.

    Args:
        brief_data (dict): ArtifactBrief-compatible dict to validate and emit.
    """
    if brief_data is None:
        return ToolResponse(content=[TextBlock(type="text", text="Error: no brief data provided.")])

    try:
        brief_obj = ArtifactBrief.model_validate(brief_data)
        payload = {
            "brief_id": brief_obj.brief_id,
            "artifact_brief": brief_obj.model_dump(),
            "summary": f"Generated ArtifactBrief '{brief_obj.title}' with {len(brief_obj.sections)} sections.",
        }
        return ToolResponse(content=[TextBlock(type="text", text=json.dumps(payload, default=str))])
    except Exception as exc:
        return ToolResponse(content=[TextBlock(type="text", text=f"Error: ArtifactBrief validation failed: {exc}")])
