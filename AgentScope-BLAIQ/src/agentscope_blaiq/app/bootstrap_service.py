from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentscope_blaiq.persistence.models import OrgRecord, RoleRecord, UserRecord, WorkspaceRecord, workspace_members

class BootstrapService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_bootstrap_data(self, user_id: str) -> dict[str, Any]:
        # Fetch user with memberships
        user_result = await self.session.execute(
            select(UserRecord)
            .where(UserRecord.id == user_id)
            .options(selectinload(UserRecord.workspaces))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return {"error": "User not found"}

        # Resolve organization
        organization = None
        if user.workspaces:
            ws = user.workspaces[0]
            org_result = await self.session.execute(
                select(OrgRecord).where(OrgRecord.id == ws.org_id)
            )
            organization = org_result.scalar_one_or_none()

        # Resolve Workspace-Specific Roles and Permissions
        # We query the workspace_members join table to get the role per workspace
        memberships_data: list[dict[str, Any]] = []
        all_permissions: set[str] = set()
        user_roles: set[str] = set()

        for ws in user.workspaces:
            # Get role and permissions for this user in this workspace
            membership_query = (
                select(RoleRecord)
                .join(workspace_members, workspace_members.c.role_id == RoleRecord.id)
                .where(workspace_members.c.workspace_id == ws.id)
                .where(workspace_members.c.user_id == user.id)
                .options(selectinload(RoleRecord.permissions))
            )
            role_result = await self.session.execute(membership_query)
            role = role_result.scalar_one_or_none()
            
            role_name = "member"
            if role:
                role_name = role.name
                user_roles.add(role_name)
                for p in role.permissions:
                    all_permissions.add(p.name)
            
            memberships_data.append({
                "workspace_id": ws.id,
                "name": ws.name,
                "slug": ws.slug,
                "role": role_name
            })

        # Global overrides for Superuser
        if user.is_superuser:
            all_permissions.add("*")
            user_roles.add("admin")
            # Ensure superuser sees all memberships as admin if requested, 
            # but for now we trust the stored roles.

        sorted_roles = sorted(user_roles)
        primary_role = "admin" if "admin" in user_roles else (sorted_roles[0] if sorted_roles else "member")

        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.full_name or user.email.split("@")[0],
                "role": primary_role
            },
            "organization": {
                "id": organization.id,
                "name": organization.name,
                "slug": organization.slug
            } if organization else None,
            "roles": sorted_roles,
            "permissions": sorted(all_permissions),
            "workspace_memberships": sorted(
                memberships_data,
                key=lambda item: (item["name"], item["workspace_id"]),
            ),
            "feature_flags": {
                "deep_research": True,
                "multi_agent_swarm": True,
                "custom_agents": True
            },
            "connectivity": {
                "core_api_base_url": "http://localhost:8030",
                "core_health": "ok"
            },
            "onboarding": {
                "completed": True,
                "step": "done"
            },
            "client_support": ["claude", "antigravity", "vscode", "remote-mcp", "notebooklm"]
        }
