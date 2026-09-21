"""Job lifecycle REST API: create, list, detail, delete."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.models.job import CreateJobRequest
from app.services.job_service import (
    JobNotFoundError,
    JobService,
    collect_backend_labels,
    get_job_service,
)
from app.services.registry_service import get_registry

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201)
async def create_job(req: CreateJobRequest, request: Request) -> dict[str, Any]:
    jobs: JobService = request.app.state.jobs
    try:
        job = await jobs.create_job(
            dataset=req.dataset,
            backends=req.backends,
            fail_stage=req.fail_stage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return jobs.job_detail(job["job_id"], get_registry(), collect_backend_labels(get_registry()))


@router.get("")
async def list_jobs(request: Request) -> list[dict[str, Any]]:
    jobs: JobService = request.app.state.jobs
    registry = get_registry()
    return [
        {k: j.get(k) for k in ("job_id", "created_at", "status", "dataset", "preview_job")}
        | {"stages": {s: jobs.stage_detail(j, s, registry, collect_backend_labels(registry))["status"] for s in j.get("stages", {})}}
        for j in jobs.list_jobs()
    ]


@router.get("/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    jobs: JobService = request.app.state.jobs
    try:
        return jobs.job_detail(job_id, get_registry(), collect_backend_labels(get_registry()))
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, request: Request) -> None:
    jobs: JobService = request.app.state.jobs
    try:
        jobs.delete_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))