from __future__ import annotations

from typing import Any

TEXT_TEMPLATE_STRUCTURES: dict[str, str] = {
    "email": "subject | greeting | body | cta | sign_off",
    "invoice": "header | invoice_meta | bill_to | line_items | totals | payment_terms | footer",
    "letter": "sender_info | date | recipient_info | salutation | body | closing | signature",
    "memo": "to_from_date_subject | executive_summary | body | action_items",
    "proposal": "executive_summary | problem | solution | scope | timeline | pricing | terms",
    "social_post": "hook | body | hashtags | cta",
    "summary": "key_finding | evidence | analysis | recommendation",
}


def make_apply_brand_voice_payload(draft_text: str | None = None, brand_voice: str | None = None) -> dict[str, Any]:
    return {
        "instruction": "Rewrite the draft to match brand voice guidelines.",
        "draft": draft_text or "",
        "brand_voice": brand_voice or "Professional default.",
    }


def make_select_template_payload(artifact_family: str | None = None) -> dict[str, Any]:
    family = artifact_family or "summary"
    return {
        "artifact_family": family,
        "template_structure": TEXT_TEMPLATE_STRUCTURES.get(family, TEXT_TEMPLATE_STRUCTURES["summary"]),
    }


def make_format_output_payload(content: str | None = None, family: str | None = None) -> dict[str, Any]:
    return {
        "formatted": True,
        "family": family or "summary",
        "content": content or "",
    }
