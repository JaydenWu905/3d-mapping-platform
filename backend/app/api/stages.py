"""Stage control + artifact/preview/log endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.services.artifact_service import (
    ArtifactFile,
    ArtifactNotFoundError,
    ArtifactNotDownloadableError,
    ArtifactService,
    PathTraversalError,
)
from app.services.job_service import (
    JobNotFoundError,
    collect_backend_labels,
    get_job_service,
)
from app.services.registry_service import get_registry
from app.services.runner_service import (
    JobBusyError,
    RunnerService,
    StageNotRunningError,
    StartStageError,
)

router = APIRouter(prefix="/jobs/{job_id}", tags=["stages"])


def _runner(request: Request) -> RunnerService:
    return request.app.state.runner


def _artifacts(request: Request) -> ArtifactService:
    return request.app.state.artifacts


# ------------------------------------------------------------ stage control
@router.post("/run-all")
async def run_all(job_id: str, request: Request) -> dict[str, str]:
    try:
        _runner(request).start_run_all(job_id)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "started"}


@router.post("/stages/{stage}/start")
async def start_stage(job_id: str, stage: str, request: Request) -> dict[str, str]:
    try:
        _runner(request).start_stage(job_id, stage)
    except StartStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "started"}


@router.post("/stages/{stage}/cancel")
async def cancel_stage(job_id: str, stage: str, request: Request) -> dict[str, str]:
    try:
        _runner(request).cancel_stage(job_id, stage)
    except StageNotRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "cancelling"}


@router.post("/stages/{stage}/retry")
async def retry_stage(job_id: str, stage: str, request: Request) -> dict[str, str]:
    try:
        _runner(request).retry_stage(job_id, stage)
    except StartStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "started"}


# -------------------------------------------------------------- log readback
@router.get("/stages/{stage}/logs")
async def get_logs(
    job_id: str,
    stage: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(400, ge=1, le=2000),
) -> dict[str, Any]:
    jobs = get_job_service()
    stage_dir = jobs.stage_dir(job_id, stage)
    run_log = stage_dir / "run.log"
    if not run_log.exists():
        return {"offset": 0, "total": 0, "lines": []}
    lines = run_log.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    start = min(offset, total)
    return {"offset": start, "total": total, "lines": lines[start : start + limit]}


# ------------------------------------------------------------ previews / downloads
@router.get("/stages/{stage}/previews/{artifact_id}")
async def get_preview(job_id: str, stage: str, artifact_id: str, request: Request):
    try:
        art = _artifacts(request).resolve_preview(job_id, stage, artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ArtifactNotDownloadableError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PathTraversalError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return _file_response(art, download=False)


@router.get("/stages/{stage}/artifacts/{artifact_id}")
async def get_artifact(job_id: str, stage: str, artifact_id: str, request: Request):
    try:
        art = _artifacts(request).resolve(job_id, stage, artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ArtifactNotDownloadableError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PathTraversalError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not art.downloadable:
        raise HTTPException(status_code=404, detail="Artifact not marked download=true")
    return _file_response(art, download=True)


def _file_response(art: ArtifactFile, *, download: bool) -> FileResponse:
    filename = art.path.name
    headers = {"X-Artifact-Id": art.artifact_id}
    if art.preview_role:
        headers["Cache-Control"] = "no-store, max-age=0"
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return FileResponse(path=str(art.path), media_type=art.content_type or None, headers=headers)
