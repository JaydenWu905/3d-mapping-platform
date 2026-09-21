"""MockRunnerAdapter — phase 1 fake algorithm runner.

Simulates the Waiting → Running → Completed (or Failed / Cancelled) lifecycle:
  * continuously rewrites the stage progress.json (atomic on Windows);
  * appends lines to run.log;
  * emits SSE events;
  * on success copies the pre-prepared demo previews from demo_jobs/<dataset>
    into the stage directory and writes a valid result_manifest.json.

All metrics embedded here are clearly demo numbers, never real algorithm output.
"""
from __future__ import annotations

import asyncio
import random
import shutil
import time
from pathlib import Path
from typing import Any

from app.config import DEMO_JOBS_DIR
from app.models.manifest import build_manifest, load_manifest
from app.models.progress import atomic_write_json, load_progress
from app.services.event_service import EventService
from app.services.job_service import JobService
from app.services.runner_adapter import RunnerAdapter, StageResult


class _Phase:
    __slots__ = ("name", "start", "end", "message")

    def __init__(self, name: str, start: float, end: float, message: str):
        self.name = name
        self.start = start
        self.end = end
        self.message = message


# Per-stage simulated behaviour. Durations are a few seconds for demo purposes.
# Progress is not purely linear: each phase uses a different slope.
_STAGE_PROFILES: dict[str, dict[str, Any]] = {
    "pose": {
        "duration_sec": 5.5,
        "total": 1500,
        "unit": "frame",
        "phases": [
            _Phase("loading", 0.0, 0.20, "Loading input sequence"),
            _Phase("tracking", 0.20, 0.85, "Tracking pose {current}/{total}"),
            _Phase("optimizing", 0.85, 0.96, "Global pose-graph optimization"),
            _Phase("exporting", 0.96, 1.00, "Exporting trajectory"),
        ],
    },
    "surface": {
        "duration_sec": 8.0,
        "total": 2000,
        "unit": "frame",
        "phases": [
            _Phase("preparing", 0.0, 0.15, "Preparing surface map"),
            _Phase("mapping", 0.15, 0.86, "Fusing frames {current}/{total}"),
            _Phase("optimizing", 0.86, 0.96, "Post-processing mesh"),
            _Phase("exporting", 0.96, 1.00, "Exporting surface mesh"),
        ],
    },
    "distance": {
        "duration_sec": 5.0,
        "total": 1_000_000,
        "unit": "voxel",
        "phases": [
            _Phase("loading", 0.0, 0.12, "Loading surface mesh"),
            _Phase("computing", 0.12, 0.80, "Brute-force ESDF propagation"),
            _Phase("optimizing", 0.80, 0.96, "Multi-resolution sweep"),
            _Phase("exporting", 0.96, 1.00, "Exporting distance slices"),
        ],
    },
}


class MockRunnerAdapter(RunnerAdapter):
    name = "mock"

    def __init__(self, job_service: JobService, event_service: EventService):
        self._jobs = job_service
        self._events = event_service
        self._cancel: set[tuple[str, str]] = set()

    # ------------------------------------------------------------- interface
    def cancel(self, job_id: str, stage: str) -> None:
        self._cancel.add((job_id, stage))

    async def run_stage(self, job_id: str, stage: str, backend: str) -> StageResult:
        self._cancel.discard((job_id, stage))
        started = time.monotonic()
        job = self._jobs.load_job(job_id)
        stage_entry = self._jobs.stage_mark(job, stage)
        profile = _STAGE_PROFILES[stage]

        # Signals "running" in job.json first (persisted for page refresh).
        self._jobs.set_stage_status(job, stage, "running", starter=True)

        prog = load_progress(self._jobs.stage_dir(job_id, stage), stage, backend)
        prog.update(status="running", phase="preparing", progress=0.0,
                    current=0, total=profile["total"], unit=profile["unit"],
                    message="Starting mock runner", elapsed_sec=0.0,
                    updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
        await self._emit_progress(job_id, stage, prog)
        await self._log(job_id, stage, f"[mock:{backend}] {stage} phase 1 (demo backend, no real algorithm)")
        await self._log(job_id, stage, f"[mock:{backend}] reading input manifest")

        demo_ok = self._ensure_demo_data(job_id, stage, job.get("dataset"))

        duration = profile["duration_sec"]
        ticks = 90
        n = 0
        prev_phase = None
        while n < ticks:
            if (job_id, stage) in self._cancel:
                return await self._finish_cancelled(job_id, stage, backend, started)

            fraction = n / ticks
            prog_frac = self._pace(fraction)
            phase = self._phase_for(profile, prog_frac)
            if phase.name != prev_phase:
                await self._log(job_id, stage, f"[mock:{backend}] phase -> {phase.name}")
                prev_phase = phase.name

            current = int(prog_frac * profile["total"])
            prog.update(
                phase=phase.name,
                progress=round(prog_frac * 100.0, 2),
                current=current,
                total=profile["total"],
                message=phase.message.format(current=current, total=profile["total"])
                if "{current}" in phase.message else phase.message,
                elapsed_sec=round(time.monotonic() - started, 1),
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
            await self._emit_progress(job_id, stage, prog)

            # Simulated failure path (only when the job asks for it).
            if job.get("fail_stage") == stage and prog_frac > 0.38 and n % 3 == 0:
                await self._log(job_id, stage, f"[mock:{backend}] ERROR: estimated state diverged at {current}", level="error")
                await self._log(job_id, stage, f"[mock:{backend}] terminate run (simulated failure for demo)")
                prog.update(status="failed", phase=phase.name, progress=round(prog_frac * 100.0, 2),
                            message="Simulated failure (demo)", elapsed_sec=round(time.monotonic() - started, 1))
                atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
                await self._events.publish(job_id, "stage.status",
                                           {"stage": stage, "status": "failed", "message": prog["message"]})
                self._jobs.set_stage_status(job, stage, "failed")
                await self._write_failed_manifest(job_id, stage, backend, started, prog_frac)
                return StageResult(stage, "failed", "Simulated failure (demo)")

            await asyncio.sleep(duration / ticks)
            n += 1

        if (job_id, stage) in self._cancel:
            return await self._finish_cancelled(job_id, stage, backend, started)

        if not demo_ok:
            return await self._finish_failed_missing_demo(job_id, stage, backend, started)

        # ---- success: copy demo previews and write the manifest ----
        self._copy_demo_stage(job_id, stage, job.get("dataset"))
        elapsed = time.monotonic() - started
        metrics, details = self._build_metrics(stage, backend, demo_dir_for(job.get("dataset")))
        manifest = build_manifest(
            job_id=job_id, stage=stage, backend=backend,
            runtime_sec=elapsed, metrics=metrics, artifacts=details["artifacts"],
            backend_details=details["backend_details"],
        )
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "result_manifest.json", manifest)

        prog.update(status="completed", phase="completed", progress=100.0,
                    current=profile["total"], message="Completed",
                    elapsed_sec=round(elapsed, 1), updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
        await self._log(job_id, stage, f"[mock:{backend}] stage complete (demo outputs written)")
        await self._emit_progress(job_id, stage, prog)
        await self._events.publish(job_id, "stage.result", {"stage": stage, "status": "completed"})
        self._jobs.set_stage_status(job, stage, "completed")
        return StageResult(stage, "completed")

    # ------------------------------------------------------------- internals
    @staticmethod
    def _pace(fraction: float) -> float:
        """Slightly bent progress curve so updates do not look like a stopwatch."""
        return min(1.0, fraction * (1.0 + 0.08 * random.random()))

    @staticmethod
    def _phase_for(profile: dict[str, Any], frac: float) -> _Phase:
        for phase in profile["phases"]:
            if frac <= phase.end:
                return phase
        return profile["phases"][-1]

    def _ensure_demo_data(self, job_id: str, stage: str, dataset: str) -> bool:
        src = demo_dir_for(dataset) / f"stage{['1_pose','2_surface','3_esdf'][['pose','surface','distance'].index(stage)]}"
        return src.exists()

    def _copy_demo_stage(self, job_id: str, stage: str, dataset: str) -> None:
        """Copy pre-prepared demo assets into the stage dir.

        Only the matching demo stage folder is copied, so demo files outside
        it (job.json, input/) can never be pulled into a live job.
        """
        src = demo_dir_for(dataset)
        key = {"pose": "stage1_pose", "surface": "stage2_surface", "distance": "stage3_esdf"}[stage]
        stage_dir = self._jobs.stage_dir(job_id, stage)
        stage_dir.mkdir(parents=True, exist_ok=True)
        demo_stage = src / key
        if not demo_stage.exists():
            return
        for item in demo_stage.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(demo_stage)
            target = stage_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    def _build_metrics(self, stage: str, backend: str, demo_dir: Path) -> tuple[dict, dict]:
        """Metrics/artifacts come from the demo manifest prepared by make_demo_data.py.

        The mock never fabricates precision numbers: it reuses fixed demo assets
        and clearly flags what it does in backend_details.
        """
        key = {"pose": "stage1_pose", "surface": "stage2_surface", "distance": "stage3_esdf"}[stage]
        seeder = load_manifest(demo_dir / key) or {}
        metrics = dict(seeder.get("metrics", {}))
        artifacts = [dict(a) for a in seeder.get("artifacts", [])]
        default_metrics = {
            "pose": {"pose_count": 0, "trajectory_length_m": 0.0},
            "surface": {"vertices": 0, "faces": 0},
            "distance": {"resolution_m": 0.1, "voxel_count": 0, "max_distance_m": 0.0},
        }
        metrics = {**default_metrics[stage], **metrics}
        return metrics, {
            "artifacts": artifacts,
            "backend_details": {
                "mock_backend": True,
                "data_source": "demo preview (not a real algorithm run)",
                "note": f"Prepared demo artifacts presented as {backend} results for phase-1 demo.",
            },
        }

    async def _finish_cancelled(self, job_id: str, stage: str, backend: str, started: float) -> StageResult:
        prog = load_progress(self._jobs.stage_dir(job_id, stage), stage, backend)
        prog.update(status="cancelled", progress=prog.get("progress", 0.0),
                    message="Cancelled by user", elapsed_sec=round(time.monotonic() - started, 1),
                    updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
        await self._log(job_id, stage, "[runner] cancelled by user")
        await self._events.publish(job_id, "stage.status", {"stage": stage, "status": "cancelled"})
        job = self._jobs.load_job(job_id)
        self._jobs.set_stage_status(job, stage, "cancelled")
        return StageResult(stage, "cancelled")

    async def _finish_failed_missing_demo(self, job_id: str, stage: str, backend: str, started: float) -> StageResult:
        prog = load_progress(self._jobs.stage_dir(job_id, stage), stage, backend)
        prog.update(status="failed", message="Demo assets missing", elapsed_sec=round(time.monotonic() - started, 1))
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", prog)
        job = self._jobs.load_job(job_id)
        self._jobs.set_stage_status(job, stage, "failed")
        await self._log(job_id, stage, "ERROR: demo assets not found (run scripts/make_demo_data.py)")
        return StageResult(stage, "failed", "Demo assets missing")

    async def _write_failed_manifest(self, job_id: str, stage: str, backend: str, started: float, frac: float) -> None:
        manifest = build_manifest(
            job_id=job_id, stage=stage, backend=backend,
            runtime_sec=round(time.monotonic() - started, 2),
            metrics={"partial_progress": round(frac * 100.0, 1)},
            artifacts=[],
            backend_details={"mock_backend": True, "note": "Run failed (simulated demo failure)."},
            status="failed",
        )
        atomic_write_json(self._jobs.stage_dir(job_id, stage) / "result_manifest.json", manifest)

    async def _emit_progress(self, job_id: str, stage: str, prog: dict) -> None:
        payload = {
            "stage": stage,
            "status": prog.get("status", "running"),
            "phase": prog.get("phase", ""),
            "progress": prog.get("progress", 0.0),
            "current": prog.get("current", 0),
            "total": prog.get("total", 0),
            "unit": prog.get("unit", ""),
            "message": prog.get("message", ""),
            "elapsed_sec": prog.get("elapsed_sec", 0.0),
        }
        await self._events.publish(job_id, "stage.progress", payload)

    async def _log(self, job_id: str, stage: str, line: str, level: str = "info") -> None:
        ts = time.strftime("%H:%M:%S")
        text = f"[{ts}] {line}"
        stage_dir = self._jobs.stage_dir(job_id, stage)
        stage_dir.mkdir(parents=True, exist_ok=True)
        with open(stage_dir / "run.log", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        await self._events.publish(job_id, "stage.log", {"stage": stage, "line": text, "level": level})


def demo_dir_for(dataset: str) -> Path:
    return DEMO_JOBS_DIR / dataset