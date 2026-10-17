#!/usr/bin/env python3
"""Streaming, CPU-only validation of a configured ROS1 Livox CustomMsg bag."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.device_config_service import load_device  # noqa: E402

NS = 1_000_000_000


def inspection_settings(device: dict) -> dict:
    sensor = device["sensor"]
    lidar, imu = sensor["lidar"], sensor["imu"]
    return {
        "lidar_topic": lidar["topic"], "imu_topic": imu["topic"],
        "expected": {lidar["topic"]: lidar["message_type"], imu["topic"]: imu["message_type"]},
        "frames": {lidar["topic"]: lidar["frame_id"], imu["topic"]: imu["frame_id"]},
        "bounds": device["preflight"],
    }


def stamp_ns(stamp):
    sec, nsec = int(stamp.sec), int(stamp.nanosec)
    if sec < 0 or not 0 <= nsec < NS:
        raise ValueError("Invalid ROS header timestamp")
    return sec * NS + nsec


def finite_xyz(value, label):
    xyz = tuple(float(getattr(value, axis)) for axis in "xyz")
    if not all(math.isfinite(x) for x in xyz):
        raise ValueError(f"Nonfinite {label}")
    return xyz


def inspect(path: Path, device: dict) -> dict:
    from rosbags.highlevel import AnyReader
    settings = inspection_settings(device)
    lidar_topic, imu_topic = settings["lidar_topic"], settings["imu_topic"]
    expected, frames, bounds = settings["expected"], settings["frames"], settings["bounds"]
    with path.open("rb") as handle:
        if handle.read(13) != b"#ROSBAG V2.0\n":
            raise ValueError("Only ROS1 bag v2.0 is supported")
    stats = {topic: {"count": 0, "first_record_ns": None, "last_record_ns": None,
                     "first_header_ns": None, "last_header_ns": None,
                     "max_header_gap_ns": 0} for topic in expected}
    warnings = []
    point_count = 0
    max_offset = 0
    max_timebase_delta = 0
    invalid_points = 0
    empty_frames = 0
    mismatched_frames = 0
    range_empty_frames = 0
    with AnyReader([path]) as reader:
        selected = {}
        for connection in reader.connections:
            if connection.topic in expected:
                if connection.msgtype != expected[connection.topic]:
                    raise ValueError(f"Wrong type for {connection.topic}: {connection.msgtype}; expected {expected[connection.topic]}")
                if connection.topic in selected:
                    raise ValueError(f"Multiple connections for {connection.topic}")
                selected[connection.topic] = connection
        if set(selected) != set(expected):
            raise ValueError(f"Missing required topics: {sorted(set(expected) - set(selected))}")
        for connection, record_ns, raw in reader.messages(connections=list(selected.values())):
            topic = connection.topic
            stat = stats[topic]
            try:
                msg = reader.deserialize(raw, connection.msgtype)
                header_ns = stamp_ns(msg.header.stamp)
                if msg.header.frame_id != frames[topic]:
                    raise ValueError(f"Frame ID mismatch on {topic}: {msg.header.frame_id!r}")
                if stat["last_record_ns"] is not None and record_ns <= stat["last_record_ns"]:
                    raise ValueError(f"Non-increasing or duplicate bag record time on {topic}")
                if stat["last_header_ns"] is not None and header_ns <= stat["last_header_ns"]:
                    raise ValueError(f"Non-increasing or duplicate header time on {topic}")
                if topic == lidar_topic:
                    if not hasattr(msg, "timebase"):
                        raise ValueError("Livox timebase field missing")
                    timebase_ns = int(msg.timebase)
                    if timebase_ns <= 0 or abs(timebase_ns - header_ns) > bounds["max_timebase_header_delta_ns"]:
                        raise ValueError("Livox timebase and header stamp exceed configured delta")
                    max_timebase_delta = max(max_timebase_delta, abs(timebase_ns - header_ns))
                    if not msg.points:
                        empty_frames += 1
                    if int(msg.point_num) != len(msg.points):
                        mismatched_frames += 1
                    usable = 0
                    for point in msg.points:
                        try:
                            xyz = finite_xyz(point, "Livox point")
                            if not math.isfinite(float(point.reflectivity)):
                                raise ValueError("Nonfinite Livox reflectivity")
                            offset = int(point.offset_time)
                            if not 0 <= offset <= bounds["max_point_offset_ns"]:
                                raise ValueError("Livox offset_time outside configured bounds")
                            max_offset = max(max_offset, offset)
                            distance = math.sqrt(sum(x * x for x in xyz))
                            usable += bounds["min_range_m"] < distance < bounds["max_range_m"]
                        except (ValueError, TypeError, AttributeError, OverflowError):
                            invalid_points += 1
                    point_count += len(msg.points)
                    if msg.points and not usable:
                        range_empty_frames += 1
                else:
                    finite_xyz(msg.linear_acceleration, "IMU acceleration")
                    finite_xyz(msg.angular_velocity, "IMU angular velocity")
                    # ROS convention: orientation_covariance[0] == -1 means unavailable.
                    if float(msg.orientation_covariance[0]) != -1:
                        quat = (msg.orientation.x, msg.orientation.y, msg.orientation.z, msg.orientation.w)
                        if not all(math.isfinite(float(v)) for v in quat):
                            raise ValueError("Nonfinite IMU orientation")
            except Exception as exc:
                raise ValueError(f"{topic} message {stat['count'] + 1}: {exc}") from exc
            stat["count"] += 1
            if stat["last_header_ns"] is not None:
                stat["max_header_gap_ns"] = max(stat["max_header_gap_ns"], header_ns - stat["last_header_ns"])
            if stat["first_record_ns"] is None:
                stat["first_record_ns"] = int(record_ns)
                stat["first_header_ns"] = header_ns
            stat["last_record_ns"] = int(record_ns)
            stat["last_header_ns"] = header_ns
    if any(stat["count"] == 0 for stat in stats.values()):
        raise ValueError("Required LiDAR or IMU topic is empty")
    if invalid_points or empty_frames or mismatched_frames or range_empty_frames:
        raise ValueError(f"LiDAR structural errors: invalid_points={invalid_points}, empty_frames={empty_frames}, "
                         f"point_count_mismatch_frames={mismatched_frames}, range_empty_frames={range_empty_frames}")
    lidar, imu = stats[lidar_topic], stats[imu_topic]
    overlap = min(lidar["last_header_ns"], imu["last_header_ns"]) - max(lidar["first_header_ns"], imu["first_header_ns"])
    lidar_span = max(lidar["last_header_ns"] - lidar["first_header_ns"], 1)
    if overlap <= 0 or overlap / lidar_span < 0.95:
        raise ValueError("IMU header time covers less than 95% of LiDAR header time range")
    if imu["max_header_gap_ns"] > NS:
        raise ValueError("IMU has a header timestamp gap over 1 second")
    if imu["first_header_ns"] > lidar["first_header_ns"] or imu["last_header_ns"] < lidar["last_header_ns"]:
        warnings.append("IMU does not cover both LiDAR time-range edges; runtime initialization may lose frames")
    if imu["max_header_gap_ns"] > 200_000_000:
        warnings.append("IMU has a header timestamp gap over 0.2 s; check acquisition continuity")
    if max_offset > bounds["warn_point_offset_ns"]:
        warnings.append("Per-point offset exceeds 0.2 s; confirm scan duration for this device configuration")
    return {"bag_format": "ROS1 bag v2.0", "topics": {
        topic: {"type": expected[topic], **stat} for topic, stat in stats.items()},
        "points_checked": point_count, "invalid_points": invalid_points, "empty_frames": empty_frames,
        "point_count_mismatch_frames": mismatched_frames, "range_empty_frames": range_empty_frames,
        "max_point_offset_ns": max_offset, "warnings": warnings,
        "max_timebase_header_delta_ns": max_timebase_delta,
        "checks": {"time_order": "strict per topic for record and header timestamps",
                   "imu_coverage": "at least 95% of LiDAR header span",
                   "point_offset": [0, bounds["max_point_offset_ns"]],
                   "range_filter_m": [bounds["min_range_m"], bounds["max_range_m"]]}}


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("bag", type=Path)
        parser.add_argument("--device-config", type=Path, required=True)
        args = parser.parse_args()
        device = load_device(args.device_config.stem, args.device_config.parent)
        print(json.dumps(inspect(args.bag, device)))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
