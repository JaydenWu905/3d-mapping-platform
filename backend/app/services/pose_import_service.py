"""Validated import of a server-registered, precomputed Pose result."""
from __future__ import annotations

import hashlib
import math
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from app.models.manifest import build_manifest
from app.models.progress import atomic_write_json, default_progress
from app.services.dataset_service import DatasetError


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pose_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    previous = -math.inf
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields = raw.split()
            if len(fields) != 8:
                raise ValueError(f"poses line {line_no}: expected 8 columns, got {len(fields)}")
            try:
                values = [float(value) for value in fields]
            except ValueError as exc:
                raise ValueError(f"poses line {line_no}: non-numeric value") from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"poses line {line_no}: non-finite value")
            if values[0] <= previous:
                raise ValueError(f"poses line {line_no}: timestamps are not strictly increasing")
            qnorm = math.sqrt(sum(value * value for value in values[4:8]))
            if not 0.98 <= qnorm <= 1.02:
                raise ValueError(f"poses line {line_no}: quaternion norm {qnorm:.6f} is invalid")
            previous = values[0]
            rows.append(values)
    if not rows:
        raise ValueError("poses file is empty")
    return rows


def import_registered_pose(job_id: str, jobs) -> dict[str, Any]:
    job = jobs.load_job(job_id)
    definition = jobs.datasets.get(job["dataset"])
    if job["backends"]["pose"] != "registered_pose_import":
        raise ValueError("Job did not select registered_pose_import")
    if definition.execution != "real":
        raise ValueError("Registered Pose import is only valid for a real dataset Job")
    errors = definition.validate()
    if errors:
        raise DatasetError("; ".join(errors))
    source = definition.source_file("poses")
    rows = read_pose_rows(source)
    expected = definition.integrity.get("poses_sha256")
    actual = sha256_file(source)
    if not expected or actual != expected:
        raise ValueError("registered Pose SHA-256 is missing or incorrect")

    stage_dir = jobs.stage_dir(job_id, "pose")
    stage_dir.mkdir(parents=True, exist_ok=True)
    progress = default_progress("pose", "registered_pose_import", "running")
    progress.update(phase="validating", message="Validating server-registered precomputed Pose")
    atomic_write_json(stage_dir / "progress.json", progress)
    imported = stage_dir / "poses.txt"
    temporary = stage_dir / f".poses.{uuid.uuid4().hex}.tmp"
    shutil.copyfile(source, temporary)
    if temporary.stat().st_size != source.stat().st_size or sha256_file(temporary) != actual:
        temporary.unlink(missing_ok=True)
        raise ValueError("copied Pose artifact failed size/SHA-256 verification")
    temporary.replace(imported)
    preview = {"frame_count": len(rows), "points": [
        {"x": r[1], "y": r[2], "z": r[3], "qx": r[4], "qy": r[5], "qz": r[6], "qw": r[7]}
        for r in rows
    ]}
    atomic_write_json(stage_dir / "trajectory_preview.json", preview)
    run_id = "pose_import_" + time.strftime("%Y%m%d_%H%M%S")
    manifest = build_manifest(job_id, "pose", "registered_pose_import", 0, {
        "pose_count": len(rows), "timestamp_start": rows[0][0], "timestamp_end": rows[-1][0],
        "trajectory_length_m": round(sum(math.dist(rows[i-1][1:4], rows[i][1:4]) for i in range(1, len(rows))), 3),
    }, [
        {"artifact_id": "trajectory_model", "role": "preview", "path": "trajectory_preview.json", "content_type": "application/json"},
        {"artifact_id": "registered_trajectory", "role": "trajectory", "path": "poses.txt", "content_type": "text/plain", "download": True,
         "size_bytes": imported.stat().st_size, "sha256": actual},
    ], backend_details={
        "mock_backend": False, "result_origin": "validated import of dataset-registered precomputed Pose",
        "run_id": run_id, "dataset_id": definition.id, "timestamp_basis": definition.input_manifest.get("timebase"),
        "pose_semantics": definition.input_manifest.get("pose_semantics"), "translation_unit": definition.input_manifest.get("unit"),
        "quaternion_order": "qx qy qz qw", "source_pose_sha256": actual,
        "note": "This backend validates and imports an existing result; it does not estimate poses.",
    })
    atomic_write_json(stage_dir / "result_manifest.json", manifest)
    progress.update(status="completed", phase="completed", progress=100.0, current=len(rows), total=len(rows), unit="pose",
                    message="Registered precomputed Pose validated and imported")
    atomic_write_json(stage_dir / "progress.json", progress)
    return manifest
