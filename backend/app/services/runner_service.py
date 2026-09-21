"""Orchestrator: kicks off MockRunnerAdapter (phase 1) as background tasks.

Concurrency contract:
  * only ONE stage task may run per job at any time (enforced here);
  * run-all awaits each stage before starting the next;
  * a failed/cancelled stage stops the chain.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import STAGES
from app.models.progress import default_progress, atomic_write_json
from app.services.job_service import collect_backend_labels
from app.services.mock_runner import MockRunnerAdapter
from app.services.registry_service import get_registry
from app.services.runner_adapter import RunnerAdapter


class JobBusyError(Exception):
    pass


class StageNotRunningError(Exception):
    pass


class StartStageError(Exception):
    pass


class RunnerService:
    def __init__(self, job_service, event_service):
        self._jobs = job_service
        self._events = event_service
        # Phase 1: the mock is the only adapter. Phase 2 swaps this one line.
        self.adapter: RunnerAdapter = MockRunnerAdapter(job_service, event_service)
        self._stage_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._job_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------- lifecycle
    def start_stage(self, job_id: str, stage: str) -> None:
        self._guard_stage_arg(stage)
        if (job_id, stage) in self._stage_tasks and not self._stage_tasks[(job_id, stage)].done():
            raise JobBusyError(f"Stage '{stage}' is already running")
        if any(self._running_stages(job_id)):
            raise JobBusyError("Another stage of this job is already running")

        job = self._jobs.load_job(job_id)
        registry = get_registry()
        labels = collect_backend_labels(registry)
        if not self._jobs.stage_detail(job, stage, registry, labels).get("can_run"):
            raise StartStageError(_block_reason(job, stage))

        self._launch(job_id, stage)

    def start_run_all(self, job_id: str) -> None:
        if job_id in self._job_tasks and not self._job_tasks[job_id].done():
            raise JobBusyError("Run All is already in progress")
        running = self._running_stages(job_id)
        if running:
            raise JobBusyError(f"Stage '{running[0]}' is still running; stop it before Run All")

        job = self._jobs.load_job(job_id)
        jobs = self._jobs
        events = self._events

        async def _run_all():
            job = jobs.load_job(job_id)
            await events.job_status(job_id, {"status": "running"})
            for stage in STAGES:
                job = jobs.load_job(job_id)
                status = job["stages"].get(stage, {}).get("status", "waiting")
                if status == "completed":
                    await events.publish(job_id, "stage.log",
                                         {"stage": stage, "line": f"[run-all] {stage} already completed, skipped"})
                    continue
                registry = get_registry()
                labels = collect_backend_labels(registry)
                if not jobs.stage_detail(job, stage, registry, labels).get("can_run"):
                    await events.publish(job_id, "stage.log",
                                         {"stage": stage, "line": f"[run-all] dependency not satisfied for {stage}, chain stopped"})
                    break
                self._launch(job_id, stage)
                result = await self._stage_tasks[(job_id, stage)]
                job = jobs.load_job(job_id)
                await events.job_status(job_id, {"status": job["status"]})
                if result.status != "completed":
                    await events.publish(job_id, "stage.log",
                                         {"stage": stage, "line": f"[run-all] {stage} {result.status}, stopping chain"})
                    break
            else:
                job = jobs.load_job(job_id)
                await events.publish(job_id, "stage.result", {"stage": "all", "status": job["status"]})

        task = asyncio.create_task(_run_all())
        self._job_tasks[job_id] = task
        task.add_done_callback(lambda t: self._job_tasks.pop(job_id, None) if self._job_tasks.get(job_id) is t else None)

    def cancel_stage(self, job_id: str, stage: str) -> None:
        self._guard_stage_arg(stage)
        key = (job_id, stage)
        task = self._stage_tasks.get(key)
        if task is None or task.done():
            raise StageNotRunningError(f"Stage '{stage}' is not running")
        self.adapter.cancel(job_id, stage)
        self._events.publish(job_id, "stage.status", {"stage": stage, "status": "cancelling"})

    def retry_stage(self, job_id: str, stage: str) -> None:
        self._guard_stage_arg(stage)
        self._guard_retryable(job_id, stage)
        # Clear stale outputs so viewers do not show an old completed manifest.
        stage_dir = self._jobs.stage_dir(job_id, stage)
        for name in ("result_manifest.json", "progress.json"):
            p = stage_dir / name
            if p.exists():
                p.unlink()
        self._reset_progress(job_id, stage)
        self.start_stage(job_id, stage)

    def _reset_progress(self, job_id: str, stage: str) -> None:
        job = self._jobs.load_job(job_id)
        backend = job["backends"].get(stage, "")
        prog = default_progress(stage, backend)
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
        # mark waiting in job.json
        st = self._jobs.stage_mark(job, stage)
        st["status"] = "waiting"
        st["started_at"] = None
        st["finished_at"] = None
        self._jobs.save_job(job)

    # --------------------------------------------------------------- helpers
    def _launch(self, job_id: str, stage: str) -> None:
        backend = self._jobs.load_job(job_id)["backends"][stage]
        task = asyncio.create_task(self.adapter.run_stage(job_id, stage, backend))
        self._stage_tasks[(job_id, stage)] = task

        def _cleanup(t: asyncio.Task) -> None:
            if self._stage_tasks.get((job_id, stage)) is t:
                self._stage_tasks.pop((job_id, stage), None)

        task.add_done_callback(_cleanup)

    def _running_stages(self, job_id: str) -> list[str]:
        out = []
        for (jid, stage), task in self._stage_tasks.items():
            if jid == job_id and not task.done():
                out.append(stage)
        return out

    @staticmethod
    def _guard_stage_arg(stage: str) -> None:
        if stage not in STAGES:
            raise StartStageError(f"Unknown stage: {stage}")

    def _guard_retryable(self, job_id: str, stage: str) -> None:
        job = self._jobs.load_job(job_id)
        status = job["stages"].get(stage, {}).get("status")
        if status not in ("failed", "cancelled", "completed"):
            raise StartStageError(f"Stage '{stage}' status is '{status}'; only failed/cancelled/completed stages can be retried")


def _block_reason(job: dict[str, Any], stage: str) -> str:
    status = job["stages"].get(stage, {}).get("status", "waiting")
    if status == "running":
        return "Stage already running"
    if status == "completed":
        return "Stage already completed"
    prev = {"pose": "", "surface": "pose", "distance": "surface"}[stage]
    if prev and job["stages"].get(prev, {}).get("status") != "completed":
        return f"{'Pose' if prev == 'pose' else 'Surface'} must be completed first"
    return "Stage cannot be started"