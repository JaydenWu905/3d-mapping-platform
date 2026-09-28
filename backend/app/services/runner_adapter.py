"""Runner Adapter interface.

Business code only ever talks to `RunnerAdapter.run_stage`. Swapping the mock
for real algorithms later = registering a different adapter, nothing else.

Subprocess adapter CLI contract:

    run_pose.sh     --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
    run_surface.sh  --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
    run_esdf.sh     --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full

The scripts are expected to write progress.json + run.log continuously and
finish with result_manifest.json inside the stage directory.
"""
from __future__ import annotations

import abc
import asyncio
import os
import re
import signal
import time
from pathlib import Path

from app.config import BACKEND_ROOT
from app.models.manifest import load_manifest
from app.models.progress import atomic_write_json, load_progress


class StageResult:
    """What a runner reports when a stage run finished."""

    def __init__(self, stage: str, status: str, error: str = "", exit_code: int = 0):
        self.stage = stage
        self.status = status  # completed | failed | cancelled
        self.error = error
        self.exit_code = exit_code


class RunnerAdapter(abc.ABC):
    """Interface each concrete adapter (mock / subprocess) must implement."""

    name: str = "runner"

    @abc.abstractmethod
    async def run_stage(self, job_id: str, stage: str, backend: str) -> StageResult:
        """Run one stage of one job. Raised as a background task."""

    @abc.abstractmethod
    def cancel(self, job_id: str, stage: str) -> None:
        """Request cancellation. The runner should stop at the next tick."""


class SubprocessRunnerAdapter(RunnerAdapter):
    """Run isolated algorithm adapters without importing them into FastAPI."""

    name = "subprocess"
    _READ_SIZE = 64 * 1024
    _LOG_RECORD_LIMIT = 16 * 1024
    _EVENT_QUEUE_SIZE = 256
    _TERMINATE_GRACE_SEC = 8.0
    _PROGRESS_EVENT_INTERVAL_SEC = 0.25
    _TQDM_RE = re.compile(
        r"\bprocessing:\s*(?P<percent>\d{1,3})%.*?"
        r"(?P<current>\d+)\s*/\s*(?P<total>\d+)\b"
    )

    def __init__(self, job_service, event_service, mode: str | None = None):
        self._jobs = job_service
        self._events = event_service
        self._mode = mode or os.environ.get("MAPPING_SURFACE_MODE", "full")
        self._processes: dict[tuple[str, str], asyncio.subprocess.Process] = {}
        self._cancel_requested: set[tuple[str, str]] = set()
        self._progress_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._progress_states: dict[tuple[str, str], dict] = {}
        self._last_progress_emit: dict[tuple[str, str], float] = {}

    async def run_stage(self, job_id: str, stage: str, backend: str) -> StageResult:
        if (stage, backend) not in (("pose", "registered_pose_import"), ("surface", "mrhash_lidar"), ("surface", "mrhash_rgbd")):
            return await self._fail(job_id, stage, backend, "No real adapter for this stage/backend", 2)
        if self._mode not in ("demo", "full"):
            return await self._fail(job_id, stage, backend, f"Invalid runner mode: {self._mode}", 2)

        key = (job_id, stage)
        job = self._jobs.load_job(job_id)
        self._jobs.set_stage_status(job, stage, "running", starter=True)
        stage_dir = self._jobs.stage_dir(job_id, stage)
        stage_dir.mkdir(parents=True, exist_ok=True)
        for stale in ("result_manifest.json",):
            (stage_dir / stale).unlink(missing_ok=True)
        progress = load_progress(stage_dir, stage, backend)
        progress.update(status="running", phase="starting", progress=0.0, current=0,
                        total=0, unit="", message="Starting real MrHash process",
                        elapsed_sec=0.0, updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        atomic_write_json(stage_dir / "progress.json", progress)
        self._progress_states[key] = dict(progress)
        self._progress_locks[key] = asyncio.Lock()
        await self._emit_progress(job_id, stage, progress)

        # A cancel request can arrive after RunnerService creates this task but
        # before the coroutine has spawned its process. Preserve that request.
        if key in self._cancel_requested:
            self._cancel_requested.discard(key)
            return await self._finish(
                job_id, stage, backend, "cancelled", "Cancelled by user", 0, time.monotonic()
            )

        command = self._build_command(job_id, stage, backend)
        started = time.monotonic()
        log_path = stage_dir / "run.log"
        tasks: list[asyncio.Task] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            self._processes[key] = process
            # Close the small race between the pre-spawn cancellation check
            # and publishing the process handle used by cancel().
            if key in self._cancel_requested:
                asyncio.create_task(self._terminate(key))
            assert process.stdout is not None
            tasks = [
                asyncio.create_task(
                    self._consume_output(job_id, stage, process.stdout, log_path),
                    name=f"runner-output-{job_id}-{stage}",
                ),
                asyncio.create_task(
                    self._poll_progress(job_id, stage, backend, process, started),
                    name=f"runner-progress-{job_id}-{stage}",
                ),
                asyncio.create_task(process.wait(), name=f"runner-wait-{job_id}-{stage}"),
            ]
            # FIRST_EXCEPTION makes reader/progress/event failures immediately
            # enter the process-group cleanup path. On success it waits for all
            # three tasks, including complete pipe drainage after process exit.
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                task.result()
            await asyncio.gather(*tasks)
            exit_code = process.returncode
            assert exit_code is not None
        except asyncio.CancelledError:
            await self._terminate(key)
            raise
        except Exception as exc:
            await self._terminate(key)
            return await self._fail(job_id, stage, backend, f"Runner exception: {exc}", 1, started)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._processes.pop(key, None)

        if key in self._cancel_requested:
            self._cancel_requested.discard(key)
            return await self._finish(job_id, stage, backend, "cancelled", "Cancelled by user", exit_code, started)
        manifest = load_manifest(stage_dir)
        if exit_code != 0:
            return await self._fail(job_id, stage, backend, f"Algorithm adapter exited with code {exit_code}", exit_code, started)
        if not manifest or manifest.get("status") != "completed":
            return await self._fail(job_id, stage, backend, "Adapter exited successfully without a completed manifest", 1, started)
        return await self._finish(job_id, stage, backend, "completed", "Completed", 0, started)

    def _build_command(self, job_id: str, stage: str, backend: str) -> list[str]:
        script = BACKEND_ROOT / "scripts" / ("run_pose.sh" if stage == "pose" else "run_surface.sh")
        return [str(script), "--job-dir", str(self._jobs.job_dir(job_id)),
                "--backend", backend, "--mode", self._mode]

    def cancel(self, job_id: str, stage: str) -> None:
        key = (job_id, stage)
        self._cancel_requested.add(key)
        process = self._processes.get(key)
        if process and process.returncode is None:
            asyncio.create_task(self._terminate(key))

    async def _terminate(self, key: tuple[str, str]) -> None:
        process = self._processes.get(key)
        if not process:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            if process.returncode is None:
                await process.wait()
            return

        deadline = time.monotonic() + self._TERMINATE_GRACE_SEC
        while time.monotonic() < deadline and self._process_group_exists(process.pid):
            await asyncio.sleep(0.05)
        if self._process_group_exists(process.pid):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            await process.wait()

    @staticmethod
    def _process_group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False

    async def _consume_output(self, job_id: str, stage: str,
                              stream: asyncio.StreamReader, log_path: Path) -> None:
        """Drain output without readline's separator limit or SSE backpressure."""
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=self._EVENT_QUEUE_SIZE)
        publisher = asyncio.create_task(
            self._publish_logs(job_id, stage, queue),
            name=f"runner-log-publisher-{job_id}-{stage}",
        )
        pending = bytearray()
        skip_lf = False

        def enqueue(line: str) -> None:
            while queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            queue.put_nowait(line)

        try:
            with log_path.open("a", encoding="utf-8") as log:
                while True:
                    read_task = asyncio.create_task(stream.read(self._READ_SIZE))
                    done, _ = await asyncio.wait(
                        (read_task, publisher), return_when=asyncio.FIRST_COMPLETED
                    )
                    if publisher in done:
                        read_task.cancel()
                        await asyncio.gather(read_task, return_exceptions=True)
                        publisher.result()
                    raw = read_task.result()
                    if not raw:
                        break
                    for byte in raw:
                        if skip_lf:
                            skip_lf = False
                            if byte == 10:
                                continue
                        if byte in (10, 13):
                            await self._write_log_record(job_id, stage, log, pending, enqueue)
                            pending.clear()
                            skip_lf = byte == 13
                        else:
                            pending.append(byte)
                            if len(pending) >= self._LOG_RECORD_LIMIT:
                                await self._write_log_record(job_id, stage, log, pending, enqueue)
                                pending.clear()
                if pending:
                    await self._write_log_record(job_id, stage, log, pending, enqueue)
                log.flush()
            while queue.full():
                queue.get_nowait()
            queue.put_nowait(None)
            await publisher
        finally:
            if not publisher.done():
                publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)

    async def _write_log_record(self, job_id: str, stage: str, log,
                                raw: bytearray, enqueue) -> None:
        line = raw.decode("utf-8", errors="replace")
        timestamped = f"[{time.strftime('%H:%M:%S')}] {line}"
        log.write(timestamped + "\n")
        log.flush()
        enqueue(timestamped)
        match = self._TQDM_RE.search(line)
        if match:
            await self._record_tqdm_progress(
                job_id, stage, int(match["percent"]),
                int(match["current"]), int(match["total"])
            )

    async def _record_tqdm_progress(self, job_id: str, stage: str, percent: int,
                                    current: int, total: int) -> None:
        key = (job_id, stage)
        lock = self._progress_locks.setdefault(key, asyncio.Lock())
        async with lock:
            progress = dict(self._progress_states.get(key) or load_progress(
                self._jobs.stage_dir(job_id, stage), stage, "mrhash_lidar"
            ))
            old_current = int(progress.get("current") or 0)
            old_total = int(progress.get("total") or 0)
            old_percent = float(progress.get("progress") or 0.0)
            if total <= 0 or current < old_current:
                return
            progress.update(
                status="running", phase="mapping",
                current=max(old_current, min(current, total)),
                total=max(old_total, total),
                progress=max(old_percent, min(float(percent), 100.0)),
                unit="messages", message="MrHash processing LiDAR messages",
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            self._progress_states[key] = progress
            atomic_write_json(
                self._jobs.stage_dir(job_id, stage) / "progress.json", progress
            )
            now = time.monotonic()
            if now - self._last_progress_emit.get(key, 0.0) >= self._PROGRESS_EVENT_INTERVAL_SEC:
                await self._emit_progress(job_id, stage, progress)
                self._last_progress_emit[key] = now

    async def _publish_logs(self, job_id: str, stage: str,
                            queue: asyncio.Queue[str | None]) -> None:
        while True:
            line = await queue.get()
            if line is None:
                return
            await self._events.publish(
                job_id, "stage.log", {"stage": stage, "line": line}
            )

    async def _poll_progress(self, job_id: str, stage: str, backend: str,
                             process: asyncio.subprocess.Process, started: float) -> None:
        last = None
        while process.returncode is None:
            key = (job_id, stage)
            lock = self._progress_locks.setdefault(key, asyncio.Lock())
            async with lock:
                disk = load_progress(self._jobs.stage_dir(job_id, stage), stage, backend)
                cached = self._progress_states.get(key, {})
                if int(cached.get("current") or 0) > int(disk.get("current") or 0):
                    disk.update({name: cached.get(name) for name in
                                 ("current", "total", "progress", "unit")})
                progress = disk
                progress["elapsed_sec"] = round(time.monotonic() - started, 1)
                self._progress_states[key] = progress
                atomic_write_json(self._jobs.stage_dir(job_id, stage) / "progress.json", progress)
            snapshot = repr(sorted(progress.items()))
            if snapshot != last:
                await self._emit_progress(job_id, stage, progress)
                last = snapshot
            await asyncio.sleep(1)

    async def _emit_progress(self, job_id: str, stage: str, progress: dict) -> None:
        payload = {key: progress.get(key) for key in
                   ("status", "phase", "progress", "current", "total", "unit", "message", "elapsed_sec")}
        payload["stage"] = stage
        await self._events.publish(job_id, "stage.progress", payload)

    async def _finish(self, job_id: str, stage: str, backend: str, status: str,
                      message: str, exit_code: int, started: float) -> StageResult:
        stage_dir = self._jobs.stage_dir(job_id, stage)
        if status != "completed":
            (stage_dir / "result_manifest.json").unlink(missing_ok=True)
        key = (job_id, stage)
        progress = dict(self._progress_states.get(key) or load_progress(stage_dir, stage, backend))
        progress.update(status=status, phase=status, message=message,
                        elapsed_sec=round(time.monotonic() - started, 1),
                        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if status == "completed":
            progress["progress"] = 100.0
            if int(progress.get("total") or 0) > 0:
                progress["current"] = progress["total"]
        atomic_write_json(stage_dir / "progress.json", progress)
        job = self._jobs.load_job(job_id)
        self._jobs.set_stage_status(job, stage, status)
        await self._emit_progress(job_id, stage, progress)
        await self._events.publish(job_id, "stage.result", {"stage": stage, "status": status})
        self._progress_states.pop(key, None)
        self._progress_locks.pop(key, None)
        self._last_progress_emit.pop(key, None)
        return StageResult(stage, status, "" if status == "completed" else message, exit_code)

    async def _fail(self, job_id: str, stage: str, backend: str, message: str,
                    exit_code: int, started: float | None = None) -> StageResult:
        return await self._finish(job_id, stage, backend, "failed", message, exit_code,
                                  started if started is not None else time.monotonic())
