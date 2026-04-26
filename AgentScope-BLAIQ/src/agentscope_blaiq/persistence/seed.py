from __future__ import annotations

import asyncio
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from agentscope_blaiq.persistence.database import async_session_factory, Base, engine
from agentscope_blaiq.persistence.models import (
    UserRecord, OrgRecord, WorkspaceRecord, RoleRecord, PermissionRecord, 
    workspace_members, ModelRegistryRecord, ToolRegistryRecord, PolicySetRecord, PolicyRuleRecord
)

async def seed_data():
    async with async_session_factory()() as session:
        # 1. Check if already seeded
        user_result = await session.execute(select(UserRecord).where(UserRecord.email == "admin@blaiq.ai"))
        existing_user = user_result.scalar_one_or_none()
        if existing_user:
            if not existing_user.hashed_password:
                existing_user.hashed_password = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
                await session.commit()
                print("Database already seeded; admin password initialized.")
            else:
                print("Database already seeded.")
            return

        print("Seeding Enterprise Data...")

        # 2. Permissions
        permissions = [
            PermissionRecord(name="workspace.view", description="View workspace"),
            PermissionRecord(name="workspace.admin", description="Administer workspace"),
            PermissionRecord(name="chat.create", description="Start new chats"),
            PermissionRecord(name="agent.create", description="Create custom agents"),
            PermissionRecord(name="tool.use", description="Use tools"),
        ]
        session.add_all(permissions)
        await session.flush()
        
        perm_map = {p.name: p for p in permissions}

        # 3. Roles
        admin_role = RoleRecord(name="admin", description="Full access")
        member_role = RoleRecord(name="member", description="Standard user")
        
        admin_role.permissions.extend(permissions)
        member_role.permissions.extend([perm_map["workspace.view"], perm_map["chat.create"], perm_map["tool.use"]])
        
        session.add_all([admin_role, member_role])
        await session.flush()

        # 4. Org & Workspace
        org = OrgRecord(name="Default Org", slug="default-org")
        session.add(org)
        await session.flush()
        
        workspace = WorkspaceRecord(org_id=org.id, name="Main Workspace", slug="main-workspace")
        session.add(workspace)
        await session.flush()

        # 5. User
        admin_user = UserRecord(
            email="admin@blaiq.ai",
            full_name="System Admin",
            is_superuser=True,
            hashed_password=bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode(),
        )
        session.add(admin_user)
        await session.flush()

        # 6. Membership
        await session.execute(
            workspace_members.insert().values(
                workspace_id=workspace.id,
                user_id=admin_user.id,
                role_id=admin_role.id
            )
        )

        # 7. Model/Tool Registry
        models = [
            ModelRegistryRecord(provider="openai", model_name="gpt-4o"),
            ModelRegistryRecord(provider="anthropic", model_name="claude-3-5-sonnet"),
            ModelRegistryRecord(provider="google", model_name="gemini-1.5-pro"),
        ]
        tools = [
            ToolRegistryRecord(name="google_search", manifest_json="{}"),
            ToolRegistryRecord(name="python_interpreter", manifest_json="{}"),
        ]
        session.add_all(models + tools)
        await session.flush()

        # 8. Initial Policy Set
        policy_set = PolicySetRecord(workspace_id=workspace.id, name="Default Policy")
        session.add(policy_set)
        await session.flush()
        
        rules = [
            PolicyRuleRecord(policy_set_id=policy_set.id, rule_type="model_allow", resource_pattern="gpt-4o,claude-3-5-sonnet"),
            PolicyRuleRecord(policy_set_id=policy_set.id, rule_type="tool_allow", resource_pattern="google_search,python_interpreter"),
        ]
        session.add_all(rules)
        
        await session.commit()
        print("Seeding complete.")

async def init_db():
    async with engine.begin() as conn:
        # This will create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)
    await seed_data()

if __name__ == "__main__":
    asyncio.run(init_db())
