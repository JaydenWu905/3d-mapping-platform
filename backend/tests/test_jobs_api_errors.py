from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from app.api import jobs as jobs_api
from app.main import app, backend_selection_error_handler
from app.models.job import CreateJobRequest
from app.services.job_service import JobService
from app.services.registry_service import BackendDisabledError, BackendNotFoundError


class Datasets:
    def __init__(self, root: Path):
        source = root / "source"
        source.mkdir()
        bag = source / "source.bag"
        poses = source / "poses.txt"
        bag.write_bytes(b"bag")
        poses.write_text("1 0 0 0 0 0 0 1\n", encoding="utf-8")
        self.definition = SimpleNamespace(
            id="oxford_mrhash_lidar",
            execution="real",
            kind="external",
            rgbd={},
            surface={"backend": "mrhash_lidar", "topic": "/hesai/pandar"},
            input_manifest={"modalities": ["lidar", "pose"]},
            validate=lambda: [],
            source_file=lambda key: bag if key == "bag" else poses,
        )

    def get(self, dataset_id: str):
        if dataset_id != self.definition.id:
            raise ValueError(f"Unknown dataset: {dataset_id}")
        return self.definition


class JobsApiBackendErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.jobs_dir = root / "jobs"
        service = JobService(self.jobs_dir, datasets=Datasets(root))
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(jobs=service)))

    @staticmethod
    def payload(surface: str) -> dict:
        return {
            "dataset": "oxford_mrhash_lidar",
            "backends": {
                "pose": "registered_pose_import",
                "surface": surface,
                "distance": "voxel_esdf",
            },
            "fail_stage": None,
        }

    def assert_no_jobs(self) -> None:
        self.assertEqual(list(self.jobs_dir.iterdir()) if self.jobs_dir.exists() else [], [])

    async def post(self, surface: str) -> tuple[int, dict]:
        request = CreateJobRequest(**self.payload(surface))
        try:
            body = await jobs_api.create_job(request, self.request)
            return 201, body
        except (BackendDisabledError, BackendNotFoundError) as exc:
            response = await backend_selection_error_handler(self.request, exc)
            return response.status_code, json.loads(response.body)
        except HTTPException as exc:
            return exc.status_code, {"detail": exc.detail}

    def test_expected_handlers_are_registered_on_the_fastapi_app(self):
        self.assertIs(app.exception_handlers[BackendDisabledError], backend_selection_error_handler)
        self.assertIs(app.exception_handlers[BackendNotFoundError], backend_selection_error_handler)

    async def test_disabled_mrhash_rgbd_returns_422_without_side_effects(self):
        status, body = await self.post("mrhash_rgbd")
        self.assertEqual(status, 422)
        self.assertIn("MrHash (RGB-D)", body["detail"])
        self.assertIn("disabled", body["detail"])
        self.assert_no_jobs()

    async def test_unknown_backend_returns_422_without_side_effects(self):
        status, body = await self.post("does_not_exist")
        self.assertEqual(status, 422)
        self.assertIn("does_not_exist", body["detail"])
        self.assertIn("not found", body["detail"])
        self.assert_no_jobs()

    async def test_incompatible_backend_returns_422_without_side_effects(self):
        status, body = await self.post("h3_rgbd")
        self.assertEqual(status, 422)
        self.assertIn("supports surface backend 'mrhash_lidar' only", body["detail"])
        self.assert_no_jobs()

    async def test_valid_oxford_mrhash_lidar_returns_201(self):
        status, body = await self.post("mrhash_lidar")
        self.assertEqual(status, 201, body)
        self.assertEqual(body["dataset"], "oxford_mrhash_lidar")
        self.assertEqual(body["backends"]["surface"], "mrhash_lidar")
        self.assertEqual([path.name for path in self.jobs_dir.iterdir()], [body["job_id"]])


if __name__ == "__main__":
    unittest.main()
