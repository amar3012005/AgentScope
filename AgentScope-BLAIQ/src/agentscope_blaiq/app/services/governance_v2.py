# -*- coding: utf-8 -*-
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

# AgentScope Core
from agentscope.message import Msg

# AgentScope Runtime (AaaS)
try:
    from agentscope_runtime.engine.app import AgentApp
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from agentscope_runtime.engine.deployers.adapter.a2a import AgentCardWithRuntimeConfig
except ImportError:
    from fastapi import FastAPI as AgentApp
    from pydantic import BaseModel
    class AgentRequest(BaseModel):
        input: list
        session_id: str
        user_id: str
    class AgentCardWithRuntimeConfig(BaseModel):
        host: str = "0.0.0.0"


def _create_decorator_app() -> AgentApp:
    try:
        return AgentApp(app_name="agentscope", app_description="AgentScope Runtime")
    except TypeError:
        return AgentApp(title="agentscope", description="AgentScope Runtime")


_fallback_app = _create_decorator_app()
app = _fallback_app
        
from typing import AsyncGenerator
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings

from agentscope_blaiq.runtime.agent_base import BaseAgent


def _humanize_governance_review(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return (
            "Summary: I could not produce a detailed governance review for this artifact.\n\n"
            "What happened: The review response came back empty.\n\n"
            "What do you want to do next?\n"
            "- Approve it as-is\n"
            "- Revise the artifact for tone and clarity\n"
            "- Regenerate the artifact"
        )

    verdict = "needs revision"
    lowered = text.lower()
    if "pass" in lowered and "fail" not in lowered:
        verdict = "looks good to ship"
    elif "fail" in lowered or "revision" in lowered:
        verdict = "needs revision"

    lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip()]
    findings: list[str] = []
    for line in lines:
        plain = line.strip()
        if plain.upper() in {"PASS", "FAIL"}:
            continue
        if plain.lower().startswith("summary:") or plain.lower().startswith("what happened") or plain.lower().startswith("what to do next"):
            continue
        if len(findings) < 3:
            findings.append(plain)

    if not findings:
        findings.append("The review completed, but the response did not include clear findings.")

    next_step = (
        "What do you want to do next?\n"
        "- Approve it as-is\n"
        "- Revise the artifact based on the review\n"
        "- Regenerate the artifact in a different tone"
    )

    return (
        f"Summary: This artifact {verdict}.\n\n"
        "What happened:\n"
        + "\n".join(f"- {item}" for item in findings)
        + "\n\n"
        + next_step
    )

class GovernanceAgent(BaseAgent):
    """
    The BLAIQ Governance Node.
    Ensures safety, brand alignment, and structural integrity of the final artifact.
    """
    def __init__(self, resolver: LiteLLMModelResolver | None = None, blueprint_dir: str | None = None):
        super().__init__(
            name="Governance",
            role="governance",
            sys_prompt="You are the BLAIQ governance agent responsible for validating final outputs.",
            resolver=resolver,
        )
        self.model = self.resolver.build_agentscope_model(self.role)
        self.blueprint_dir = blueprint_dir or "/app/data/blueprints"

    async def review_artifact_internal(
        self,
        artifact_content: str,
    ) -> AsyncGenerator[Msg, None]:
        
        # Load Brand Context (The "Soul" of the brand)
        brand_context = "General business professional style."
        for brand_file in ["solvis_brand_tone.md", "brand_tone.md", "brand_dna.md"]:
            try:
                import os
                path = f"{self.blueprint_dir}/{brand_file}"
                if os.path.exists(path):
                    with open(path, "r") as f:
                        brand_context = f.read()
                        break
            except Exception:
                continue

        system_prompt = f"""You are the BLAIQ Governance Reviewer — an expert artifact quality validator.

### YOUR MISSION:
Review the provided artifact and return a structured quality assessment.

### EVALUATION CRITERIA:
1. **Structural Integrity**: Does the artifact follow the expected format and structure for its type?
2. **Content Quality**: Is the content coherent, professional, and free of errors?
3. **Brand Compliance**: Does the artifact follow the Solvis brand guidelines provided below?
4. **Factual Accuracy**: Are there any obvious factual inconsistencies or hallucinations?

### OUTPUT FORMAT:
Return a HUMAN-FRIENDLY review for the operator, not an internal checklist.
Write exactly these 3 sections in plain language:

Summary: one short sentence saying whether the artifact is ready or needs revision.

What happened:
- 2-3 short bullets explaining the most important findings in human terms.

What do you want to do next?
- Offer clear next-step choices such as approve, revise, or regenerate.

Keep the tone calm, clear, and collaborative. Do not sound robotic. Do not dump rubric labels.

### SOLVIS BRAND CONTEXT:
{brand_context}
"""
        messages = [
            {"name": "system", "content": system_prompt, "role": "system"},
            {"name": "user", "content": f"Review the following artifact for quality, brand compliance, and structural integrity:\n\n{artifact_content}", "role": "user"}
        ]
        
        response = await self.model(messages)
        
        # Bulletproof extraction
        content = ""
        if isinstance(response, dict):
            content = response.get("text") or response.get("content") or str(response)
        else:
            content = getattr(response, "text", None) or getattr(response, "content", str(response))
        
        if isinstance(content, list):
            try:
                parts = []
                for c in content:
                    text_part = ""
                    if isinstance(c, dict):
                        text_part = c.get("text") or c.get("content", "")
                    else:
                        text_part = str(c)
                    
                    if text_part and text_part not in parts:
                        parts.append(text_part)
                # Use double newline to prevent clumping
                content = "\n\n".join(parts)
            except Exception:
                content = str(content)
        elif not isinstance(content, str):
            content = str(content)
            
        clean_content = _humanize_governance_review(content)
        
        yield Msg(
            name="GovernanceAgent",
            content=clean_content,
            role="assistant",
            metadata={"kind": "governance_review"}
        )

# Setup logging
logger = logging.getLogger("governance-v2")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Governance V2 cluster node online.")
    yield
    logger.info("Governance V2 cluster node offline.")

# Initialize the real production app
app = AgentApp(
    app_name="GovernanceV2",
    app_description="Brand Safety & Quality Assurance Node",
    lifespan=lifespan,
    a2a_config=AgentCardWithRuntimeConfig(host="0.0.0.0")
)


@app.query(framework="agentscope")
async def process(self, 
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    resolver = LiteLLMModelResolver.from_settings(settings)
    governance = GovernanceAgent(resolver=resolver)

    latest_msg = msgs[-1]
    if isinstance(latest_msg, dict):
        latest_msg = Msg(**latest_msg)

    artifact_content = latest_msg.get_text_content()

    logger.info(f"Governing artifact for session {request.session_id}")
    logger.info(f"[GOVERNANCE INPUT] Artifact content length: {len(artifact_content) if artifact_content else 0}")

    await governance._universal_acting_hook(phase="reviewing")

    if not artifact_content or not artifact_content.strip():
        logger.warning("[GOVERNANCE INPUT] Empty artifact content; skipping review.")
        yield Msg(
            name="Governance",
            content=(
                "Summary: There was no artifact content to review.\n\n"
                "What happened:\n"
                "- The generation step did not produce reviewable output.\n"
                "- Governance could not run a meaningful quality check.\n\n"
                "What do you want to do next?\n"
                "- Regenerate the artifact\n"
                "- Revise the prompt or inputs\n"
                "- Stop here"
            ),
            role="assistant",
            metadata={"kind": "governance_review", "skipped": True},
        ), True
        return

    async for item in governance.review_artifact_internal(
        artifact_content=artifact_content,
    ):
        logger.info(f"[GOVERNANCE RESPONSE] {item.content}")
        yield item, True

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
