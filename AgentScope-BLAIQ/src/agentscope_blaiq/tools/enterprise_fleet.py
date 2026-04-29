# -*- coding: utf-8 -*-
import asyncio
import os
import httpx
import logging
import json
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
from agentscope.tool import ToolResponse, Toolkit
from agentscope.message import TextBlock

from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient
from agentscope_blaiq.runtime.config import settings

logger = logging.getLogger(__name__)

# CORE FIX: Global context for tracking the active session ID to prevent LLM hallucinations
active_session_id: ContextVar[str] = ContextVar("active_session_id", default="")

class BlaiqEnterpriseFleet:
    """
    The 'Remote Control' for the BLAIQ Agent Fleet.
    Wraps AaaS nodes and HIVE-MIND memory into standard AgentScope tools.
    """
    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url
        
        # Determine host for services (Docker internal vs Local for TUI)
        host = os.environ.get("BLAIQ_SERVICE_HOST", "research-service") # Default to internal
        buddy_host = os.environ.get("BLAIQ_SERVICE_HOST", "text-buddy-service")
        content_host = os.environ.get("BLAIQ_SERVICE_HOST", "content-director-service")
        vangogh_host = os.environ.get("BLAIQ_SERVICE_HOST", "van-gogh-service")
        oracle_host = os.environ.get("BLAIQ_SERVICE_HOST", "oracle-service")
        gov_host = os.environ.get("BLAIQ_SERVICE_HOST", "governance-service")
        
        if os.environ.get("BLAIQ_SERVICE_HOST") == "localhost":
             host = buddy_host = content_host = vangogh_host = oracle_host = gov_host = "localhost"

        # Mapping endpoint URL and its internal AgentApp target name
        # COOLIFY MAPPING: Research (8096:8091), Text (8097:8092), Director (8098:8092), VanGogh (8099:8092), Oracle (8094:8092)
        if host == "localhost":
            self.fleet_configs = {
                "research": {"url": f"http://localhost:8096/process", "recall_url": f"http://localhost:8096/recall", "target": "DeepResearchV2"},
                "text_buddy": {"url": f"http://localhost:8097/process", "target": "TextBuddyV2"},
                "content_director": {"url": f"http://localhost:8098/process", "target": "ContentDirectorV2"},
                "van_gogh": {"url": f"http://localhost:8099/process", "target": "VanGoghV2"},
                "oracle": {"url": f"http://localhost:8094/process", "target": "OracleV2"},
                "governance": {"url": f"http://localhost:8093/process", "target": "GovernanceV2"}
            }
        else:
            self.fleet_configs = {
                "research": {"url": f"http://{host}:8091/process", "recall_url": f"http://{host}:8091/recall", "target": "DeepResearchV2"},
                "text_buddy": {"url": f"http://{buddy_host}:8092/process", "target": "TextBuddyV2"},
                "content_director": {"url": f"http://{content_host}:8092/process", "target": "ContentDirectorV2"},
                "van_gogh": {"url": f"http://{vangogh_host}:8092/process", "target": "VanGoghV2"},
                "oracle": {"url": f"http://{oracle_host}:8094/process", "target": "OracleV2"},
                "governance": {"url": f"http://{gov_host}:8092/process", "target": "GovernanceV2"},
                "strategist": {"url": f"http://{os.environ.get('BLAIQ_SERVICE_HOST', 'strategist-service')}:8092/process", "target": "StrategistV2"}
            }
        
        # HIVE-MIND Component
        self.hivemind = HivemindMCPClient(
            rpc_url=settings.hivemind_mcp_rpc_url,
            api_key=settings.hivemind_api_key,
            timeout_seconds=settings.hivemind_timeout_seconds
        )

    async def architect_mission(self, query: str, session_id: str, **kwargs: Any) -> str:
        """
        Triggers the Master Strategist to architect a mission plan and decide if a mission is needed.
        Args:
            query (str): The user goal.
            session_id (str): The active session ID.
        """
        on_chunk = kwargs.get("on_chunk")
        payload = {
            "input": [{"role": "user", "content": [{"type": "text", "text": query}]}],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        # Strategist is on port 8090 but in Docker it might be mapped differently.
        # Based on strategist_v2.py, it runs on 8090.
        # Let's check docker-compose.coolify.yml if possible.
        # Assuming 8090 is the internal port.
        config = self.fleet_configs.get("strategist")
        if config and "localhost" in config["url"]:
            config["url"] = "http://localhost:8090/process"
        else:
            host = os.environ.get("BLAIQ_SERVICE_HOST", "strategist-service")
            config["url"] = f"http://{host}:8090/process"

        res = await self._rpc_call("strategist", payload, on_chunk=on_chunk)
        return res

    async def _rpc_call(self, service_key: str, payload: Dict[str, Any], use_recall: bool = False, on_chunk: Optional[Callable[[str], Any]] = None) -> str:
        """Helper to call remote AaaS nodes with explicit targeting and streaming support."""
        config = self.fleet_configs.get(service_key)
        if not config:
            return f"Error: Unknown service {service_key}"
            
        endpoint = config["recall_url"] if use_recall and "recall_url" in config else config["url"]
        payload["target"] = config["target"]
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                
                # Check if it's a streaming response or flat JSON
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type and not response.text.startswith("data: "):
                    text = response.text
                    if on_chunk:
                        if asyncio.iscoroutinefunction(on_chunk): await on_chunk(text)
                        else: on_chunk(text)
                    return text
                
                text_content = ""
                for line in response.text.splitlines():
                    if not line.strip(): continue
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
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
                            
                            if part_text:
                                text_content += part_text
                                if on_chunk:
                                    if asyncio.iscoroutinefunction(on_chunk): await on_chunk(part_text)
                                    else: on_chunk(part_text)
                            
                            if data.get("last", False):
                                break
                        except Exception:
                            continue
                            
                return text_content
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
        res = await self._rpc_call("text_buddy", payload, on_chunk=on_chunk)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

    async def orchestrate_visuals(self, text_artifact: str, evidence_brief: str, session_id: Optional[str] = None, **kwargs: Any) -> ToolResponse:
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
        combined = text_artifact
        if evidence_brief:
            combined = (
                f"## RESEARCH EVIDENCE (already gathered — do NOT call hivemind_recall)\n"
                f"{evidence_brief}\n\n"
                f"## TEXT ARTIFACT\n"
                f"{text_artifact}"
            )
        payload = {
            "input": [{
                "role": "user",
                "content": [{"type": "text", "text": combined}],
                "metadata": {"evidence_brief": evidence_brief}
            }],
            "session_id": session_id,
            "user_id": "fleet-admin"
        }
        res = await self._rpc_call("content_director", payload, on_chunk=on_chunk)
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
        res = await self._rpc_call("van_gogh", payload, on_chunk=on_chunk)
        return ToolResponse(content=[TextBlock(type="text", text=res)])

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
        # 1. Trigger the Oracle service to formulate the question/options
        res = await self._rpc_call("oracle", payload)
        
        # 2. Extract structured metadata from the Oracle response if available
        # Some oracles might return JSON strings with options/why
        options = []
        why = ""
        try:
            if "{" in res:
                data = json.loads(res)
                options = data.get("options", [])
                why = data.get("why_it_matters", "")
        except Exception:
            pass

        # 3. Return a structured signal that the orchestrator can intercept.
        # We return this as text so the agent 'thinks' it called the tool successfully,
        # but the orchestrator (strategist_v2) will see this and trigger the suspension.
        return ToolResponse(content=[TextBlock(type="text", text=json.dumps({
            "metadata": {
                "kind": "hitl_request",
                "session_id": session_id,
                "requires_input": True,
                "options": options,
                "why_it_matters": why
            },
            "content": question
        }))])

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

    # HIVE-MIND Tools (Fast Path)
    toolkit.register_tool_function(fleet.hivemind_recall)
    toolkit.register_tool_function(fleet.hivemind_save)

    # Core Fleet Tools
    toolkit.register_tool_function(fleet.research_evidence)
    toolkit.register_tool_function(fleet.synthesize_text)
    toolkit.register_tool_function(fleet.orchestrate_visuals)
    toolkit.register_tool_function(fleet.render_visuals)
    toolkit.register_tool_function(fleet.govern_artifact)

    # Failsafe Tools
    toolkit.register_tool_function(fleet.ask_human)

    return toolkit
