"""Server-controlled dataset registry.

Clients select an id only.  External paths come exclusively from versioned
server configuration and are never accepted from an HTTP request.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import DATASETS_CONFIG_DIR, DEMO_JOBS_DIR, PROJECT_ROOT
from app.models.progress import read_json


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetDefinition:
    id: str
    name: str
    description: str
    kind: str
    execution: str
    input_manifest: dict[str, Any]
    source_dir: Path
    files: dict[str, str]
    surface: dict[str, Any]
    integrity: dict[str, Any]

    def source_file(self, key: str) -> Path:
        rel = self.files.get(key, "")
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise DatasetError(f"Dataset '{self.id}' has invalid '{key}' file entry")
        target = (self.source_dir / rel).resolve()
        root = self.source_dir.resolve()
        if root not in target.parents:
            raise DatasetError(f"Dataset '{self.id}' file '{key}' escapes its root")
        return target

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.kind == "external":
            if not self.source_dir.is_dir():
                errors.append("configured source directory is unavailable")
            for key in ("bag", "poses"):
                try:
                    path = self.source_file(key)
                except DatasetError as exc:
                    errors.append(str(exc))
                    continue
                if not path.is_file():
                    errors.append(f"required {key} file is unavailable")
            if not errors:
                bag = self.source_file("bag")
                poses = self.source_file("poses")
                if self.integrity.get("bag_size_bytes") != bag.stat().st_size:
                    errors.append("bag size does not match the registered dataset")
                if self.integrity.get("poses_size_bytes") != poses.stat().st_size:
                    errors.append("poses size does not match the registered dataset")
                expected = self.integrity.get("poses_sha256")
                if expected and expected != _sha256(poses):
                    errors.append("poses SHA-256 does not match the registered dataset")
                bag_expected = self.integrity.get("bag_sha256")
                if not bag_expected or bag_expected != _sha256(bag):
                    errors.append("bag SHA-256 is missing or does not match the registered dataset")
        return errors


class DatasetService:
    def __init__(self, config_dir: Path | None = None, demo_dir: Path | None = None):
        self.config_dir = config_dir or DATASETS_CONFIG_DIR
        self.demo_dir = demo_dir or DEMO_JOBS_DIR

    def get(self, dataset_id: str) -> DatasetDefinition:
        defs = {d.id: d for d in self.definitions()}
        if dataset_id not in defs:
            raise DatasetError(f"Unknown dataset: {dataset_id}")
        return defs[dataset_id]

    def definitions(self) -> list[DatasetDefinition]:
        out: list[DatasetDefinition] = []
        if self.demo_dir.exists():
            for folder in sorted(self.demo_dir.iterdir()):
                if not folder.is_dir():
                    continue
                manifest = read_json(folder / "input" / "input_manifest.json", {}) or {}
                out.append(DatasetDefinition(
                    id=folder.name, name=manifest.get("name", folder.name),
                    description=manifest.get("description", ""), kind="demo",
                    execution="mock", input_manifest=manifest, source_dir=folder,
                    files={}, surface={}, integrity={},
                ))
        if self.config_dir.exists():
            for path in sorted(self.config_dir.glob("*.json")):
                raw = json.loads(path.read_text(encoding="utf-8"))
                root_value = raw.get("root", "")
                root = Path(root_value)
                if root.is_absolute():
                    raise DatasetError(f"Dataset '{raw.get('id', path.stem)}' root must be relative")
                # Dataset roots are relative to the workspace containing this platform.
                workspace_root = PROJECT_ROOT.parent.resolve()
                source_dir = (workspace_root / root).resolve()
                if source_dir != workspace_root and workspace_root not in source_dir.parents:
                    raise DatasetError(
                        f"Dataset '{raw.get('id', path.stem)}' root escapes the workspace"
                    )
                out.append(DatasetDefinition(
                    id=raw["id"], name=raw.get("name", raw["id"]),
                    description=raw.get("description", ""),
                    kind=raw.get("kind", "external"), execution=raw.get("execution", "real"),
                    input_manifest=dict(raw.get("input_manifest", {})), source_dir=source_dir,
                    files=dict(raw.get("files", {})), surface=dict(raw.get("surface", {})),
                    integrity=dict(raw.get("integrity", {})),
                ))
        return out

    def list_public(self) -> list[dict[str, Any]]:
        result = []
        for definition in self.definitions():
            errors = definition.validate()
            manifest = dict(definition.input_manifest)
            manifest["execution"] = definition.execution
            manifest["available"] = not errors
            if errors:
                manifest["availability_message"] = "; ".join(errors)
            result.append({
                "id": definition.id, "name": definition.name,
                "description": definition.description, "input_manifest": manifest,
            })
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_dataset_service: DatasetService | None = None


def get_dataset_service() -> DatasetService:
    global _dataset_service
    if _dataset_service is None:
        _dataset_service = DatasetService()
    return _dataset_service
