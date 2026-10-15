from __future__ import annotations

import hashlib
import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models.job import derive_job_status, new_job
from app.services.upload_service import UploadError, UploadService
from app.services.runner_adapter import StageResult, SubprocessRunnerAdapter


class TwoStageTests(unittest.TestCase):
    def test_two_stage_completion_and_dependency(self):
        job = new_job("ins", {"pose": "glim", "surface": "mrhash_lidar"}, requested_stages=["pose", "surface"])
        self.assertEqual(job["stages"]["distance"]["status"], "not_integrated")
        self.assertEqual(derive_job_status(job), "created")
        job["stages"]["pose"]["status"] = "completed"
        self.assertEqual(derive_job_status(job), "created")
        job["stages"]["surface"]["status"] = "completed"
        self.assertEqual(derive_job_status(job), "completed")
        job["stages"]["surface"]["status"] = "queued"
        self.assertEqual(derive_job_status(job), "running")

    def test_demo_still_requires_three_stages(self):
        job = new_job("demo", {"pose": "p", "surface": "s", "distance": "d"})
        job["stages"]["pose"]["status"] = "completed"
        job["stages"]["surface"]["status"] = "completed"
        self.assertEqual(derive_job_status(job), "created")


class UploadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.platform = Path(self.tmp.name) / "platform"
        self.platform.mkdir()
        self.config = self.platform / "backend/config/datasets"
        self.config.mkdir(parents=True)
        self.template = self.config / "ins_longcorridor01.json"
        self.template.write_text(json.dumps({"id": "template", "pose": {"bag_path": "old"},
            "input_manifest": {}, "files": {}, "integrity": {}}))
        self.upload = UploadService(self.platform / "uploads", self.template)
        self.data = b"verified bag bytes"
        self.patches = [
            patch("app.services.upload_service.PROFILE_SIZE", len(self.data)),
            patch("app.services.upload_service.PROFILE_SHA", hashlib.sha256(self.data).hexdigest()),
            patch("app.services.upload_service.PROJECT_ROOT", self.platform),
            patch("app.services.upload_service.DATASETS_CONFIG_DIR", self.config),
            patch.object(UploadService, "_preflight", return_value={"topics": {
                "/livox_mid360/livox/lidar": {"count": 1539},
                "/livox_mid360/livox/imu": {"count": 30770}}}),
        ]
        for index, item in enumerate(self.patches):
            started = item.start()
            if index == len(self.patches) - 1:
                self.preflight_mock = started
            self.addCleanup(item.stop)

    async def _send(self, upload_id, offset, data, digest=None):
        async def stream():
            yield data[:3]
            yield data[3:]
        return await self.upload.chunk(upload_id, offset, digest or hashlib.sha256(data).hexdigest(), stream())

    async def test_chunk_retry_resume_integrity_and_registration(self):
        state = self.upload.create("source.bag", len(self.data), "ins_livox_mid360_verified_bag")
        upload_id = state["upload_id"]
        with self.assertRaisesRegex(UploadError, "incomplete"):
            await self.upload.finalize(upload_id)
        with self.assertRaisesRegex(UploadError, "checksum"):
            await self._send(upload_id, 0, b"wrong", "0" * 64)
        self.assertEqual(self.upload.status(upload_id)["offset"], 0)
        await self._send(upload_id, 0, self.data[:8])
        with self.assertRaisesRegex(UploadError, "Offset mismatch"):
            await self._send(upload_id, 0, self.data[:8])
        resumed = UploadService(self.platform / "uploads", self.template)
        self.assertEqual(resumed.status(upload_id)["offset"], 8)
        await resumed.chunk(upload_id, 8, hashlib.sha256(self.data[8:]).hexdigest(), self._stream(self.data[8:]))
        result = await resumed.finalize(upload_id)
        self.assertEqual(result["status"], "registered")
        self.assertFalse((self.platform / "uploads/sessions" / upload_id / "preflight.bag").exists())
        self.assertEqual(await resumed.finalize(upload_id), result)
        definition = json.loads((self.config / f"{result['dataset_id']}.json").read_text())
        self.assertEqual(definition["pose"]["bag_path"], f"platform/uploads/datasets/{result['dataset_id']}/source.bag")
        self.assertEqual((self.platform / "uploads/datasets" / result["dataset_id"] / "source.bag").read_bytes(), self.data)

    async def test_corrupt_file_never_registers(self):
        state = self.upload.create("source.bag", len(self.data), "ins_livox_mid360_verified_bag")
        await self._send(state["upload_id"], 0, b"x" * len(self.data))
        with self.assertRaisesRegex(UploadError, "SHA-256"):
            await self.upload.finalize(state["upload_id"])
        self.assertEqual(list(self.config.glob("ins_upload_*.json")), [])

    async def test_preflight_failure_preserves_upload_without_registration(self):
        state = self.upload.create("source.bag", len(self.data), "ins_livox_mid360_verified_bag")
        await self._send(state["upload_id"], 0, self.data)
        self.preflight_mock.side_effect = UploadError("missing IMU topic")
        with self.assertRaisesRegex(UploadError, "missing IMU"):
            await self.upload.finalize(state["upload_id"])
        self.assertEqual(self.upload.status(state["upload_id"])["status"], "uploading")
        self.assertEqual(list(self.config.glob("ins_upload_*.json")), [])

    def test_packaging_dependencies_are_declared_and_installed(self):
        import scipy
        import fast_simplification
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        self.assertIn("scipy>=", requirements)
        self.assertIn("fast-simplification>=", requirements)
        self.assertTrue(scipy.__version__)
        self.assertTrue(fast_simplification.__version__)

    @staticmethod
    async def _stream(data):
        yield data


class GpuQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_job_serialization_and_queued_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.services.runner_adapter.PROJECT_ROOT", Path(tmp)):
            jobs = {name: {"job_id": name, "stages": {"pose": {"status": "waiting"}}} for name in ("a", "b", "c")}

            class FakeJobs:
                def load_job(self, name):
                    return jobs[name]

                def set_stage_status(self, job, stage, status):
                    job["stages"][stage]["status"] = status

            service = FakeJobs()
            async def publish(*args):
                pass
            adapter = SubprocessRunnerAdapter(service, SimpleNamespace(publish=publish))
            first_entered = asyncio.Event()
            release = asyncio.Event()
            entries = []

            async def locked(job_id, stage, backend):
                entries.append(job_id)
                if job_id == "a":
                    first_entered.set()
                    await release.wait()
                return StageResult(stage, "completed")

            adapter._run_stage_locked = locked
            a = asyncio.create_task(adapter.run_stage("a", "pose", "glim"))
            await first_entered.wait()
            b = asyncio.create_task(adapter.run_stage("b", "pose", "glim"))
            c = asyncio.create_task(adapter.run_stage("c", "pose", "glim"))
            await asyncio.sleep(0.1)
            self.assertEqual(jobs["b"]["stages"]["pose"]["status"], "queued")
            adapter.cancel("c", "pose")
            self.assertEqual((await asyncio.wait_for(c, 2)).status, "cancelled")
            self.assertEqual(entries, ["a"])
            release.set()
            await asyncio.gather(a, b)
            self.assertEqual(entries, ["a", "b"])
