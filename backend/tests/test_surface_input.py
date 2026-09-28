from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.surface_input_service import SurfaceInputError, prepare_mrhash_lidar_input, validate_surface_input

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

class Jobs:
    def __init__(self, root: Path):
        self.root = root
        self.job = {"job_id": "j", "dataset": "ox", "backends": {"pose": "registered_pose_import", "surface": "mrhash_lidar"},
                    "stages": {"pose": {"status": "completed"}}}
        source = root / "dataset"; source.mkdir()
        self.bag = source / "source.bag"; self.bag.write_bytes(b"bag")
        self.definition = SimpleNamespace(id="ox", source_dir=source,
            source_file=lambda key: self.bag, integrity={"bag_size_bytes": 3, "bag_sha256": digest(self.bag)},
            input_manifest={"bag_message_count": 3123}, surface={"topic": "/lidar"})
        self.datasets = SimpleNamespace(get=lambda _id: self.definition)
        pose = self.stage_dir("j", "pose"); pose.mkdir(parents=True)
        trajectory = pose / "poses.txt"
        trajectory.write_text("1 0 0 0 0 0 0 1\n2 1 0 0 0 0 0 1\n")
        self.manifest = {"status": "completed", "backend": "registered_pose_import", "artifacts": [{
            "artifact_id": "registered_trajectory", "role": "trajectory", "path": "poses.txt",
            "size_bytes": trajectory.stat().st_size, "sha256": digest(trajectory)}], "backend_details": {
            "timestamp_basis": {"lookup_key": "record"}, "pose_semantics": "T_world_lidar", "translation_unit": "meter",
            "quaternion_order": "qx qy qz qw", "run_id": "r", "result_origin": "registered"}}
        (pose / "result_manifest.json").write_text(json.dumps(self.manifest))
    def load_job(self, _id): return self.job
    def job_dir(self, _id): return self.root / "j"
    def stage_dir(self, _id, stage): return self.root / "j" / ("stage1_pose" if stage == "pose" else "stage2_surface")

class SurfaceInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.jobs = Jobs(Path(self.tmp.name))
    def write_pose(self):
        (self.jobs.stage_dir("j", "pose") / "result_manifest.json").write_text(json.dumps(self.jobs.manifest))
    def test_valid_warning_idempotent_and_launch_validation(self):
        first = prepare_mrhash_lidar_input("j", self.jobs)
        second = prepare_mrhash_lidar_input("j", self.jobs)
        self.assertEqual(first["matching"]["pose_count"], 2)
        self.assertEqual(first["matching"]["bag_message_count"], 3123)
        self.assertEqual(first["compatibility"]["warnings"][0]["code"], "FRAME_COUNT_MISMATCH")
        self.assertEqual(first, second)
        validate_surface_input(self.jobs.job_dir("j"))
    def test_missing_artifact(self):
        self.jobs.manifest["artifacts"] = []; self.write_pose()
        with self.assertRaisesRegex(SurfaceInputError, "required Pose artifact"): prepare_mrhash_lidar_input("j", self.jobs)
    def test_bad_sha(self):
        self.jobs.manifest["artifacts"][0]["sha256"] = "0" * 64; self.write_pose()
        with self.assertRaisesRegex(SurfaceInputError, "SHA-256"): prepare_mrhash_lidar_input("j", self.jobs)
    def test_path_escape(self):
        self.jobs.manifest["artifacts"][0]["path"] = "../poses.txt"; self.write_pose()
        with self.assertRaisesRegex(SurfaceInputError, "safe relative"): prepare_mrhash_lidar_input("j", self.jobs)
    def test_missing_semantics(self):
        del self.jobs.manifest["backend_details"]["timestamp_basis"]; self.write_pose()
        with self.assertRaisesRegex(SurfaceInputError, "timestamp_basis"): prepare_mrhash_lidar_input("j", self.jobs)

if __name__ == "__main__": unittest.main()
