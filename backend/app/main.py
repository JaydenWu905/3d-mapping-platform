"""FastAPI application entrypoint.

Startup (SEED_DEMO_JOB_ON_START): ensure jobs dirs exist and, if the demo
job is not present yet, seed a *completed* demo job so the first visitor
already sees pose/surface/distance results without touching Run.
Everything under /api; the frontend dev server proxies /api here.
"""
from __future__ import annotations

import asyncio
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import backends, events, jobs, stages
from app.config import CORS_ORIGINS, DEMO_JOBS_DIR, JOBS_DIR, SEED_DEMO_JOB_ON_START, STAGES
from app.services.artifact_service import ArtifactService
from app.services.event_service import EventService, get_event_service
from app.services.job_service import JobService, get_job_service
from app.services.runner_service import RunnerService


def _seed_demo_job(jobs: JobService) -> None:
    """Copy demo_jobs/demo_room as a completed job named 'demo' (idempotent)."""
    src = DEMO_JOBS_DIR / "demo_room"
    if not src.exists():
        return
    dest = jobs.job_dir("demo")
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, dest)
    except Exception:  # pragma: no cover - best effort
        return


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs: JobService = get_job_service()
    events: EventService = get_event_service()
    app.state.jobs = jobs
    app.state.events = events
    app.state.runner = RunnerService(jobs, events)
    app.state.artifacts = ArtifactService(jobs)

    if SEED_DEMO_JOB_ON_START:
        _seed_demo_job(jobs)

    yield
    # Tear down any still-running runner tasks so uvicorn can exit cleanly.
    tasks = list(app.state.runner._stage_tasks.values())
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="3D Mapping Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(backends.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(stages.router, prefix="/api")
app.include_router(events.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}