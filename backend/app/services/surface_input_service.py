"""Versioned Pose-to-Surface contract preparation and validation."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.models.progress import atomic_write_json, read_json
from app.services.pose_import_service import read_pose_rows, sha256_file


class SurfaceInputError(ValueError):
    pass


def _artifact(manifest: dict[str, Any], artifact_id: str, role: str) -> dict[str, Any]:
    matches = [a for a in manifest.get("artifacts", []) if a.get("artifact_id") == artifact_id and a.get("role") == role]
    if len(matches) != 1:
        raise SurfaceInputError(f"required Pose artifact {artifact_id!r} with role {role!r} is missing or ambiguous")
    return matches[0]


def _resolve(stage_dir: Path, artifact: dict[str, Any]) -> Path:
    rel = artifact.get("path")
    if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise SurfaceInputError("Pose artifact path is not a safe relative path")
    root = stage_dir.resolve()
    target = (stage_dir / rel).resolve()
    if root not in target.parents or not target.is_file():
        raise SurfaceInputError("Pose artifact escapes its stage or is missing")
    size, digest = target.stat().st_size, sha256_file(target)
    if artifact.get("size_bytes") != size or artifact.get("sha256") != digest:
        raise SurfaceInputError("Pose artifact size or SHA-256 does not match its result manifest")
    return target


def prepare_mrhash_lidar_input(job_id: str, jobs) -> dict[str, Any]:
    job = jobs.load_job(job_id)
    definition = jobs.datasets.get(job["dataset"])
    pose_dir = jobs.stage_dir(job_id, "pose")
    pose = read_json(pose_dir / "result_manifest.json", None)
    if not isinstance(pose, dict) or pose.get("status") != "completed":
        raise SurfaceInputError("completed Pose result_manifest.json is required")
    details = pose.get("backend_details", {})
    missing = [key for key in ("timestamp_basis", "pose_semantics", "translation_unit", "quaternion_order") if not details.get(key)]
    if missing:
        raise SurfaceInputError("Pose manifest missing required semantics: " + ", ".join(missing))
    trajectory_artifact = _artifact(pose, "registered_trajectory", "trajectory")
    trajectory = _resolve(pose_dir, trajectory_artifact)
    rows = read_pose_rows(trajectory)
    bag = definition.source_file("bag").resolve()
    root = definition.source_dir.resolve()
    if root not in bag.parents or not bag.is_file():
        raise SurfaceInputError("registered sensor artifact escapes dataset root or is missing")
    bag_sha = definition.integrity.get("bag_sha256")
    if not bag_sha or definition.integrity.get("bag_size_bytes") != bag.stat().st_size or sha256_file(bag) != bag_sha:
        raise SurfaceInputError("registered sensor artifact size/SHA-256 validation failed")
    declared = definition.input_manifest.get("bag_message_count")
    pose_count = len(rows)
    warnings: list[dict[str, str]] = []
    missing_count = max(int(declared) - pose_count, 0) if declared is not None else None
    if declared is not None and int(declared) != pose_count:
        warnings.append({"code": "FRAME_COUNT_MISMATCH", "message": f"{pose_count} poses for {declared} bag messages; {missing_count} messages are unmatched/skipped"})
    manifest = {
        "schema_version": "1.0", "job_id": job_id, "dataset_id": definition.id,
        "surface_backend": "mrhash_lidar", "modalities": ["lidar", "pose"],
        "sensor_artifact": {"artifact_id": "registered_lidar_bag", "role": "sensor_data", "reference": str(bag.relative_to(root)),
                            "registry_root": str(root), "size_bytes": bag.stat().st_size, "sha256": bag_sha},
        "trajectory_artifact": {"artifact_id": trajectory_artifact["artifact_id"], "role": trajectory_artifact["role"],
                                "reference": str(trajectory.relative_to(jobs.job_dir(job_id).resolve())),
                                "size_bytes": trajectory.stat().st_size, "sha256": trajectory_artifact["sha256"]},
        "timestamp_basis": details["timestamp_basis"], "pose_semantics": details["pose_semantics"],
        "translation_unit": details["translation_unit"], "quaternion_order": details["quaternion_order"],
        "lidar_topic": definition.surface.get("topic"),
        "matching": {"bag_message_count": declared, "pose_count": pose_count, "matched_count": pose_count,
                     "missing_or_skipped_count": missing_count},
        "source_pose": {"backend": pose.get("backend"), "run_id": details.get("run_id"), "origin": details.get("result_origin")},
        "camera": None, "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "compatibility": {"status": "compatible_with_warnings" if warnings else "compatible", "errors": [], "warnings": warnings},
    }
    out = jobs.stage_dir(job_id, "surface") / "input" / "surface_input_manifest.json"
    existing = read_json(out, None)
    if isinstance(existing, dict):
        comparable_existing = {key: value for key, value in existing.items() if key != "prepared_at"}
        comparable_new = {key: value for key, value in manifest.items() if key != "prepared_at"}
        if comparable_existing == comparable_new:
            manifest["prepared_at"] = existing.get("prepared_at", manifest["prepared_at"])
    atomic_write_json(out, manifest)
    return manifest


def validate_surface_input(job_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    manifest_path = job_dir / "stage2_surface" / "input" / "surface_input_manifest.json"
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise SurfaceInputError("valid surface_input_manifest.json schema 1.0 is required")
    job_root = job_dir.resolve()
    trajectory = (job_root / manifest["trajectory_artifact"]["reference"]).resolve()
    if job_root not in trajectory.parents or not trajectory.is_file():
        raise SurfaceInputError("trajectory reference escapes Job or is missing")
    sensor = manifest["sensor_artifact"]
    registry_root = Path(sensor["registry_root"]).resolve()
    bag = (registry_root / sensor["reference"]).resolve()
    if registry_root not in bag.parents or not bag.is_file():
        raise SurfaceInputError("sensor reference escapes registered root or is missing")
    for path, artifact in ((trajectory, manifest["trajectory_artifact"]), (bag, sensor)):
        if path.stat().st_size != artifact["size_bytes"] or sha256_file(path) != artifact["sha256"]:
            raise SurfaceInputError(f"{artifact['artifact_id']} failed launch-time integrity validation")
    return manifest, bag, trajectory
