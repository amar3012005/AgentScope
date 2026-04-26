from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Tuple

from agentscope_blaiq.agents.custom.manifest import CustomAgentManifest, validate_custom_agent_manifest

DEFAULT_MANIFEST_SCHEMA_VERSION = "1.0"


class ManifestStore:
    """In-memory manifest store with optional disk persistence.

    When ``store_dir`` is provided the store JSON-serialises its state to
    ``<store_dir>/manifest_store.json`` on every write and reloads it on init.
    With no ``store_dir`` the store is purely in-memory (useful for tests and
    single-process deployments that don't need cross-restart persistence).
    """

    def __init__(self, store_dir: Optional[Path] = None) -> None:
        self._store_dir = Path(store_dir) if store_dir is not None else None
        # {agent_id: {version: manifest}}
        self._versions: dict[str, dict[str, CustomAgentManifest]] = {}
        # {agent_id: current_active_version}
        self._active_versions: dict[str, str] = {}
        if self._store_dir is not None:
            self._load()

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------

    def _state_file(self) -> Path:
        assert self._store_dir is not None
        return self._store_dir / "manifest_store.json"

    def _save(self) -> None:
        if self._store_dir is None:
            return
        self._store_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "active_versions": self._active_versions,
            "versions": {
                agent_id: {
                    ver: manifest.model_dump()
                    for ver, manifest in ver_map.items()
                }
                for agent_id, ver_map in self._versions.items()
            },
        }
        self._state_file().write_text(json.dumps(data, default=str), encoding="utf-8")

    def _load(self) -> None:
        path = self._state_file()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._active_versions = data.get("active_versions", {})
            for agent_id, ver_map in data.get("versions", {}).items():
                self._versions[agent_id] = {
                    ver: CustomAgentManifest.model_validate(manifest_dict)
                    for ver, manifest_dict in ver_map.items()
                }
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        manifest: CustomAgentManifest,
        version: str = "1.0.0",
        **_kwargs: Any,
    ) -> Tuple[bool, List[str]]:
        ok, errors = validate_custom_agent_manifest(manifest)
        if not ok:
            return False, errors
        agent_id = manifest.metadata.agent_id
        if agent_id not in self._versions:
            self._versions[agent_id] = {}
        self._versions[agent_id][version] = manifest
        self._active_versions[agent_id] = version
        self._save()
        return True, []

    def get(self, agent_id: str, **_kwargs: Any) -> Optional[CustomAgentManifest]:
        active_ver = self._active_versions.get(agent_id)
        if active_ver is None:
            return None
        return self._versions.get(agent_id, {}).get(active_ver)

    def list_all(self, **_kwargs: Any) -> List[CustomAgentManifest]:
        result = []
        for agent_id, active_ver in self._active_versions.items():
            manifest = self._versions.get(agent_id, {}).get(active_ver)
            if manifest is not None:
                result.append(manifest)
        return result

    def list_ids(self, **_kwargs: Any) -> List[str]:
        return sorted(self._active_versions.keys())

    def get_version(self, agent_id: str, version: str, **_kwargs: Any) -> Optional[CustomAgentManifest]:
        return self._versions.get(agent_id, {}).get(version)

    def list_versions(self, agent_id: str, **_kwargs: Any) -> List[str]:
        return list(self._versions.get(agent_id, {}).keys())

    def activate(self, agent_id: str, version: str, **_kwargs: Any) -> bool:
        if agent_id not in self._versions:
            return False
        if version not in self._versions[agent_id]:
            return False
        self._active_versions[agent_id] = version
        self._save()
        return True

    def rollback(self, agent_id: str, **_kwargs: Any) -> bool:
        versions = list(self._versions.get(agent_id, {}).keys())
        if len(versions) < 2:
            return False
        current = self._active_versions.get(agent_id)
        if current is None or current not in versions:
            return False
        idx = versions.index(current)
        if idx == 0:
            return False
        self._active_versions[agent_id] = versions[idx - 1]
        self._save()
        return True

    def deregister(self, agent_id: str, **_kwargs: Any) -> bool:
        if agent_id not in self._active_versions:
            return False
        del self._active_versions[agent_id]
        self._versions.pop(agent_id, None)
        self._save()
        return True


class PostgresManifestStore:
    """Postgres-backed manifest store for custom agents."""

    def __init__(self, session_factory: Any) -> None:
        try:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: F401
        except ImportError:
            pass
        self._session_factory = session_factory

    async def register(
        self,
        manifest: CustomAgentManifest,
        *,
        version: str = "1.0.0",
        workspace_id: Optional[str] = None,
        created_by: Optional[str] = None,
        is_public: bool = False,
    ) -> Tuple[bool, List[str]]:
        from sqlalchemy import update as sa_update
        from agentscope_blaiq.persistence.models import AgentCatalogRecord

        ok, errors = validate_custom_agent_manifest(manifest)
        if not ok:
            return False, errors
        agent_id = manifest.metadata.agent_id
        manifest_json = manifest.model_dump_json()
        async with self._session_factory() as session:
            await session.execute(
                sa_update(AgentCatalogRecord)
                .where(
                    AgentCatalogRecord.name == agent_id,
                    AgentCatalogRecord.workspace_id == workspace_id,
                    AgentCatalogRecord.is_active == True,
                )
                .values(is_active=False)
            )
            record = AgentCatalogRecord(
                workspace_id=workspace_id,
                created_by=created_by,
                name=agent_id,
                version=version,
                manifest_json=manifest_json,
                is_public=is_public,
                is_active=True,
            )
            session.add(record)
            await session.commit()
        return True, []

    async def get(self, agent_id: str, *, workspace_id: Optional[str] = None) -> Optional[CustomAgentManifest]:
        from sqlalchemy import select
        from agentscope_blaiq.persistence.models import AgentCatalogRecord

        async with self._session_factory() as session:
            stmt = select(AgentCatalogRecord).where(
                AgentCatalogRecord.name == agent_id,
                AgentCatalogRecord.is_active == True,
            )
            if workspace_id:
                stmt = stmt.where(AgentCatalogRecord.workspace_id == workspace_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                return CustomAgentManifest.model_validate_json(record.manifest_json)
        return None

    async def list_all(self, *, workspace_id: Optional[str] = None) -> List[CustomAgentManifest]:
        from sqlalchemy import select
        from agentscope_blaiq.persistence.models import AgentCatalogRecord

        async with self._session_factory() as session:
            stmt = select(AgentCatalogRecord).where(AgentCatalogRecord.is_active == True)
            if workspace_id:
                stmt = stmt.where(AgentCatalogRecord.workspace_id == workspace_id)
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [CustomAgentManifest.model_validate_json(r.manifest_json) for r in records]

    async def deregister(self, agent_id: str, *, workspace_id: Optional[str] = None) -> bool:
        from sqlalchemy import update as sa_update
        from agentscope_blaiq.persistence.models import AgentCatalogRecord

        async with self._session_factory() as session:
            stmt = (
                sa_update(AgentCatalogRecord)
                .where(
                    AgentCatalogRecord.name == agent_id,
                    AgentCatalogRecord.workspace_id == workspace_id,
                )
                .values(is_active=False)
            )
            res = await session.execute(stmt)
            await session.commit()
            return res.rowcount > 0


# Backwards-compat aliases
CustomAgentManifestStore = ManifestStore
PersistentCustomAgentManifestStore = ManifestStore


class InMemoryCustomAgentManifestStore:
    """Legacy in-memory stub used by older engine code."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def _agent_id(self, manifest: Any) -> str:
        meta = getattr(manifest, "metadata", None)
        if meta is not None:
            return str(getattr(meta, "agent_id", "") or getattr(meta, "id", ""))
        return str(getattr(manifest, "agent_id", "") or getattr(manifest, "id", ""))

    def upsert(self, manifest: Any) -> Any:
        self._store[self._agent_id(manifest)] = manifest
        return manifest

    def get(self, agent_id: str, **_: Any) -> Any:
        return self._store.get(agent_id)

    def list(self, **_: Any) -> List[Any]:
        return list(self._store.values())

    def delete(self, agent_id: str, **_: Any) -> bool:
        return self._store.pop(agent_id, None) is not None

    async def register(self, manifest: Any, *, tenant_id: str = "default", **_: Any) -> Any:
        return self.upsert(manifest)

    async def list_active(self, *, tenant_id: str = "default") -> List[Any]:
        return self.list()

    async def deactivate(
        self, agent_id: str, *, tenant_id: str = "default", workspace_id: str = "default"
    ) -> bool:
        return self.delete(agent_id)


class ManifestRecord:
    """Thin record wrapper returned by ManifestStore operations."""

    def __init__(self, manifest: Any, *, is_active: bool = True, tenant_id: str = "default") -> None:
        self.manifest = manifest
        self.is_active = is_active
        self.tenant_id = tenant_id

    def __repr__(self) -> str:
        return f"ManifestRecord(agent_id={getattr(self.manifest, 'agent_id', None)}, active={self.is_active})"
