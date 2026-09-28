"""Job persistence & stage state assembly.

Everything that matters survives a backend restart as plain JSON under jobs/:
job.json, <stage>/progress.json, <stage>/result_manifest.json.
"""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

from app.config import DEMO_JOBS_DIR, JOBS_DIR, STAGES
from app.models.job import (
    derive_job_status,
    new_job,
    stage_dependency_satisfied,
)
from app.models.manifest import load_manifest
from app.models.progress import atomic_write_json, load_progress, read_json
from app.services.registry_service import BackendRegistry
from app.services.dataset_service import DatasetError, DatasetService, get_dataset_service


class JobNotFoundError(Exception):
    pass


class StageNotFoundError(Exception):
    pass


class JobBusyError(Exception):
    pass


class JobService:
    """Owns on-disk job layout and assembles API-facing job detail dicts."""

    def __init__(self, jobs_dir: Path | None = None, datasets: DatasetService | None = None):
        self.jobs_dir = jobs_dir or JOBS_DIR
        self.demo_dir = DEMO_JOBS_DIR
        self.datasets = datasets or get_dataset_service()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ locks
    def lock(self, job_id: str) -> asyncio.Lock:
        return self._locks.setdefault(job_id, asyncio.Lock())

    # ------------------------------------------------------------------ paths
    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def stage_dir(self, job_id: str, stage: str) -> Path:
        return self.jobs_dir / job_id / f"stage{['1_pose','2_surface','3_esdf'][STAGES.index(stage)]}"

    def _safe_job_id(self, job_id: str) -> str:
        if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
            raise JobNotFoundError("Invalid job_id")
        return job_id

    # ---------------------------------------------------------------- datasets
    def list_datasets(self) -> list[dict[str, Any]]:
        return self.datasets.list_public()

    # -------------------------------------------------------------- creation
    async def create_job(
        self,
        dataset: str,
        backends: dict[str, str],
        fail_stage: str | None = None,
        registry: BackendRegistry | None = None,
        preview_job: bool = False,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        from app.services.registry_service import get_registry

        registry = registry or get_registry()
        missing = [s for s in STAGES if s not in backends]
        if missing:
            raise ValueError(f"Missing backend selection for stage(s): {', '.join(missing)}")
        for stage in STAGES:
            registry.ensure_runnable(stage, backends[stage])

        dataset_def = self.datasets.get(dataset)
        validator = getattr(self.datasets, "validation_errors", None)
        errors = validator(dataset_def) if validator else dataset_def.validate()
        if errors:
            raise ValueError(f"Dataset '{dataset}' is unavailable: {'; '.join(errors)}")
        if dataset_def.execution == "real" and backends.get("surface") != dataset_def.surface.get("backend"):
            raise ValueError(
                f"Dataset '{dataset}' currently supports surface backend "
                f"'{dataset_def.surface.get('backend')}' only"
            )
        if dataset_def.execution == "real" and backends.get("pose") != "registered_pose_import":
            raise ValueError("Real registered datasets require pose backend 'registered_pose_import'")
        surface_def = registry.find("surface", backends.get("surface", ""))
        if dataset_def.execution == "real" and surface_def:
            available = set(dataset_def.input_manifest.get("modalities", []))
            required = {"pose" if item == "camera_pose" else item for item in surface_def.input_modalities}
            if not required.issubset(available):
                raise ValueError(
                    f"Dataset '{dataset}' modalities {sorted(available)} are incompatible with "
                    f"surface backend '{surface_def.id}' requiring {sorted(required)}"
                )

        job = new_job(dataset, backends, fail_stage, job_id=job_id, preview_job=preview_job)
        job_dir = self.job_dir(job["job_id"])
        if job_dir.exists():
            await self._ensure_remove(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        # Copy only the selected dataset's input skeleton into the job.
        dataset_dir = self.demo_dir / dataset
        src_input = dataset_dir / "input"
        if dataset_def.kind == "demo" and src_input.exists():
            shutil.copytree(src_input, job_dir / "input")
        else:
            input_dir = job_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            manifest = dict(dataset_def.input_manifest)
            manifest.update({"execution": dataset_def.execution, "dataset_kind": dataset_def.kind})
            atomic_write_json(input_dir / "input_manifest.json", manifest)
            if not dataset_def.rgbd:
                # Stable names keep the existing LiDAR adapter independent from source filenames.
                (input_dir / "source.bag").symlink_to(dataset_def.source_file("bag"))
                (input_dir / "poses.txt").symlink_to(dataset_def.source_file("poses"))

        self.save_job(job)
        return job

    async def _ensure_remove(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)

    # ------------------------------------------------------------- persistence
    def load_job(self, job_id: str) -> dict[str, Any]:
        job_id = self._safe_job_id(job_id)
        path = self.job_dir(job_id) / "job.json"
        job = read_json(path, None)
        if not isinstance(job, dict):
            raise JobNotFoundError(f"Unknown job: {job_id}")
        job["status"] = derive_job_status(job)
        return job

    def save_job(self, job: dict[str, Any]) -> None:
        job["status"] = derive_job_status(job)
        atomic_write_json(self.job_dir(job["job_id"]) / "job.json", job)

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        if not self.jobs_dir.exists():
            return jobs
        for folder in self.jobs_dir.iterdir():
            if not folder.is_dir():
                continue
            job = read_json(folder / "job.json", None)
            if not isinstance(job, dict):
                continue
            job["status"] = derive_job_status(job)
            jobs.append(job)
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs

    def delete_job(self, job_id: str) -> None:
        job_id = self._safe_job_id(job_id)
        path = self.job_dir(job_id)
        if not path.exists():
            raise JobNotFoundError(f"Unknown job: {job_id}")
        shutil.rmtree(path)

    # ------------------------------------------------------------ stage state
    def set_stage_status(
        self, job: dict[str, Any], stage: str, status: str, *, starter: bool = False
    ) -> None:
        st = job["stages"].setdefault(
            stage, {"stage": stage, "backend": job["backends"].get(stage, ""),
                    "status": "waiting", "started_at": None, "finished_at": None}
        )
        st["status"] = status
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if starter:
            st["started_at"] = now
            st["finished_at"] = None
        if status in ("completed", "failed", "cancelled"):
            st["finished_at"] = now
        self.save_job(job)

    def stage_mark(self, job: dict[str, Any], stage: str) -> dict[str, Any]:
        """Current persisted stage entry (for runners to mutate)."""
        return job["stages"][stage]

    # ------------------------------------------------------------ API assembly
    def stage_detail(
        self,
        job: dict[str, Any],
        stage: str,
        registry: BackendRegistry,
        backend_label: dict[str, str],
    ) -> dict[str, Any]:
        if stage not in STAGES:
            raise StageNotFoundError(f"Unknown stage: {stage}")
        st = job["stages"].get(stage)
        if st is None:
            st = {"stage": stage, "backend": job["backends"].get(stage, ""),
                  "status": "waiting", "started_at": None, "finished_at": None}
        backend_id = st.get("backend") or job["backends"].get(stage, "")
        stage_dir = self.stage_dir(job["job_id"], stage)
        progress = load_progress(stage_dir, stage, backend_id)
        manifest = load_manifest(stage_dir)

        status = st.get("status", "waiting")
        if status == "waiting" and manifest and manifest.get("status") == "completed":
            status = "completed"  # self-heal when a run finished but job.json lagged

        def_ = registry.find(stage, backend_id)
        can_run, reason = self._can_run(job, stage, status, registry, backend_id)

        return {
            "stage": stage,
            "backend": backend_id,
            "backend_display": label_by(def_, backend_label.get(backend_id, backend_id)),
            "backend_status": def_.status if def_ else None,
            "status": status,
            "phase": progress.get("phase", ""),
            "progress": round(float(progress.get("progress", 0.0)), 2),
            "current": progress.get("current", 0),
            "total": progress.get("total", 0),
            "unit": progress.get("unit", ""),
            "message": progress.get("message", ""),
            "elapsed_sec": round(float(progress.get("elapsed_sec", 0.0)), 1),
            "started_at": st.get("started_at"),
            "finished_at": st.get("finished_at"),
            "manifest": manifest,
            "can_run": can_run,
            "run_blocked_reason": reason,
        }

    def _can_run(
        self,
        job: dict[str, Any],
        stage: str,
        status: str,
        registry: BackendRegistry,
        backend_id: str,
    ) -> tuple[bool, str]:
        if status == "running":
            return False, "Stage already running"
        if status in ("completed",):
            return False, "Stage already completed"
        try:
            dataset_def = self.datasets.get(job.get("dataset", ""))
        except DatasetError as exc:
            return False, str(exc)
        if dataset_def.execution == "real":
            if stage == "pose":
                if backend_id != "registered_pose_import":
                    return False, "Real registered datasets require registered_pose_import"
            elif stage == "distance":
                return False, "No real Distance runner is integrated yet"
            elif stage != "surface" or backend_id not in ("mrhash_lidar", "mrhash_rgbd"):
                return False, f"No real runner is available for {stage}/{backend_id}"
        dep = stage_dependency_satisfied(job, stage)
        if not dep:
            label = {"pose": "Pose", "surface": "Surface", "distance": "Distance"}[stage]
            prev = {"pose": "", "surface": "Pose", "distance": "Surface"}[stage]
            return False, f"{prev} must be completed before running {label}"
        def_ = registry.find(stage, backend_id)
        if def_ is None:
            return False, f"Backend '{backend_id}' not in registry"
        if def_.status == "disabled":
            return False, "Selected backend is disabled"
        return True, ""

    def reconcile_interrupted_jobs(self) -> int:
        """Mark persisted running stages failed after a backend restart."""
        changed = 0
        for job in self.list_jobs():
            dirty = False
            for stage, state in job.get("stages", {}).items():
                if state.get("status") != "running":
                    continue
                state["status"] = "failed"
                state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                progress = load_progress(self.stage_dir(job["job_id"], stage), stage,
                                         state.get("backend", ""))
                progress.update(status="failed", phase="interrupted",
                                message="Backend restarted while the subprocess was running",
                                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
                atomic_write_json(self.stage_dir(job["job_id"], stage) / "progress.json", progress)
                dirty = True
                changed += 1
            if dirty:
                self.save_job(job)
        return changed

    def job_detail(self, job_id: str, registry: BackendRegistry, backend_labels: dict[str, str]) -> dict[str, Any]:
        job = self.load_job(job_id)
        return {
            "job_id": job["job_id"],
            "created_at": job.get("created_at", ""),
            "status": job["status"],
            "dataset": job.get("dataset", ""),
            "backends": job.get("backends", {}),
            "preview_job": job.get("preview_job", False),
            "fail_stage": job.get("fail_stage"),
            "stages": {
                stage: self.stage_detail(job, stage, registry, backend_labels)
                for stage in STAGES
            },
        }


def label_by(def_, fallback: str) -> str:
    return def_.display_name if def_ is not None else fallback


def collect_backend_labels(registry: BackendRegistry) -> dict[str, str]:
    labels: dict[str, str] = {}
    for stage in STAGES:
        for b in registry.list_stage(stage):
            labels[b.id] = b.display_name
    return labels


_job_service: JobService | None = None


def get_job_service() -> JobService:
    global _job_service
    if _job_service is None:
        _job_service = JobService()
    return _job_service
