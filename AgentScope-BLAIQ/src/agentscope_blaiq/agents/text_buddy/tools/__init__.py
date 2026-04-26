from __future__ import annotations

import logging

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger("agentscope_blaiq.agents.text_buddy.tools")

TEXT_TEMPLATE_STRUCTURES: dict[str, str] = {
    "email": "subject | greeting | body | cta | sign_off",
    "invoice": "header | invoice_meta | bill_to | line_items | totals | payment_terms | footer",
    "letter": "sender_info | date | recipient_info | salutation | body | closing | signature",
    "memo": "to_from_date_subject | executive_summary | body | action_items",
    "proposal": "executive_summary | problem | solution | scope | timeline | pricing | terms",
    "social_post": "hook | body | hashtags | cta",
    "summary": "key_finding | evidence | analysis | recommendation",
}


async def apply_brand_voice(draft_text: str, brand_voice_guidelines: str) -> ToolResponse:
    """Apply enterprise brand voice to draft text.

    Args:
        draft_text (str): The draft text to transform.
        brand_voice_guidelines (str): Brand voice markdown rules or guidelines.
    """
    logger.info("Tool called: apply_brand_voice")
    return ToolResponse(
        content=[TextBlock(type="text", text=f"Brand voice applied to {len(draft_text)} chars.")],
    )


async def select_template(artifact_family: str) -> ToolResponse:
    """Select the appropriate structure template for an artifact family.

    Args:
        artifact_family (str): The type of artifact (email, invoice, letter, etc.)
    """
    logger.info("Tool called: select_template for %s", artifact_family)
    structure = TEXT_TEMPLATE_STRUCTURES.get(artifact_family, TEXT_TEMPLATE_STRUCTURES["summary"])
    return ToolResponse(
        content=[TextBlock(type="text", text=f"Template for {artifact_family}: {structure}")],
    )


async def format_output(content: str, family: str) -> ToolResponse:
    """Format the final content according to the family template rules.

    Args:
        content (str): The raw composed content.
        family (str): The artifact family for formatting rules.
    """
    logger.info("Tool called: format_output for %s", family)
    return ToolResponse(
        content=[TextBlock(type="text", text=f"Output formatted as {family}.")],
    )


__all__ = [
    "TEXT_TEMPLATE_STRUCTURES",
    "apply_brand_voice",
    "select_template",
    "format_output",
]
