from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.runner_adapter import SubprocessRunnerAdapter


class FakeJobs:
    def __init__(self, root: Path):
        self.root = root
        self.job = {
            "job_id": "test-job",
            "backends": {"surface": "mrhash_lidar"},
            "stages": {"surface": {"status": "waiting"}},
        }
        self.job_dir("test-job").mkdir(parents=True)
        self.save_job(self.job)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def stage_dir(self, job_id: str, stage: str) -> Path:
        return self.job_dir(job_id) / "stage2_surface"

    def load_job(self, job_id: str) -> dict:
        return self.job

    def save_job(self, job: dict) -> None:
        (self.job_dir(job["job_id"]) / "job.json").write_text(json.dumps(job))

    def set_stage_status(self, job: dict, stage: str, status: str, **_kwargs) -> None:
        job["stages"][stage]["status"] = status
        self.save_job(job)


class Events:
    def __init__(self, fail_logs: bool = False):
        self.fail_logs = fail_logs
        self.items: list[tuple[str, dict]] = []

    async def publish(self, _job_id: str, event_type: str, payload: dict) -> None:
        if self.fail_logs and event_type == "stage.log":
            raise RuntimeError("simulated event failure")
        self.items.append((event_type, payload))


class CommandRunner(SubprocessRunnerAdapter):
    _TERMINATE_GRACE_SEC = 0.3

    def __init__(self, jobs, events, code: str):
        super().__init__(jobs, events, mode="demo")
        self.code = code

    def _build_command(self, job_id: str, stage: str, backend: str) -> list[str]:
        return [sys.executable, "-c", self.code, str(self._jobs.job_dir(job_id))]


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class SubprocessRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jobs = FakeJobs(Path(self.temp.name))

    async def test_carriage_returns_and_long_unterminated_output(self) -> None:
        code = r'''
import json, pathlib, sys
stage = pathlib.Path(sys.argv[1]) / "stage2_surface"
stage.mkdir(parents=True, exist_ok=True)
sys.stdout.write("".join("progress-%06d\\r" % i for i in range(12000)))
sys.stdout.write("x" * 200000)
sys.stdout.flush()
(stage / "result_manifest.json").write_text(json.dumps({"status": "completed"}))
'''
        events = Events()
        runner = CommandRunner(self.jobs, events, code)
        result = await asyncio.wait_for(
            runner.run_stage("test-job", "surface", "mrhash_lidar"), timeout=10
        )
        self.assertEqual(result.status, "completed")
        log = self.jobs.stage_dir("test-job", "surface").joinpath("run.log").read_text()
        self.assertIn("progress-000000", log)
        self.assertIn("progress-011999", log)
        self.assertGreaterEqual(log.count("x" * 100), 10)
        self.assertLessEqual(max(map(len, log.splitlines())), runner._LOG_RECORD_LIMIT + 12)
        log_events = [item for item in events.items if item[0] == "stage.log"]
        self.assertLess(len(log_events), 2000)
        self.assertNotIn(("test-job", "surface"), runner._processes)

    async def test_event_failure_reaps_process_group(self) -> None:
        pid_file = self.jobs.job_dir("test-job") / "child.pid"
        code = r'''
import pathlib, subprocess, sys, time
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
(pathlib.Path(sys.argv[1]) / "child.pid").write_text(str(p.pid))
print("trigger-event-failure", flush=True)
time.sleep(60)
'''
        runner = CommandRunner(self.jobs, Events(fail_logs=True), code)
        result = await asyncio.wait_for(
            runner.run_stage("test-job", "surface", "mrhash_lidar"), timeout=5
        )
        self.assertEqual(result.status, "failed")
        child_pid = int(pid_file.read_text())
        await asyncio.sleep(0.1)
        self.assertFalse(pid_exists(child_pid))
        self.assertNotIn(("test-job", "surface"), runner._processes)

    async def test_cancel_reaps_process_group(self) -> None:
        pid_file = self.jobs.job_dir("test-job") / "child.pid"
        code = r'''
import pathlib, subprocess, sys, time
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
(pathlib.Path(sys.argv[1]) / "child.pid").write_text(str(p.pid))
print("ready", flush=True)
time.sleep(60)
'''
        runner = CommandRunner(self.jobs, Events(), code)
        task = asyncio.create_task(runner.run_stage("test-job", "surface", "mrhash_lidar"))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.02)
        self.assertTrue(pid_file.exists())
        runner.cancel("test-job", "surface")
        result = await asyncio.wait_for(task, timeout=5)
        self.assertEqual(result.status, "cancelled")
        child_pid = int(pid_file.read_text())
        await asyncio.sleep(0.1)
        self.assertFalse(pid_exists(child_pid))
        self.assertNotIn(("test-job", "surface"), runner._processes)


if __name__ == "__main__":
    unittest.main()
