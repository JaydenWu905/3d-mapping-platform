"""Backend Registry.

All algorithm listings live in backend/config/backends/*.json. The frontend
never hardcodes a backend id; everything it needs comes from these files.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import BACKENDS_CONFIG_DIR, STAGES, STAGE_LABELS
from app.models.job import BackendDef


class RegistryError(Exception):
    pass


class BackendNotFoundError(RegistryError):
    pass


class BackendDisabledError(RegistryError):
    pass


class BackendRegistry:
    """Loads and caches the three stage registry files."""

    def __init__(self, config_dir: Path | None = None):
        self._config_dir = config_dir or BACKENDS_CONFIG_DIR
        self._stages: dict[str, dict[str, BackendDef]] = {}
        self._by_id: dict[tuple[str, str], BackendDef] = {}
        self.reload()

    def reload(self) -> None:
        self._stages = {}
        self._by_id = {}
        for stage in STAGES:
            path = self._config_dir / f"{stage}.json"
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            defs = [BackendDef(**d) for d in raw.get("backends", [])]
            self._stages[stage] = {d.id: d for d in defs}
            for d in defs:
                self._by_id[(stage, d.id)] = d

    def list_stage(self, stage: str) -> list[BackendDef]:
        return list(self._stages.get(stage, {}).values())

    def all(self) -> dict[str, list[BackendDef]]:
        return {stage: self.list_stage(stage) for stage in STAGES}

    def find(self, stage: str, backend_id: str) -> BackendDef | None:
        return self._by_id.get((stage, backend_id))

    def ensure_runnable(self, stage: str, backend_id: str) -> BackendDef:
        """Raise BackendNotFoundError / BackendDisabledError if not runnable."""
        def_ = self.find(stage, backend_id)
        if def_ is None:
            raise BackendNotFoundError(f"Backend '{backend_id}' not found for stage '{stage}'")
        if def_.status == "disabled":
            raise BackendDisabledError(
                f"Backend '{def_.display_name}' is disabled and cannot be run"
            )
        return def_

    def stage_label(self, stage: str) -> str:
        return STAGE_LABELS.get(stage, stage)


_registry: BackendRegistry | None = None


def get_registry() -> BackendRegistry:
    global _registry
    if _registry is None:
        _registry = BackendRegistry()
    return _registry