from __future__ import annotations

from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
import hashlib
import sys


@lru_cache(maxsize=None)
def load_legacy_agent_module(current_file: str, legacy_module_name: str) -> ModuleType:
    """Load the legacy flat agent module that lives beside the package dir.

    The normalized package layout keeps a compatibility bridge so each package
    can reuse the mature implementation from the legacy flat module while the
    migration to package-native code completes.
    """

    agent_file = Path(current_file).resolve()
    legacy_path = agent_file.parent.parent / f"{legacy_module_name}.py"
    if not legacy_path.is_file():
        raise FileNotFoundError(f"Legacy agent module not found: {legacy_path}")

    cache_key = hashlib.sha1(str(legacy_path).encode("utf-8")).hexdigest()[:12]
    module_name = f"agentscope_blaiq._legacy_agents.{legacy_module_name}_{cache_key}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    spec = spec_from_file_location(module_name, legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load legacy agent module: {legacy_path}")

    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
