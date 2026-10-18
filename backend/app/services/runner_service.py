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
from app.services.backend_runtime import has_real_runner, missing_runner_reason
from app.services.job_service import collect_backend_labels
from app.services.mock_runner import MockRunnerAdapter
from app.services.registry_service import get_registry
from app.services.runner_adapter import RunnerAdapter
from app.services.runner_adapter import SubprocessRunnerAdapter
from app.services.surface_input_service import prepare_surface_input


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
        self.mock_adapter: RunnerAdapter = MockRunnerAdapter(job_service, event_service)
        self.subprocess_adapter: RunnerAdapter = SubprocessRunnerAdapter(job_service, event_service)
        self._task_adapters: dict[tuple[str, str], RunnerAdapter] = {}
        self._stage_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._job_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------- lifecycle
    def start_stage(self, job_id: str, stage: str) -> None:
        self._guard_stage_arg(stage)
        if job_id in self._job_tasks and not self._job_tasks[job_id].done():
            raise JobBusyError("A planned chain is active for this job")
        if (job_id, stage) in self._stage_tasks and not self._stage_tasks[(job_id, stage)].done():
            raise JobBusyError(f"Stage '{stage}' is already running")
        if any(self._running_stages(job_id)):
            raise JobBusyError("Another stage of this job is already running")

        job = self._jobs.load_job(job_id)
        registry = get_registry()
        labels = collect_backend_labels(registry)
        if not self._jobs.stage_detail(job, stage, registry, labels).get("can_run"):
            raise StartStageError(_block_reason(job, stage))

        if stage == "surface" and self._needs_surface_input_prep(job):
            try:
                prepare_surface_input(job_id, self._jobs)
            except Exception as exc:
                raise StartStageError(f"Surface input preparation failed: {exc}") from exc

        self._launch(job_id, stage)

    def start_run_all(self, job_id: str) -> None:
        job = self._jobs.load_job(job_id)
        if job.get("requested_stages", STAGES) != STAGES:
            raise StartStageError("Real two-stage jobs use run-planned; Distance is not integrated")
        self._start_chain(job_id, STAGES)

    def start_run_planned(self, job_id: str) -> None:
        job = self._jobs.load_job(job_id)
        if job.get("requested_stages", STAGES) != ["pose", "surface"]:
            raise StartStageError("run-planned requires a two-stage job")
        self._start_chain(job_id, ["pose", "surface"])

    def _start_chain(self, job_id: str, stages: list[str]) -> None:
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
            for stage in stages:
                job = jobs.load_job(job_id)
                status = job["stages"].get(stage, {}).get("status", "waiting")
                if status == "completed":
                    await events.publish(job_id, "stage.log",
                                         {"stage": stage, "line": f"[run-all] {stage} already completed, skipped"})
                    continue
                if stage == "surface" and self._needs_surface_input_prep(job):
                    try:
                        prepared = await asyncio.to_thread(prepare_surface_input, job_id, jobs)
                        warnings = prepared["compatibility"]["warnings"]
                        await events.publish(job_id, "stage.log", {"stage": stage, "line":
                            "[run-all] Surface input prepared" + (f" with {len(warnings)} warning(s)" if warnings else "")})
                    except Exception as exc:
                        stage_dir = jobs.stage_dir(job_id, stage)
                        progress = default_progress(stage, job["backends"][stage], "failed")
                        progress.update(phase="input_preparation_failed", message=f"Surface input preparation failed: {exc}")
                        atomic_write_json(stage_dir / "progress.json", progress)
                        jobs.set_stage_status(job, stage, "failed", starter=True)
                        await events.publish(job_id, "stage.log", {"stage": stage, "line": f"[run-all] {progress['message']}"})
                        break
                registry = get_registry()
                labels = collect_backend_labels(registry)
                if not jobs.stage_detail(job, stage, registry, labels).get("can_run"):
                    reason = jobs.stage_detail(job, stage, registry, labels).get("run_blocked_reason")
                    await events.publish(job_id, "stage.log",
                                         {"stage": stage, "line": f"[run-all] {reason}; chain stopped"})
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
        adapter = self._task_adapters.get(key)
        if adapter is not None:
            adapter.cancel(job_id, stage)
        asyncio.create_task(self._events.publish(
            job_id, "stage.status", {"stage": stage, "status": "cancelling"}
        ))

    def retry_stage(self, job_id: str, stage: str) -> None:
        self._guard_stage_arg(stage)
        if job_id in self._job_tasks and not self._job_tasks[job_id].done():
            raise JobBusyError("A planned chain is active for this job")
        self._guard_retryable(job_id, stage)
        if any(self._running_stages(job_id)):
            raise JobBusyError("Another stage of this job is already running")
        job = self._jobs.load_job(job_id)
        # Any rerun invalidates every downstream artifact from the old inputs.
        for dependent in STAGES[STAGES.index(stage) + 1:]:
            if dependent in job.get("requested_stages", STAGES):
                (self._jobs.stage_dir(job_id, dependent) / "result_manifest.json").unlink(missing_ok=True)
                self._reset_progress(job_id, dependent)
        # Clear stale outputs so viewers do not show an old completed manifest.
        stage_dir = self._jobs.stage_dir(job_id, stage)
        for name in ("result_manifest.json", "progress.json"):
            p = stage_dir / name
            if p.exists():
                p.unlink()
        self._reset_progress(job_id, stage)
        self.start_stage(job_id, stage)
        # Existing event makes all connected pages re-read the invalidated manifests.
        asyncio.create_task(self._events.publish(job_id, "stage.result", {"stage": stage, "status": "waiting"}))

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
        job = self._jobs.load_job(job_id)
        backend = job["backends"][stage]
        adapter = self._adapter_for(job, stage, backend)
        task = asyncio.create_task(adapter.run_stage(job_id, stage, backend))
        self._stage_tasks[(job_id, stage)] = task
        self._task_adapters[(job_id, stage)] = adapter

        def _cleanup(t: asyncio.Task) -> None:
            if self._stage_tasks.get((job_id, stage)) is t:
                self._stage_tasks.pop((job_id, stage), None)
                self._task_adapters.pop((job_id, stage), None)

        task.add_done_callback(_cleanup)

    def _adapter_for(self, job: dict[str, Any], stage: str, backend: str) -> RunnerAdapter:
        definition = self._jobs.datasets.get(job.get("dataset", ""))
        if definition.execution == "mock":
            return self.mock_adapter
        if has_real_runner(stage, backend):
            return self.subprocess_adapter
        raise StartStageError(missing_runner_reason(stage, backend))

    def _needs_surface_input_prep(self, job: dict[str, Any]) -> bool:
        if job.get("backends", {}).get("surface") not in ("mrhash_lidar", "mrhash_rgbd"):
            return False
        # Mirror adapter selection: mock datasets replay fixtures, not real inputs.
        return self._jobs.datasets.get(job.get("dataset", "")).execution != "mock"

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
        if stage not in job.get("requested_stages", STAGES):
            raise StartStageError("Stage is not integrated in this job")
        status = job["stages"].get(stage, {}).get("status")
        if status not in ("failed", "cancelled", "completed"):
            raise StartStageError(f"Stage '{stage}' status is '{status}'; only failed/cancelled/completed stages can be retried")
        definition = self._jobs.datasets.get(job.get("dataset", ""))


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
