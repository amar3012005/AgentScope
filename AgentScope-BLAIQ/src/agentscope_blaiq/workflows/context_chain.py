"""Multi-turn conversation context management for BLAIQ workflows.

Loads, formats, and compresses prior conversation turns from HIVE-MIND
memory chains so agents can reference prior context without exceeding
their context windows.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maximum characters for prior context injected into agent prompts
MAX_CONTEXT_CHARS = 3000
# Recent turns kept at full fidelity
RECENT_TURN_COUNT = 3
# Max chars per older (compressed) turn
COMPRESSED_TURN_CHARS = 200


def extract_turns_from_chain(chain_response: dict[str, Any] | None) -> list[dict[str, str]]:
    """Extract individual conversation turns from a HIVE-MIND traverse_graph response.

    Returns a list of dicts with keys: query, answer, evidence_summary, timestamp.
    Ordered oldest-first.
    """
    if not chain_response:
        return []

    turns: list[dict[str, str]] = []

    # HIVE-MIND traverse_graph returns content as a list of text blocks
    content_list: list[Any] = []
    if isinstance(chain_response, dict):
        content_list = chain_response.get("content", [])
        if not isinstance(content_list, list):
            content_list = [content_list]
    elif isinstance(chain_response, list):
        content_list = chain_response

    for item in content_list:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        if not text or len(text) < 20:
            continue

        # Try to parse structured turn data
        try:
            parsed = json.loads(text) if text.strip().startswith("{") else None
            if parsed and isinstance(parsed, dict):
                turns.append({
                    "query": parsed.get("query", parsed.get("title", "")),
                    "answer": parsed.get("answer", parsed.get("content", text)),
                    "evidence_summary": parsed.get("evidence_summary", ""),
                    "timestamp": parsed.get("timestamp", parsed.get("created_at", "")),
                })
                continue
        except (json.JSONDecodeError, TypeError):
            pass

        # Parse "User: ... Assistant: ..." format
        if "User:" in text and "Assistant:" in text:
            parts = text.split("Assistant:", 1)
            user_part = parts[0].replace("User:", "").strip()
            assistant_part = parts[1].split("Evidence:", 1)[0].strip() if len(parts) > 1 else ""
            evidence_part = (
                parts[1].split("Evidence:", 1)[1].strip()
                if len(parts) > 1 and "Evidence:" in parts[1]
                else ""
            )
            turns.append({
                "query": user_part,
                "answer": assistant_part,
                "evidence_summary": evidence_part,
                "timestamp": "",
            })
            continue

        # Fallback: treat entire text as a single context block
        turns.append({
            "query": "",
            "answer": text[:500],
            "evidence_summary": "",
            "timestamp": "",
        })

    return turns


def _compress_turn(turn: dict[str, str], max_chars: int = COMPRESSED_TURN_CHARS) -> str:
    """Compress a single turn to a brief summary."""
    query = turn.get("query", "")[:80]
    answer = turn.get("answer", "")[:max_chars]
    if query:
        return f"Q: {query}\nA: {answer}"
    return answer


def format_prior_context(
    chain_response: dict[str, Any] | None,
    *,
    max_total_chars: int = MAX_CONTEXT_CHARS,
    recent_count: int = RECENT_TURN_COUNT,
) -> str:
    """Format prior conversation turns into a prompt-ready context block.

    Strategy:
    - Most recent N turns: full content
    - Older turns: compressed to ~200 chars each
    - Total capped at max_total_chars

    Args:
        chain_response: Raw HIVE-MIND traverse_graph or recall response.
        max_total_chars: Maximum total characters for the context block.
        recent_count: Number of recent turns to keep at full fidelity.

    Returns:
        Formatted markdown string, empty if no prior context.
    """
    turns = extract_turns_from_chain(chain_response)
    if not turns:
        return ""

    parts: list[str] = []

    # Split into older and recent
    if len(turns) > recent_count:
        older = turns[:-recent_count]
        recent = turns[-recent_count:]

        # Compress older turns
        if older:
            compressed_lines = [_compress_turn(t) for t in older]
            compressed_block = "\n".join(compressed_lines)
            parts.append(f"### Earlier conversation (summarized)\n{compressed_block}")
    else:
        recent = turns

    # Recent turns at full fidelity
    for i, turn in enumerate(recent):
        query = turn.get("query", "")
        answer = turn.get("answer", "")
        evidence = turn.get("evidence_summary", "")

        turn_parts: list[str] = []
        if query:
            turn_parts.append(f"**User**: {query}")
        if answer:
            turn_parts.append(f"**Assistant**: {answer}")
        if evidence:
            turn_parts.append(f"*Evidence*: {evidence[:300]}")

        if turn_parts:
            parts.append(f"### Turn {len(turns) - len(recent) + i + 1}\n" + "\n".join(turn_parts))

    if not parts:
        return ""

    full_context = "## Prior Conversation Context\n\n" + "\n\n".join(parts)

    # Truncate if over budget
    if len(full_context) > max_total_chars:
        full_context = full_context[:max_total_chars] + "\n\n[...older context truncated]"

    return full_context
