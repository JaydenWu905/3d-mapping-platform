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
from app.services.pose_spec import (
    cross_check_lookup_keys,
    resolve_workspace,
    validate_dataset_pose,
)


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
    pose: dict[str, Any]
    runtime: dict[str, Any]
    surface: dict[str, Any]
    integrity: dict[str, Any]
    rgbd: dict[str, Any]

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
        if self.kind == "external" and self.rgbd:
            # Imported lazily to keep the registry model independent of the
            # Surface implementation while sharing one authoritative validator.
            from app.services.surface_input_service import validate_rgbd_dataset
            errors.extend(validate_rgbd_dataset(self, strict_hashes=True))
        elif self.kind == "external":
            if not self.source_dir.is_dir():
                errors.append("configured source directory is unavailable")
            # A raw sensor input (the ROS bag) is ALWAYS required for a real
            # dataset.  Only the precomputed Pose file is optional, because a
            # SLAM-producing Pose backend (e.g. GLIM) may estimate the
            # trajectory at runtime.  The two files are therefore handled
            # separately on purpose: 'bag' can never become optional through
            # the 'poses' relaxation.
            if "bag" not in self.files:
                errors.append("dataset registry does not declare a required 'bag' file")
            for key in ("bag", "poses"):
                if key not in self.files:
                    continue
                try:
                    path = self.source_file(key)
                except DatasetError as exc:
                    errors.append(str(exc))
                    continue
                if not path.is_file():
                    errors.append(
                        "required bag file is unavailable" if key == "bag"
                        else "registered poses file is unavailable"
                    )
            if not errors:
                bag = self.source_file("bag")
                if self.integrity.get("bag_size_bytes") != bag.stat().st_size:
                    errors.append("bag size does not match the registered dataset")
                bag_expected = self.integrity.get("bag_sha256")
                if not bag_expected or bag_expected != _sha256(bag):
                    errors.append("bag SHA-256 is missing or does not match the registered dataset")
                if "poses" in self.files:
                    poses = self.source_file("poses")
                    if self.integrity.get("poses_size_bytes") != poses.stat().st_size:
                        errors.append("poses size does not match the registered dataset")
                    expected = self.integrity.get("poses_sha256")
                    if expected and expected != _sha256(poses):
                        errors.append("poses SHA-256 does not match the registered dataset")
            errors.extend(self.validate_pose())
            modalities = set(self.input_manifest.get("modalities") or [])
            if "pose" in modalities and "poses" not in self.files and not self.pose:
                errors.append(
                    "dataset declares the 'pose' modality but registers neither a 'poses' file "
                    "nor a Pose backend that can estimate it"
                )
        return errors

    def validate_pose(self) -> list[str]:
        """Errors that make the declared Pose backend unexecutable."""
        if not self.pose:
            return []
        backend = self.pose.get("backend")
        runtime_block = self.runtime.get(backend) if isinstance(backend, str) else None
        return validate_dataset_pose(
            self.pose,
            runtime_block=runtime_block,
            workspace=resolve_workspace(PROJECT_ROOT),
            declared_files=self.files,
        ) + cross_check_lookup_keys(self.pose, self.surface)


class DatasetService:
    def __init__(self, config_dir: Path | None = None, demo_dir: Path | None = None):
        self.config_dir = config_dir or DATASETS_CONFIG_DIR
        self.demo_dir = demo_dir or DEMO_JOBS_DIR
        # Strict hashing is performed once when a registry entry is first
        # loaded by this service. Launch validation then uses index hashes and
        # per-file existence/size checks instead of re-hashing image corpora.
        self._validation_cache: dict[str, list[str]] = {}

    def validation_errors(self, definition: DatasetDefinition) -> list[str]:
        if definition.id not in self._validation_cache:
            self._validation_cache[definition.id] = definition.validate()
        return list(self._validation_cache[definition.id])

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
                    files={}, pose={}, runtime={}, surface={}, integrity={}, rgbd={},
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
                    files=dict(raw.get("files", {})), pose=dict(raw.get("pose", {})),
                    runtime=dict(raw.get("runtime", {})),
                    surface=dict(raw.get("surface", {})),
                    integrity=dict(raw.get("integrity", {})), rgbd=dict(raw.get("rgbd", {})),
                ))
        return out

    def list_public(self) -> list[dict[str, Any]]:
        result = []
        for definition in self.definitions():
            errors = self.validation_errors(definition)
            manifest = dict(definition.input_manifest)
            manifest["execution"] = definition.execution
            manifest["pose_backend"] = definition.pose.get("backend")
            manifest["surface_backend"] = definition.surface.get("backend")
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
