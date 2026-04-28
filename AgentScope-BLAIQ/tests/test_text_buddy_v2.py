from __future__ import annotations

import asyncio

from agentscope_blaiq.app.services.text_buddy_v2 import TextBuddy


class FakeResolver:
    def __init__(self) -> None:
        self.model = RecordingModel()

    def build_agentscope_model(self, role: str):
        assert role == "text_buddy"
        return self.model


class RecordingModel:
    def __init__(self) -> None:
        self.messages = None
        self.kwargs = None

    async def __call__(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return {"content": "Drafted artifact"}


def test_generate_artifact_inlines_skills_without_passing_toolkit_to_model():
    asyncio.run(_run_generate_artifact_assertions())


async def _run_generate_artifact_assertions():
    resolver = FakeResolver()
    buddy = TextBuddy(resolver=resolver)

    results = [
        item
        async for item in buddy.generate_artifact(
            request_text="Write a launch email.",
            artifact_type="email",
            evidence_brief="Launch is on May 1.",
            hitl_feedback="Keep it concise.",
        )
    ]

    assert len(results) == 1
    assert results[0].get_text_content() == "Drafted artifact"
    assert resolver.model.kwargs == {}

    system_prompt = resolver.model.messages[0]["content"]
    assert "AGENTSCOPE SKILLS:" in system_prompt
    assert "Launch is on May 1." in system_prompt
    assert "Keep it concise." in system_prompt
