from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.services.surface_input_service import (
    SurfaceInputError,
    prepare_mrhash_rgbd_input,
    mrhash_depth_scaling,
    validate_mrhash_rgbd_surface_input,
    validate_rgbd_dataset,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RGBDFixture:
    def __init__(self, root: Path):
        self.root = root
        (root / "rgb").mkdir(parents=True)
        (root / "depth").mkdir()
        frames = []
        poses = []
        for i, timestamp in enumerate((1.0, 2.0)):
            rgb = root / "rgb" / f"color-{i}.jpg"
            depth = root / "depth" / f"range-{i}.png"
            Image.new("RGB", (2, 2), (i, 0, 0)).save(rgb)
            Image.new("I;16", (2, 2), i + 1000).save(depth)
            frames.append({
                "frame_id": f"f{i}", "rgb_timestamp": timestamp,
                "depth_timestamp": timestamp + 0.001, "pose_timestamp": timestamp,
                "pose_index": i,
                "rgb": {"path": str(rgb.relative_to(root)), "size_bytes": rgb.stat().st_size, "sha256": sha(rgb)},
                "depth": {"path": str(depth.relative_to(root)), "size_bytes": depth.stat().st_size, "sha256": sha(depth)},
            })
            poses.append({"timestamp": timestamp, "translation": [float(i), 0, 0], "quaternion": [0, 0, 0, 1]})
        self.index = root / "sequence-index.json"
        self.trajectory = root / "trajectory.json"
        self.index.write_text(json.dumps({"schema_version": "1.0", "frames": frames}))
        self.trajectory.write_text(json.dumps({"schema_version": "1.0", "transform_direction": "T_world_camera", "poses": poses}))
        self.spec = {
            "sequence_index": self.record(self.index), "trajectory": self.record(self.trajectory), "frame_count": 2,
            "timestamp": {"basis": "capture", "unit": "second", "clock_domain": "camera_hardware"},
            "association": {"max_rgb_depth_delta": 0.01, "max_rgb_pose_delta": 0.01, "max_depth_pose_delta": 0.01},
            "missing_frame_policy": "reject",
            "camera": {"width": 2, "height": 2, "model": "pinhole", "fx": 2.0, "fy": 2.0, "cx": 1.0, "cy": 1.0,
                       "distortion_model": "none", "distortion_coefficients": [], "images_rectified": True},
            "depth": {"unit": "millimeter", "scale_to_meters": 0.001, "invalid_value": 0, "min_valid_m": 0.1, "max_valid_m": 10.0},
            "registration": {"rgb_depth_registered": True, "T_depth_rgb": None, "source_frame": "rgb", "target_frame": "depth",
                             "vector_convention": "homogeneous_column", "matrix_layout": "row_major", "translation_unit": "meter"},
            "pose": {"transform_direction": "T_world_camera", "source_frame": "camera", "target_frame": "world",
                     "quaternion_order": "qx qy qz qw", "handedness": "right", "world_axis_convention": "x-right y-up z-back"},
            "provenance": {"algorithm": "fixture", "version": "1", "revision": "test", "configuration": "fixture",
                           "run_id": "fixture-1"},
        }
        self.definition = SimpleNamespace(
            source_dir=root, rgbd=self.spec,
            input_manifest={"modalities": ["rgb", "depth", "pose"]},
        )

    def record(self, path: Path) -> dict:
        return {"path": str(path.relative_to(self.root)), "size_bytes": path.stat().st_size, "sha256": sha(path)}

    def rewrite_index(self, data: dict) -> None:
        self.index.write_text(json.dumps(data))
        self.spec["sequence_index"] = self.record(self.index)

    def rewrite_trajectory(self, data: dict) -> None:
        self.trajectory.write_text(json.dumps(data))
        self.spec["trajectory"] = self.record(self.trajectory)


class RGBDValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.f = RGBDFixture(Path(self.tmp.name) / "dataset")

    def error(self) -> str:
        errors = validate_rgbd_dataset(self.f.definition, strict_hashes=True)
        self.assertTrue(errors)
        return errors[0]
    def registration(self, registered, matrix):
        return {"rgb_depth_registered": registered, "T_depth_rgb": matrix, "source_frame": "rgb", "target_frame": "depth",
                "vector_convention": "homogeneous_column", "matrix_layout": "row_major", "translation_unit": "meter"}

    def test_valid_two_frames(self):
        self.assertEqual(validate_rgbd_dataset(self.f.definition, strict_hashes=True), [])

    def test_prepare_manifest_and_launch_revalidation(self):
        self.f.definition.id = "rgbd"
        self.f.definition.surface = {"backend": "mrhash_rgbd"}
        jobs_root = Path(self.tmp.name) / "jobs"
        jobs = SimpleNamespace(
            load_job=lambda _id: {"job_id": "j", "dataset": "rgbd", "backends": {"surface": "mrhash_rgbd"}},
            datasets=SimpleNamespace(get=lambda _id: self.f.definition),
            stage_dir=lambda _id, _stage: jobs_root / "j/stage2_surface",
        )
        manifest = prepare_mrhash_rgbd_input("j", jobs)
        self.assertEqual(manifest["modalities"], ["rgb", "depth", "pose"])
        self.assertEqual(manifest["depth"]["mrhash_depth_scaling"], 1000.0)
        self.assertEqual(manifest["compatibility"]["status"], "contract_validated_backend_not_ready")
        validate_mrhash_rgbd_surface_input(jobs_root / "j")

    def test_rgb_missing(self):
        (self.f.root / "rgb/color-1.jpg").unlink()
        self.assertIn("rgb", self.error())

    def test_depth_missing(self):
        (self.f.root / "depth/range-1.png").unlink()
        self.assertIn("depth", self.error())

    def test_frame_count_mismatch(self):
        data = json.loads(self.f.index.read_text()); data["frames"].pop(); self.f.rewrite_index(data)
        self.assertIn("frame count", self.error())

    def test_non_increasing_timestamp(self):
        data = json.loads(self.f.index.read_text()); data["frames"][1]["rgb_timestamp"] = 1.0; self.f.rewrite_index(data)
        self.assertIn("strictly increasing", self.error())

    def test_association_delta(self):
        data = json.loads(self.f.index.read_text()); data["frames"][1]["depth_timestamp"] = 2.5; self.f.rewrite_index(data)
        self.assertIn("allowed delta", self.error())

    def test_pose_missing_or_count_mismatch(self):
        data = json.loads(self.f.trajectory.read_text()); data["poses"].pop(); self.f.rewrite_trajectory(data)
        self.assertIn("Pose", self.error())

    def test_invalid_intrinsics(self):
        self.f.spec["camera"]["fx"] = 0
        self.assertIn("intrinsics", self.error())

    def test_invalid_depth_scale(self):
        self.f.spec["depth"]["scale_to_meters"] = 0
        self.assertIn("depth scale", self.error())

    def test_depth_scaling_mapping(self):
        self.assertEqual(mrhash_depth_scaling(0.001), 1000.0)
        with self.assertRaisesRegex(SurfaceInputError, "finite and positive"):
            mrhash_depth_scaling(float("inf"))

    def test_missing_pose_modality(self):
        self.f.definition.input_manifest["modalities"] = ["rgb", "depth"]
        self.assertIn("modalities", self.error())

    def test_transform_direction_required(self):
        del self.f.spec["pose"]["transform_direction"]
        self.assertIn("transform_direction", self.error())

    def test_camera_world_direction_rejected(self):
        self.f.spec["pose"]["transform_direction"] = "T_camera_world"
        self.assertIn("normalized to T_world_camera", self.error())

    def test_trajectory_direction_must_match_contract(self):
        data = json.loads(self.f.trajectory.read_text()); data["transform_direction"] = "T_camera_world"; self.f.rewrite_trajectory(data)
        self.assertIn("must match", self.error())

    def test_unregistered_extrinsic_missing(self):
        self.f.spec["registration"] = self.registration(False, None)
        self.assertIn("requires T_depth_rgb", self.error())

    def test_registered_extrinsic_must_be_null(self):
        self.f.spec["registration"]["T_depth_rgb"] = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.assertIn("must be null", self.error())

    def test_extrinsic_non_finite(self):
        self.f.spec["registration"] = self.registration(False, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, float("nan")], [0, 0, 0, 1]])
        self.assertIn("finite 4x4", self.error())

    def test_extrinsic_not_4x4(self):
        self.f.spec["registration"] = self.registration(False, [[1, 0], [0, 1]])
        self.assertIn("4x4", self.error())

    def test_extrinsic_invalid_last_row(self):
        self.f.spec["registration"] = self.registration(False, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 1, 1]])
        self.assertIn("last row", self.error())

    def test_extrinsic_non_rigid_rotation(self):
        self.f.spec["registration"] = self.registration(False, [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        self.assertIn("orthonormal", self.error())

    def test_valid_t_depth_rgb(self):
        self.f.spec["registration"] = self.registration(False, [[0, -1, 0, 0.1], [1, 0, 0, 0.2], [0, 0, 1, 0.3], [0, 0, 0, 1]])
        self.assertEqual(validate_rgbd_dataset(self.f.definition, strict_hashes=True), [])

    def test_unconverted_colmap_rejected(self):
        self.f.spec["pose"].update(source_format="COLMAP_qvec_tvec", converted_from_world_to_camera=False)
        self.assertIn("COLMAP", self.error())

    def test_path_escape(self):
        data = json.loads(self.f.index.read_text()); data["frames"][0]["rgb"]["path"] = "../outside.jpg"; self.f.rewrite_index(data)
        self.assertIn("safe relative", self.error())

    def test_symlink_escape(self):
        outside = Path(self.tmp.name) / "outside.jpg"; Image.new("RGB", (2, 2)).save(outside)
        link = self.f.root / "rgb/linked.jpg"; link.symlink_to(outside)
        data = json.loads(self.f.index.read_text()); data["frames"][0]["rgb"] = {
            "path": "rgb/linked.jpg", "size_bytes": outside.stat().st_size, "sha256": sha(outside)}
        self.f.rewrite_index(data)
        self.assertIn("including symlinks", self.error())

    def test_size_and_sha_mismatch(self):
        data = json.loads(self.f.index.read_text()); data["frames"][0]["rgb"]["size_bytes"] += 1; self.f.rewrite_index(data)
        self.assertIn("size", self.error())
        self.f = RGBDFixture(Path(self.tmp.name) / "dataset2")
        data = json.loads(self.f.index.read_text()); data["frames"][0]["rgb"]["sha256"] = "0" * 64; self.f.rewrite_index(data)
        self.assertIn("SHA-256", self.error())

    def test_invalid_quaternion(self):
        data = json.loads(self.f.trajectory.read_text()); data["poses"][0]["quaternion"] = [0, 0, 0, 0]; self.f.rewrite_trajectory(data)
        self.assertIn("quaternion", self.error())


if __name__ == "__main__":
    unittest.main()
