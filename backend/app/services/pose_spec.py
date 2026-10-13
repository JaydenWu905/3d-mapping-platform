"""Dataset-registry contract for executable Pose backends.

A real dataset registry file (``backend/config/datasets/*.json``) declares a
``pose`` block next to its existing ``surface`` block.  The configuration is
split in two on purpose:

* dataset semantics — topics, frame ids, sensor scaling, extrinsic and the GLIM
  config directory.  These describe the *dataset* and travel with it;
* ``runtime`` (a sibling top level key) — machine specific toolchain paths (ROS
  setup, LD_LIBRARY_PATH, rosbags interpreter, dump directory, lock file).
  These describe the *machine* and can be overridden per run through
  environment variables, so a server path never becomes part of the dataset
  data model.

Example (shipped as ``docs/ins-longcorridor01-dataset-example.json``)::

    "pose": {
      "backend": "glim",
      "bag_path": "INS/2024-06-04-16-24-55.bag",
      "lidar_topic": "/livox_mid360/livox/lidar",
      "imu_topic": "/livox_mid360/livox/imu",
      "lidar_frame_id": "livox_mid360_frame",
      "imu_frame_id": "livox_frame",
      "acc_scale": 9.80665,
      "perpoint_relative_time": true,
      "perpoint_time_scale": 1e-9,
      "T_lidar_imu": [0.011, 0.02329, -0.04412, 0, 0, 0, 1],
      "config_path": "INS/glim_ins_config",
      "timestamp": {
        "native_lookup_key": "physical LiDAR sensor/header timestamp",
        "surface_lookup_key": "ROS bag record timestamp",
        "max_delta_sec": 0.05,
        "min_matched_ratio": 0.98
      }
    },
    "runtime": {
      "glim": {"rosbags_python": "envs/rosbags/bin/python"}
    }

``workspace_root`` is the directory that contains the platform repository
(``PROJECT_ROOT.parent``); every declared path is workspace relative and is
refused if it escapes.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class PoseSpecError(ValueError):
    """Raised when a dataset's Pose configuration cannot be executed."""


#: Canonical Pose semantics for every backend (docs/pose-stage-contract.md).
POSE_SEMANTICS = "T_world_lidar"
TRANSLATION_UNIT = "meter"
QUATERNION_ORDER = "qx qy qz qw"

#: Timestamp conventions (docs/pose-timestamp-contract.md).
NATIVE_SENSOR_LOOKUP_KEY = "physical LiDAR sensor/header timestamp"
BAG_RECORD_LOOKUP_KEY = "ROS bag record timestamp"
NATIVE_SENSOR_CLOCK = "lidar_sensor"
BAG_RECORD_CLOCK = "rosbag"

#: Fields without which a backend cannot be started at all.
BACKEND_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "glim": (
        "lidar_topic",
        "imu_topic",
        "lidar_frame_id",
        "imu_frame_id",
        "config_path",
    ),
}

#: Strict defaults: a native Pose sample reused by several bag frames usually
#: means a one-frame shift or a rate mismatch, so it blocks the handoff.
DEFAULT_MAX_DUPLICATE_REUSE = 0
DEFAULT_MAX_DELTA_SEC = 0.05
DEFAULT_MIN_MATCHED_RATIO = 0.98
DEFAULT_RUN_TIMEOUT_SEC = 7200.0

#: GLIM 1.2.2 (ROS2) writes its dump to this **process-global** directory when
#: ``dump_on_unload`` is true (docs/ins-glim-dataset-profile.md §11).  The
#: platform cannot relocate it, so it is a constant and not a setting: a knob
#: that only moved where the platform *looks* would break discovery instead of
#: changing GLIM.  Because the path is shared, every real GLIM run is serialised
#: by ``glim_lock.GlimExecutionLock`` and the directory is inspected (and, when
#: stale, quarantined) only **after** the lock has been acquired.
GLIM_SHARED_DUMP_DIR = "/tmp/dump"

#: Default target for the real GLIM node executable.  ``ros2 run`` is
#: deliberately NOT used: it would insert an opaque wrapper process between the
#: adapter and the node, and the graceful ``dump_on_unload`` path needs SIGINT
#: delivered to the node itself.  The shell expands this expression and
#: ``exec``s it, so the node becomes the adapter's direct child.
DEFAULT_GLIM_NODE_COMMAND = "$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode"

NATIVE_POSE_HANDOFF_FAILURE = "complete_with_blocked_handoff"

_POSE_NUMBER_FIELDS = ("acc_scale", "perpoint_time_scale")
_POSE_POSITIVE_FIELDS = ("run_timeout_sec",)
_POSE_FRAME_FIELDS = ("lidar_topic", "imu_topic", "lidar_frame_id", "imu_frame_id")
_POSE_TOPIC_FIELDS = ("internal_points_topic", "internal_imu_topic")
_POSE_BOOL_FIELDS = ("headless", "perpoint_relative_time")

_POSE_DEFAULTS: dict[str, Any] = {
    "internal_points_topic": "/mapping/glim/points",
    "internal_imu_topic": "/mapping/glim/imu",
    "headless": True,
    "run_timeout_sec": DEFAULT_RUN_TIMEOUT_SEC,
    "demo": {"max_lidar_frames": 60, "max_duration_sec": 30.0},
}

_TIMESTAMP_DEFAULTS: dict[str, Any] = {
    "native_lookup_key": NATIVE_SENSOR_LOOKUP_KEY,
    "surface_lookup_key": BAG_RECORD_LOOKUP_KEY,
    "max_delta_sec": DEFAULT_MAX_DELTA_SEC,
    "min_matched_ratio": DEFAULT_MIN_MATCHED_RATIO,
    "max_duplicate_reuse_count": DEFAULT_MAX_DUPLICATE_REUSE,
    "on_failure": NATIVE_POSE_HANDOFF_FAILURE,
}

#: Machine/runtime defaults.  They mirror the environment verified for the
#: reference reproduction and MUST be confirmed on any new machine.
RUNTIME_DEFAULTS: dict[str, Any] = {
    "ros_setup": "/opt/ros/humble/setup.bash",
    "ld_library_path": "/usr/local/lib",
    "rosbags_python": "envs/rosbags/bin/python",
    "playback_rate": 1.0,
    "finalize_wait_sec": 5.0,
    "dump_wait_sec": 60.0,
    "trajectory_filename": "traj_lidar.txt",
    "lock_path": "runtime/locks/glim.lock",
    "quarantine_dir": "runtime/quarantine",
    "node_command": DEFAULT_GLIM_NODE_COMMAND,
    "dump_policy": "quarantine",
    "node_params": {},
    "config_overrides": {},
}

#: ``environment variable -> runtime key``.  The machine, not the dataset
#: registry, has the last word about toolchain locations.
RUNTIME_ENV_OVERRIDES: dict[str, str] = {
    "GLIM_ROS_SETUP": "ros_setup",
    "GLIM_LD_LIBRARY_PATH": "ld_library_path",
    "GLIM_ROSBAGS_PYTHON": "rosbags_python",
    "GLIM_PLAYBACK_RATE": "playback_rate",
    "GLIM_FINALIZE_WAIT_SEC": "finalize_wait_sec",
    "GLIM_DUMP_WAIT_SEC": "dump_wait_sec",
    "GLIM_LOCK_PATH": "lock_path",
    "GLIM_QUARANTINE_DIR": "quarantine_dir",
    "GLIM_NODE_COMMAND": "node_command",
    "GLIM_CONFIG_PATH": "config_path",
}


def workspace_root(project_root: Path) -> Path:
    """Directory that owns server-managed datasets and tool environments."""
    return project_root.resolve().parent


def resolve_workspace(project_root: Path, env: Mapping[str, str] | None = None) -> Path:
    """The workspace directory, overridable with ``GLIM_WORKSPACE``.

    The default is the directory that contains the platform repository, which is
    where server-managed datasets live.  Some deployments (and the test suite)
    keep them elsewhere, so the workspace is itself a runtime setting; it must
    be absolute, because a relative workspace would resolve against whatever
    working directory the subprocess happens to have.
    """
    env = dict(os.environ if env is None else env)
    override = env.get("GLIM_WORKSPACE")
    if not override:
        return workspace_root(project_root)
    path = Path(override)
    if not path.is_absolute():
        raise PoseSpecError("GLIM_WORKSPACE must be an absolute path")
    return path.resolve()


def resolve_workspace_path(
    value: Any, *, workspace: Path, label: str, must_exist: bool = True
) -> Path:
    """Resolve a workspace-relative path, refusing escapes and optional misses."""
    if not isinstance(value, str) or not value.strip():
        raise PoseSpecError(f"{label} must be a non-empty workspace-relative path")
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise PoseSpecError(f"{label} must be a workspace-relative path without '..'")
    root = workspace.resolve()
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise PoseSpecError(f"{label} escapes the workspace root")
    if must_exist and not target.exists():
        raise PoseSpecError(f"{label} is unavailable: {target}")
    return target


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def normalize_timestamp_block(raw: Any, errors: list[str]) -> dict[str, Any]:
    block = dict(_TIMESTAMP_DEFAULTS)
    if raw is None:
        return block
    if not isinstance(raw, dict):
        errors.append("pose.timestamp must be an object")
        return block
    for key in ("native_lookup_key", "surface_lookup_key"):
        if key in raw:
            if not isinstance(raw[key], str) or not raw[key].strip():
                errors.append(f"pose.timestamp.{key} must be a non-empty string")
            else:
                block[key] = raw[key].strip()
    for key in ("max_delta_sec", "min_matched_ratio"):
        if key in raw:
            if not _finite_number(raw[key]) or float(raw[key]) <= 0:
                errors.append(f"pose.timestamp.{key} must be a positive number")
            else:
                block[key] = float(raw[key])
    if block["min_matched_ratio"] > 1.0:
        errors.append("pose.timestamp.min_matched_ratio must be <= 1.0")
    if "max_duplicate_reuse_count" in raw:
        value = raw["max_duplicate_reuse_count"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append("pose.timestamp.max_duplicate_reuse_count must be a non-negative integer")
        else:
            block["max_duplicate_reuse_count"] = value
    if "on_failure" in raw:
        if raw["on_failure"] not in (NATIVE_POSE_HANDOFF_FAILURE, "fail_stage"):
            errors.append(
                "pose.timestamp.on_failure must be "
                f"'{NATIVE_POSE_HANDOFF_FAILURE}' or 'fail_stage'"
            )
        else:
            block["on_failure"] = raw["on_failure"]
    return block


def normalize_pose_spec(raw: Any) -> dict[str, Any]:
    """Validate a dataset ``pose`` block and fill the documented defaults.

    Raises ``PoseSpecError`` with a human readable reason.  Registry validation
    and the runtime adapter both read this canonical shape, so a dataset either
    works everywhere or is reported unavailable everywhere.
    """
    if not isinstance(raw, dict) or not raw:
        raise PoseSpecError("dataset registry has no 'pose' block")
    backend = raw.get("backend")
    if not isinstance(backend, str) or not backend.strip():
        raise PoseSpecError("pose.backend must name a Pose backend")

    spec: dict[str, Any] = dict(raw)
    spec["backend"] = backend.strip()
    errors: list[str] = []

    for key in BACKEND_REQUIRED_FIELDS.get(spec["backend"], ()):
        if not spec.get(key):
            errors.append(f"pose.{key} is required for backend '{spec['backend']}'")
    for key in _POSE_FRAME_FIELDS:
        value = spec.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"pose.{key} must be a non-empty string")
    topic_defaults = {key: _POSE_DEFAULTS[key] for key in _POSE_TOPIC_FIELDS}
    for key, default in topic_defaults.items():
        value = spec.get(key, default)
        if not isinstance(value, str) or not value.startswith("/"):
            errors.append(f"pose.{key} must be an absolute ROS topic name")
        else:
            spec[key] = value
    for key in _POSE_BOOL_FIELDS:
        if key in spec and not isinstance(spec[key], bool):
            errors.append(f"pose.{key} must be a boolean")
    for key in _POSE_NUMBER_FIELDS:
        value = spec.get(key)
        if value is None:
            continue
        if not _finite_number(value) or float(value) <= 0:
            errors.append(f"pose.{key} must be a positive finite number")
    for key in _POSE_POSITIVE_FIELDS:
        if key in spec:
            if not _finite_number(spec[key]) or float(spec[key]) <= 0:
                errors.append(f"pose.{key} must be a positive number of seconds")
            else:
                spec[key] = float(spec[key])
    if "run_timeout_sec" not in spec:
        spec["run_timeout_sec"] = DEFAULT_RUN_TIMEOUT_SEC

    extrinsic = spec.get("T_lidar_imu")
    if extrinsic is not None:
        if (
            not isinstance(extrinsic, list)
            or len(extrinsic) != 7
            or not all(_finite_number(v) for v in extrinsic)
        ):
            errors.append("pose.T_lidar_imu must be 7 finite numbers [x y z qx qy qz qw]")
        else:
            norm = math.sqrt(sum(float(v) ** 2 for v in extrinsic[3:7]))
            if not 0.98 <= norm <= 1.02:
                errors.append("pose.T_lidar_imu quaternion must be unit length")

    spec["timestamp"] = normalize_timestamp_block(spec.get("timestamp"), errors)

    demo = spec.get("demo")
    if demo is None:
        spec["demo"] = dict(_POSE_DEFAULTS["demo"])
    elif not isinstance(demo, dict):
        errors.append("pose.demo must be an object")
    else:
        merged = dict(_POSE_DEFAULTS["demo"])
        for key, value in demo.items():
            if key not in merged:
                errors.append(f"pose.demo.{key} is not a supported option")
            elif not _finite_number(value) or float(value) <= 0:
                errors.append(f"pose.demo.{key} must be a positive number")
            else:
                merged[key] = float(value)
        spec["demo"] = merged

    if errors:
        raise PoseSpecError("; ".join(errors))
    return spec


def load_pose_spec(input_manifest: Any) -> dict[str, Any]:
    """Read the ``pose`` block that JobService copied into the job input manifest."""
    if not isinstance(input_manifest, dict):
        raise PoseSpecError("job input_manifest.json is missing or invalid")
    return normalize_pose_spec(input_manifest.get("pose"))


def load_runtime_block(input_manifest: Any, backend: str) -> dict[str, Any]:
    """Machine/runtime configuration for one backend (may be absent)."""
    if not isinstance(input_manifest, dict):
        return {}
    runtime = input_manifest.get("runtime")
    if not isinstance(runtime, dict):
        return {}
    block = runtime.get(backend)
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise PoseSpecError(f"runtime.{backend} must be an object")
    unknown = sorted(set(block) - set(RUNTIME_DEFAULTS) - {"config_path"})
    if unknown:
        raise PoseSpecError(f"runtime.{backend} has unsupported keys: {', '.join(unknown)}")
    return dict(block)


def validate_dataset_pose(
    pose_block: Any,
    *,
    runtime_block: Any = None,
    workspace: Path,
    declared_files: Mapping[str, Any] | None = None,
    check_paths: bool = True,
) -> list[str]:
    """Validate a registry ``pose`` block for dataset listing / Job creation.

    ``check_paths`` validates the paths that belong to the dataset itself (the
    GLIM config directory, an optional explicit bag path).  Machine toolchain
    paths are deliberately not checked here: the adapter reports them with a
    precise, actionable message at run time, and the same dataset must remain
    valid on a machine that overrides them through ``GLIM_*`` variables.
    """
    try:
        spec = normalize_pose_spec(pose_block)
        if runtime_block is not None:
            load_runtime_block({"runtime": {spec["backend"]: runtime_block}}, spec["backend"])
    except PoseSpecError as exc:
        return [str(exc)]

    errors: list[str] = []
    declared_files = declared_files or {}
    if "bag" not in declared_files:
        errors.append("dataset registry has no 'bag' file for the Pose backend")

    if check_paths:
        config_value = spec.get("config_path")
        if spec["backend"] == "glim" and not config_value:
            errors.append("pose.config_path is required to locate the GLIM config directory")
        if config_value:
            try:
                config = resolve_workspace_path(
                    config_value, workspace=workspace, label="pose.config_path"
                )
                if not config.is_dir():
                    errors.append(f"pose.config_path is not a directory: {config}")
                elif not (config / "config_ros.json").is_file():
                    errors.append(
                        "pose.config_path has no GLIM config_ros.json: "
                        f"{config / 'config_ros.json'}"
                    )
            except PoseSpecError as exc:
                errors.append(str(exc))
        if spec.get("bag_path"):
            try:
                resolve_workspace_path(spec["bag_path"], workspace=workspace, label="pose.bag_path")
            except PoseSpecError as exc:
                errors.append(str(exc))
    return errors


def cross_check_lookup_keys(pose_block: Any, surface_block: Any) -> list[str]:
    """Pose and Surface must agree about the clock they exchange (contract §11)."""
    if not isinstance(pose_block, dict) or not isinstance(surface_block, dict):
        return []
    timestamp = pose_block.get("timestamp")
    if not isinstance(timestamp, dict):
        return []
    declared = timestamp.get("surface_lookup_key")
    required = surface_block.get("pose_lookup_key")
    if not declared or not required:
        return []
    if str(declared) != str(required):
        return [
            "pose.timestamp.surface_lookup_key "
            f"({declared!r}) does not match surface.pose_lookup_key ({required!r})"
        ]
    return []


@dataclass(frozen=True)
class GlimRuntime:
    """Resolved, machine-specific GLIM runtime settings."""

    workspace: Path
    config_path: Path
    ros_setup: str
    ld_library_path: str
    rosbags_python: Path
    playback_rate: float
    finalize_wait_sec: float
    dump_wait_sec: float
    trajectory_filename: str
    lock_path: Path
    quarantine_dir: Path
    node_command: str
    dump_policy: str
    node_params: dict[str, Any] = field(default_factory=dict)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)


def _coerce_runtime_value(key: str, value: Any, label: str) -> Any:
    if key in ("playback_rate", "finalize_wait_sec", "dump_wait_sec"):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise PoseSpecError(f"{label} must be a number") from exc
        if not math.isfinite(number) or number <= 0:
            raise PoseSpecError(f"{label} must be a positive number")
        return number
    if key in ("node_params", "config_overrides"):
        if not isinstance(value, dict):
            raise PoseSpecError(f"{label} must be an object")
        return dict(value)
    if key == "dump_policy":
        if value not in ("quarantine", "require_empty"):
            raise PoseSpecError(f"{label} must be 'quarantine' or 'require_empty'")
        return value
    if not isinstance(value, str) or not value.strip():
        raise PoseSpecError(f"{label} must be a non-empty string")
    return value.strip()


def resolve_glim_runtime(
    pose_spec: Mapping[str, Any],
    *,
    workspace: Path,
    runtime_block: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> GlimRuntime:
    """Resolve machine settings with precedence ``environment > registry > default``."""
    env = dict(os.environ if env is None else env)
    values: dict[str, Any] = dict(RUNTIME_DEFAULTS)
    sources: dict[str, str] = {key: "default" for key in RUNTIME_DEFAULTS}
    for key, value in dict(runtime_block or {}).items():
        values[key] = _coerce_runtime_value(key, value, f"runtime.glim.{key}")
        sources[key] = "dataset registry"
    for env_name, key in RUNTIME_ENV_OVERRIDES.items():
        if env.get(env_name):
            values[key] = _coerce_runtime_value(key, env[env_name], env_name)
            sources[key] = f"environment {env_name}"

    config_value = pose_spec.get("config_path")
    if env.get("GLIM_CONFIG_PATH"):
        config_value = env["GLIM_CONFIG_PATH"]
        sources["config_path"] = "environment GLIM_CONFIG_PATH"
    config_path = resolve_workspace_path(
        config_value, workspace=workspace, label="pose.config_path"
    )
    rosbags_python = resolve_workspace_path(
        values["rosbags_python"], workspace=workspace, label="runtime.glim.rosbags_python"
    )
    lock_path = resolve_workspace_path(
        values["lock_path"], workspace=workspace, label="runtime.glim.lock_path", must_exist=False
    )
    quarantine_dir = resolve_workspace_path(
        values["quarantine_dir"], workspace=workspace, label="runtime.glim.quarantine_dir",
        must_exist=False,
    )

    return GlimRuntime(
        workspace=workspace.resolve(),
        config_path=config_path,
        ros_setup=str(values["ros_setup"]),
        ld_library_path=str(values["ld_library_path"]),
        rosbags_python=rosbags_python,
        playback_rate=float(values["playback_rate"]),
        finalize_wait_sec=float(values["finalize_wait_sec"]),
        dump_wait_sec=float(values["dump_wait_sec"]),
        trajectory_filename=str(values["trajectory_filename"]),
        lock_path=lock_path,
        quarantine_dir=quarantine_dir,
        node_command=str(values["node_command"]),
        dump_policy=str(values["dump_policy"]),
        node_params=dict(values["node_params"]),
        config_overrides=dict(values["config_overrides"]),
        sources=sources,
    )
