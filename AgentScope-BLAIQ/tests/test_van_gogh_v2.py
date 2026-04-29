from __future__ import annotations

import asyncio
import json

from agentscope_blaiq.app.services.van_gogh_v2 import VanGogh


class FakeResolver:
    def __init__(self, content: str) -> None:
        self.model = RecordingModel(content)

    def build_agentscope_model(self, role: str):
        assert role == "vangogh"
        return self.model


class RecordingModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages = None

    async def __call__(self, messages, **kwargs):
        self.messages = messages
        assert kwargs == {}
        return {"content": self.content}


def test_render_artifact_preserves_metadata_and_parses_json_response():
    asyncio.run(_run_render_artifact_assertions())


async def _run_render_artifact_assertions():
    payload = {
        "image_prompts": [{"id": "slide_1", "prompt": "Clean product workspace"}],
        "ui_code": "```jsx\nexport default function App() { return <main /> }\n```",
        "design_rationale": "Uses the requested brand system.",
    }
    resolver = FakeResolver(f"```json\n{json.dumps(payload)}\n```")
    designer = VanGogh(resolver=resolver)

    results = [
        item
        async for item in designer.render_artifact(
            visual_spec="Build a one-slide hero.",
            brand_dna="Use a crisp editorial palette.",
            metadata={"artifact_type": "pitch_deck"},
        )
    ]

    assert len(results) == 1
    assert results[0].metadata["artifact_type"] == "pitch_deck"
    assert results[0].metadata["detail"]["design_rationale"] == "Uses the requested brand system."
    assert "Use a crisp editorial palette." in resolver.model.messages[0]["content"]
