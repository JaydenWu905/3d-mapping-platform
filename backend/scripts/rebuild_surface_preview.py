#!/usr/bin/env python3
"""Safely rebuild one completed Job's Surface GLB without rerunning mapping."""
from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.models.progress import read_json  # noqa: E402
from app.services.artifact_service import ArtifactService  # noqa: E402
from app.services.job_service import JobService  # noqa: E402
from app.services.mesh_preview import (  # noqa: E402
    DEFAULT_PREVIEW_FACES,
    atomic_replace_preview,
    build_preview_glb,
)


def rebuild(job_id: str, target_faces: int) -> dict:
    jobs = JobService()
    job = jobs.load_job(job_id)
    stage = job.get("stages", {}).get("surface", {})
    stage_dir = jobs.stage_dir(job_id, "surface")
    manifest_path = stage_dir / "result_manifest.json"
    manifest = read_json(manifest_path, None)
    if stage.get("status") != "completed":
        raise ValueError("Surface stage must be completed")
    if not isinstance(manifest, dict) or manifest.get("status") != "completed":
        raise ValueError("completed Surface manifest is missing")
    if manifest.get("backend_details", {}).get("mode") != "full":
        raise ValueError("refusing to rewrite a preview not sourced from a full run")

    artifacts = manifest.get("artifacts", [])
    preview = next(
        (item for item in artifacts if item.get("artifact_id") == "surface_model"), None
    )
    if not isinstance(preview, dict) or preview.get("role") != "preview":
        raise ValueError("manifest has no surface_model preview")
    mesh = ArtifactService(jobs).resolve(job_id, "surface", "surface_mesh").path
    preview_path = (stage_dir / str(preview.get("path", ""))).resolve()
    if stage_dir.resolve() not in preview_path.parents:
        raise ValueError("surface_model path escapes the stage directory")

    candidate = preview_path.with_name(
        f".{preview_path.stem}.candidate-{os.getpid()}{preview_path.suffix}"
    )
    updated = copy.deepcopy(manifest)
    try:
        metrics = build_preview_glb(mesh, candidate, target_faces)
        updated.setdefault("metrics", {}).update(metrics)
        preview["note"] = (
            "Topology-preserving QEM preview from the complete native mesh; "
            "exact duplicate vertices are welded before simplification."
        )
        updated_preview = next(
            item for item in updated["artifacts"]
            if item.get("artifact_id") == "surface_model"
        )
        updated_preview["note"] = preview["note"]
        updated.setdefault("backend_details", {})["preview_note"] = preview["note"]
        atomic_replace_preview(candidate, preview_path, manifest_path, updated)
        return metrics
    finally:
        candidate.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--target-faces", type=int, default=DEFAULT_PREVIEW_FACES)
    args = parser.parse_args()
    metrics = rebuild(args.job_id, args.target_faces)
    print({"job_id": args.job_id, **metrics})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
