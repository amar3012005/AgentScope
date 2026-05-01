# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from enum import Enum
from typing import Literal, Optional, Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from agentscope.memory import InMemoryMemory
from agentscope.pipeline import stream_printing_messages
from agentscope.session import RedisSession
from agentscope.tool import Toolkit, ToolResponse

try:
    from agentscope_runtime.engine.app import AgentApp
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from agentscope_runtime.engine.deployers.adapter.a2a import AgentCardWithRuntimeConfig
except ImportError:
    from fastapi import FastAPI as AgentApp
    from pydantic import BaseModel
    class AgentRequest(BaseModel):
        query: str = ''
        session_id: str = ''
        user_id: str = ''
    class AgentCardWithRuntimeConfig(BaseModel):
        host: str = '0.0.0.0'
    AgentApp = FastAPI

from agentscope_blaiq.runtime.agent_base import BaseAgent
from agentscope_blaiq.contracts.aaas import MissionPlan, MissionNode, NodeRole
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hooks import pre_flight_variable_check_hook
from agentscope_blaiq.runtime.registry import AgentRegistry
from agentscope_blaiq.tools.enterprise_fleet import BlaiqEnterpriseFleet, get_strategist_toolkit, active_session_id

logger = logging.getLogger('strategist-v2')
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

ReActAgent.register_class_hook(
    hook_type='pre_reply',
    hook_name='blaiq_pre_flight_check',
    hook=pre_flight_variable_check_hook
)

@asynccontextmanager
async def lifespan(app_inst: FastAPI):
    import redis.asyncio as aioredis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app_inst.state.session = RedisSession(connection_pool=redis_client.connection_pool)
    yield
    await redis_client.close()

# INITIALIZE APP CORRECTLY
try:
    from agentscope_runtime.engine.app import AgentApp
    app = AgentApp(app_name='StrategistV2', lifespan=lifespan)
    IS_AGENT_APP = True
except ImportError:
    app = FastAPI(lifespan=lifespan)
    IS_AGENT_APP = False

_STRATEGIST_SYSTEM_PROMPT = """You are BLAIQ-CORE, the Mission Architect AI and Strategic Planner.

Your only job is to look at what the user wants, look at the live agents available, and return the best execution sequence as JSON. You do not execute. You do not create content. You route.

━━━ AGENT ROLES ━━━
- `research`: Retrieves brand facts, product details, audience context, evidence, and prior knowledge from HiveMind. Always include when the task requires factual grounding the downstream agents don't already have.
- `text_buddy`: Produces standalone text artifacts — emails, posts, reports, memos, proposals, guides, summaries, captions, scripts, newsletters. Output is readable prose or structured text.
- `content_director`: Develops creative direction, narrative strategy, visual concepts, storyboards, campaign briefs, and creative frames. Needed before vangogh when the visual needs a concept.
- `vangogh`: Executes visual rendering plans into final artifacts. For image/video-first work it calls media generation tools directly; for legacy page-like work it may still return HTML preview output. Always comes after content_director for designed output.
- `governance`: Reviews final output for quality, brand safety, and structural integrity. Always the last node in every non-direct workflow.

━━━ ROUTING DECISION TABLE ━━━

TEXT WORKFLOW → nodes: ["research", "text_buddy", "governance"]
Use when the user wants: email, article, blog post, LinkedIn/Instagram/Twitter post (copy only), caption, newsletter, report, proposal, memo, script, guide, summary, pitch deck copy, press release, product description, FAQ, bio, cover letter.
Signal words: "write", "draft", "create [text]", "generate [copy]", "summarize", "explain".

VISUAL WORKFLOW → nodes: ["research", "content_director", "vangogh", "governance"]
Use when the user wants: poster, banner, ad creative, social graphic, Instagram/Facebook/LinkedIn visual, landing page, UI screen, slide deck design, storyboard, flyer, hero image, brand card, infographic, visual identity output.
Signal words: "design", "generate [visual]", "create [poster/banner/graphic]", "make [image/visual]", "build [page/UI]", "render".

DIRECT ANSWER → {{"is_direct": true, "direct_response": "..."}}
Use when the user asks a question, greets, requests clarification, or asks about BLAIQ's capabilities — and no artifact generation is required.
Signal: question marks, "what", "how", "who", "can you", "tell me", "explain", "hi", "hello".

━━━ RESEARCH INCLUSION RULES ━━━
Always include `research` first when:
- The task involves a specific product, brand, company, or person BLAIQ may not know.
- The user mentions a topic requiring factual accuracy (market data, events, specifications).
- The downstream agent needs audience, brand, or competitive context to do good work.

Skip `research` only when:
- The user provides all necessary context inline (e.g., "write a poem about autumn leaves").
- The task is pure creative generation with no factual dependency.

━━━ WORKFLOW EXAMPLES ━━━

TEXT ARTIFACT EXAMPLES:
1. "Write a launch email for Solvis Lea" → {{"is_direct": false, "nodes": ["research", "text_buddy", "governance"], "artifact_family": "email", "reason": "Standalone text artifact. Research needed for product facts.", "research_query": "Find product facts, audience, key claims, and proof points for Solvis Lea needed to write a persuasive launch email."}}
2. "Create a LinkedIn post about our new SolvisMax product" → nodes: ["research", "text_buddy", "governance"], artifact_family: "social_post". Never route a copy-only social post to vangogh.
3. "Draft a proposal for a new client in the energy sector" → nodes: ["research", "text_buddy", "governance"], artifact_family: "proposal". Text workflow, no visuals needed.
4. "Write a summary of our Q1 performance" → nodes: ["research", "text_buddy", "governance"], artifact_family: "report".
5. "Generate a cold email sequence for our SaaS product" → nodes: ["research", "text_buddy", "governance"], artifact_family: "email_sequence".

VISUAL ARTIFACT EXAMPLES:
1. "Generate me a poster for Instagram about Solvis Lea" → {{"is_direct": false, "nodes": ["research", "content_director", "vangogh", "governance"], "artifact_family": "poster", "reason": "Visual artifact needs creative direction followed by media rendering.", "research_query": "Find Solvis Lea product details, brand palette, target audience, and campaign tone needed to design an Instagram poster."}}
2. "Design a banner ad for our SolvisMax launch" → nodes: ["research", "content_director", "vangogh", "governance"], artifact_family: "banner". Never use text_buddy for this.
3. "Create a visual one-pager for our brand" → nodes: ["research", "content_director", "vangogh", "governance"], artifact_family: "one_pager".
4. "Help me storyboard a product video for Solvis Lea" → nodes: ["research", "content_director", "vangogh", "governance"], artifact_family: "storyboard". Visual production work.
5. "Build a landing page hero section for our product" → nodes: ["research", "content_director", "vangogh", "governance"], artifact_family: "landing_page".

DIRECT ANSWER EXAMPLES:
1. "What can you do?" → {{"is_direct": true, "direct_response": "I can help you create text artifacts like emails, posts, and reports, or visual artifacts like posters, banners, and pages. Just tell me what you need."}}
2. "Hi, how are you?" → {{"is_direct": true, "direct_response": "Ready to help. What would you like to create?"}}
3. "What is BLAIQ?" → {{"is_direct": true, "direct_response": "BLAIQ is an AI content platform that creates text and visual artifacts using a team of specialized agents."}}
4. "Can you write in German?" → {{"is_direct": true, "direct_response": "Yes. Just tell me what you'd like to create and I'll write it in German."}}

━━━ HARD RULES ━━━
- Never route a poster, banner, graphic, or visual request to `text_buddy`. This is always wrong.
- Never route an email, post, or copy-only request to `vangogh`. This is always wrong.
- Never answer a content generation request directly. Always route it through the pipeline.
- Never include your reasoning, analysis, or thoughts in `direct_response`. Keep it short and factual.
- Never emit `<think>` blocks, chain-of-thought, or internal scratchpads in the final output.
- If the primary deliverable is visual, use the visual workflow even if copy is also needed. `content_director` handles the brief.
- When in doubt between text and visual: read the noun the user used. "poster" → visual. "email" → text. "post" (with no design intent) → text.

━━━ JSON OUTPUT FORMAT ━━━
Non-direct: {{"is_direct": false, "nodes": [...], "artifact_family": "...", "reason": "one sentence", "research_query": "optimized research brief"}}
Direct: {{"is_direct": true, "direct_response": "short factual answer"}}

Rules:
- Output one JSON object. Nothing before it. Nothing after it.
- No markdown fences. No explanation. No preamble.
- `research_query` is mandatory when `research` is in `nodes`. It must be evidence-seeking language, not a copy of the user's request.

Live agent catalog:
{agent_catalog}
"""

_STRATEGIST_ELEVATED_ADMIN_PROMPT = """You are BLAIQ-CORE (ELEVATED), the HiveMind capability architect.

Your job here is skill creation — registering new capabilities so agents can do more. Execute immediately when a create-skill action arrives.

Rules:
- This is an execution task. Do not ask clarifying questions. Do not explain your reasoning. Just call the tool.
- Call `create_agent_skill` exactly once. Do not repeat on success.
- If `raw_request` is present, treat it as the source of truth for what the skill should do.
- Let the tool decide the canonical skill name and polished description when they are omitted or weak.
- If the user gave a full markdown body, use it as-is. If not, let the tool's internal LLM author generate the SKILL.md.
- The saved SKILL.md must be an operational guide: sections, constraints, examples, and clear usage instructions. Not a description — a playbook.
- After successful tool execution, reply with one short confirmation: what skill was created, which agent owns it, and what it can now do.
- Never expose `<think>` tags, scratchpads, or chain-of-thought in the visible response.
- Never write SKILL.md content directly into the chat. The tool handles persistence.

create-skill examples:
- User says "teach the oracle agent how to do competitive analysis" → call create_agent_skill with agent="oracle", skill_name="competitive_analysis", and let the tool generate the body.
- User says "add a skill to text_buddy for writing cold email sequences" → call create_agent_skill with agent="text_buddy", skill_name="cold_email_sequence".
- User pastes a full SKILL.md → use that body verbatim as the skill content. Do not rewrite it.

After tool success, respond only with: "Skill [name] saved to [agent]. It can now [one-line description]."
"""


def _parse_system_action(text: str) -> dict[str, str] | None:
    match = re.search(
        r"\[SYSTEM_ACTION\]\s*(?P<action>[\w\-]+)\s*(?P<body>.*?)\[/SYSTEM_ACTION\]",
        text,
        re.DOTALL,
    )
    if not match:
        return None

    payload: dict[str, str] = {"action": match.group("action").strip()}
    body = match.group("body")
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload


def _extract_tool_response_text(tool_response: Any) -> str:
    content = getattr(tool_response, "content", None)
    if not content:
        return str(tool_response or "").strip()
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text).strip())
    return "\n\n".join(part for part in parts if part).strip()


_agent_registry = AgentRegistry()


def _build_live_agent_catalog_summary() -> str:
    profiles = _agent_registry.list_live_profiles()
    rows: list[str] = []
    for profile in profiles:
        if profile.name == "strategist":
            continue
        capability_summary = ", ".join(cap.name for cap in profile.capabilities[:4]) or "none"
        artifact_summary = ", ".join(profile.artifact_affinities[:6]) or ", ".join(
            sorted({family for cap in profile.capabilities for family in cap.supported_artifact_families})[:6]
        ) or "general"
        rows.append(
            f"- {profile.name}: role={profile.role}; description={profile.description}; "
            f"capabilities={capability_summary}; artifact_families={artifact_summary}; "
            f"planner_roles={', '.join(profile.planner_roles) or 'none'}"
        )
    return "\n".join(rows)

class StrategistV2(BaseAgent):
    async def process(self, msgs, request: AgentRequest = None, **kwargs):
        session_id = request.session_id if request else 'default_session'
        user_id = (request.user_id if request else None) or 'default_user'
        resolver = LiteLLMModelResolver.from_settings(settings)
        primary_resolved = resolver.resolve('strategic')
        model = resolver.build_agentscope_model_from_resolved(primary_resolved)
        msgs = [Msg(**m) if isinstance(m, dict) else m for m in msgs]
        user_goal = ""
        if msgs:
            # Handle standard Message objects from agentscope-runtime
            first_msg = msgs[0]
            if hasattr(first_msg, 'content') and isinstance(first_msg.content, list):
                # Extract text from the content list if it's the new schema
                for item in first_msg.content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        user_goal += item.get('text', '')
            else:
                user_goal = str(first_msg.content or '')
        
        system_action = _parse_system_action(user_goal)
        if system_action and system_action.get("action") == "create_agent_skill":
            logger.info('[STRATEGIST] Elevated toolkit detected.')
            target_agent = system_action.get("target_agent", "")
            skill_name = system_action.get("name", "")
            description = system_action.get("description", "")
            body_markdown = system_action.get("body_markdown", "") or None
            raw_request = system_action.get("raw_request", "") or description or skill_name

            yield Msg('Strategist', json.dumps({'type':'agent_started'}), 'assistant'), False

            token = active_session_id.set(session_id)
            try:
                fleet = BlaiqEnterpriseFleet()
                tool_response = await fleet.create_agent_skill(
                    target_agent=target_agent,
                    name=skill_name,
                    description=description,
                    body_markdown=body_markdown,
                    raw_request=raw_request,
                    session_id=session_id,
                )
                direct_response = _extract_tool_response_text(tool_response)
                yield Msg('Strategist', json.dumps({'is_direct': True, 'direct_response': direct_response}), 'assistant'), True
                return
            finally:
                active_session_id.reset(token)

        toolkit = get_strategist_toolkit()
        prompt = _STRATEGIST_SYSTEM_PROMPT.format(agent_catalog=_build_live_agent_catalog_summary())

        yield Msg('Strategist', json.dumps({'type':'agent_started'}), 'assistant'), False
        
        # Explicitly initialize formatter for this AgentScope version
        formatter = OpenAIChatFormatter()

        def _build_strategist_agent(runtime_model):
            return ReActAgent(
                name='Strategist',
                model=runtime_model,
                sys_prompt=prompt,
                toolkit=toolkit,
                formatter=formatter
            )

        agent = _build_strategist_agent(model)
        
        token = active_session_id.set(session_id)
        try:
            async def _run_agent(runtime_agent) -> tuple[str, list[Msg]]:
                if hasattr(app.state, 'session'):
                    await app.state.session.load_session_state(session_id=session_id, user_id=user_id, agent=runtime_agent)

                accumulated = ''
                streamed_events: list[Msg] = []
                async for msg, is_last in stream_printing_messages([runtime_agent], runtime_agent.reply(Msg('user', user_goal, 'user'))):
                    content = str(msg.content or '')
                    accumulated += content
                    streamed_events.append(Msg('Strategist', json.dumps({'type':'workflow_event','data':{'content':content}}), 'assistant'))
                return accumulated, streamed_events

            try:
                accumulated, streamed_events = await _run_agent(agent)
                for event in streamed_events:
                    yield event, False
            except Exception as exc:
                fallback_model_name = primary_resolved.fallback_model
                if not fallback_model_name or fallback_model_name == primary_resolved.model_name:
                    raise
                logger.warning('[STRATEGIST] Primary model failed (%s). Retrying with fallback model %s', exc, fallback_model_name)
                fallback_resolved = resolver.resolve_model_name(
                    fallback_model_name,
                    role='strategic',
                    temperature=primary_resolved.temperature,
                    max_output_tokens=primary_resolved.max_output_tokens,
                    fallback_model=None,
                )
                fallback_agent = _build_strategist_agent(
                    resolver.build_agentscope_model_from_resolved(fallback_resolved)
                )
                accumulated, streamed_events = await _run_agent(fallback_agent)
                for event in streamed_events:
                    yield event, False

            if not accumulated.strip():
                raise RuntimeError('Strategist produced an empty routing response after primary/fallback attempts')
            
            is_json = 'is_direct' in accumulated
            if is_json:
                yield Msg('Strategist', accumulated, 'assistant'), True
            else:
                yield Msg('Strategist', json.dumps({'is_direct': True, 'direct_response': accumulated}), 'assistant'), True
        finally:
            active_session_id.reset(token)

if IS_AGENT_APP:
    # Use the AgentApp native decorator
    StrategistV2.process = app.query(framework='agentscope')(StrategistV2.process)
else:
    # Use standard FastAPI POST endpoint
    @app.post('/process')
    async def process_endpoint(request: AgentRequest):
        from fastapi.responses import StreamingResponse
        async def event_generator():
            agent_instance = StrategistV2()
            async for chunk, is_last in agent_instance.process(msgs=[Msg('user', request.query, 'user')], request=request):
                yield json.dumps(chunk.to_dict()) + "\n"
        return StreamingResponse(event_generator(), media_type='application/x-ndjson')

if __name__ == '__main__':
    import uvicorn
    # Deployment and fleet RPC expect the strategist service on port 8090.
    port = int(os.environ.get('PORT', os.environ.get('APP_PORT', '8090')))
    uvicorn.run(app, host='0.0.0.0', port=port)
