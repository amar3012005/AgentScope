from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text
from agentscope_blaiq.persistence.database import Base, get_engine
from agentscope_blaiq.persistence.seed import seed_data


async def _apply_legacy_compat(active_engine: AsyncEngine) -> None:
    """Patch known legacy schema drifts to keep bootstrap deterministic."""
    async with active_engine.begin() as conn:
        # Legacy Postgres deployments may still carry roles.permissions_json as
        # NOT NULL with no default, which breaks normalized RoleRecord inserts.
        try:
            column_check = await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'roles'
                      AND column_name = 'permissions_json'
                    LIMIT 1
                    """
                )
            )
            if column_check.scalar():
                await conn.execute(text("ALTER TABLE roles ALTER COLUMN permissions_json SET DEFAULT '[]'"))
                await conn.execute(text("UPDATE roles SET permissions_json = '[]' WHERE permissions_json IS NULL"))
        except Exception:
            # Ignore for SQLite / non-Postgres / already-compatible schemas.
            pass

        # Older workflow tables were created before workspace/user scoping was
        # added. SQLAlchemy create_all() does not alter existing tables, so
        # add the nullable columns and indexes explicitly during bootstrap.
        try:
            await conn.execute(text("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(64)"))
            await conn.execute(text("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS user_id VARCHAR(64)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_workflows_workspace_id ON workflows (workspace_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_workflows_user_id ON workflows (user_id)"))
        except Exception:
            # Ignore for fresh schemas before the workflows table exists or
            # non-Postgres engines that do not support IF NOT EXISTS syntax.
            pass


async def bootstrap_database(engine: AsyncEngine | None = None) -> None:
    """Create the schema for a fresh v1 deployment and seed initial data.

    This is the explicit bootstrap path used by the application lifespan.
    """

    active_engine = engine or get_engine()
    async with active_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _apply_legacy_compat(active_engine)
    
    # Run idempotent seeding
    await seed_data()
