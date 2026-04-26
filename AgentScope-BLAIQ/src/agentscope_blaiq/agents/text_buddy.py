"""Compatibility shim for legacy text_buddy module imports."""

from agentscope_blaiq.agents.text_buddy.agent import TEXT_FAMILIES, TextBuddyAgent

__all__ = ["TextBuddyAgent", "TEXT_FAMILIES"]
