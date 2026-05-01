# -*- coding: utf-8 -*-
import asyncio
import os
import httpx
import logging
import json
import re
from pathlib import Path
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
from agentscope.tool import ToolResponse, Toolkit
from agentscope.message import TextBlock

from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.tools.openrouter_media import OpenRouterMediaService, image_tool_response, video_tool_response

logger = logging.getLogger(__name__)

# CORE FIX: Global context for tracking the active session ID to prevent LLM hallucinations
active_session_id: ContextVar[str] = ContextVar("active_session_id", default="")

_SKILL_AUTHOR_PROMPT = """You are the official BLAIQ Skill Author.

Write a production-grade AgentScope SKILL.md body for the given target agent.

Requirements:
- Return markdown only. Do not include YAML frontmatter.
- The document must read like a high-level README for the capability, but remain operational.
- Use this exact section structure:
    # <Skill Title>
    ## Purpose
    ## When To Use
    ## Operating Instructions
    ## Output Requirements
    ## Constraints
    ## Examples
- Make the instructions specific to the target agent.
- Include 2 concrete examples.
- Avoid placeholders, generic filler, and meta commentary.
- Make the skill robust enough that the agent can apply it without extra clarification.
- Focus on agent behavior and workflow, not fabricated domain facts.
- Do not invent formulas, benchmark numbers, market data, percentages, or unsupported claims unless the caller explicitly provided them.
- If the capability depends on factual research, instruct the agent to gather or verify evidence before making claims.
- Examples must demonstrate usage patterns, not fictional output presented as truth.

Target agent: {target_agent}
Skill name: {name}
Skill description: {description}

If the caller provided body guidance, incorporate it faithfully:
{body_guidance}
"""


_SKILL_METADATA_PROMPT = """You are the official BLAIQ Skill Metadata Author.

Your job is to convert a raw user request into production-safe skill metadata for an AgentScope skill.

Return exactly one JSON object with this shape:
{{
    "name": "snake_case_skill_name",
    "title": "Human Readable Skill Title",
    "description": "One sentence describing what the skill enables the target agent to do.",
    "body_guidance": "Short guidance for the downstream skill author about scope, workflow, and quality bar."
}}

Rules:
- `name` must be concise, descriptive, and valid snake_case.
- `description` must be clear, professional, and grounded in the user's actual intent.
- `body_guidance` should tell the skill author what kind of playbook to generate.
- Do not invent market facts, formulas, metrics, or operational claims that the user did not request.
- If the request is research-oriented, say the skill must gather evidence before making claims.
- Output JSON only. No markdown fences. No commentary.

Target agent: {target_agent}
Raw user request: {raw_request}
Existing name hint: {name_hint}
Existing description hint: {description_hint}
"""


def _normalize_skill_name(name: str, description: str) -> str:
        base = (name or description or "generated_skill").strip().lower()
        base = re.sub(r"[^a-z0-9_\-\s]", "", base)
        base = base.replace("-", "_")
        base = re.sub(r"\s+", "_", base)
        return re.sub(r"_+", "_", base).strip("_")[:80] or "generated_skill"


def _looks_generated_placeholder(text: str) -> bool:
        stripped = (text or "").strip().lower()
        return not stripped or "to be generated" in stripped


def _is_weak_skill_name(name: str) -> bool:
    candidate = (name or "").strip().lower()
    return candidate in {"", "generate", "skill", "new_skill", "create_skill", "custom_skill"}


def _extract_json_object(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None


def _friendly_skill_governance_message(review_text: str) -> str:
        text = str(review_text or "").strip()
        if not text:
            return "I finished the governance check, but it did not return a readable summary."

        summary_match = re.search(r"summary:\s*(.+)", text, re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else "The governance review completed."

        findings: list[str] = []
        in_findings = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith("what happened"):
                in_findings = True
                continue
            if lowered.startswith("what do you want to do next"):
                break
            if in_findings:
                clean = line.lstrip("-* ").strip()
                if clean:
                    findings.append(clean)
            if len(findings) >= 2:
                break

        if not findings:
            return summary
        if len(findings) == 1:
            return f"{summary} Main note: {findings[0]}"
        return f"{summary} Main notes: {findings[0]} Also, {findings[1]}"


def register_global_agent_skills(toolkit: Toolkit) -> None:
    """Register globally shared agent skills for all participating agents."""
    skills_dir = Path(__file__).resolve().parents[1] / "skills"
    
    # Recursively find all SKILL.md files and register their parent directories
    for skill_path in skills_dir.rglob("SKILL.md"):
        try:
            skill_folder = str(skill_path.parent)
            toolkit.register_agent_skill(skill_folder)
            logger.debug(f"Registered agent skill from: {skill_folder}")
        except ValueError:
            # Skill may already be registered on this toolkit.
            continue
        except Exception as e:
            logger.error(f"Failed to register skill at {skill_path}: {e}")

class BlaiqEnterpriseFleet:
    """
    The 'Remote Control' for the BLAIQ Agent Fleet.
    Wraps AaaS nodes and HIVE-MIND memory into standard AgentScope tools.
    """
    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url
        self.media_service = OpenRouterMediaService()
        
        # Determine host for services (Docker internal vs Local for TUI)
        common_host = os.environ.get("BLAIQ_SERVICE_HOST")
        strategist_host = os.environ.get("STRATEGIST_HOST", common_host or "strategist-service")
        research_host = os.environ.get("RESEARCH_HOST", common_host or "research-service")
        buddy_host = os.environ.get("TEXT_BUDDY_HOST", common_host or "text-buddy-service")
        content_host = os.environ.get("CONTENT_DIRECTOR_HOST", common_host or "content-director-service")
        vangogh_host = os.environ.get("VAN_GOGH_HOST", common_host or "van-gogh-service")
        oracle_host = os.environ.get("ORACLE_HOST", common_host or "oracle-service")
        gov_host = os.environ.get("GOVERNANCE_HOST", common_host or "governance-service")

        if common_host == "localhost":
            strategist_host = research_host = buddy_host = content_host = vangogh_host = oracle_host = gov_host = "localhost"

        # Internal ports match docker-compose: strategist=8090, research=8091,
        # text_buddy=8093, content_director=8095, van_gogh=8096, oracle=8092, governance=8094
        if strategist_host == "localhost":
            self.fleet_configs = {
                "strategist": {"url": f"http://localhost:8095/process", "target": "StrategistV2"},
                "research": {"url": f"http://localhost:8096/process", "recall_url": f"http://localhost:8096/recall", "target": "DeepResearchV2"},
                "text_buddy": {"url": f"http://localhost:8097/process", "target": "TextBuddyV2"},
                "content_director": {"url": f"http://localhost:8098/process", "target": "ContentDirectorV2"},
                "van_gogh": {"url": f"http://localhost:8099/process", "target": "VanGoghV2"},
                "oracle": {"url": f"http://localhost:8094/process", "target": "OracleV2"},
                "governance": {"url": f"http://localhost:8093/process", "target": "GovernanceV2"}
            }
        else:
            self.fleet_configs = {
                "strategist": {"url": f"http://{strategist_host}:8090/process", "target": "StrategistV2"},
                "research": {"url": f"http://{research_host}:8091/process", "recall_url": f"http://{research_host}:8091/recall", "target": "DeepResearchV2"},
                "text_buddy": {"url": f"http://{buddy_host}:8092/process", "target": "TextBuddyV2"},
                "content_director": {"url": f"http://{content_host}:8095/process", "target": "ContentDirectorV2"},
                "van_gogh": {"url": f"http://{vangogh_host}:8096/process", "target": "VanGoghV2"},
                "oracle": {"url": f"http://{oracle_host}:8092/process", "target": "OracleV2"},
                "governance": {"url": f"http://{gov_host}:8092/process", "target": "GovernanceV2"}
            }
        
        # HIVE-MIND Component
        self.hivemind = HivemindMCPClient(
            rpc_url=settings.hivemind_mcp_rpc_url,
            api_key=settings.hivemind_api_key,
            timeout_seconds=settings.hivemind_timeout_seconds
        )

    async def _rpc_call(self, service_key: str, payload: Dict[str, Any], use_recall: bool = False, on_chunk: Optional[Callable[[str], Any]] = None, return_last_only: bool = False) -> str:
        """Helper to call remote AaaS nodes with explicit targeting and streaming support."""
        config = self.fleet_configs.get(service_key)
        if not config:
            return f"Error: Unknown service {service_key}"
            
        endpoint = config["recall_url"] if use_recall and "recall_url" in config else config["url"]
        payload["target"] = config["target"]
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                text_content = ""
                last_chunk_text = ""
                # Track message-level metadata by msg id so content deltas can
                # inherit kind (e.g. content_abstract) from their parent message.
                active_msg_metadata: dict[str, dict] = {}
                active_msg_content: dict[str, str] = {}

                async def _process_line(raw_line: str) -> None:
                    nonlocal text_content, last_chunk_text
                    line = raw_line.strip()
                    if not line or not line.startswith("data: "):
                        return
                    try:
                        data = json.loads(line[6:])

                        # Register message-level metadata for later delta lookup.
                        if data.get("object") == "message" and data.get("id"):
                            msg_meta = data.get("metadata") or {}
                            if msg_meta:
                                active_msg_metadata[data["id"]] = msg_meta

                        metadata = data.get("metadata") or {}
                        msg_id = data.get("id") or data.get("msg_id")
                        # Content deltas carry no metadata — inherit from parent message.
                        if data.get("object") == "content" and data.get("delta") and data.get("msg_id"):
                            parent_meta = active_msg_metadata.get(data["msg_id"], {})
                            if parent_meta:
                                metadata = parent_meta

                        # Handle both AgentScope AaaS formats
                        content = data.get("content")
                        part_text = ""
                        if isinstance(content, str):
                            part_text = content
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    part_text += part.get("text", "")

                        # Support the direct 'text' field for robustness
                        if data.get("object") == "content" and data.get("text"):
                            part_text = data["text"]

                        if msg_id and part_text:
                            active_msg_content[msg_id] = active_msg_content.get(msg_id, "") + part_text

                        # Preserve structured intermediate artifacts so the workflow bridge
                        # can promote them into explicit UI events.
                        kind = metadata.get("kind")
                        is_thought = kind == "agent_thought"
                        is_abstract_stream = kind == "content_abstract" and bool(part_text)
                        is_completed_artifact = (
                            kind
                            and data.get("object") == "message"
                            and data.get("status") == "completed"
                        )
                        if on_chunk and (is_thought or is_abstract_stream or is_completed_artifact):
                            content_payload = part_text
                            if kind == "content_abstract" and msg_id:
                                content_payload = active_msg_content.get(msg_id, part_text)
                            structured_payload = json.dumps(
                                {
                                    "object": data.get("object"),
                                    "status": data.get("status"),
                                    "content": content_payload,
                                    "metadata": metadata,
                                },
                            )
                            if asyncio.iscoroutinefunction(on_chunk):
                                await on_chunk(structured_payload)
                            else:
                                on_chunk(structured_payload)

                        if part_text:
                            text_content += part_text
                            last_chunk_text = part_text
                            # Any kind-tagged chunk (artifact, abstract, thought) is
                            # already forwarded via the structured payload above.
                            # Skip raw-text emission to keep chat clean.
                            if on_chunk and not kind:
                                if asyncio.iscoroutinefunction(on_chunk):
                                    await on_chunk(part_text)
                                else:
                                    on_chunk(part_text)
                    except Exception:
                        pass

                async with client.stream("POST", endpoint, json=payload) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    # Flat JSON (non-streaming) response — read and return directly.
                    if "application/json" in content_type:
                        full = await response.aread()
                        text = full.decode()
                        if on_chunk:
                            if asyncio.iscoroutinefunction(on_chunk):
                                await on_chunk(text)
                            else:
                                on_chunk(text)
                        return text
                    # SSE stream — process lines as they arrive.
                    async for raw_line in response.aiter_lines():
                        await _process_line(raw_line)

                return last_chunk_text if return_last_only else text_content
            except Exception as e:
                logger.error(f"Fleet RPC failed to {endpoint} ({config['target']}): {e}")
                return f"Error: {str(e)}"

    # --- HIVE-MIND TOOLS ---

    async def hivemind_recall(self, query: str, session_id: Optional[str] = None) -> ToolResponse:
        """
        Recalls facts and memories from the global BLAIQ HIVE-MIND using AI filtering.
        Args:
            query (str): The search query for memory retrieval.
            session_id (str, optional): IGNORED. Current session is used automatically.
        """
        # CORE FIX: Use the non-hallucinated session ID from context
        session_id = active_session_id.get() or session_id
        
        try:
            # Use AI synthesis instead of raw vector recall to eliminate noise
            raw_res = await self.hivemind.query_with_ai(question=query, context_limit=8)
            res = self.hivemind._extract_tool_payload(raw_res)

            # Try to extract the synthesized text depending on payload structure
            answer = res.get("answer") or res.get("text") or res.get("content")
            
            if not answer and isinstance(res, str):
                answer = res
            elif not answer:
                answer = str(res)
                
            if not answer or answer == "{}" or answer == "None":
                return ToolResponse(content=[TextBlock(type="text", text="No relevant data found for this query.")])

            # Only mark research done on success
            if session_id:
                try:
                    from agentscope_blaiq.persistence.redis_state import RedisStateStore
                    state_store = RedisStateStore()
                    if state_store.client:
                        await state_store.client.set(f"blaiq:session:{session_id}:research_done", "1", ex=3600)
                except Exception as e:
                    logger.warning(f"Failed to mark research done in Redis: {e}")

            return ToolResponse(content=[TextBlock(type="text", text=answer)])
        except Exception as e:
            return ToolResponse(content=[TextBlock(type="text", text=f"Recall failed: {str(e)}")])

    async def hivemind_save(self, title: str, content: str, tags: Optional[List[str]] = None) -> ToolResponse:
        """
        Saves a new fact or decision to the global BLAIQ HIVE-MIND for future recall.
        Args:
            title (str): The title of the memory.
            content (str): The content to persist.
            tags (list, optional): Labels for categorization.
        """
        try:
            res = await self.hivemind.save_memory(title=title, content=content, tags=tags)
            return ToolResponse(content=[TextBlock(type="text", text=f"Memory saved successfully: {res.get('id', 'OK')}")])
        except Exception as e:
            return ToolResponse(content=[TextBlock(type="text", text=f"Save failed: {str(e)}")])

    # --- FLEET AAAS TOOLS ---

    async def research_evidence(self, query: str, session_id: Optional[str] = None, **kwargs: Any) -> ToolResponse:
        """
        MANDATORY FIRST STEP for evidence gathering. 
        Researches facts, data, or product details required for the mission from the BLAIQ Knowledge Graph.
        Args:
            query (str): The research subject or specific variable to find.
            session_id (str, optional): IGNORED.
        """
        # CORE FIX: Use the non-hallucinated session ID from context
        session_id = active_session_id.get() or session_id
        on_chunk = kwargs.get("on_chunk")
        
        payload = {
            "input": [{"role": "user", "content": [{"type": "text", "text": query}]}],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("research", payload, use_recall=True, on_chunk=on_chunk)

        # Only mark research done when the service actually returned data, not an error
        is_error = res.startswith("Error:") or not res.strip()
        if not is_error and session_id:
            try:
                from agentscope_blaiq.persistence.redis_state import RedisStateStore
                state_store = RedisStateStore()
                if state_store.client:
                    await state_store.client.set(f"blaiq:session:{session_id}:research_done", "1", ex=3600)
            except Exception as e:
                logger.warning(f"Failed to mark research done in Redis: {e}")

        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def synthesize_text(self, goal: str, evidence_brief: str, artifact_type: str, session_id: Optional[str] = None, **kwargs: Any) -> ToolResponse:
        """
        Triggers the TextBuddy Agent to synthesize a text artifact using structural blueprints.
        Args:
            goal (str): The original user goal/request (e.g. "Create a company history report").
            evidence_brief (str): The factual context from Research.
            artifact_type (str): The type of output needed (report, email, etc.)
            session_id (str, optional): IGNORED.
        """
        session_id = active_session_id.get() or session_id
        on_chunk = kwargs.get("on_chunk")
        user_instruction = f"{goal}\n\nArtifact type: {artifact_type}"
        payload = {
            "input": [{
                "role": "user",
                "content": [{"type": "text", "text": user_instruction}],
                "metadata": {"evidence_brief": evidence_brief, "artifact_type": artifact_type}
            }],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("text_buddy", payload, on_chunk=on_chunk, return_last_only=True)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def create_agent_skill(
        self,
        target_agent: str,  # "text_buddy" or "content_director"
        name: str = "",
        description: str = "",
        body_markdown: Optional[str] = None,
        raw_request: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs: Any
    ) -> ToolResponse:
        """
        Creates a new capability (skill) for a specific agent (TextBuddy or ContentDirector).
        This persists a SKILL.md file to the appropriate folder for immediate use.
        Args:
            name (str): Optional name hint. The tool may derive a better canonical skill name.
            description (str): Optional description hint. The tool may rewrite it for clarity.
            target_agent (str): Which agent it belongs to. Valid values: "text_buddy", "content_director".
            body_markdown (str, optional): Optional guidance or exact body. If omitted, the tool generates the full SKILL.md body with an LLM.
            raw_request (str, optional): The user's raw capability request. Preferred source for metadata generation.
            session_id (str, optional): IGNORED.
        """
        target_agent_clean = target_agent.lower().replace(" ", "_").replace("-", "_")

        if target_agent_clean not in {"text_buddy", "content_director"}:
            return ToolResponse(content=[TextBlock(type="text", text=f"Error: Invalid target_agent '{target_agent}'. Use 'text_buddy' or 'content_director'.")])

        raw_request_text = (raw_request or "").strip()
        if raw_request_text.lower().startswith("execute the create_agent_skill action using the tool"):
            raw_request_text = ""

        description_hint = description.strip()
        name_hint = "" if _is_weak_skill_name(name) else name.strip()
        request_text = (raw_request_text or description_hint or name_hint or "").strip()
        if not request_text:
            return ToolResponse(content=[TextBlock(type="text", text="Error: a skill request is required to generate a skill.")])

        canonical_name = name_hint
        canonical_description = description_hint
        body_guidance = ""

        try:
            resolver = LiteLLMModelResolver.from_settings(settings)
            metadata_prompt = _SKILL_METADATA_PROMPT.format(
                target_agent=target_agent_clean,
                raw_request=request_text,
                name_hint=name_hint or "none",
                description_hint=description_hint or "none",
            )
            metadata_response = await resolver.acompletion(
                role="custom",
                model_name="gpt-4o",
                messages=[{"role": "user", "content": metadata_prompt}],
                max_tokens=700,
                temperature=0.1,
            )
            metadata_text = resolver.extract_text(metadata_response).strip()
            metadata = _extract_json_object(metadata_text) or {}
            canonical_name = str(metadata.get("name") or canonical_name or "").strip()
            canonical_description = str(metadata.get("description") or canonical_description or request_text).strip()
            body_guidance = str(metadata.get("body_guidance") or "").strip()
        except Exception as exc:
            logger.warning("Skill metadata generation failed for request '%s': %s", request_text, exc)

        safe_name = _normalize_skill_name(canonical_name or request_text, canonical_description or request_text)
        if not canonical_name:
            canonical_name = safe_name
        if not canonical_description:
            canonical_description = request_text

        generated_body = body_markdown or ""
        if _looks_generated_placeholder(generated_body):
            try:
                prompt = _SKILL_AUTHOR_PROMPT.format(
                    target_agent=target_agent_clean,
                    name=canonical_name,
                    description=canonical_description,
                    body_guidance=body_guidance or f"Generate the complete skill body from this request: {request_text}",
                )
                response = await resolver.acompletion(
                    role="custom",
                    model_name="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2200,
                    temperature=0.2,
                )
                generated_body = resolver.extract_text(response).strip()
                if generated_body.startswith("```markdown"):
                    generated_body = generated_body.split("```markdown", 1)[1].rsplit("```", 1)[0].strip()
                elif generated_body.startswith("```"):
                    generated_body = generated_body.split("```", 1)[1].rsplit("```", 1)[0].strip()
            except Exception as exc:
                logger.error("LLM skill authoring failed for %s: %s", safe_name, exc)
                return ToolResponse(content=[TextBlock(type="text", text=f"Failed to generate skill body: {exc}")])

            final_name = canonical_name or safe_name

        skills_dir = Path(__file__).resolve().parents[1] / "skills" / target_agent_clean / safe_name
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_path = skills_dir / "SKILL.md"
        skill_content = (
            f"---\n"
            f"name: {final_name}\n"
            f"description: {canonical_description}\n"
            f"target_agent: {target_agent_clean}\n"
            f"---\n\n"
            f"{generated_body}"
        )

        try:
            skill_path.write_text(skill_content, encoding="utf-8")
            logger.info(f"Persisted new skill '{final_name}' to {skill_path}")
            governance_summary = "Governance review was skipped."
            governance_session_id = active_session_id.get() or session_id or "skill-governance"
            try:
                governance_input = (
                    f"Review this newly created AgentScope skill for clarity, structure, and readiness.\n\n"
                    f"Path: {skill_path}\n"
                    f"Target agent: {target_agent_clean}\n"
                    f"Description: {canonical_description}\n"
                    f"Raw request: {request_text}\n\n"
                    f"{skill_content}"
                )
                governance_result = await self.govern_artifact(
                    artifact_content=governance_input,
                    session_id=governance_session_id,
                )
                if governance_result.content:
                    first_block = governance_result.content[0]
                    governance_summary = getattr(first_block, "text", None) or str(first_block)
            except Exception as exc:
                logger.warning("Governance review failed for skill %s: %s", final_name, exc)
                governance_summary = f"Governance review could not complete: {exc}"

            return ToolResponse(content=[TextBlock(
                type="text",
                text=(
                    f"Skill '{final_name}' was created for {target_agent} and saved to {skill_path}. "
                    f"It can now handle: {canonical_description}\n\n"
                    f"Governance check: {_friendly_skill_governance_message(governance_summary)}"
                )
            )])
        except Exception as e:
            return ToolResponse(content=[TextBlock(type="text", text=f"Failed to create skill: {str(e)}")])

    async def orchestrate_visuals(
        self,
        text_artifact: str,
        evidence_brief: str,
        session_id: Optional[str] = None,
        artifact_type: str = "visual_html",
        **kwargs: Any,
    ) -> ToolResponse:
        """
        Triggers the Content Director to generate visual strategy and VanGogh instructions.
        Follows Brand DNA guidelines by default.
        Args:
            text_artifact (str): The completed text from TextBuddy.
            evidence_brief (str): The factual context.
            session_id (str, optional): IGNORED.
        """
        session_id = active_session_id.get() or session_id
        on_chunk = kwargs.get("on_chunk")
        payload = {
            "input": [{
                "role": "user",
                "content": [{"type": "text", "text": text_artifact}],
                "metadata": {
                    "evidence_brief": evidence_brief,
                    "artifact_type": artifact_type,
                }
            }],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("content_director", payload, on_chunk=on_chunk, return_last_only=True)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def render_visuals(self, visual_spec: str, session_id: str, brand_dna: str = "", **kwargs: Any) -> ToolResponse:
        """
        Triggers Van Gogh to render visual assets (Image Prompts + React/Tailwind code).
        Args:
            visual_spec (str): The detailed visual instructions from Content Director.
            session_id (str): The active session ID.
            brand_dna (str): The brand guidelines to follow.
        """
        on_chunk = kwargs.get("on_chunk")
        payload = {
            "input": [{
                "role": "user", 
                "content": [{"type": "text", "text": visual_spec}],
                "metadata": {"brand_dna": brand_dna}
            }],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("van_gogh", payload, on_chunk=on_chunk, return_last_only=True)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def generate_image(
        self,
        prompt: str,
        reference_image: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ToolResponse:
        """Generate images from a text prompt or a text+image prompt using OpenRouter."""
        try:
            result = await self.media_service.generate_image(
                prompt=prompt,
                reference_image=reference_image,
                model=model,
            )
            return image_tool_response(result)
        except Exception as exc:
            return ToolResponse(content=[TextBlock(type="text", text=f"Error: {exc}")])

    async def generate_video(
        self,
        prompt: str,
        model: Optional[str] = None,
    ) -> ToolResponse:
        """Generate videos from a text prompt using OpenRouter."""
        try:
            result = await self.media_service.generate_video(prompt=prompt, model=model)
            return video_tool_response(result)
        except Exception as exc:
            return ToolResponse(content=[TextBlock(type="text", text=f"Error: {exc}")])

    async def ask_human(
        self, 
        question: str, 
        session_id: Optional[str] = None,
        mission: str = "active",
        missing_variable: str = "info",
        current_status: str = "ongoing",
        artifact_type: str = "task"
    ) -> ToolResponse:
        """
        FAILSAFE ONLY. Use ONLY if 'hivemind_recall' and 'research_evidence' have failed.
        Suspends the workflow to ask the user for missing information or approvals via the Oracle HITL.
        Args:
            question (str): The clarification question.
            session_id (str, optional): IGNORED.
            mission (str): The high-level goal (e.g., 'Solve Leah Invoice').
            missing_variable (str): What is specifically missing after research attempts.
            current_status (str): What the agent was doing.
            artifact_type (str): The type of output being generated.
        """
        # CORE FIX: Use the non-hallucinated session ID from context
        session_id = active_session_id.get() or session_id
        
        # CORE FIX: Enforce research-first policy via Redis guard
        try:
            from agentscope_blaiq.persistence.redis_state import RedisStateStore
            state_store = RedisStateStore()
            if state_store.client:
                is_done = await state_store.client.get(f"blaiq:session:{session_id}:research_done")
                if not is_done:
                    logger.warning(f"Research Guard triggered for session {session_id}. Blocking ask_human.")
                    return ToolResponse(content=[TextBlock(type="text", text="ERROR: Research-First Policy Violation. You MUST call 'hivemind_recall' or 'research_evidence' to search for entities before asking the human.")])
        except Exception as e:
            logger.warning(f"Redis guard check failed: {e}")

        # Inject context as a JSON block in the text stream for the Oracle to discover
        context_block = json.dumps({
            "mission": mission,
            "missing_variable": missing_variable,
            "current_status": current_status,
            "artifact_type": artifact_type
        })
        
        payload = {
            "input": [{
                "role": "assistant", 
                "content": [
                    {"type": "text", "text": question},
                    {"type": "text", "text": context_block}
                ]
            }],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("oracle", payload)
        
        # Write to Redis and block until answer
        try:
            from agentscope_blaiq.persistence.redis_state import RedisStateStore
            import asyncio
            state_store = RedisStateStore()
            if state_store.client:
                # Store the question
                await state_store.client.set(f"blaiq:session:{session_id}:hitl_question", res, ex=3600)
                logger.info(f"Waiting for human input for session {session_id}")
                
                # Poll for answer
                for _ in range(600): # 10 minute timeout
                    await asyncio.sleep(1)
                    answer = await state_store.client.get(f"blaiq:session:{session_id}:hitl_answer")
                    if answer:
                        await state_store.client.delete(f"blaiq:session:{session_id}:hitl_answer")
                        ans_text = answer.decode('utf-8') if isinstance(answer, bytes) else str(answer)
                        return ToolResponse(content=[TextBlock(type="text", text=f"Human answered: {ans_text}")])
                
                # If we timeout, remove the question to clear the queue
                await state_store.client.delete(f"blaiq:session:{session_id}:hitl_question")
                return ToolResponse(content=[TextBlock(type="text", text="Human timed out. Please proceed using your best judgment.")])
        except Exception as e:
            logger.warning(f"Redis HITL polling failed: {e}")
            
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def ask_oracle_hitl(
        self,
        question: str,
        session_id: str,
        artifact_type: str = "report",
        evidence: str = "",
        **kwargs: Any,
    ) -> ToolResponse:
        """Call oracle service to formulate a HITL question. Returns immediately — no polling."""
        on_chunk = kwargs.get("on_chunk")
        context_block = json.dumps({
            "mission": question,
            "artifact_type": artifact_type,
            "evidence_summary": evidence[:500] if evidence else "",
        })
        payload = {
            "input": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "text", "text": context_block},
                ],
            }],
            "session_id": session_id,
            "user_id": "fleet-swarm",
        }
        res = await self._rpc_call("oracle", payload, on_chunk=on_chunk)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def govern_artifact(self, artifact_content: str, session_id: str, **kwargs: Any) -> ToolResponse:
        """
        FINAL STEP. Triggers Governance to perform a safety, brand, and quality check on the final output.
        Args:
            artifact_content (str): The final generated content or code.
            session_id (str): The active session ID.
        """
        on_chunk = kwargs.get("on_chunk")
        payload = {
            "input": [{"role": "user", "content": [{"type": "text", "text": artifact_content}]}],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("governance", payload, on_chunk=on_chunk)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def architect_mission(self, query: str, session_id: str, **kwargs: Any) -> str:
        """
        Calls the Strategist service to architect a mission plan.
        Returns the raw concatenated response string (not a ToolResponse) so the
        SwarmEngine can parse planning events directly.
        Args:
            query (str): The user goal.
            session_id (str): The active session ID.
        """
        on_chunk = kwargs.get("on_chunk")
        session_id = active_session_id.get() or session_id
        payload = {
            "input": [{"role": "user", "content": [{"type": "text", "text": query}]}],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        return await self._rpc_call("strategist", payload, on_chunk=on_chunk)

async def _research_retry_middleware(
    kwargs: dict,
    next_handler: Callable,
) -> AsyncGenerator[ToolResponse, None]:
    """Retry middleware for research tools.

    Retries hivemind_recall and research_evidence up to 3 times when the
    service returns an error string. Yields ToolResponse(is_interrupted=True)
    after exhausting retries so the agent handles it gracefully rather than
    escalating to ask_human.
    """
    tool_call = kwargs.get("tool_call", {})
    tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")

    if tool_name not in {"hivemind_recall", "research_evidence"}:
        async for response in await next_handler(**kwargs):
            yield response
        return

    max_retries = 3
    for attempt in range(max_retries):
        collected: list[ToolResponse] = []
        async for response in await next_handler(**kwargs):
            collected.append(response)

        # Detect error string in first content block
        first_text = ""
        if collected:
            block = collected[0].content[0] if collected[0].content else None
            if block is not None:
                first_text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")

        if first_text.startswith("Error:") or first_text.startswith("Recall failed:"):
            if attempt < max_retries - 1:
                logger.warning(f"Research tool '{tool_name}' attempt {attempt + 1} failed, retrying...")
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            # Exhausted — signal graceful degradation, do NOT call ask_human
            logger.error(f"Research tool '{tool_name}' failed after {max_retries} attempts. Degrading gracefully.")
            yield ToolResponse(
                is_interrupted=True,
                content=[TextBlock(
                    type="text",
                    text=(
                        f"Research service unavailable after {max_retries} attempts. "
                        "Proceed using your internal knowledge and clearly state that "
                        "live data could not be retrieved. Do NOT call ask_human."
                    ),
                )],
            )
            return

        for r in collected:
            yield r
        return


def get_enterprise_toolkit() -> Toolkit:
    """Returns the fully equipped fleet toolkit including HIVE-MIND access."""
    fleet = BlaiqEnterpriseFleet()
    toolkit = Toolkit()
    register_global_agent_skills(toolkit)

    # HIVE-MIND Tools (Fast Path)
    toolkit.register_tool_function(fleet.hivemind_recall)
    toolkit.register_tool_function(fleet.hivemind_save)

    # Core Fleet Tools
    toolkit.register_tool_function(fleet.research_evidence)
    toolkit.register_tool_function(fleet.synthesize_text)
    toolkit.register_tool_function(fleet.create_agent_skill)
    toolkit.register_tool_function(fleet.orchestrate_visuals)
    toolkit.register_tool_function(fleet.render_visuals)
    toolkit.register_tool_function(fleet.generate_image)
    toolkit.register_tool_function(fleet.generate_video)
    toolkit.register_tool_function(fleet.govern_artifact)

    # Failsafe Tools
    toolkit.register_tool_function(fleet.ask_human)

    return toolkit


def get_strategist_toolkit() -> Toolkit:
    """Pure router — strategist must NOT execute tasks itself.

    Empty toolkit forces the strategist to emit routing JSON only. The outer
    SwarmEngine then runs the actual specialist pipeline (research, text_buddy,
    content_director, vangogh, governance), which is what produces the per-agent
    started/completed events the frontend AgentCards subscribe to.
    """
    return Toolkit()


def get_role_fallback_toolkit(role: str) -> Toolkit:
    """Toolkit handed to the strategist when a specialist agent fails.

    The fallback strategist uses these tools to retry the failed work itself.
    Each role gets the *same* tool the original agent uses, so the retry can
    legitimately accomplish the task instead of just re-reporting the failure.
    """
    fleet = BlaiqEnterpriseFleet()
    toolkit = Toolkit()
    register_global_agent_skills(toolkit)

    if role == "research":
        toolkit.register_tool_function(fleet.hivemind_recall)
        toolkit.register_tool_function(fleet.research_evidence)
    elif role == "text_buddy":
        toolkit.register_tool_function(fleet.synthesize_text)
        toolkit.register_tool_function(fleet.create_agent_skill)
    elif role == "content_director":
        toolkit.register_tool_function(fleet.orchestrate_visuals)
        toolkit.register_tool_function(fleet.create_agent_skill)
    elif role == "vangogh":
        toolkit.register_tool_function(fleet.render_visuals)
        toolkit.register_tool_function(fleet.generate_image)
        toolkit.register_tool_function(fleet.generate_video)
    elif role == "governance":
        toolkit.register_tool_function(fleet.govern_artifact)
    else:
        # Unknown role — give recall as a generic retrieval primitive
        toolkit.register_tool_function(fleet.hivemind_recall)

    return toolkit
