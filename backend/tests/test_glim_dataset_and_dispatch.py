from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.models.job import BackendDef
from app.services.backend_runtime import REAL_RUNNERS, has_real_runner, real_backend_ids, runner_script
from app.services.dataset_service import DatasetDefinition
from app.services.job_service import (
    pose_backend_compatibility,
    pose_is_produced,
    surface_backend_compatibility,
)
from app.services.pose_spec import cross_check_lookup_keys, validate_dataset_pose
from app.services.runner_adapter import SubprocessRunnerAdapter
from app.services.runner_service import RunnerService, StartStageError


GLIM_SPEC = {
    "backend": "glim",
    "lidar_topic": "/livox_mid360/livox/lidar",
    "imu_topic": "/livox_mid360/livox/imu",
    "lidar_frame_id": "livox_mid360_frame",
    "imu_frame_id": "livox_frame",
    "acc_scale": 9.80665,
    "perpoint_relative_time": True,
    "perpoint_time_scale": 1e-9,
    "T_lidar_imu": [0.011, 0.02329, -0.04412, 0.0, 0.0, 0.0, 1.0],
    "config_path": "INS/glim_ins_config",
    "timestamp": {
        "native_lookup_key": "physical LiDAR sensor/header timestamp",
        "surface_lookup_key": "ROS bag record timestamp",
        "max_delta_sec": 0.05,
        "min_matched_ratio": 0.98,
    },
}


class FakeRegistry:
    """Minimal registry mirroring BackendRegistry's interface."""

    def __init__(self) -> None:
        self.backends = {
            "pose": {
                "registered_pose_import": BackendDef(
                    id="registered_pose_import", display_name="Registered Pose Import",
                    status="ready", input_modalities=["registered_pose"],
                ),
                "glim": BackendDef(
                    id="glim", display_name="GLIM", status="ready",
                    input_modalities=["lidar", "imu"],
                    capabilities={"real_execution": True, "produces_pose": True,
                                  "requires_pose_spec": True},
                ),
            },
            "surface": {
                "mrhash_lidar": BackendDef(
                    id="mrhash_lidar", display_name="MrHash (LiDAR)", status="ready",
                    input_modalities=["lidar", "camera_pose"],
                ),
            },
        }

    def find(self, stage: str, backend_id: str):
        return self.backends.get(stage, {}).get(backend_id)

    def ensure_runnable(self, stage: str, backend_id: str):
        return self.find(stage, backend_id)


def real_dataset(**overrides) -> SimpleNamespace:
    base = dict(
        id="ins_longcorridor01", execution="real", kind="external", rgbd={},
        input_manifest={"modalities": ["lidar", "imu", "rgb", "depth"]},
        pose=dict(GLIM_SPEC),
        surface={"backend": "mrhash_lidar", "topic": "/livox_mid360/livox/lidar",
                 "pose_lookup_key": "ROS bag record timestamp"},
        files={"bag": "2024-06-04-16-24-55.bag"},
        validate=lambda: [],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class DatasetRegistryTests(unittest.TestCase):
    """docs/glim-integration-acceptance.md §2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "INS" / "glim_ins_config").mkdir(parents=True)
        (self.workspace / "INS" / "glim_ins_config" / "config_ros.json").write_text(
            '{"glim_ros": {"points_topic": "/ins/points"}}', encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"GLIM_WORKSPACE": str(self.workspace)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def validate(self, pose_block, files=None, check_paths=True):
        return validate_dataset_pose(
            pose_block, workspace=self.workspace,
            declared_files=files if files is not None else {"bag": "bag.bag"},
            check_paths=check_paths,
        )

    def test_valid_glim_spec_passes_without_a_precomputed_pose(self):
        self.assertEqual(self.validate(GLIM_SPEC), [])
        # The registry may omit files.poses entirely for a SLAM backend.
        self.assertEqual(self.validate(GLIM_SPEC, files={"bag": "bag.bag"}), [])

    def test_missing_bag_is_reported_for_the_pose_backend(self):
        errors = self.validate(GLIM_SPEC, files={})
        self.assertTrue(any("no 'bag' file" in error for error in errors), errors)

    def test_missing_lidar_or_imu_is_reported(self):
        for key in ("lidar_topic", "imu_topic"):
            spec = dict(GLIM_SPEC)
            spec.pop(key)
            self.assertTrue(any(key in error for error in self.validate(spec)))

    def test_invalid_sensor_config_is_reported(self):
        for key, value, expected in (
            ("T_lidar_imu", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "T_lidar_imu"),
            ("T_lidar_imu", [0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0], "unit length"),
            ("acc_scale", 0, "acc_scale"),
            ("acc_scale", -1, "acc_scale"),
            ("perpoint_time_scale", 0, "perpoint_time_scale"),
            ("config_path", "", "config_path"),
        ):
            spec = dict(GLIM_SPEC)
            spec[key] = value
            errors = self.validate(spec)
            self.assertTrue(any(expected in error for error in errors), (key, errors))

    def test_config_path_must_exist_when_paths_are_checked(self):
        spec = dict(GLIM_SPEC, config_path="INS/does_not_exist")
        self.assertTrue(any("config_path" in error for error in self.validate(spec)))
        self.assertEqual(self.validate(spec, check_paths=False), [])

    def test_pose_and_surface_must_agree_on_the_lookup_key(self):
        mismatched_surface = {"backend": "mrhash_lidar", "pose_lookup_key": "something else"}
        self.assertTrue(cross_check_lookup_keys(GLIM_SPEC, mismatched_surface))
        self.assertEqual(
            cross_check_lookup_keys(GLIM_SPEC,
                                    {"pose_lookup_key": "ROS bag record timestamp"}),
            [],
        )

    def definition(self, **overrides) -> DatasetDefinition:
        bag = self.root / "bag.bag"
        bag.write_bytes(b"bag")
        base = dict(
            id="ins", name="INS", description="", kind="external", execution="real",
            input_manifest={"modalities": ["lidar", "imu"]},
            source_dir=self.root, files={"bag": "bag.bag"}, pose={}, runtime={},
            surface={"backend": "mrhash_lidar"}, rgbd={},
            integrity={"bag_size_bytes": 3,
                       "bag_sha256": hashlib.sha256(b"bag").hexdigest()},
        )
        base.update(overrides)
        return DatasetDefinition(**base)

    def test_bag_is_required_even_though_poses_is_optional(self):
        self.assertEqual(self.definition().validate(), [])
        errors = self.definition(files={}).validate()
        self.assertTrue(any("required 'bag' file" in error for error in errors), errors)

    def test_declared_poses_file_must_exist_but_may_be_absent_from_the_registry(self):
        self.assertEqual(self.definition().validate(), [])
        errors = self.definition(files={"bag": "bag.bag", "poses": "poses.txt"}).validate()
        self.assertTrue(any("poses file is unavailable" in error for error in errors), errors)

    def test_pose_modality_without_pose_source_is_inconsistent(self):
        errors = self.definition(input_manifest={"modalities": ["lidar", "pose"]}).validate()
        self.assertTrue(any("'pose' modality" in error for error in errors), errors)

    def test_glim_dataset_validates_with_paths_checked(self):
        definition = self.definition(
            pose=dict(GLIM_SPEC), surface={"backend": "mrhash_lidar",
                                           "pose_lookup_key": "ROS bag record timestamp"},
        )
        self.assertEqual(definition.validate(), [])


class CompatibilityTests(unittest.TestCase):
    """docs/glim-integration-acceptance.md §3 (capability driven, no id special cases)."""

    def setUp(self) -> None:
        self.registry = FakeRegistry()

    def test_glim_is_compatible_when_the_dataset_declares_lidar_and_imu(self):
        dataset = real_dataset()
        self.assertEqual(pose_backend_compatibility(dataset, self.registry, "glim"), (True, ""))
        self.assertTrue(pose_is_produced(dataset, self.registry, "glim"))

    def test_missing_imu_makes_glim_unavailable_with_an_explicit_reason(self):
        dataset = real_dataset(input_manifest={"modalities": ["lidar", "pose"]})
        ok, reason = pose_backend_compatibility(dataset, self.registry, "glim")
        self.assertFalse(ok)
        self.assertIn("imu", reason)

    def test_registered_pose_import_still_requires_the_pose_modality(self):
        dataset = real_dataset(pose={}, input_manifest={"modalities": ["lidar", "imu"]})
        ok, reason = pose_backend_compatibility(dataset, self.registry, "registered_pose_import")
        self.assertFalse(ok)
        self.assertIn("pose", reason)
        ok, _ = pose_backend_compatibility(
            real_dataset(pose={}, input_manifest={"modalities": ["lidar", "pose"]}),
            self.registry, "registered_pose_import",
        )
        self.assertTrue(ok)

    def test_glim_without_a_registered_pose_block_is_rejected(self):
        ok, reason = pose_backend_compatibility(real_dataset(pose={}), self.registry, "glim")
        self.assertFalse(ok)
        self.assertIn("pose", reason)

    def test_declared_pose_backend_wins(self):
        dataset = real_dataset(pose={"backend": "registered_pose_import"})
        ok, reason = pose_backend_compatibility(dataset, self.registry, "glim")
        self.assertFalse(ok)
        self.assertIn("registered_pose_import", reason)

    def test_produced_pose_enables_the_surface_backend(self):
        dataset = real_dataset()
        ok, reason = surface_backend_compatibility(
            dataset, self.registry, "mrhash_lidar", pose_backend_id="glim")
        self.assertTrue(ok, reason)
        # Without a Pose-producing Pose backend the dataset has no 'pose' modality.
        ok, reason = surface_backend_compatibility(
            dataset, self.registry, "mrhash_lidar", pose_backend_id="registered_pose_import")
        self.assertFalse(ok)
        self.assertIn("pose", reason)

    def test_mock_datasets_keep_the_free_backend_choice(self):
        demo = SimpleNamespace(execution="mock", input_manifest={}, surface={}, pose={})
        self.assertEqual(pose_backend_compatibility(demo, self.registry, "glim"), (True, ""))
        self.assertEqual(
            surface_backend_compatibility(demo, self.registry, "mrhash_lidar"), (True, ""))

    def test_backend_runtime_is_the_single_source_of_truth(self):
        self.assertEqual(set(REAL_RUNNERS), {
            ("pose", "registered_pose_import"), ("pose", "glim"),
            ("surface", "mrhash_lidar"), ("surface", "mrhash_rgbd"),
        })
        self.assertEqual(real_backend_ids("pose"), ("registered_pose_import", "glim"))
        self.assertTrue(has_real_runner("pose", "glim"))
        self.assertFalse(has_real_runner("pose", "fast_livo2"))
        self.assertEqual(runner_script("pose", "glim"), "run_pose.sh")
        self.assertEqual(runner_script("surface", "mrhash_lidar"), "run_surface.sh")


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fake_jobs(self, execution: str):
        definition = SimpleNamespace(execution=execution)
        return SimpleNamespace(
            datasets=SimpleNamespace(get=lambda _id: definition),
            job_dir=lambda job_id: self.root / job_id,
        )

    def test_real_pose_backends_are_dispatched_to_the_subprocess_adapter(self):
        service = RunnerService(self.fake_jobs("real"), SimpleNamespace())
        job = {"dataset": "ins", "backends": {"pose": "glim"}}
        self.assertIs(service._adapter_for(job, "pose", "glim"), service.subprocess_adapter)
        self.assertIs(service._adapter_for(job, "pose", "registered_pose_import"),
                      service.subprocess_adapter)
        self.assertIs(service._adapter_for(job, "surface", "mrhash_lidar"),
                      service.subprocess_adapter)

    def test_mock_datasets_use_the_mock_adapter(self):
        service = RunnerService(self.fake_jobs("mock"), SimpleNamespace())
        job = {"dataset": "demo_room", "backends": {"pose": "glim"}}
        self.assertIs(service._adapter_for(job, "pose", "glim"), service.mock_adapter)

    def test_unsupported_real_combination_fails_explicitly(self):
        service = RunnerService(self.fake_jobs("real"), SimpleNamespace())
        job = {"dataset": "ins", "backends": {"distance": "voxel_esdf"}}
        with self.assertRaisesRegex(StartStageError, "No real Distance runner"):
            service._adapter_for(job, "distance", "voxel_esdf")
        with self.assertRaisesRegex(StartStageError, "No real runner is available"):
            service._adapter_for(job, "pose", "fast_livo2")

    def test_command_construction_uses_the_registered_stage_script(self):
        jobs = self.fake_jobs("real")
        adapter = SubprocessRunnerAdapter(jobs, SimpleNamespace(), mode="demo")
        pose_command = adapter._build_command("job1", "pose", "glim")
        self.assertTrue(pose_command[0].endswith("run_pose.sh"))
        self.assertEqual(pose_command[1:5], ["--job-dir", str(self.root / "job1"),
                                             "--backend", "glim"])
        self.assertEqual(pose_command[-2:], ["--mode", "demo"])
        surface_command = adapter._build_command("job1", "surface", "mrhash_lidar")
        self.assertTrue(surface_command[0].endswith("run_surface.sh"))

    def test_unsupported_pair_is_reported_as_a_failed_stage_without_spawning(self):
        class Events:
            async def publish(self, *_args, **_kwargs) -> None:
                return None

        jobs = SimpleNamespace(
            job_dir=lambda job_id: self.root / job_id,
            stage_dir=lambda job_id, stage: self.root / job_id / f"stage_{stage}",
            load_job=lambda _job_id: {"job_id": "job1", "stages": {"distance": {"status": "waiting"}}},
            set_stage_status=lambda *args, **kwargs: None,
        )
        adapter = SubprocessRunnerAdapter(jobs, Events(), mode="demo")
        result = asyncio.run(adapter.run_stage("job1", "distance", "voxel_esdf"))
        self.assertEqual(result.status, "failed")
        self.assertIn("No real Distance runner", result.error)
        self.assertEqual(adapter._processes, {})


if __name__ == "__main__":
    unittest.main()
