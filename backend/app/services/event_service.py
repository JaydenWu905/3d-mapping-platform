"""In-process SSE event fan-out.

Events live only in memory: on page refresh the frontend re-fetches full job
state via REST and then re-subscribes. No durable event log is needed for
phase 1.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict

EVENT_TYPES = {
    "job.status",
    "stage.status",
    "stage.progress",
    "stage.log",
    "stage.result",
    "snapshot",
}


class EventService:
    def __init__(self, queue_size: int = 400):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._queue_size = queue_size

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[job_id].add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(job_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(job_id, None)

    def subscriber_count(self, job_id: str) -> int:
        return len(self._subscribers.get(job_id, ()))

    async def publish(self, job_id: str, event_type: str, data: dict) -> None:
        if event_type not in EVENT_TYPES:
            return
        event = {"type": event_type, "data": data}
        for q in list(self._subscribers.get(job_id, ())):
            try:
                # Drop-oldest so a slow client cannot wedge the runner.
                while q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ---- convenience emitters -------------------------------------------------
    async def job_status(self, job_id: str, payload: dict) -> None:
        await self.publish(job_id, "job.status", payload)

    async def stage_status(self, job_id: str, payload: dict) -> None:
        await self.publish(job_id, "stage.status", payload)

    async def stage_progress(self, job_id: str, payload: dict) -> None:
        await self.publish(job_id, "stage.progress", payload)

    async def stage_log(self, job_id: str, line: str) -> None:
        await self.publish(job_id, "stage.log", {"line": line})

    async def stage_result(self, job_id: str, payload: dict) -> None:
        await self.publish(job_id, "stage.result", payload)


def sse_frame(event_type: str, data: dict) -> str:
    """Serialize one SSE frame. `event:` carries the typed payload contract."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


_event_service: EventService | None = None


def get_event_service() -> EventService:
    global _event_service
    if _event_service is None:
        _event_service = EventService()
    return _event_service