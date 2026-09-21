"""Server-Sent Events: snapshot + live deltas for one job.

SSE contract:
  1. immediately sends a `snapshot` frame with the full job detail;
  2. then streams typed frames (`job.status`, `stage.status`, `stage.progress`,
     `stage.log`, `stage.result`) until disconnect;
  3. heartbeat comment every ~15 s keeps proxies from closing idle streams.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.event_service import EventService, get_event_service
from app.services.job_service import collect_backend_labels, get_job_service
from app.services.registry_service import get_registry

router = APIRouter(prefix="/jobs/{job_id}/events", tags=["events"])

HEARTBEAT_SECONDS = 15.0


@router.get("")
async def stream_job_events(job_id: str, request: Request):
    jobs = get_job_service()
    events: EventService = get_event_service()
    queue = events.subscribe(job_id)

    async def _stream():
        try:
            # 1. snapshot: full REST state so the scrollback is complete.
            try:
                detail = jobs.job_detail(job_id, get_registry(), collect_backend_labels(get_registry()))
                yield _frame("snapshot", detail)
            except Exception:
                yield _frame("snapshot", {"job_id": job_id, "status": "missing"})

            # 2. live deltas.
            heartbeat = asyncio.create_task(_heartbeat(queue))
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS * 2)
                    except asyncio.TimeoutError:
                        continue
                    yield _frame(event["type"], event["data"])
            finally:
                heartbeat.cancel()
        finally:
            events.unsubscribe(job_id, queue)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _heartbeat(queue: asyncio.Queue) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        # Put a sentinel event; the `event:` name keeps it a no-op for clients.
        try:
            queue.put_nowait({"type": "heartbeat", "data": {"ts": 0}})
        except asyncio.QueueFull:
            pass


def _frame(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"