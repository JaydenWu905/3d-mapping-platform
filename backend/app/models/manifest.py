"""result_manifest.json model helpers.

The public schema is kept stable across backends. Algorithm-specific data may
only live under `backend_details`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.progress import read_json


def load_manifest(stage_dir: Path) -> dict[str, Any] | None:
    manifest = read_json(stage_dir / "result_manifest.json", None)
    return manifest if isinstance(manifest, dict) else None


def build_manifest(
    job_id: str,
    stage: str,
    backend: str,
    runtime_sec: float,
    metrics: dict[str, Any],
    artifacts: list[dict[str, Any]],
    backend_details: dict[str, Any] | None = None,
    status: str = "completed",
    frame_id: str = "world",
    unit: str = "meter",
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "stage": stage,
        "backend": backend,
        "status": status,
        "frame_id": frame_id,
        "unit": unit,
        "runtime_sec": round(runtime_sec, 2),
        "artifacts": artifacts,
        "metrics": metrics,
        "backend_details": backend_details or {},
    }