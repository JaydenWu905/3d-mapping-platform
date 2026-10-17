"""Versioned, server-owned sensor profiles for upload, preflight and adapters."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT, PROJECT_ROOT

DEVICE_CONFIG_DIR = BACKEND_ROOT / "config" / "upload_devices"
MACHINE_RUNTIME_PATH = PROJECT_ROOT / "ops" / "device_runtime.json"
SUPPORTED_LIDAR_TYPE = "livox_ros_driver2/msg/CustomMsg"
SUPPORTED_IMU_TYPE = "sensor_msgs/msg/Imu"
SUPPORTED_MRHASH_PROFILE = "ins_livox_mid360_custom"
SUPPORTED_MRHASH_CONFIG = "ins_livox_mid360.cfg"


class DeviceConfigError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeviceConfigError(message)


def resolve_glim_preset(preset_id: str) -> str:
    try:
        runtime = json.loads(MACHINE_RUNTIME_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeviceConfigError(f"Cannot read ops/device_runtime.json: {exc}") from exc
    value = (runtime.get("glim_config_presets") or {}).get(preset_id)
    _require(isinstance(value, str) and bool(value) and not Path(value).is_absolute()
             and ".." not in Path(value).parts,
             f"GLIM config preset {preset_id} is not a safe installed workspace path")
    return value


def load_device(device_id: str, config_dir: Path = DEVICE_CONFIG_DIR) -> dict[str, Any]:
    _require(bool(re.fullmatch(r"[a-z][a-z0-9_]*", device_id)), "Invalid device profile ID")
    path = config_dir / f"{device_id}.json"
    _require(path.is_file(), f"Unknown device profile: {device_id}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeviceConfigError(f"Invalid device profile {device_id}: {exc}") from exc
    _require(isinstance(raw, dict), f"Device profile {device_id} must be a JSON object")
    _require(raw.get("id") == device_id and raw.get("schema_version") == 2,
             f"Device profile {device_id} has inconsistent ID or schema version")
    _require(isinstance(raw.get("version"), str) and bool(raw["version"]),
             "Device profile version is required")
    sensor = raw.get("sensor") or {}
    lidar, imu = sensor.get("lidar") or {}, sensor.get("imu") or {}
    _require(sensor.get("bag_format") == "ROS1 bag v2.0", "Only ROS1 bag v2.0 is supported")
    for label, part in (("LiDAR", lidar), ("IMU", imu)):
        _require(all(isinstance(part.get(key), str) and part[key].strip()
                     for key in ("topic", "message_type", "frame_id")),
                 f"{label} topic, message_type and frame_id are required")
    _require(lidar["topic"] != imu["topic"], "LiDAR and IMU topics must differ")
    _require(lidar["message_type"] == SUPPORTED_LIDAR_TYPE,
             f"Unsupported LiDAR message type {lidar['message_type']}; bridge and MrHash reader support {SUPPORTED_LIDAR_TYPE} only")
    _require(imu["message_type"] == SUPPORTED_IMU_TYPE,
             f"Unsupported IMU message type {imu['message_type']}; bridge supports {SUPPORTED_IMU_TYPE} only")
    calibration = raw.get("calibration") or {}
    transform = calibration.get("T_lidar_imu")
    _require(isinstance(transform, list) and len(transform) == 7 and all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in transform), "T_lidar_imu must contain seven finite numbers")
    _require(abs(math.sqrt(sum(value * value for value in transform[3:])) - 1.0) < 1e-3,
             "T_lidar_imu quaternion must have unit length")
    _require(calibration.get("transform_direction") == "T_lidar_imu" and
             calibration.get("quaternion_order") == "qx qy qz qw" and
             calibration.get("translation_unit") == "meter",
             "Calibration must declare T_lidar_imu in meters with qx qy qz qw")
    _require(calibration.get("imu_acceleration_input_unit") in ("g", "m/s^2"),
             "IMU acceleration unit must be g or m/s^2")
    _require(all(isinstance(calibration.get(key), str) and bool(calibration[key])
                 for key in ("status", "source")),
             "Calibration status and source are required for traceability")
    capture = raw.get("capture") or {}
    _require(capture.get("point_offset_unit") == "nanosecond relative to LiDAR header stamp",
             "Livox CustomMsg offset_time must be nanoseconds relative to LiDAR header stamp")
    _require(isinstance(capture.get("imu_selection"), str) and bool(capture["imu_selection"]),
             "Capture IMU selection must identify the IMU used for GLIM")
    glim = (raw.get("algorithms") or {}).get("glim") or {}
    mrhash = (raw.get("algorithms") or {}).get("mrhash") or {}
    _require(mrhash.get("profile_id") == SUPPORTED_MRHASH_PROFILE and
             mrhash.get("reader_format") == "livox_custom" and
             mrhash.get("reference_config") == SUPPORTED_MRHASH_CONFIG,
             "Unsupported MrHash reader/profile; a new message format needs reader adaptation")
    _require(isinstance(glim.get("config_preset"), str) and bool(glim["config_preset"]),
             "GLIM config_preset is required")
    resolve_glim_preset(glim["config_preset"])
    for key in ("acc_scale", "perpoint_time_scale"):
        value = glim.get(key)
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and
                 math.isfinite(value) and value > 0, f"GLIM {key} must be positive")
    _require(isinstance(glim.get("perpoint_relative_time"), bool),
             "GLIM perpoint_relative_time must be boolean")
    _require(glim["perpoint_relative_time"] is True and
             abs(glim["perpoint_time_scale"] - 1e-9) < 1e-15,
             "Livox CustomMsg offset_time requires relative time and 1e-9 seconds per nanosecond")
    expected_acc_scale = 9.80665 if calibration["imu_acceleration_input_unit"] == "g" else 1.0
    _require(abs(glim["acc_scale"] - expected_acc_scale) < 1e-4,
             "GLIM acc_scale does not match the declared IMU acceleration unit")
    preflight = raw.get("preflight") or {}
    for key in ("max_point_offset_ns", "warn_point_offset_ns", "max_timebase_header_delta_ns"):
        _require(isinstance(preflight.get(key), int) and preflight[key] > 0,
                 f"Preflight {key} must be a positive integer")
    for key in ("min_range_m", "max_range_m"):
        _require(isinstance(preflight.get(key), (int, float)) and preflight[key] > 0,
                 f"Preflight {key} must be positive")
    _require(preflight["min_range_m"] < preflight["max_range_m"],
             "Preflight minimum range must be below maximum range")
    _require(preflight["warn_point_offset_ns"] <= preflight["max_point_offset_ns"],
             "Preflight point offset warning threshold must not exceed rejection threshold")
    camera = raw.get("camera") or {}
    _require(camera.get("rgb_consumed_by_current_pipeline") is False and
             camera.get("depth_consumed_by_current_pipeline") is False,
             "RGB/depth is not consumed by the current GLIM/MrHash LiDAR pipeline")
    raw["config_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    raw["config_file"] = path.name
    return raw


def list_devices(config_dir: Path = DEVICE_CONFIG_DIR) -> list[dict[str, Any]]:
    devices = []
    for path in sorted(config_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 2:
            continue
        if raw.get("enabled", True):
            devices.append(load_device(raw["id"], config_dir))
    return devices


def effective_pose(device: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    sensor = device["sensor"]
    glim = device["algorithms"]["glim"]
    pose = dict(base)
    pose.update(backend="glim", lidar_topic=sensor["lidar"]["topic"],
                imu_topic=sensor["imu"]["topic"],
                lidar_frame_id=sensor["lidar"]["frame_id"],
                imu_frame_id=sensor["imu"]["frame_id"],
                T_lidar_imu=device["calibration"]["T_lidar_imu"],
                acc_scale=glim["acc_scale"],
                perpoint_relative_time=glim["perpoint_relative_time"],
                perpoint_time_scale=glim["perpoint_time_scale"])
    pose["config_path"] = resolve_glim_preset(glim["config_preset"])
    return pose


def effective_surface(device: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    surface = dict(base)
    surface.update(backend="mrhash_lidar", topic=device["sensor"]["lidar"]["topic"],
                   mrhash_profile=device["algorithms"]["mrhash"]["profile_id"],
                   mrhash_reference_config=device["algorithms"]["mrhash"]["reference_config"],
                   integration_end_frame=None)
    return surface
