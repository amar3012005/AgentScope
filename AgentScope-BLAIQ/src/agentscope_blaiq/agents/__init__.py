"""Specialist agents for AgentScope-BLAIQ.

This package keeps import side effects intentionally minimal so subpackages
can be loaded independently during migration.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

__all__ = [
    "ContentDirectorAgent",
    "GovernanceAgent",
    "ResearchAgent",
    "StrategicAgent",
    "TextBuddyAgent",
    "VangoghAgent",
    "content_director",
    "governance",
    "research",
    "strategic",
    "text_buddy",
    "vangogh",
]

_LAZY_EXPORTS = {
    "ContentDirectorAgent": "agentscope_blaiq.agents.content_director",
    "GovernanceAgent": "agentscope_blaiq.agents.governance",
    "ResearchAgent": "agentscope_blaiq.agents.research",
    "StrategicAgent": "agentscope_blaiq.agents.strategic",
    "TextBuddyAgent": "agentscope_blaiq.agents.text_buddy",
    "VangoghAgent": "agentscope_blaiq.agents.vangogh",
}


if TYPE_CHECKING:  # pragma: no cover - import-only typing aid
    from agentscope_blaiq.agents.content_director import ContentDirectorAgent
    from agentscope_blaiq.agents.governance import GovernanceAgent
    from agentscope_blaiq.agents.research import ResearchAgent
    from agentscope_blaiq.agents.strategic import StrategicAgent
    from agentscope_blaiq.agents.text_buddy import TextBuddyAgent
    from agentscope_blaiq.agents.vangogh import VangoghAgent


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_path)
    return getattr(module, name)
