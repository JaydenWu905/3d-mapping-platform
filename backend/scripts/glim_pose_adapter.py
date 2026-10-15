#!/usr/bin/env python3
"""Real GLIM Pose adapter for server-registered ROS1 Livox datasets.

Pipeline (docs/pose-stage-contract.md, docs/pose-timestamp-contract.md,
docs/ins-glim-dataset-profile.md):

    job input bag (dataset registry)
        -> materialise GLIM config from the dataset's sensor parameters
        -> ROS2 GLIM node (dump_on_unload, headless, global lock around /tmp/dump)
        -> glim_ros1_bridge.py streams LiDAR + IMU and writes bag_index.tsv
        -> native/traj_lidar.txt                    (native sensor clock)
        -> explicit timestamp association to bag record time
        -> canonical stage1_pose/poses.txt + trajectory_preview.json
        -> stage1_pose/result_manifest.json         (+ surface_handoff)

The adapter is dataset agnostic: every topic, frame id, sensor scaling,
extrinsic and path comes from the dataset registry / job input manifest.
``--dry-run`` performs the whole validation and planning step (config
materialisation, command and environment construction, dump/lock inspection)
without launching GLIM, so it is usable on a machine without ROS2 or a GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.models.manifest import build_manifest  # noqa: E402
from app.models.progress import atomic_write_json, read_json  # noqa: E402
from app.services import glim_config_service as cfg  # noqa: E402
from app.services import pose_timestamp_service as ts  # noqa: E402
from app.services.child_supervisor import (  # noqa: E402
    ChildSupervisor,
    RunCancelled,
    RunTimedOut,
)
from app.services.glim_lock import (  # noqa: E402
    GlimDumpError,
    GlimExecutionLock,
    GlimLockError,
    inspect_dump_dir,
)
from app.services.pose_spec import (  # noqa: E402
    DEFAULT_GLIM_NODE_COMMAND,
    DEFAULT_RUN_TIMEOUT_SEC,
    GLIM_SHARED_DUMP_DIR,
    PoseSpecError,
    load_pose_spec,
    load_runtime_block,
    resolve_glim_runtime,
    resolve_workspace,
    resolve_workspace_path,
)
from app.services.process_tree import (  # noqa: E402
    child_popen_kwargs,
    install_termination_handler,
    terminate_tree,
)

STAGE = "pose"
BACKEND = "glim"
GLIM_STARTUP_GRACE_SEC = 3.0
GLIM_EXIT_GRACE_SEC = 10.0
NODE_PROBE_TIMEOUT_SEC = 30.0
TIMEOUT_EXIT_CODE = 124

#: Files/directories that belong to one Pose run of one job.  They are removed
#: before a run starts (after the GLIM lock is held) so a retry can never pick up
#: a previous attempt's trajectory, index or association report.
LOCAL_RUN_STATE = ("native", "dump", "poses.txt", "trajectory_preview.json",
                   "result_manifest.json")


class GlimPoseError(RuntimeError):
    """Unrecoverable adapter failure (Pose stage must fail)."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Logger:
    """Write the adapter's log to stdout (platform run.log) and native/run.log."""

    def __init__(self, path: Path | None):
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def __call__(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        if self.path is not None:
            # The native directory is cleared at the start of a run (stale-state
            # cleanup), so the logger must not assume it still exists.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")


class Progress:
    def __init__(self, path: Path):
        self.path = path
        self.started = time.monotonic()

    def write(self, phase: str, message: str, *, percent: float = 0.0,
              current: float = 0, total: float = 0, unit: str = "",
              status: str = "running") -> None:
        atomic_write_json(self.path, {
            "stage": STAGE, "backend": BACKEND, "status": status, "phase": phase,
            "progress": round(float(percent), 2), "current": current, "total": total,
            "unit": unit, "message": message,
            "elapsed_sec": round(time.monotonic() - self.started, 1),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--backend", default=BACKEND)
    parser.add_argument("--mode", choices=("demo", "full"), default="full")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and plan without launching GLIM or the bridge")
    parser.add_argument("--glim-startup-grace-sec", type=float, default=GLIM_STARTUP_GRACE_SEC)
    return parser.parse_args(argv)


def load_job_inputs(job_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return ``(job, pose_spec, runtime_block)`` for a job directory."""
    job = read_json(job_dir / "job.json", None)
    if not isinstance(job, dict):
        raise GlimPoseError("job.json is missing")
    manifest = read_json(job_dir / "input" / "input_manifest.json", None)
    if not isinstance(manifest, dict):
        raise GlimPoseError("input/input_manifest.json is missing")
    try:
        spec = load_pose_spec(manifest)
        runtime_block = load_runtime_block(manifest, spec["backend"])
    except PoseSpecError as exc:
        raise GlimPoseError(str(exc)) from exc
    if spec["backend"] != BACKEND:
        raise GlimPoseError(
            f"this adapter runs the '{BACKEND}' Pose backend, but the dataset declares "
            f"'{spec['backend']}'"
        )
    return job, spec, runtime_block


def resolve_bag(job_dir: Path, spec: dict[str, Any], workspace: Path) -> tuple[Path, dict[str, Any]]:
    """The registry bag, exposed to the job as ``input/source.bag``.

    JobService links ``input/source.bag`` to the bag registered for the dataset.
    ``pose.bag_path`` is an optional explicit declaration; when present it must
    identify the same bag, which is checked through the symlink target, or by
    size when the job tree was materialised without symlinks.  The authoritative
    content check remains the registry SHA-256 verified at the Surface boundary.
    """
    bag = job_dir / "input" / "source.bag"
    resolved = bag.resolve()
    if not bag.is_file():
        raise GlimPoseError(f"job input bag is missing: {bag}")
    identity: dict[str, Any] = {
        "job_bag": str(bag), "resolved_job_bag": str(resolved),
        "declared_bag_path": spec.get("bag_path"), "match": "job_input_only",
    }
    declared = spec.get("bag_path")
    if not declared:
        return resolved, identity
    declared_path = resolve_workspace_path(declared, workspace=workspace, label="pose.bag_path")
    if not declared_path.is_file():
        raise GlimPoseError(f"pose.bag_path is not a file: {declared_path}")
    if bag.is_symlink():
        if declared_path != resolved:
            raise GlimPoseError(
                "pose.bag_path does not point at the bag registered for this job "
                f"(declared {declared_path}, job bag links to {resolved})"
            )
        identity["match"] = "symlink_target"
    elif declared_path.stat().st_size == bag.stat().st_size:
        identity["match"] = "size"
    else:
        raise GlimPoseError(
            "pose.bag_path does not match the bag registered for this job "
            f"(declared {declared_path}, job bag {bag})"
        )
    return resolved, identity


def build_plan(
    job_dir: Path,
    job: dict[str, Any],
    spec: dict[str, Any],
    mode: str,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve every path, argument list and environment for one GLIM run."""
    workspace = resolve_workspace(PROJECT_ROOT, env)
    runtime = resolve_glim_runtime(spec, workspace=workspace, env=env)
    stage_dir = job_dir / "stage1_pose"
    native_dir = stage_dir / "native"
    bag, bag_identity = resolve_bag(job_dir, spec, workspace)

    points_topic = spec.get("internal_points_topic", "/mapping/glim/points")
    imu_topic = spec.get("internal_imu_topic", "/mapping/glim/imu")
    overrides = cfg.merge_overrides(
        cfg.build_overrides(spec, points_topic=points_topic, imu_topic=imu_topic),
        runtime.config_overrides,
    )
    node_args = cfg.build_ros_node_args(
        native_dir / "config", node_params=runtime.node_params
    )
    node_command = runtime.node_command
    glim_argv = cfg.build_node_argv(node_command, node_args)
    glim_shell = cfg.build_glim_shell(
        runtime.ros_setup, runtime.ld_library_path, node_command, node_args,
        # The default template and a plain executable path are quoted (protects
        # against word splitting); an operator's multi-word command stays verbatim.
        quote_node_command=(node_command == DEFAULT_GLIM_NODE_COMMAND
                            or " " not in node_command.strip()),
    )
    ros_env = cfg.build_ros_env(env if env is not None else os.environ)

    demo = spec.get("demo") or {}
    if mode == "demo":
        max_frames = int(demo.get("max_lidar_frames", 0)) or None
        max_duration = float(demo.get("max_duration_sec", 0.0)) or None
    else:
        max_frames = None
        max_duration = None

    bridge_argv = cfg.build_bridge_argv(
        runtime.rosbags_python,
        Path(__file__).with_name("glim_ros1_bridge.py"),
        bag=bag,
        lidar_topic=spec["lidar_topic"],
        imu_topic=spec["imu_topic"],
        points_out=points_topic,
        imu_out=imu_topic,
        lidar_frame=spec["lidar_frame_id"],
        imu_frame=spec["imu_frame_id"],
        bag_index=native_dir / "bag_index.tsv",
        playback_rate=runtime.playback_rate,
        max_lidar_frames=max_frames,
        max_duration_sec=max_duration,
    )
    # The bridge imports rclpy/sensor_msgs itself, so it runs through the same
    # ROS runtime shell as GLIM (source first, then LD_LIBRARY_PATH override).
    bridge_shell = cfg.build_bridge_shell(
        runtime.ros_setup, runtime.ld_library_path, bridge_argv
    )
    job_input_manifest = read_json(job_dir / "input" / "input_manifest.json", {}) or {}
    expected = job_input_manifest.get("bag_message_count")
    if isinstance(expected, int) and expected > 0:
        bridge_argv.extend(["--expected-lidar-frames", str(expected)])

    return {
        "job": job,
        "job_dir": job_dir,
        "stage_dir": stage_dir,
        "native_dir": native_dir,
        "bag": bag,
        "bag_identity": bag_identity,
        "spec": spec,
        "runtime": runtime,
        "overrides": overrides,
        "points_topic": points_topic,
        "imu_topic": imu_topic,
        "glim_argv": glim_argv,
        "glim_shell": glim_shell,
        "glim_node_args": node_args,
        "node_command": node_command,
        "is_default_node_command": node_command == DEFAULT_GLIM_NODE_COMMAND,
        "ros_env": ros_env,
        "bridge_argv": bridge_argv,
        "bridge_shell": bridge_shell,
        "mode": mode,
        "run_timeout_sec": float(spec.get("run_timeout_sec", DEFAULT_RUN_TIMEOUT_SEC)),
        "expected_lidar_frames": expected if isinstance(expected, int) else None,
    }


def discover_dump_dir(candidates: Iterable[Path], trajectory_filename: str) -> Path | None:
    """First candidate directory that already contains the native trajectory."""
    for candidate in candidates:
        if candidate.is_dir() and (candidate / trajectory_filename).is_file():
            return candidate
    return None


def clean_local_run_state(stage_dir: Path) -> list[str]:
    """Remove this job's own leftovers from a previous Pose attempt.

    Scoped strictly to ``stage_dir`` (one job, one stage): a retry must never be
    able to reuse an earlier ``traj_lidar.txt``, ``bag_index.tsv``,
    ``association.json`` or canonical preview.  Nothing outside this stage
    directory is touched — in particular the shared GLIM dump path is handled
    separately, and only after the global GLIM lock has been acquired.
    """
    removed: list[str] = []
    stage_dir = stage_dir.resolve()
    for name in LOCAL_RUN_STATE:
        target = stage_dir / name
        if target.is_symlink() or target.is_file():
            target.unlink()
            removed.append(name)
        elif target.is_dir():
            shutil.rmtree(target)
            removed.append(name)
    return removed


def resolve_glim_node(runtime, *, env: dict[str, str]) -> dict[str, Any]:
    """Resolve the real ``glim_rosnode`` path so a wrong environment fails early.

    Only used when the default node command is in effect: an operator-provided
    ``runtime.glim.node_command`` is authoritative and is not second-guessed.
    """
    info: dict[str, Any] = {
        "node_command": runtime.node_command,
        "default_command": runtime.node_command == DEFAULT_GLIM_NODE_COMMAND,
        "probe": cfg.build_prefix_probe_shell(runtime.ros_setup, runtime.ld_library_path),
        "prefix": None,
        "node_path": None,
        "resolved": False,
        "error": None,
    }
    try:
        completed = subprocess.run(
            ["bash", "-lc", info["probe"]], env=env,
            capture_output=True, text=True, timeout=NODE_PROBE_TIMEOUT_SEC, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        info["error"] = f"could not run the ROS2 prefix probe: {exc}"
        return info
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        info["error"] = (
            "ros2 pkg prefix glim_ros failed with code "
            f"{completed.returncode}: {detail[-1] if detail else 'no output'}"
        )
        return info
    prefix = (completed.stdout or "").strip().splitlines()
    if not prefix:
        info["error"] = "ros2 pkg prefix glim_ros produced no output"
        return info
    info["prefix"] = prefix[-1]
    node_path = Path(prefix[-1]) / "lib" / "glim_ros" / "glim_rosnode"
    info["node_path"] = str(node_path)
    if not node_path.is_file():
        info["error"] = f"GLIM node executable not found: {node_path}"
        return info
    info["resolved"] = True
    return info


def request_glim_shutdown(supervisor: ChildSupervisor, *, grace: float) -> dict[str, Any]:
    """Ask the GLIM node to unload gracefully so it dumps its result.

    The node is the adapter's direct child (see ``build_glim_shell``: the shell
    resolves the executable and ``exec``s it), so SIGINT goes straight to
    ``glim_rosnode`` — the signal ``dump_on_unload`` listens for.  No ``ros2 run``
    wrapper is involved, so no signal forwarding is assumed.
    """
    glim = supervisor.child("glim")
    outcome = {"signal": None, "target": "glim_rosnode", "pid": getattr(glim, "pid", None)}
    if glim is None or glim.poll() is not None:
        outcome["signal"] = "none"
        return outcome
    if os.name == "posix":
        outcome["signal"] = "SIGINT"
        glim.send_signal(signal.SIGINT)
    else:  # pragma: no cover - GLIM only runs on Linux
        outcome["signal"] = "terminate"
        outcome["note"] = "non-POSIX host: graceful dump_on_unload is not available"
        terminate_tree(glim, grace=grace)
    return outcome


def collect_native_outputs(dump_dir: Path, native_dir: Path, trajectory_filename: str) -> dict[str, Any]:
    """Move the shared dump into the job and expose the native trajectory."""
    native_dir.mkdir(parents=True, exist_ok=True)
    target = native_dir / "dump"
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(dump_dir), str(target))
    trajectory = target / trajectory_filename
    if not trajectory.is_file():
        raise GlimPoseError(f"GLIM dump has no {trajectory_filename}: {target}")
    canonical_native = native_dir / trajectory_filename
    shutil.copyfile(trajectory, canonical_native)
    return {
        "dump_dir_moved_to": str(target),
        "native_trajectory": str(canonical_native),
        "dump_trajectory": str(trajectory),
        "files": sorted(path.name for path in target.iterdir()),
    }


def build_preview(rows: list[ts.TrajectoryRow]) -> dict[str, Any]:
    return {
        "frame_count": len(rows),
        "points": [
            {"x": row.values[0], "y": row.values[1], "z": row.values[2],
             "qx": row.values[3], "qy": row.values[4], "qz": row.values[5], "qw": row.values[6]}
            for row in rows
        ],
    }


def trajectory_length(rows: list[ts.TrajectoryRow]) -> float:
    return round(sum(
        math.dist(rows[index - 1].values[0:3], rows[index].values[0:3])
        for index in range(1, len(rows))
    ), 3)


def artifact(stage_dir: Path, artifact_id: str, role: str, path: Path,
             content_type: str, *, download: bool | None = None, note: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "artifact_id": artifact_id, "role": role,
        "path": str(path.relative_to(stage_dir)), "content_type": content_type,
    }
    if download is not None:
        entry["download"] = download
    if note:
        entry["note"] = note
    if path.is_file():
        entry["size_bytes"] = path.stat().st_size
        if role != "preview":
            entry["sha256"] = sha256_file(path)
    return entry


def unassociable_report(reason: str, *, frames: list[ts.BagFrame] | None,
                        native_count: int | None, spec: dict[str, Any]) -> dict[str, Any]:
    timestamp_spec = spec["timestamp"]
    frames = frames or []
    return {
        "method": ts.ASSOCIATION_METHOD,
        "native_lookup_key": timestamp_spec["native_lookup_key"],
        "output_lookup_key": timestamp_spec["surface_lookup_key"],
        "max_delta_sec": timestamp_spec["max_delta_sec"],
        "min_matched_ratio": timestamp_spec["min_matched_ratio"],
        "max_duplicate_reuse_count": timestamp_spec["max_duplicate_reuse_count"],
        "bag_frame_count": len(frames),
        "native_pose_count": native_count,
        "matched_count": 0,
        "skipped_count": len(frames),
        "matched_ratio": 0.0,
        "mean_delta_sec": None,
        "max_delta_sec_observed": None,
        "head_unmatched_count": 0,
        "tail_unmatched_count": 0,
        "interior_unmatched_count": 0,
        "duplicate_pose_reuse_count": 0,
        "duplicate_pose_reuse_rate": 0.0,
        "non_monotonic_match_count": 0,
        "output_timestamps_strictly_increasing": False,
        "accepted": False,
        "reject_reasons": [reason],
    }


def finalize_pose_outputs(
    *,
    job: dict[str, Any],
    spec: dict[str, Any],
    stage_dir: Path,
    native_dir: Path,
    native_rows: list[ts.TrajectoryRow],
    trajectory_filename: str,
    outcome: ts.AssociationOutcome | None,
    report: dict[str, Any],
    glim_context: dict[str, Any],
    runtime_sec: float,
    log: Logger,
) -> tuple[dict[str, Any], bool]:
    """Write the canonical Pose artifacts and return ``(manifest, accepted)``.

    ``accepted=False`` means the trajectory itself is valid but the Surface
    lookup clock could not be reconstructed: the canonical ``poses.txt`` then
    keeps the native sensor timestamps and ``surface_handoff.compatible`` is
    false, so Surface is blocked instead of silently mis-associating poses.
    """
    accepted = bool(outcome is not None and outcome.accepted)
    timestamp_spec = spec["timestamp"]
    poses_path = stage_dir / "poses.txt"
    if accepted:
        assert outcome is not None
        count = ts.write_pose_trajectory(poses_path, outcome.rows)
        canonical_rows = ts.read_pose_trajectory(poses_path)
        timestamp_basis = {
            "clock": "rosbag", "lookup_key": timestamp_spec["surface_lookup_key"],
            "unit": "second",
            "source": "nearest native Pose sample by physical LiDAR sensor timestamp",
        }
        surface_handoff = {
            "compatible": True, "reason": None,
            "required_lookup_key": timestamp_spec["surface_lookup_key"],
            "association_method": ts.ASSOCIATION_METHOD,
        }
        log(f"timestamp association accepted: {count} canonical rows, "
            f"max residual {report.get('max_delta_sec_observed')} s")
    else:
        ts.write_pose_trajectory(
            poses_path, [(f"{row.timestamp:.9f}", row.values) for row in native_rows]
        )
        canonical_rows = list(native_rows)
        timestamp_basis = {
            "clock": "lidar_sensor", "lookup_key": timestamp_spec["native_lookup_key"],
            "unit": "second", "source": "GLIM native trajectory (not normalised)",
        }
        surface_handoff = {
            "compatible": False,
            "reason": "timestamp normalization failed: "
                      + "; ".join(report.get("reject_reasons") or ["unknown reason"]),
            "required_lookup_key": timestamp_spec["surface_lookup_key"],
            "association_method": ts.ASSOCIATION_METHOD,
        }
        log("TIMESTAMP HANDOFF BLOCKED: " + str(surface_handoff["reason"]))

    ts.write_association_report(native_dir / "association.json", report)
    atomic_write_json(stage_dir / "trajectory_preview.json", build_preview(canonical_rows))

    artifacts = [
        artifact(stage_dir, "trajectory_model", "preview", stage_dir / "trajectory_preview.json",
                 "application/json"),
        artifact(stage_dir, "registered_trajectory", "trajectory", poses_path,
                 "text/plain", download=True,
                 note="Canonical Pose trajectory (T_world_lidar); timestamps follow the "
                      "declared timestamp_basis."),
        artifact(stage_dir, "glim_native_trajectory", "data", native_dir / trajectory_filename,
                 "text/plain", download=True,
                 note="Backend-native GLIM trajectory in the physical LiDAR sensor clock."),
        artifact(stage_dir, "pose_timestamp_association", "data", native_dir / "association.json",
                 "application/json", download=True),
        artifact(stage_dir, "glim_bag_frame_index", "data", native_dir / "bag_index.tsv",
                 "text/plain", download=True),
        artifact(stage_dir, "glim_effective_config", "data",
                 native_dir / "config" / "config_ros.json", "application/json", download=True),
        artifact(stage_dir, "glim_run_log", "data", native_dir / "run.log",
                 "text/plain", download=True),
    ]
    manifest = build_manifest(job["job_id"] if "job_id" in job else stage_dir.parent.name,
                              STAGE, BACKEND, runtime_sec, {
        "pose_count": len(canonical_rows),
        "timestamp_start": canonical_rows[0].timestamp,
        "timestamp_end": canonical_rows[-1].timestamp,
        "trajectory_length_m": trajectory_length(canonical_rows),
        "native_pose_count": len(native_rows),
        "bag_frame_count": report.get("bag_frame_count"),
        "matched_count": report.get("matched_count"),
        "matched_ratio": report.get("matched_ratio"),
        "max_delta_sec_observed": report.get("max_delta_sec_observed"),
        "glim_runtime_sec": round(runtime_sec, 2),
        "surface_handoff_compatible": accepted,
    }, artifacts, backend_details={
        "mock_backend": False,
        "algorithm": "GLIM (ROS2 node) + ROS1 Livox bridge",
        "result_origin": "GLIM runtime estimation",
        "run_id": "glim_" + time.strftime("%Y%m%d_%H%M%S"),
        "dataset_id": job.get("dataset"),
        "pose_semantics": "T_world_lidar",
        "translation_unit": "meter",
        "quaternion_order": "qx qy qz qw",
        "timestamp_basis": timestamp_basis,
        "native_timestamp_basis": {
            "clock": "lidar_sensor",
            "lookup_key": timestamp_spec["native_lookup_key"],
            "unit": "second",
        },
        "surface_handoff": surface_handoff,
        "timestamp_association": report,
        "glim": glim_context,
    })
    atomic_write_json(stage_dir / "result_manifest.json", manifest)
    return manifest, accepted


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    stage_dir = job_dir / "stage1_pose"
    native_dir = stage_dir / "native"
    log = Logger(native_dir / "run.log" if not args.dry_run else None)
    progress = Progress(stage_dir / "progress.json")
    started = time.monotonic()
    supervisor: ChildSupervisor | None = None
    lock: GlimExecutionLock | None = None

    try:
        job, spec, runtime_block = load_job_inputs(job_dir)
        plan = build_plan(job_dir, job, spec, args.mode)
        runtime = plan["runtime"]
        # One supervisor owns every child and every cleanup obligation of this
        # run, so cancel / timeout / failure all take the same path
        # (see child_supervisor).  The configured run timeout enters through the
        # same cancel path, never through a second termination implementation.
        supervisor = ChildSupervisor(timeout_sec=plan["run_timeout_sec"])
        install_termination_handler(supervisor.request_cancel)
        lock = GlimExecutionLock(runtime.lock_path)
        progress.write("validating", "Validated dataset pose specification and runtime settings")
        log(f"job={job_dir.name} dataset={job.get('dataset')} mode={args.mode}")
        log(f"bag={plan['bag']}")
        log(f"bag identity: {plan['bag_identity']['match']}")
        log(f"run timeout: {plan['run_timeout_sec']:g}s")
        log(f"runtime sources: {json.dumps(runtime.sources, ensure_ascii=False)}")

        # The shared GLIM dump path is process-global, so it is only inspected
        # (and the job's own previous leftovers only removed) once the global
        # GLIM lock is held.
        node_info = resolve_glim_node(runtime, env=plan["ros_env"])
        if args.dry_run and not node_info["resolved"]:
            log(f"GLIM node not resolved yet (dry run): {node_info['error']}")

        dump_policy: dict[str, Any] = {
            "dump_dir": GLIM_SHARED_DUMP_DIR, "policy": runtime.dump_policy,
            "action": "deferred_until_lock", "quarantined_to": None,
            "existed": Path(GLIM_SHARED_DUMP_DIR).exists(),
        }
        cleaned: list[str] = []
        if args.dry_run:
            log(f"shared GLIM dump dir (GLIM 1.2.2 behaviour): {GLIM_SHARED_DUMP_DIR}")
            dump_policy = inspect_dump_dir(
                Path(GLIM_SHARED_DUMP_DIR),
                policy=runtime.dump_policy,
                quarantine_dir=runtime.quarantine_dir,
                job_id=job_dir.name,
                dry_run=True,
            )
        else:
            try:
                status = lock.acquire(job_id=job_dir.name)
            except GlimLockError as exc:
                raise GlimPoseError(str(exc)) from exc
            if not status.acquired:
                raise GlimPoseError(status.reason)
            supervisor.add_cleanup("glim_lock", lock.release)
            for event in lock.events:
                log(event)
            cleaned = clean_local_run_state(stage_dir)
            log(f"cleaned previous local run state: {cleaned or 'nothing to remove'}")
            dump_policy = inspect_dump_dir(
                Path(GLIM_SHARED_DUMP_DIR),
                policy=runtime.dump_policy,
                quarantine_dir=runtime.quarantine_dir,
                job_id=job_dir.name,
            )
            log(f"shared dump dir {GLIM_SHARED_DUMP_DIR}: {dump_policy['action']}"
                + (f" -> {dump_policy['quarantined_to']}"
                   if dump_policy.get("quarantined_to") else ""))

        config_summary = cfg.materialize_config(
            runtime.config_path,
            native_dir / "config",
            plan["overrides"],
            registered_copy=native_dir / "config_registered",
        )
        for warning in config_summary["headless_warnings"]:
            log(f"WARNING: {warning}")
        log(f"GLIM config: {config_summary['effective']} "
            f"({len(config_summary['applied'])} parameter override(s))")

        if args.dry_run:
            report = {
                "dry_run": True, "backend": BACKEND, "mode": args.mode,
                "job_id": job_dir.name, "dataset": job.get("dataset"),
                "pose_spec": {key: value for key, value in spec.items() if key != "runtime"},
                "runtime": {
                    "config_path": str(runtime.config_path),
                    "ros_setup": runtime.ros_setup,
                    "ld_library_path": runtime.ld_library_path,
                    "rosbags_python": str(runtime.rosbags_python),
                    "node_command": runtime.node_command,
                    "lock_path": str(runtime.lock_path),
                    "quarantine_dir": str(runtime.quarantine_dir),
                    "playback_rate": runtime.playback_rate,
                    "finalize_wait_sec": runtime.finalize_wait_sec,
                    "dump_wait_sec": runtime.dump_wait_sec,
                    "sources": runtime.sources,
                    "rosbags_python_available": runtime.rosbags_python.is_file(),
                    "ros_setup_available": Path(runtime.ros_setup).is_file(),
                },
                "config": {key: config_summary[key] for key in ("registered", "effective", "applied", "headless_warnings")},
                "dump": dump_policy,
                "glim_shared_dump_dir": GLIM_SHARED_DUMP_DIR,
                "glim_shared_dump_dir_note": (
                    "GLIM 1.2.2 ROS2 always dumps here with dump_on_unload=true; the platform "
                    "cannot relocate it, so this is a constant and never a setting"
                ),
                "would_clean_local_state": list(LOCAL_RUN_STATE),
                "lock": {"path": str(runtime.lock_path), "state": "not_acquired_in_dry_run"},
                "glim_argv": plan["glim_argv"],
                "glim_shell": plan["glim_shell"],
                "glim_node_command": plan["node_command"],
                "glim_node_args": plan["glim_node_args"],
                "glim_node": node_info,
                "run_timeout_sec": plan["run_timeout_sec"],
                # LD_LIBRARY_PATH is overridden *inside* the shell, after
                # `source`; the process environment only drops OMP_NUM_THREADS.
                "ros_runtime": {
                    "ros_setup": runtime.ros_setup,
                    "ld_library_path": runtime.ld_library_path,
                    "ld_export_after_source": True,
                    "omp_num_threads_unset_in_shell": True,
                    "omp_num_threads_present_in_env": "OMP_NUM_THREADS" in plan["ros_env"],
                    "ld_library_path_present_in_env": "LD_LIBRARY_PATH" in plan["ros_env"],
                },
                "bridge_argv": plan["bridge_argv"],
                "bridge_shell": plan["bridge_shell"],
                "expected_lidar_frames": plan["expected_lidar_frames"],
                "planned_native_dir": str(native_dir),
                "bag_identity": plan["bag_identity"],
                "planned_artifacts": ["poses.txt", "trajectory_preview.json", "result_manifest.json"],
                "dry_run_note": "no GLIM, no bridge and no ROS2 was executed",
            }
            atomic_write_json(native_dir / "dry_run_report.json", report)
            progress.write("dry_run_completed", "Dry run completed: configuration and plan validated")
            print(json.dumps({"status": "dry_run_ok", "report": str(native_dir / "dry_run_report.json")}, indent=2))
            return 0

        if node_info["default_command"] and not node_info["resolved"]:
            # The default node command needs a working ROS2 environment; fail
            # before starting anything instead of surfacing shell exit code 127.
            raise GlimPoseError(
                f"cannot resolve the GLIM node executable ({node_info['error']}); "
                "set runtime.glim.node_command or fix runtime.glim.ros_setup"
            )

        trajectory_filename = runtime.trajectory_filename
        dump_candidates = [Path(GLIM_SHARED_DUMP_DIR), stage_dir / "dump"]

        progress.write("starting_glim", "Starting GLIM CUDA node (headless)")
        supervisor.register("glim", subprocess.Popen(
            ["bash", "-lc", plan["glim_shell"]],
            env=plan["ros_env"], cwd=str(stage_dir), **child_popen_kwargs(),
        ))
        deadline = time.monotonic() + max(args.glim_startup_grace_sec, 0.0)
        while time.monotonic() < deadline:
            supervisor.raise_if_cancelled()
            glim = supervisor.child("glim")
            if glim is not None and glim.poll() is not None:
                raise GlimPoseError(
                    f"GLIM exited during startup with code {glim.returncode}; "
                    "check native/run.log and the registered GLIM config"
                )
            time.sleep(0.25)
        log("GLIM node started; streaming the ROS1 bag through the bridge")

        progress.write("streaming", "Streaming ROS1 LiDAR + IMU into GLIM")
        # Same controlled ROS runtime shell as GLIM, so the bridge's own
        # `import rclpy` works without the platform being started from a
        # sourced shell; `exec` makes the bridge Python the direct child.
        supervisor.register("bridge", subprocess.Popen(
            ["bash", "-lc", plan["bridge_shell"]],
            env=plan["ros_env"], cwd=str(stage_dir), **child_popen_kwargs(),
        ))
        bridge = supervisor.child("bridge")
        while bridge.poll() is None:
            supervisor.raise_if_cancelled()
            time.sleep(0.5)
        if bridge.returncode != 0:
            raise GlimPoseError(f"ROS1 bridge exited with code {bridge.returncode}")
        log("bridge finished; asking GLIM to dump its result")

        progress.write("finalizing", f"Waiting {runtime.finalize_wait_sec:g}s before GLIM shutdown")
        deadline = time.monotonic() + runtime.finalize_wait_sec
        while time.monotonic() < deadline:
            supervisor.raise_if_cancelled()
            time.sleep(0.25)

        glim = supervisor.child("glim")
        shutdown = request_glim_shutdown(supervisor, grace=runtime.dump_wait_sec)
        log(f"graceful shutdown: {shutdown['signal']} -> {shutdown['target']} (pid {shutdown['pid']})")

        progress.write("dumping", "Waiting for GLIM to dump its native trajectory")
        dump_dir: Path | None = None
        deadline = time.monotonic() + runtime.dump_wait_sec
        while time.monotonic() < deadline:
            supervisor.raise_if_cancelled()
            dump_dir = discover_dump_dir(dump_candidates, trajectory_filename) or dump_dir
            if glim is not None and glim.poll() is not None:
                break
            time.sleep(0.5)
        dump_dir = dump_dir or discover_dump_dir(dump_candidates, trajectory_filename)
        if glim is not None and glim.poll() is None:
            raise GlimPoseError(
                f"GLIM did not exit within {runtime.dump_wait_sec:g}s after SIGINT; "
                "the dump may be incomplete"
            )
        if dump_dir is None:
            exit_code = glim.returncode if glim is not None else None
            raise GlimPoseError(
                f"GLIM did not produce {trajectory_filename} in "
                f"{', '.join(str(path) for path in dump_candidates)} "
                f"(GLIM exit code {exit_code}); the native trajectory is required"
            )
        glim_exit_code = glim.returncode if glim is not None else None
        if glim_exit_code != 0:
            raise GlimPoseError(
                f"GLIM exited with code {glim_exit_code} after SIGINT; "
                "refusing to accept a potentially incomplete dump"
            )
        log(f"native trajectory found: {dump_dir / trajectory_filename} "
            f"(GLIM exit code {glim_exit_code})")

        progress.write("normalizing", "Associating native Pose timestamps with bag record timestamps")
        collected = collect_native_outputs(dump_dir, native_dir, trajectory_filename)
        native_rows = ts.read_pose_trajectory(native_dir / trajectory_filename)

        index_path = native_dir / "bag_index.tsv"
        frames: list[ts.BagFrame] | None = None
        outcome: ts.AssociationOutcome | None = None
        report: dict[str, Any]
        if not index_path.is_file():
            report = unassociable_report(
                "bag_index.tsv is missing: the bridge did not record the bag frame times, "
                "so the Surface lookup clock cannot be reconstructed",
                frames=None, native_count=len(native_rows), spec=spec,
            )
        else:
            try:
                frames = ts.read_bag_frame_index(index_path)
            except ts.PoseTimestampError as exc:
                report = unassociable_report(
                    f"bag_index.tsv could not be read: {exc}",
                    frames=None, native_count=len(native_rows), spec=spec,
                )
            else:
                timestamp_spec = spec["timestamp"]
                outcome = ts.associate_to_bag_record_time(
                    frames, native_rows,
                    max_delta_sec=timestamp_spec["max_delta_sec"],
                    min_matched_ratio=timestamp_spec["min_matched_ratio"],
                    max_duplicate_reuse_count=timestamp_spec["max_duplicate_reuse_count"],
                    native_lookup_key=timestamp_spec["native_lookup_key"],
                    output_lookup_key=timestamp_spec["surface_lookup_key"],
                )
                report = outcome.report

        accepted = bool(outcome is not None and outcome.accepted)
        if not accepted and spec["timestamp"]["on_failure"] == "fail_stage":
            raise GlimPoseError(
                "timestamp normalization failed and pose.timestamp.on_failure='fail_stage': "
                + "; ".join(report.get("reject_reasons") or ["unknown reason"])
            )

        glim_context = {
            "config_path": str(runtime.config_path),
            "effective_config": str(native_dir / "config"),
            "registered_config": str(native_dir / "config_registered"),
            "applied_overrides": config_summary["applied"],
            "headless_warnings": config_summary["headless_warnings"],
            "command": plan["glim_argv"],
            "shell": plan["glim_shell"],
            "bridge_command": plan["bridge_argv"],
            "bridge_shell": plan["bridge_shell"],
            "ros_runtime": {
                "ros_setup": runtime.ros_setup,
                "ld_library_path": runtime.ld_library_path,
                "ld_export_after_source": True,
                "omp_num_threads_unset_in_shell": True,
            },
            "mode": args.mode,
            "playback_rate": runtime.playback_rate,
            "glim_exit_code": glim_exit_code,
            "run_timeout_sec": plan["run_timeout_sec"],
            "node_command": plan["node_command"],
            "node_path": node_info.get("node_path"),
            "node_resolution": node_info,
            "graceful_shutdown": shutdown,
            "cleaned_local_state": cleaned,
            "runtime_sources": runtime.sources,
            "dump": dump_policy | collected,
            "lock": {"path": str(runtime.lock_path), "acquired": True,
                     "stale_taken_over_from": status.stale_taken_over_from},
            "signals": supervisor.signals,
        }
        manifest, accepted = finalize_pose_outputs(
            job=job, spec=spec, stage_dir=stage_dir, native_dir=native_dir,
            native_rows=native_rows, trajectory_filename=trajectory_filename,
            outcome=outcome, report=report, glim_context=glim_context,
            runtime_sec=time.monotonic() - started, log=log,
        )
        pose_count = int(manifest["metrics"]["pose_count"])
        progress.write(
            "completed",
            "GLIM Pose completed" + ("" if accepted else " (Surface handoff blocked)"),
            percent=100.0, current=pose_count, total=pose_count, unit="pose",
        )
        print(json.dumps({
            "status": "completed", "poses": pose_count,
            "surface_handoff_compatible": accepted,
            "association": native_dir.joinpath("association.json").name,
        }, indent=2))
        return 0

    except RunTimedOut as exc:
        # Same cleanup path as a cancel (children terminated, lock released by
        # the supervisor's cleanup hook); the stage is reported as failed.
        log(f"TIMEOUT: {exc}")
        progress.write("failed", f"GLIM Pose run timeout exceeded: {exc}", status="failed")
        print(f"GLIM Pose adapter timed out: {exc}", file=sys.stderr, flush=True)
        return TIMEOUT_EXIT_CODE
    except RunCancelled as exc:
        log(f"cancelled: {exc}")
        progress.write("cancelled", "GLIM Pose cancelled by the platform", status="cancelled")
        return 130
    except (GlimPoseError, PoseSpecError, GlimDumpError, cfg.GlimConfigError,
            ts.PoseTimestampError, OSError, ValueError) as exc:
        log(f"ERROR: {exc}")
        progress.write("failed", str(exc), status="failed")
        print(f"GLIM Pose adapter failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if supervisor is not None:
            supervisor.terminate_all()
            supervisor.run_cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
