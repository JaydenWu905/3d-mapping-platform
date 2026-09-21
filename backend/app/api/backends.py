"""Backend registry + dataset listing API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import STAGES
from app.services.job_service import get_job_service
from app.services.registry_service import BackendNotFoundError, get_registry

router = APIRouter(tags=["meta"])


@router.get("/backends")
async def list_backends(request: Request) -> dict[str, object]:
    """All backends grouped by stage (the frontend's only source of truth)."""
    registry = get_registry()
    return {
        "stages": STAGES,
        "groups": {stage: registry.list_stage(stage) for stage in STAGES},
    }


@router.get("/backends/{stage}")
async def list_stage_backends(stage: str, request: Request) -> list[object]:
    registry = get_registry()
    try:
        return registry.list_stage(stage)
    except BackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/datasets")
async def list_datasets(request: Request) -> list[dict]:
    return get_job_service().list_datasets()