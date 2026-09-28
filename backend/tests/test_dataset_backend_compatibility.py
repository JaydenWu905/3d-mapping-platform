from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.models.job import BackendDef
from app.services.job_service import JobService
from app.services.registry_service import BackendRegistry


class Registry:
    def __init__(self):
        self.backends = {
            "pose": BackendDef(id="registered_pose_import", display_name="Pose", status="ready"),
            "surface": BackendDef(id="mrhash_lidar", display_name="LiDAR", status="ready", input_modalities=["lidar", "camera_pose"]),
            "distance": BackendDef(id="mock_distance", display_name="Distance", status="ready"),
        }

    def ensure_runnable(self, stage, backend):
        return self.backends[stage]

    def find(self, stage, backend):
        return self.backends.get(stage)


class DatasetBackendCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_room_job_creation_remains_compatible(self):
        dataset = SimpleNamespace(
            id="demo_room", execution="mock", kind="demo", rgbd={}, surface={},
            input_manifest={"sensor": {"type": "lidar"}}, validate=lambda: [],
        )
        datasets = SimpleNamespace(get=lambda _id: dataset)
        registry = Registry()
        with tempfile.TemporaryDirectory() as tmp:
            jobs = JobService(Path(tmp), datasets=datasets)
            job = await jobs.create_job(
                "demo_room",
                {"pose": "registered_pose_import", "surface": "mrhash_lidar", "distance": "mock_distance"},
                registry=registry,
                job_id="demo-regression",
            )
            self.assertEqual(job["dataset"], "demo_room")
            self.assertTrue((Path(tmp) / "demo-regression/input/input_manifest.json").is_file())

    async def test_rgbd_dataset_cannot_select_lidar_only_backend(self):
        dataset = SimpleNamespace(
            id="rgbd", execution="real", surface={"backend": "mrhash_rgbd"},
            input_manifest={"modalities": ["rgb", "depth", "pose"]}, validate=lambda: [],
        )
        datasets = SimpleNamespace(get=lambda _id: dataset)
        with tempfile.TemporaryDirectory() as tmp:
            jobs = JobService(Path(tmp), datasets=datasets)
            with self.assertRaisesRegex(ValueError, "supports surface backend 'mrhash_rgbd' only"):
                await jobs.create_job("rgbd", {"pose": "registered_pose_import", "surface": "mrhash_lidar", "distance": "mock_distance"}, registry=Registry())

    async def test_rgbd_missing_pose_modality_is_incompatible(self):
        dataset = SimpleNamespace(
            id="rgbd", execution="real", kind="external", rgbd={"contract": True},
            surface={"backend": "mrhash_rgbd"}, input_manifest={"modalities": ["rgb", "depth"]},
            validate=lambda: [],
        )
        registry = Registry()
        registry.backends["surface"] = BackendDef(
            id="mrhash_rgbd", display_name="RGB-D", status="experimental",
            input_modalities=["rgb", "depth", "camera_pose"],
        )
        datasets = SimpleNamespace(get=lambda _id: dataset)
        with tempfile.TemporaryDirectory() as tmp:
            jobs = JobService(Path(tmp), datasets=datasets)
            with self.assertRaisesRegex(ValueError, "incompatible.*pose"):
                await jobs.create_job("rgbd", {"pose": "registered_pose_import", "surface": "mrhash_rgbd", "distance": "mock_distance"}, registry=registry)

    async def test_complete_rgbd_modalities_are_compatible_at_job_boundary(self):
        dataset = SimpleNamespace(
            id="rgbd", execution="real", kind="external", rgbd={"contract": True},
            surface={"backend": "mrhash_rgbd"}, input_manifest={"modalities": ["rgb", "depth", "pose"]},
            validate=lambda: [],
        )
        registry = Registry()
        registry.backends["surface"] = BackendDef(
            id="mrhash_rgbd", display_name="RGB-D", status="experimental",
            input_modalities=["rgb", "depth", "camera_pose"],
        )
        datasets = SimpleNamespace(get=lambda _id: dataset)
        with tempfile.TemporaryDirectory() as tmp:
            jobs = JobService(Path(tmp), datasets=datasets)
            job = await jobs.create_job("rgbd", {"pose": "registered_pose_import", "surface": "mrhash_rgbd", "distance": "mock_distance"}, registry=registry)
            self.assertEqual(job["dataset"], "rgbd")

    def test_real_registry_keeps_mrhash_rgbd_disabled(self):
        backend = BackendRegistry().find("surface", "mrhash_rgbd")
        self.assertIsNotNone(backend)
        self.assertEqual(backend.status, "disabled")

    async def test_lidar_dataset_cannot_select_rgbd_only_backend(self):
        dataset = SimpleNamespace(
            id="lidar", execution="real", surface={"backend": "mrhash_lidar"},
            input_manifest={"modalities": ["lidar", "pose"]}, validate=lambda: [],
        )
        registry = Registry()
        registry.backends["surface"] = BackendDef(id="mrhash_rgbd", display_name="RGB-D", status="experimental", input_modalities=["rgb", "depth", "camera_pose"])
        datasets = SimpleNamespace(get=lambda _id: dataset)
        with tempfile.TemporaryDirectory() as tmp:
            jobs = JobService(Path(tmp), datasets=datasets)
            with self.assertRaisesRegex(ValueError, "supports surface backend 'mrhash_lidar' only"):
                await jobs.create_job("lidar", {"pose": "registered_pose_import", "surface": "mrhash_rgbd", "distance": "mock_distance"}, registry=registry)


if __name__ == "__main__":
    unittest.main()
