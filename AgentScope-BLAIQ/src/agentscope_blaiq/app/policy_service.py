from __future__ import annotations

import json
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from agentscope_blaiq.persistence.models import (
    PolicySetRecord, PolicyRuleRecord, ModelRegistryRecord, ToolRegistryRecord
)

class PolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_policies(self, workspace_id: str | None = None) -> dict[str, Any]:
        # 1. Fetch from Registries first to get the absolute source of truth for "Available" items
        models_result = await self.session.execute(
            select(ModelRegistryRecord).where(ModelRegistryRecord.is_enabled == True)
        )
        registry_models = [m.model_name for m in models_result.scalars().all()]

        tools_result = await self.session.execute(
            select(ToolRegistryRecord).where(ToolRegistryRecord.is_enabled == True)
        )
        registry_tools = [t.name for t in tools_result.scalars().all()]

        # 2. Build Default Policy (Fallback)
        # Only use registry items as defaults if they exist
        flat_policy = {
            "allowedModels": registry_models or ["gpt-4o", "claude-3-5-sonnet"],
            "allowedTools": registry_tools or ["google_search", "python_interpreter"],
            "dataRetentionDays": 30,
            "approvalRequirements": ["destructive_action", "high_cost_run"],
            "canUseTools": True
        }

        # 3. Query Workspace-Specific or Global Policy Sets
        query = select(PolicySetRecord).where(PolicySetRecord.is_active == True)
        if workspace_id:
            query = query.where(PolicySetRecord.workspace_id == workspace_id)
        
        result = await self.session.execute(query.options(selectinload(PolicySetRecord.rules)))
        policy_sets = result.scalars().all()
        
        if not policy_sets:
            # If no policies exist but registries do, we return the registry-informed defaults
            return flat_policy
            
        # 4. Merge Rules — apply allow/deny effects from policy rules
        for ps in policy_sets:
            for r in ps.rules:
                if r.rule_type == "model_allow" and r.effect == "allow":
                    models = sorted(set(m.strip() for m in r.resource_pattern.split(",")))
                    flat_policy["allowedModels"] = models
                elif r.rule_type == "model_allow" and r.effect == "deny":
                    deny_models = {m.strip() for m in r.resource_pattern.split(",")}
                    flat_policy["allowedModels"] = sorted(
                        m for m in flat_policy["allowedModels"] if m not in deny_models
                    )
                elif r.rule_type == "tool_allow" and r.effect == "allow":
                    tools = sorted(set(t.strip() for t in r.resource_pattern.split(",")))
                    flat_policy["allowedTools"] = tools
                elif r.rule_type == "tool_deny" or (r.rule_type == "tool_allow" and r.effect == "deny"):
                    flat_policy["canUseTools"] = False
                elif r.rule_type == "data_retention":
                    try:
                        flat_policy["dataRetentionDays"] = int(r.resource_pattern)
                    except (ValueError, TypeError):
                        pass

        # Deterministic sort for stable API responses
        flat_policy["allowedModels"] = sorted(flat_policy["allowedModels"])
        flat_policy["allowedTools"] = sorted(flat_policy["allowedTools"])
        flat_policy["approvalRequirements"] = sorted(flat_policy["approvalRequirements"])

        return flat_policy
