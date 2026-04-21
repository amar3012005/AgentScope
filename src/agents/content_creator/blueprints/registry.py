"""Reusable blueprint registry for artifact rendering."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from agents.content_creator.artifact_types.registry import ArtifactKind

BLUEPRINTS_DIR = Path(__file__).parent / "specs"


class BlueprintRegistry:
    """Loads and resolves blueprint specs per artifact kind."""

    def __init__(self, specs_dir: str | Path | None = None) -> None:
        self._specs_dir = Path(specs_dir) if specs_dir else BLUEPRINTS_DIR
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        self._cache.clear()
        if not self._specs_dir.exists():
            return
        for path in sorted(self._specs_dir.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                blueprint_id = str(data.get("id") or path.stem).strip()
                if blueprint_id:
                    self._cache[blueprint_id] = data
            except Exception:
                continue

    def get(self, blueprint_id: str) -> Dict[str, Any]:
        if blueprint_id not in self._cache:
            raise KeyError(f"Blueprint '{blueprint_id}' not found")
        return self._cache[blueprint_id]

    def resolve(
        self,
        artifact_kind: ArtifactKind | str,
        preferred_blueprint_id: str | None = None,
    ) -> Dict[str, Any]:
        if preferred_blueprint_id and preferred_blueprint_id in self._cache:
            return self._cache[preferred_blueprint_id]
        kind_value = str(getattr(artifact_kind, "value", artifact_kind))
        candidates = [bp for bp in self._cache.values() if str(bp.get("artifact_kind", "")) == kind_value]
        if not candidates:
            return {
                "id": "default-minimal",
                "artifact_kind": kind_value,
                "layout": {},
                "styles": {},
                "page_blueprints": [],
            }
        for candidate in candidates:
            if bool(candidate.get("default")):
                return candidate
        return candidates[0]


_REGISTRY: BlueprintRegistry | None = None


def get_blueprint_registry() -> BlueprintRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = BlueprintRegistry()
    return _REGISTRY

