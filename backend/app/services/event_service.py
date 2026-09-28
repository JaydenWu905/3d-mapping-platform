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
    _RESERVED_CONTROL_SLOTS = 8

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
            self._enqueue(q, event)

    def _enqueue(self, q: asyncio.Queue, event: dict) -> None:
        """Bounded, priority-aware enqueue for slow SSE consumers.

        Log traffic may be discarded. Progress is coalesced per stage. Control
        and terminal frames use reserved capacity and can evict only disposable
        traffic, so a tqdm burst cannot hide completion.
        """
        event_type = event["type"]
        if event_type == "stage.log" and q.qsize() >= max(
            1, q.maxsize - self._RESERVED_CONTROL_SLOTS
        ):
            return

        buffered: list[dict] = []
        while True:
            try:
                buffered.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break

        if event_type == "stage.progress":
            stage = event["data"].get("stage")
            buffered = [
                old for old in buffered
                if not (old.get("type") == "stage.progress"
                        and old.get("data", {}).get("stage") == stage)
            ]
        elif event_type == "stage.status":
            stage = event["data"].get("stage")
            buffered = [
                old for old in buffered
                if not (old.get("type") == "stage.status"
                        and old.get("data", {}).get("stage") == stage
                        and not self._is_terminal(old))
            ]
        elif event_type == "job.status":
            buffered = [
                old for old in buffered
                if old.get("type") != "job.status" or self._is_terminal(old)
            ]

        if len(buffered) >= q.maxsize:
            disposable = next(
                (i for i, old in enumerate(buffered)
                 if old.get("type") in ("stage.log", "heartbeat")
                 or not self._is_terminal(old)),
                None,
            )
            if disposable is None and event_type == "stage.progress":
                disposable = next(
                    (i for i, old in enumerate(buffered)
                     if old.get("type") == "stage.progress"), None
                )
            if disposable is None:
                # A queue containing only control/terminal events is already
                # more useful than another log/progress frame.
                if event_type in ("stage.log", "stage.progress", "heartbeat"):
                    for old in buffered:
                        q.put_nowait(old)
                    return
                disposable = 0
            buffered.pop(disposable)

        buffered.append(event)
        for item in buffered[-q.maxsize:]:
            q.put_nowait(item)

    @staticmethod
    def _is_terminal(event: dict) -> bool:
        return (
            event.get("type") == "stage.result"
            or event.get("data", {}).get("status")
            in ("completed", "failed", "cancelled")
        )

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
