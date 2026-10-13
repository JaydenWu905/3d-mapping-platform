from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_ROOT / "scripts"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

import glim_pose_adapter as adapter  # noqa: E402
import glim_ros1_bridge as bridge  # noqa: E402
from app.services import glim_config_service as cfg  # noqa: E402
from app.services import pose_timestamp_service as ts  # noqa: E402
from app.services.child_supervisor import ChildSupervisor  # noqa: E402
from app.services.pose_spec import normalize_pose_spec  # noqa: E402
from app.services.surface_input_service import (  # noqa: E402
    SurfaceInputError,
    prepare_mrhash_lidar_input,
)


POSE_SPEC = {
    "backend": "glim",
    "bag_path": "INS/2024-06-04-16-24-55.bag",
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    """A disposable job + workspace that looks like a registered GLIM dataset."""

    def __init__(self, root: Path):
        self.root = root
        self.workspace = root / "autodl-tmp"
        self.job_dir = root / "jobs" / "job-glim"
        self.dump_dir = root / "tmp-dump"
        self._build_workspace()
        self._build_job()

    def _build_workspace(self) -> None:
        config = self.workspace / "INS" / "glim_ins_config"
        config.mkdir(parents=True)
        (config / "config.json").write_text(
            '{\n  /*** Global ***/\n  "global": {"config_ros": "config_ros.json"}\n}\n',
            encoding="utf-8")
        (config / "config_ros.json").write_text(
            '{\n'
            '  "glim_ros": {\n'
            '    // registered topics are overridden by the platform\n'
            '    "points_topic": "/ins/points",\n'
            '    "imu_topic": "/ins/imu",\n'
            '    "acc_scale": 0.0,\n'
            '    "extension_modules": ["libmemory_monitor.so"],\n'
            '  }\n'
            '}\n',
            encoding="utf-8")
        (config / "config_sensors.json").write_text(
            '{\n  "sensors": {\n    "T_lidar_imu": [0, 0, 0, 0, 0, 0, 1],\n'
            '    "perpoint_relative_time": false,\n    "perpoint_time_scale": 1.0,\n  }\n}\n',
            encoding="utf-8")
        rosbags = self.workspace / "envs" / "rosbags" / "bin"
        rosbags.mkdir(parents=True)
        rosbags_python = rosbags / "python"
        rosbags_python.write_text("#!/bin/sh\nexec python3 \"$@\"\n", encoding="utf-8")
        # POSIX needs the interpreter to be executable; the adapter validates the
        # path but the shell payload execs it directly.
        rosbags_python.chmod(0o755)
        (self.workspace / "INS" / "2024-06-04-16-24-55.bag").write_bytes(b"bag-bytes")

    def _build_job(self, pose_overrides: dict | None = None) -> None:
        (self.job_dir / "input").mkdir(parents=True, exist_ok=True)
        job = {
            "job_id": self.job_dir.name,
            "created_at": "2026-10-03T00:00:00",
            "status": "created",
            "dataset": "ins_longcorridor01",
            "backends": {"pose": "glim", "surface": "mrhash_lidar", "distance": "voxel_esdf"},
            "fail_stage": None,
            "preview_job": False,
            "stages": {
                "pose": {"stage": "pose", "backend": "glim", "status": "waiting",
                         "started_at": None, "finished_at": None},
            },
        }
        (self.job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        pose = dict(POSE_SPEC)
        pose.update(pose_overrides or {})
        input_manifest = {
            "schema_version": "0.1",
            "dataset_id": "ins_longcorridor01",
            "modalities": ["lidar", "imu", "rgb", "depth"],
            "pose": pose,
            "runtime": {"glim": {"rosbags_python": "envs/rosbags/bin/python"}},
        }
        (self.job_dir / "input" / "input_manifest.json").write_text(
            json.dumps(input_manifest), encoding="utf-8")
        source_bag = self.job_dir / "input" / "source.bag"
        if source_bag.exists() or source_bag.is_symlink():
            source_bag.unlink()
        try:
            source_bag.symlink_to(self.workspace / "INS" / "2024-06-04-16-24-55.bag")
        except OSError:  # Windows without the symlink privilege
            source_bag.write_bytes((self.workspace / "INS" / "2024-06-04-16-24-55.bag").read_bytes())

    def env(self) -> dict:
        env = dict(os.environ)
        env["GLIM_WORKSPACE"] = str(self.workspace)
        env.pop("GLIM_CONFIG_PATH", None)
        env.pop("GLIM_NODE_COMMAND", None)
        return env

    def install_fake_glim(self) -> tuple[Path, Path]:
        """A stand-in for the ROS2 node: records its pid, then sleeps."""
        pid_file = self.workspace / "fake_glim.pid"
        script = self.workspace / "fake_glim.sh"
        script.write_text(
            f'#!/bin/sh\necho $$ > "{pid_file}"\nexec sleep 300\n', encoding="utf-8")
        script.chmod(0o755)
        setup = self.workspace / "ros_setup.sh"
        setup.write_text("# stand-in for /opt/ros/humble/setup.bash\n", encoding="utf-8")
        return script, pid_file

    def lock_path(self) -> Path:
        return self.workspace / "runtime" / "locks" / "glim.lock"

    @property
    def job_bag(self) -> Path:
        """``input/source.bag`` as materialised by the platform for this job."""
        return self.job_dir / "input" / "source.bag"

    @property
    def resolved_bag(self) -> Path:
        """The bag path the adapter must hand to the bridge.

        The adapter validates the job input link and then streams the *registered*
        bag, so the bridge must receive the resolved path — not a hard-coded
        ``source.bag``.
        """
        return self.job_bag.resolve()

    def make_rosbags_python_record_invocations(self) -> Path:
        """Replace the rosbags interpreter with one that records being invoked."""
        marker = self.workspace / "rosbags_invoked.marker"
        shim = self.workspace / "envs" / "rosbags" / "bin" / "python"
        shim.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec python3 "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        return marker

    def install_failing_glim_node(self) -> Path:
        """A node that starts and then exits non-zero during initialisation.

        Everything else stays valid (a usable ``ros_setup`` stub and an
        executable rosbags interpreter), so the run fails because of the node and
        not because the ROS prerequisites are broken.
        """
        script = self.workspace / "failing_glim.sh"
        script.write_text("#!/bin/sh\necho 'fake glim: initialisation failed' >&2\nexit 7\n",
                          encoding="utf-8")
        script.chmod(0o755)
        setup = self.workspace / "ros_setup.sh"
        if not setup.exists():
            setup.write_text("# stand-in for /opt/ros/humble/setup.bash\n", encoding="utf-8")
        return script

    def run_adapter_inprocess(self, *args: str, dump_dir: Path | None = None,
                              env: dict | None = None,
                              timeout: float = 120) -> subprocess.CompletedProcess:
        """Run the adapter in a subprocess with a redirected shared dump path.

        The redirect uses a tiny shim that imports the adapter module and rebinds
        the module constant, so tests never inspect or quarantine the real
        ``/tmp/dump``.  It is a test harness only — there is deliberately no
        user-facing setting for the GLIM dump location.
        """
        target = dump_dir if dump_dir is not None else self.dump_dir
        shim = (
            "import sys; "
            f"sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
            "import glim_pose_adapter as adapter; "
            f"adapter.GLIM_SHARED_DUMP_DIR = {str(target)!r}; "
            "raise SystemExit(adapter.main(sys.argv[1:]))"
        )
        return subprocess.run(
            [sys.executable, "-c", shim, "--job-dir", str(self.job_dir),
             "--backend", "glim", *args],
            capture_output=True, text=True, env=env or self.env(), timeout=timeout,
        )

    def run_adapter(self, *args: str) -> subprocess.CompletedProcess:
        return self.run_adapter_inprocess(*args)

    @property
    def stage_dir(self) -> Path:
        return self.job_dir / "stage1_pose"

    @property
    def native_dir(self) -> Path:
        return self.stage_dir / "native"


class DryRunTests(unittest.TestCase):
    """docs/glim-integration-acceptance.md §4: testable without GPU/ROS2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(Path(self.tmp.name))

    def test_dry_run_validates_plans_and_materialises_without_executing(self):
        completed = self.fx.run_adapter("--dry-run", "--mode", "demo")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads((self.fx.native_dir / "dry_run_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["mode"], "demo")
        self.assertIn("no GLIM, no bridge and no ROS2 was executed", report["dry_run_note"])

        # Command construction: dataset config drives the GLIM node parameters.
        argv = report["glim_argv"]
        self.assertIn("--ros-args", argv)
        self.assertIn(f"config_path:={self.fx.native_dir / 'config'}", argv)
        self.assertIn("dump_on_unload:=true", argv)
        self.assertTrue(report["glim_shell"].startswith("source "))
        # The real node executable is exec'd directly; no `ros2 run` wrapper.
        self.assertEqual(report["glim_node_command"], adapter.DEFAULT_GLIM_NODE_COMMAND)
        self.assertIn('exec "$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode"',
                      report["glim_shell"])
        self.assertNotIn("ros2 run", report["glim_shell"])
        self.assertEqual(report["run_timeout_sec"], 7200.0)

        # ROS runtime semantics: source -> LD_LIBRARY_PATH override -> unset
        # OMP_NUM_THREADS -> exec, for GLIM and for the bridge.
        self.assertTrue(report["ros_runtime"]["ld_export_after_source"])
        self.assertTrue(report["ros_runtime"]["omp_num_threads_unset_in_shell"])
        self.assertFalse(report["ros_runtime"]["omp_num_threads_present_in_env"])
        for shell in (report["glim_shell"], report["bridge_shell"]):
            source_at = shell.index("source '/opt/ros/humble/setup.bash'")
            export_at = shell.index("export LD_LIBRARY_PATH='/usr/local/lib':${LD_LIBRARY_PATH:-}")
            unset_at = shell.index("unset OMP_NUM_THREADS")
            exec_at = shell.index("exec ")
            self.assertLess(source_at, export_at)
            self.assertLess(export_at, unset_at)
            self.assertLess(unset_at, exec_at)
        # The bridge needs rclpy itself, so it is started through the same shell
        # and execs the rosbags interpreter directly.
        rosbags_python = self.fx.workspace / "envs" / "rosbags" / "bin" / "python"
        self.assertIn(f"exec '{rosbags_python}'", report["bridge_shell"])
        self.assertIn("glim_ros1_bridge.py", report["bridge_shell"])
        self.assertIn("--lidar-topic", report["bridge_shell"])
        self.assertIn("livox_mid360_frame", report["bridge_shell"])
        # The bridge streams the *registered* bag the job input resolves to, not
        # the job-local link name.
        self.assertIn(f"'{self.fx.resolved_bag}'", report["bridge_shell"])
        if self.fx.job_bag.is_symlink():
            self.assertEqual(self.fx.resolved_bag,
                             self.fx.workspace / "INS" / "2024-06-04-16-24-55.bag")

        # Bridge construction: dataset topics/frames + bag index in the job.
        bridge = report["bridge_argv"]
        self.assertIn("/livox_mid360/livox/lidar", bridge)
        self.assertIn("/livox_mid360/livox/imu", bridge)
        self.assertIn("livox_mid360_frame", bridge)
        self.assertIn(str(self.fx.native_dir / "bag_index.tsv"), bridge)
        self.assertIn("--max-lidar-frames", bridge)

        # Dataset semantics were overlaid onto the registered GLIM config.
        applied = {(entry["file"], entry["section"], entry["key"]) for entry in report["config"]["applied"]}
        self.assertIn(("config_ros.json", "glim_ros", "points_topic"), applied)
        self.assertIn(("config_ros.json", "glim_ros", "acc_scale"), applied)
        self.assertIn(("config_sensors.json", "sensors", "T_lidar_imu"), applied)
        self.assertIn(("config_sensors.json", "sensors", "perpoint_time_scale"), applied)
        self.assertEqual(report["config"]["headless_warnings"], [])

        # Paths stay inside the job, and no stage result is claimed.
        self.assertTrue(str(report["planned_native_dir"]).startswith(str(self.fx.job_dir)))
        self.assertFalse((self.fx.stage_dir / "result_manifest.json").exists())
        self.assertFalse((self.fx.stage_dir / "poses.txt").exists())
        self.assertEqual(report["lock"]["state"], "not_acquired_in_dry_run")
        # The dump location is GLIM's own process-global path, not a setting.
        self.assertEqual(report["glim_shared_dump_dir"], str(self.fx.dump_dir))
        self.assertIn("never a setting", report["glim_shared_dump_dir_note"])
        self.assertNotIn("dump_dir", report["runtime"])
        self.assertEqual(report["dump"]["action"], "none")

    def test_dry_run_writes_effective_and_untouched_registered_config(self):
        self.fx.run_adapter("--dry-run")
        effective = json.loads(
            (self.fx.native_dir / "config" / "config_ros.json").read_text(encoding="utf-8"))
        self.assertEqual(effective["glim_ros"]["points_topic"], "/mapping/glim/points")
        self.assertEqual(effective["glim_ros"]["imu_topic"], "/mapping/glim/imu")
        self.assertEqual(effective["glim_ros"]["acc_scale"], 9.80665)
        self.assertEqual(effective["glim_ros"]["lidar_frame_id"], "livox_mid360_frame")
        sensors = json.loads(
            (self.fx.native_dir / "config" / "config_sensors.json").read_text(encoding="utf-8"))
        self.assertEqual(sensors["sensors"]["T_lidar_imu"], POSE_SPEC["T_lidar_imu"])
        self.assertTrue(sensors["sensors"]["perpoint_relative_time"])
        self.assertEqual(sensors["sensors"]["perpoint_time_scale"], 1e-9)
        # The registered (comment-carrying) original is preserved byte for byte.
        registered = self.fx.native_dir / "config_registered" / "config_ros.json"
        self.assertEqual(registered.read_text(encoding="utf-8"),
                         (self.fx.workspace / "INS" / "glim_ins_config" / "config_ros.json")
                         .read_text(encoding="utf-8"))

    def test_dry_run_reports_a_broken_dataset_spec(self):
        self.fx._build_job(pose_overrides={"lidar_topic": None})
        completed = self.fx.run_adapter("--dry-run")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("lidar_topic", completed.stderr)

    def test_dry_run_reports_a_missing_bag(self):
        (self.fx.job_dir / "input" / "source.bag").unlink()
        completed = self.fx.run_adapter("--dry-run")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("bag is missing", completed.stderr)


def native_rows(times: list[float]) -> list[ts.TrajectoryRow]:
    return [ts.TrajectoryRow(t, (float(i), 0.5, 0.0, 0.0, 0.0, 0.0, 1.0))
            for i, t in enumerate(times)]


def wait_for(predicate, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def pid_exists(pid: int) -> bool:
    if os.name != "posix":
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class CancelBehaviourTests(unittest.TestCase):
    """A cancelled run must stop GLIM, reap it and release the lock.

    The orchestration half of this contract is covered portably in
    ``test_child_supervisor``.  This test drives the real adapter process, so it
    needs POSIX signal delivery and a real process group.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(Path(self.tmp.name))

    @unittest.skipUnless(
        os.name == "posix",
        "ENVIRONMENT LIMITATION: the windows sandbox cannot deliver SIGTERM or prove "
        "process-group reaping; production target is Ubuntu/ROS2",
    )
    def test_cancel_terminates_glim_and_releases_the_glim_lock(self):
        script, pid_file = self.fx.install_fake_glim()
        env = self.fx.env()
        env["GLIM_NODE_COMMAND"] = str(script)
        env["GLIM_ROS_SETUP"] = str(self.fx.workspace / "ros_setup.sh")
        shim = (
            "import sys; "
            f"sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
            "import glim_pose_adapter as adapter; "
            f"adapter.GLIM_SHARED_DUMP_DIR = {str(self.fx.dump_dir)!r}; "
            "raise SystemExit(adapter.main(sys.argv[1:]))"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", shim, "--job-dir", str(self.fx.job_dir),
             "--backend", "glim", "--glim-startup-grace-sec", "0.2"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        )
        self.addCleanup(process.kill)
        self.assertTrue(wait_for(pid_file.exists), "fake GLIM should have started")
        glim_pid = int(pid_file.read_text().strip())
        self.assertTrue(wait_for(self.fx.lock_path().exists), "GLIM lock should be held")
        self.assertTrue(pid_exists(glim_pid))

        process.send_signal(signal.SIGTERM)
        self.assertIsNotNone(process.wait(timeout=60))

        self.assertFalse(self.fx.lock_path().exists(), "lock must be released on cancel")
        self.assertTrue(wait_for(lambda: not pid_exists(glim_pid), timeout=15),
                        "GLIM must not survive the cancel")
        progress = json.loads((self.fx.stage_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["status"], "cancelled")
        self.assertFalse((self.fx.stage_dir / "result_manifest.json").exists())


class FailedJobs:
    """Minimal JobService surface used by prepare_mrhash_lidar_input."""

    def __init__(self, root: Path, dataset_id: str, bag: Path, definition):
        self.root = root
        self.dataset_id = dataset_id
        self.bag = bag
        self.definition = definition
        self.datasets = SimpleNamespace(get=lambda _id: self.definition)
        self.job = {"job_id": "job-glim", "dataset": dataset_id,
                    "backends": {"pose": "glim", "surface": "mrhash_lidar"},
                    "stages": {"pose": {"status": "completed"}}}

    def load_job(self, _job_id):
        return self.job

    def job_dir(self, _job_id):
        return self.root

    def stage_dir(self, _job_id, stage):
        return self.root / ("stage1_pose" if stage == "pose" else "stage2_surface")


class CanonicalOutputTests(unittest.TestCase):
    """docs/pose-stage-contract.md §2/§3/§6 + docs/pose-timestamp-contract.md §10/§11."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage_dir = self.root / "stage1_pose"
        self.native_dir = self.stage_dir / "native"
        self.native_dir.mkdir(parents=True)
        self.log = adapter.Logger(self.native_dir / "run.log")
        # The adapter always reads the dataset's normalised pose spec.
        self.spec = normalize_pose_spec(POSE_SPEC)
        self.glim_context = {"mode": "demo", "command": ["ros2", "run", "glim_ros", "glim_rosnode"]}
        # Native trajectory in the physical LiDAR sensor clock.
        self.sensor_times = [100.0 + 0.1 * i for i in range(400)]
        (self.native_dir / "traj_lidar.txt").write_text(
            "".join(f"{t:.9f} {i} 0.5 0 0 0 0 1\n" for i, t in enumerate(self.sensor_times)),
            encoding="utf-8",
        )
        # Bag index: record time is one LiDAR frame later than the sensor time.
        (self.native_dir / "bag_index.tsv").write_text(
            bridge.BAG_INDEX_HEADER
            + "".join(f"{int((t + 0.1) * 1e9)}\t{int(t * 1e9)}\t20160\n" for t in self.sensor_times),
            encoding="utf-8",
        )

    def finalize(self, frames=None, trajectory_rows=None, *, index_missing=False) -> tuple[dict, bool]:
        rows = trajectory_rows or ts.read_pose_trajectory(self.native_dir / "traj_lidar.txt")
        if index_missing:
            frames = None
        elif frames is None:
            frames = ts.read_bag_frame_index(self.native_dir / "bag_index.tsv")
        outcome = ts.associate_to_bag_record_time(
            frames, rows, max_delta_sec=0.05, min_matched_ratio=0.98,
        ) if frames is not None else None
        report = outcome.report if outcome else adapter.unassociable_report(
            "bag_index.tsv is missing: the bridge did not record the bag frame times",
            frames=None, native_count=len(rows), spec=self.spec)
        return adapter.finalize_pose_outputs(
            job={"job_id": "job-glim", "dataset": "ins_longcorridor01"},
            spec=self.spec, stage_dir=self.stage_dir, native_dir=self.native_dir,
            native_rows=rows, trajectory_filename="traj_lidar.txt",
            outcome=outcome, report=report, glim_context=self.glim_context,
            runtime_sec=12.5, log=self.log,
        )

    def fake_jobs(self, pose_lookup_key="ROS bag record timestamp") -> FailedJobs:
        bag = self.root / "source.bag"
        bag.write_bytes(b"bag-bytes")
        definition = SimpleNamespace(
            id="ins_longcorridor01", source_dir=self.root,
            source_file=lambda key: bag,
            integrity={"bag_size_bytes": bag.stat().st_size, "bag_sha256": sha256(bag)},
            input_manifest={"bag_message_count": len(self.sensor_times)},
            surface={"backend": "mrhash_lidar", "topic": "/livox_mid360/livox/lidar",
                     **({"pose_lookup_key": pose_lookup_key} if pose_lookup_key else {})},
        )
        return FailedJobs(self.root, "ins_longcorridor01", bag, definition)

    def test_accepted_association_produces_canonical_pose_and_passes_the_gate(self):
        manifest, accepted = self.finalize()
        self.assertTrue(accepted)
        # Canonical contract: 8 columns, keyed by bag record time.
        rows = ts.read_pose_trajectory(self.stage_dir / "poses.txt")
        self.assertEqual(len(rows), len(self.sensor_times))
        self.assertAlmostEqual(rows[0].timestamp, self.sensor_times[0] + 0.1, places=6)
        self.assertEqual(manifest["stage"], "pose")
        self.assertEqual(manifest["backend"], "glim")
        self.assertEqual(manifest["status"], "completed")
        roles = {(a["artifact_id"], a["role"]) for a in manifest["artifacts"]}
        self.assertIn(("registered_trajectory", "trajectory"), roles)
        self.assertIn(("trajectory_model", "preview"), roles)
        self.assertIn(("pose_timestamp_association", "data"), roles)
        self.assertIn(("glim_native_trajectory", "data"), roles)
        details = manifest["backend_details"]
        self.assertEqual(details["pose_semantics"], "T_world_lidar")
        self.assertEqual(details["translation_unit"], "meter")
        self.assertEqual(details["quaternion_order"], "qx qy qz qw")
        self.assertEqual(details["timestamp_basis"]["lookup_key"], "ROS bag record timestamp")
        self.assertEqual(details["timestamp_basis"]["clock"], "rosbag")
        self.assertTrue(details["surface_handoff"]["compatible"])

        association = json.loads((self.native_dir / "association.json").read_text(encoding="utf-8"))
        for key in ("method", "native_lookup_key", "output_lookup_key", "bag_frame_count",
                    "native_pose_count", "matched_count", "skipped_count", "matched_ratio",
                    "mean_delta_sec", "max_delta_sec_observed", "head_unmatched_count",
                    "tail_unmatched_count", "duplicate_pose_reuse_count",
                    "non_monotonic_match_count"):
            self.assertIn(key, association)

        # The real Pose -> Surface preparation accepts it and records the gate.
        jobs = self.fake_jobs()
        surface_manifest = prepare_mrhash_lidar_input("job-glim", jobs)
        self.assertEqual(surface_manifest["timestamp_gate"]["pose_lookup_key"],
                         "ROS bag record timestamp")
        self.assertEqual(surface_manifest["timestamp_gate"]["required_pose_lookup_key"],
                         "ROS bag record timestamp")

    def test_rejected_association_keeps_native_poses_and_blocks_surface(self):
        # Sparse native poses: most bag frames fall outside the tolerance.
        sparse = native_rows([100.0 + 0.5 * i for i in range(60)])
        manifest, accepted = self.finalize(trajectory_rows=sparse)
        self.assertFalse(accepted)
        details = manifest["backend_details"]
        self.assertEqual(details["timestamp_basis"]["lookup_key"],
                         "physical LiDAR sensor/header timestamp")
        self.assertEqual(details["timestamp_basis"]["clock"], "lidar_sensor")
        self.assertFalse(details["surface_handoff"]["compatible"])
        self.assertIn("timestamp normalization failed", details["surface_handoff"]["reason"])
        # The valid native result is preserved, not deleted.
        self.assertTrue((self.stage_dir / "poses.txt").is_file())
        self.assertTrue((self.native_dir / "traj_lidar.txt").is_file())
        self.assertTrue((self.stage_dir / "trajectory_preview.json").is_file())
        rows = ts.read_pose_trajectory(self.stage_dir / "poses.txt")
        self.assertEqual(rows[0].timestamp, sparse[0].timestamp)

        jobs = self.fake_jobs()
        with self.assertRaisesRegex(SurfaceInputError, "incompatible Surface handoff"):
            prepare_mrhash_lidar_input("job-glim", jobs)

    def test_surface_gate_also_blocks_a_mismatched_required_lookup_key(self):
        self.finalize()
        jobs = self.fake_jobs(pose_lookup_key="some other clock")
        with self.assertRaisesRegex(SurfaceInputError, "does not match the Surface required"):
            prepare_mrhash_lidar_input("job-glim", jobs)

    def test_missing_bag_index_blocks_the_handoff_without_failing_the_pose(self):
        (self.native_dir / "bag_index.tsv").unlink()
        manifest, accepted = self.finalize(index_missing=True)
        self.assertFalse(accepted)
        self.assertEqual(manifest["status"], "completed")
        self.assertFalse(manifest["backend_details"]["surface_handoff"]["compatible"])

    def test_on_failure_fail_stage_is_honoured_by_the_adapter_contract(self):
        # `fail_stage` is enforced in main(); the helper still reports honestly.
        spec = dict(self.spec)
        spec["timestamp"] = dict(self.spec["timestamp"], on_failure="fail_stage")
        self.spec = spec
        manifest, accepted = self.finalize(trajectory_rows=native_rows([100.0 + 0.5 * i for i in range(60)]))
        self.assertFalse(accepted)
        self.assertFalse(manifest["backend_details"]["surface_handoff"]["compatible"])


class LocalRunStateTests(unittest.TestCase):
    """A retry must never reuse the previous attempt's Pose artifacts."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage_dir = self.root / "jobs" / "job-a" / "stage1_pose"
        self.other_stage = self.root / "jobs" / "job-b" / "stage1_pose"

    def write_stale(self, stage: Path) -> None:
        (stage / "native").mkdir(parents=True)
        (stage / "dump").mkdir(parents=True)
        (stage / "native" / "traj_lidar.txt").write_text("1 0 0 0 0 0 0 1\n", encoding="utf-8")
        (stage / "native" / "bag_index.tsv").write_text("1\t1\t1\n", encoding="utf-8")
        (stage / "native" / "association.json").write_text("{}", encoding="utf-8")
        (stage / "dump" / "traj_lidar.txt").write_text("stale\n", encoding="utf-8")
        (stage / "poses.txt").write_text("1 0 0 0 0 0 0 1\n", encoding="utf-8")
        (stage / "trajectory_preview.json").write_text("{}", encoding="utf-8")
        (stage / "result_manifest.json").write_text("{}", encoding="utf-8")
        (stage / "run.log").write_text("platform log must survive\n", encoding="utf-8")

    def test_clean_local_run_state_removes_only_this_stage(self):
        self.write_stale(self.stage_dir)
        self.write_stale(self.other_stage)
        removed = adapter.clean_local_run_state(self.stage_dir)
        self.assertEqual(sorted(removed),
                         ["dump", "native", "poses.txt", "result_manifest.json",
                          "trajectory_preview.json"])
        for name in ("native", "dump", "poses.txt", "trajectory_preview.json",
                     "result_manifest.json"):
            self.assertFalse((self.stage_dir / name).exists(), name)
        # The platform's stage log is written by the runner, not by us.
        self.assertTrue((self.stage_dir / "run.log").is_file())
        # Another job's stage directory is untouched.
        self.assertTrue((self.other_stage / "native" / "traj_lidar.txt").is_file())
        self.assertTrue((self.other_stage / "poses.txt").is_file())

    def test_clean_local_run_state_is_idempotent(self):
        self.write_stale(self.stage_dir)
        adapter.clean_local_run_state(self.stage_dir)
        self.assertEqual(adapter.clean_local_run_state(self.stage_dir), [])


class RetryStaleArtifactTests(unittest.TestCase):
    """Adapter-level proof that stale artifacts cannot be mistaken for a result."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fx = Fixture(self.root)

    def seed_stale_artifacts(self) -> None:
        (self.fx.native_dir / "dump").mkdir(parents=True, exist_ok=True)
        (self.fx.stage_dir / "dump").mkdir(parents=True, exist_ok=True)
        stale_poses = "1.0 0 0 0 0 0 0 1\n2.0 1 0 0 0 0 0 1\n"
        (self.fx.native_dir / "traj_lidar.txt").write_text(stale_poses, encoding="utf-8")
        (self.fx.native_dir / "bag_index.tsv").write_text(
            "1000000000\t1000000000\t20160\n", encoding="utf-8")
        (self.fx.native_dir / "association.json").write_text(
            '{"accepted": true, "matched_ratio": 1.0}', encoding="utf-8")
        (self.fx.stage_dir / "dump" / "traj_lidar.txt").write_text(stale_poses, encoding="utf-8")
        (self.fx.stage_dir / "poses.txt").write_text(stale_poses, encoding="utf-8")
        (self.fx.stage_dir / "trajectory_preview.json").write_text("{}", encoding="utf-8")
        (self.fx.native_dir / "run.log").write_text("stale\n", encoding="utf-8")

    def test_retry_with_a_failing_node_does_not_reuse_stale_artifacts(self):
        self.seed_stale_artifacts()
        # Only the GLIM node fails; the ROS setup and the rosbags interpreter stay
        # valid, so the failure cannot be blamed on a broken prerequisite.
        node = self.fx.install_failing_glim_node()
        bridge_marker = self.fx.make_rosbags_python_record_invocations()
        env = self.fx.env()
        env["GLIM_NODE_COMMAND"] = str(node)
        env["GLIM_ROS_SETUP"] = str(self.fx.workspace / "ros_setup.sh")
        completed = self.fx.run_adapter_inprocess("--glim-startup-grace-sec", "0.2", env=env)
        # The run failed (behaviour, not message text).
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertNotEqual(completed.returncode, adapter.TIMEOUT_EXIT_CODE)
        # It failed because of the node: the bridge was never invoked.
        self.assertFalse(bridge_marker.exists(),
                         "the failing node must be detected before the bridge starts")
        # No result is claimed, and the stale inputs are gone.
        self.assertFalse((self.fx.stage_dir / "result_manifest.json").exists())
        self.assertFalse((self.fx.native_dir / "traj_lidar.txt").exists())
        self.assertFalse((self.fx.native_dir / "bag_index.tsv").exists())
        self.assertFalse((self.fx.native_dir / "association.json").exists())
        self.assertFalse((self.fx.stage_dir / "dump").exists())
        self.assertFalse((self.fx.stage_dir / "poses.txt").exists())
        self.assertFalse((self.fx.stage_dir / "trajectory_preview.json").exists())
        progress = json.loads((self.fx.stage_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["status"], "failed")
        self.assertTrue(progress["message"], "the failure reason must be recorded")
        # The failure is logged, and the stale trajectory was never promoted to a
        # canonical Pose result.
        self.assertTrue((self.fx.native_dir / "run.log").is_file())
        # The lock is released even on this failure path.
        self.assertFalse(self.fx.lock_path().exists())


class TimeoutBehaviourTests(unittest.TestCase):
    """`pose.run_timeout_sec` must reuse the cancel path, not a second one."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fx = Fixture(self.root)

    def test_run_timeout_terminates_children_releases_lock_and_marks_failed(self):
        script, pid_file = self.fx.install_fake_glim()
        # The timeout fires inside the GLIM startup wait, so the test does not
        # depend on being able to launch the ROS2 bridge on the dev machine.
        self.fx._build_job(pose_overrides={"run_timeout_sec": 0.1})
        env = self.fx.env()
        env["GLIM_NODE_COMMAND"] = str(script)
        env["GLIM_ROS_SETUP"] = str(self.fx.workspace / "ros_setup.sh")
        completed = self.fx.run_adapter_inprocess("--glim-startup-grace-sec", "30",
                                                 env=env, timeout=120)
        # The GLIM node never exits and never dumps; the run timeout must win.
        self.assertEqual(completed.returncode, adapter.TIMEOUT_EXIT_CODE,
                         completed.stdout + completed.stderr)
        self.assertIn("timeout", (completed.stdout + completed.stderr).lower())
        progress = json.loads((self.fx.stage_dir / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["status"], "failed")
        self.assertIn("timeout", progress["message"].lower())
        self.assertFalse((self.fx.stage_dir / "result_manifest.json").exists())
        self.assertFalse(self.fx.lock_path().exists(), "timeout must release the GLIM lock")
        if os.name == "posix" and pid_file.is_file():
            # The fake node records its pid; timeout must have reaped it.
            self.assertFalse(pid_exists(int(pid_file.read_text().strip())),
                             "the timed-out GLIM child must not survive")

    def test_timeout_is_configurable_and_defaults_to_two_hours(self):
        spec = normalize_pose_spec(POSE_SPEC)
        self.assertEqual(spec["run_timeout_sec"], 7200.0)
        self.assertEqual(normalize_pose_spec({**POSE_SPEC, "run_timeout_sec": 1200})["run_timeout_sec"],
                         1200.0)
        from app.services.pose_spec import PoseSpecError
        with self.assertRaisesRegex(PoseSpecError, "run_timeout_sec"):
            normalize_pose_spec({**POSE_SPEC, "run_timeout_sec": -1})


class GracefulShutdownTests(unittest.TestCase):
    """The graceful dump signal must target the real node, not a wrapper."""

    def test_default_node_command_execs_the_real_executable(self):
        shell = cfg.build_glim_shell(
            "/opt/ros/humble/setup.bash",
            "/usr/local/lib",
            adapter.DEFAULT_GLIM_NODE_COMMAND,
            # A separator-free relative path keeps the expected string identical
            # on POSIX and Windows.
            cfg.build_ros_node_args(Path("config")),
            quote_node_command=True,
        )
        self.assertIn('exec "$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode"', shell)
        self.assertNotIn("ros2 run", shell)
        self.assertIn("dump_on_unload:=true", shell)
        self.assertEqual(
            shell,
            "source '/opt/ros/humble/setup.bash'"
            " && export LD_LIBRARY_PATH='/usr/local/lib':${LD_LIBRARY_PATH:-}"
            " && unset OMP_NUM_THREADS"
            " && exec \"$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode\""
            " '--ros-args' '-p' 'config_path:=config' '-p' 'dump_on_unload:=true'",
        )

    def test_bridge_shell_shares_the_same_ros_runtime_semantics(self):
        shell = cfg.build_bridge_shell(
            "/opt/ros/humble/setup.bash", "/usr/local/lib",
            ["/envs/rosbags/bin/python", "/repo/glim_ros1_bridge.py", "--bag", "/bag.bag"],
        )
        self.assertEqual(
            shell,
            "source '/opt/ros/humble/setup.bash'"
            " && export LD_LIBRARY_PATH='/usr/local/lib':${LD_LIBRARY_PATH:-}"
            " && unset OMP_NUM_THREADS"
            " && exec '/envs/rosbags/bin/python' '/repo/glim_ros1_bridge.py'"
            " '--bag' '/bag.bag'",
        )

    def test_process_env_does_not_prepend_ld_library_path(self):
        # Prepending it to the inherited environment would be undone by
        # setup.bash and could re-select ROS's GTSAM 4.2 again.
        env = cfg.build_ros_env({"LD_LIBRARY_PATH": "/ros/lib", "OMP_NUM_THREADS": "8",
                                 "PATH": "/usr/bin"})
        self.assertEqual(env["LD_LIBRARY_PATH"], "/ros/lib")
        self.assertNotIn("OMP_NUM_THREADS", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_sigint_is_sent_to_the_registered_glim_child(self):
        class FakeNode:
            pid = 4242

            def __init__(self) -> None:
                self.signals: list[int] = []
                self.returncode = None

            def poll(self):
                return self.returncode

            def send_signal(self, signum: int) -> None:
                self.signals.append(signum)

            def terminate(self) -> None:  # pragma: no cover - non-POSIX path
                self.returncode = -15

            def kill(self) -> None:  # pragma: no cover - non-POSIX path
                self.returncode = -9

            def wait(self, timeout=None):  # pragma: no cover - non-POSIX path
                return self.returncode

        node = FakeNode()
        supervisor = ChildSupervisor()
        supervisor.register("glim", node)
        outcome = adapter.request_glim_shutdown(supervisor, grace=1.0)
        self.assertEqual(outcome["target"], "glim_rosnode")
        self.assertEqual(outcome["pid"], 4242)
        if os.name == "posix":
            self.assertEqual(outcome["signal"], "SIGINT")
            self.assertEqual(node.signals, [signal.SIGINT])
        else:  # pragma: no cover - GLIM only runs on Linux
            self.assertEqual(outcome["signal"], "terminate")
            self.assertIsNotNone(node.poll())

    def test_shutdown_is_a_noop_for_an_already_finished_node(self):
        class Finished:
            pid = 1

            def poll(self):
                return 0

        supervisor = ChildSupervisor()
        supervisor.register("glim", Finished())
        self.assertEqual(adapter.request_glim_shutdown(supervisor, grace=1.0)["signal"], "none")


if __name__ == "__main__":
    unittest.main()
