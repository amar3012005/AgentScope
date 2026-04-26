from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscope_blaiq.contracts.agent_catalog import AgentKind, LiveAgentProfile


logger = logging.getLogger(__name__)


class AgentProfileDocumentStore:
    """Small JSON-document store for planner-facing agent profiles.

    The profile document is canonical for dynamic profiles. Runtime code still
    owns execution adapters, so this store only persists routing metadata and
    raw source cards.
    """

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.path = self.root_dir / "profiles.json"

    def ensure(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"schema_version": "v1", "profiles": {}, "updated_at": _now_iso()})

    def load_profiles(self) -> list[LiveAgentProfile]:
        self.ensure()
        payload = self._read()
        profiles: list[LiveAgentProfile] = []
        for profile_id, raw_profile in (payload.get("profiles") or {}).items():
            try:
                profile = LiveAgentProfile.model_validate(raw_profile)
            except Exception as exc:
                logger.warning("Skipping invalid agent profile document %s: %s", profile_id, exc)
                continue
            profiles.append(profile)
        return profiles

    def load_remote_profiles(self) -> list[LiveAgentProfile]:
        return [profile for profile in self.load_profiles() if profile.agent_kind == AgentKind.remote]

    def save_profile(self, profile: LiveAgentProfile) -> None:
        self.ensure()
        payload = self._read()
        profiles = payload.setdefault("profiles", {})
        profiles[profile.profile_id] = profile.model_dump(mode="json")
        payload["updated_at"] = _now_iso()
        self._write(payload)

    def delete_profile(self, profile_id: str) -> bool:
        self.ensure()
        payload = self._read()
        profiles: dict[str, Any] = payload.setdefault("profiles", {})
        if profile_id not in profiles:
            return False
        del profiles[profile_id]
        payload["updated_at"] = _now_iso()
        self._write(payload)
        return True

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": "v1", "profiles": {}, "updated_at": _now_iso()}
        except json.JSONDecodeError as exc:
            logger.warning("Agent profile store is unreadable at %s: %s", self.path, exc)
            return {"schema_version": "v1", "profiles": {}, "updated_at": _now_iso()}

    def _write(self, payload: dict[str, Any]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
