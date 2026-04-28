# -*- coding: utf-8 -*-
import logging
from typing import Dict, Any, Optional

from agentscope.agent import ReActAgent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

# BLAIQ Internal Utilities
from agentscope_blaiq.app.factory.blueprint import AgentBlueprint
from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit
# We will use placeholders for now and refine based on existing files

import os
import json
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver

logger = logging.getLogger(__name__)

class AgentFactory:
    """
    Inflates AgentScope ReActAgents from JSON Blueprints.
    """
    
    @staticmethod
    async def generate_blueprint(prompt: str) -> AgentBlueprint:
        """
        Uses a Master Architect LLM to design a blueprint based on a user prompt.
        """
        resolver = LiteLLMModelResolver.from_settings()
        
        architect_prompt = f"""
        Design a highly specialized Agent Blueprint for this request: "{prompt}"
        
        REQUIREMENTS:
        - name: A cool, unique name for the agent (e.g., "VerseWeaver", "CodeScribe").
        - description: One sentence explaining its specialty.
        - model: Use "gpt-4o" for best results.
        - system: A professional system prompt.
        - output_schema: A JSON Schema (Dict) for the final response. 
          Example: {{"type": "object", "properties": {{"result": {{"type": "string"}}}}, "required": ["result"]}}
        - tools: A list of toolsets. 
          Example: [{{"type": "agent_toolset_20260401", "configs": [{{"name": "web_search", "enabled": true}}]}}]
        
        RETURN ONLY VALID RAW JSON. No markdown backticks. No conversational text.
        """
        
        response = await resolver.acompletion(
            role="custom", 
            model_name="gpt-4o",
            messages=[{"role": "user", "content": architect_prompt}],
            max_tokens=2500,
            temperature=0.3
        )
        
        raw_text = resolver.extract_text(response)
        logger.info(f"--- ARCHITECT RAW RESPONSE ---\n{raw_text}\n------------------------------")
        
        # Clean markdown code blocks if present
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()
            
        data = resolver.safe_json_loads(raw_text)
        return AgentBlueprint(**data)

    @staticmethod
    def save_blueprint(blueprint: AgentBlueprint, base_path: Optional[str] = None):
        """
        Persists the blueprint to the library.
        """
        if base_path is None:
            # Docker internal path mapped to host volume
            base_path = "/app/data/blueprints" if os.path.exists("/app/data") else "/Users/amar/blaiq/AgentScope-BLAIQ/data/blueprints"
            
        os.makedirs(base_path, exist_ok=True)
        filename = f"{blueprint.name.lower().replace(' ', '_')}.json"
        path = os.path.join(base_path, filename)
        
        with open(path, "w") as f:
            json.dump(blueprint.model_dump(), f, indent=2)
        
        logger.info(f"Saved new blueprint: {path}")
        return path
    
    @staticmethod
    def create_agent(blueprint: AgentBlueprint) -> ReActAgent:
        """
        Creates a fully initialized ReActAgent from a blueprint.
        """
        from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
        import agentscope
        
        logger.info(f"Inflating agent: {blueprint.name} using model {blueprint.model}")
        
        # 1. Build Model via Resolver
        resolver = LiteLLMModelResolver.from_settings()
        # We manually build the model object for the requested model string
        resolved = resolver.resolve_model_name(blueprint.model, role="custom")
        
        client_kwargs: dict[str, Any] = {}
        if resolved.api_base:
            client_kwargs["base_url"] = resolved.api_base

        from agentscope.model import OpenAIChatModel
        model_name = resolved.model_name if resolved.api_base else resolver._strip_provider_prefix(resolved.model_name)
        model = OpenAIChatModel(
            model_name=model_name,
            api_key=resolved.api_key,
            stream=False,
            reasoning_effort=resolved.reasoning_effort,  # type: ignore[arg-type]
            client_kwargs=client_kwargs or None,
            generate_kwargs={
                "temperature": resolved.temperature,
                "max_tokens": resolved.max_output_tokens,
                "timeout": resolved.timeout_seconds,
            },
        )

        # 2. Build and Filter Toolkit
        full_toolkit = get_enterprise_toolkit()
        
        # 3. Inject Structured Schema Enforcement if present
        sys_prompt = blueprint.system
        if blueprint.output_schema:
            schema_str = json.dumps(blueprint.output_schema, indent=2)
            sys_prompt += f"\n\nSTRICT OUTPUT REQUIREMENT:\nYou MUST return your final answer as a JSON object matching this schema:\n{schema_str}\n\nEnsure the response is ONLY the JSON object, no conversational filler."

        # 4. Instantiate ReActAgent
        agent = ReActAgent(
            name=blueprint.name,
            sys_prompt=sys_prompt,
            model=model,
            formatter=OpenAIChatFormatter(),
            memory=InMemoryMemory(),
            toolkit=full_toolkit,
            parallel_tool_calls=True,
        )
        
        return agent

    @classmethod
    def from_json(cls, json_data: Dict[str, Any]) -> ReActAgent:
        blueprint = AgentBlueprint(**json_data)
        return cls.create_agent(blueprint)
