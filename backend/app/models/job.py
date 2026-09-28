"""Job persistence model (plain dicts on disk) and Pydantic API schemas."""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.config import STAGE_LABELS, STAGES

StageStatusValue = Literal["waiting", "running", "completed", "failed", "cancelled"]


def new_job_id() -> str:
    return f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def ensure_stage_state(stage: str, backend_id: str) -> dict[str, Any]:
    """Fresh persisted state for one stage of a job (written into job.json)."""
    return {
        "stage": stage,
        "backend": backend_id,
        "status": "waiting",
        "started_at": None,
        "finished_at": None,
    }


def new_job(
    dataset: str,
    backends: dict[str, str],
    fail_stage: Optional[str] = None,
    job_id: Optional[str] = None,
    preview_job: bool = False,
) -> dict[str, Any]:
    """Create the in-memory / on-disk structure of a job."""
    job_id = job_id or new_job_id()
    return {
        "job_id": job_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "created",
        "dataset": dataset,
        "backends": dict(backends),
        "fail_stage": fail_stage if fail_stage in STAGES else None,
        "preview_job": preview_job,
        "stages": {
            stage: ensure_stage_state(stage, backends[stage]) for stage, label in [(s, STAGE_LABELS[s]) for s in STAGES]
        },
    }


def derive_job_status(job: dict[str, Any]) -> str:
    """Recompute the overall job status from its stage statuses (server of truth = disk)."""
    statuses = [st["status"] for st in job["stages"].values()]
    if any(s == "running" for s in statuses):
        return "running"
    if any(s == "failed" for s in statuses):
        return "failed"
    if any(s == "cancelled" for s in statuses):
        return "cancelled"
    if all(s == "completed" for s in statuses) and statuses:
        return "completed"
    return "created"


def stage_dependency_satisfied(job: dict[str, Any], stage: str) -> bool:
    """Dependency control:
    Pose may run any time. Surface needs Pose completed.
    Distance needs Surface completed (which itself implies Pose completed).
    """
    if stage == "pose":
        return True
    if stage == "surface":
        return job["stages"]["pose"]["status"] == "completed"
    if stage == "distance":
        return job["stages"]["surface"]["status"] == "completed"
    return False


class BackendDef(BaseModel):
    id: str
    display_name: str
    status: Literal["ready", "experimental", "disabled"]
    input_modalities: list[str] = Field(default_factory=list)
    preview_types: list[str] = Field(default_factory=list)
    description: str = ""
    home_url: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)
    unavailable_reason: str = ""


class BackendStageResponse(BaseModel):
    stage: str
    stage_label: str
    backends: list[BackendDef]


class CreateJobRequest(BaseModel):
    dataset: str
    backends: dict[str, str]
    fail_stage: Optional[str] = None


class DatasetResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    input_manifest: dict[str, Any] = Field(default_factory=dict)


class StageDetail(BaseModel):
    stage: str
    backend: str
    backend_status: Optional[str] = None
    status: StageStatusValue
    phase: str = ""
    progress: float = 0.0
    current: float = 0.0
    total: float = 0.0
    unit: str = ""
    message: str = ""
    elapsed_sec: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    manifest: Optional[dict[str, Any]] = None
    can_run: bool = False
    run_blocked_reason: str = ""


class JobSummary(BaseModel):
    job_id: str
    created_at: str
    status: str
    dataset: str
    backends: dict[str, str]
    preview_job: bool = False


class JobDetail(JobSummary):
    stages: dict[str, StageDetail]
