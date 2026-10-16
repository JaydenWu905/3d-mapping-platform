#!/usr/bin/env python3
"""Streaming, CPU-only validation of a ROS1 Livox MID-360 bag."""
import json
import math
import sys
from pathlib import Path

from rosbags.highlevel import AnyReader

LIDAR = "/livox_mid360/livox/lidar"
IMU = "/livox_mid360/livox/imu"
EXPECTED = {LIDAR: "livox_ros_driver2/msg/CustomMsg", IMU: "sensor_msgs/msg/Imu"}
FRAMES = {LIDAR: "livox_mid360_frame", IMU: "livox_frame"}
NS = 1_000_000_000
MAX_POINT_OFFSET_NS = NS
WARN_POINT_OFFSET_NS = 200_000_000
MAX_TIMEBASE_DELTA_NS = 50_000_000
MIN_RANGE_M, MAX_RANGE_M = 0.2, 100.0


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


def inspect(path: Path) -> dict:
    with path.open("rb") as handle:
        if handle.read(13) != b"#ROSBAG V2.0\n":
            raise ValueError("Only ROS1 bag v2.0 is supported")
    stats = {topic: {"count": 0, "first_record_ns": None, "last_record_ns": None,
                     "first_header_ns": None, "last_header_ns": None,
                     "max_header_gap_ns": 0} for topic in EXPECTED}
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
            if connection.topic in EXPECTED:
                if connection.msgtype != EXPECTED[connection.topic]:
                    raise ValueError(f"Wrong type for {connection.topic}: {connection.msgtype}")
                if connection.topic in selected:
                    raise ValueError(f"Multiple connections for {connection.topic}")
                selected[connection.topic] = connection
        if set(selected) != set(EXPECTED):
            raise ValueError(f"Missing required topics: {sorted(set(EXPECTED) - set(selected))}")
        for connection, record_ns, raw in reader.messages(connections=list(selected.values())):
            topic = connection.topic
            stat = stats[topic]
            try:
                msg = reader.deserialize(raw, connection.msgtype)
                header_ns = stamp_ns(msg.header.stamp)
                if msg.header.frame_id != FRAMES[topic]:
                    raise ValueError(f"Frame ID mismatch on {topic}: {msg.header.frame_id!r}")
                if stat["last_record_ns"] is not None and record_ns <= stat["last_record_ns"]:
                    raise ValueError(f"Non-increasing or duplicate bag record time on {topic}")
                if stat["last_header_ns"] is not None and header_ns <= stat["last_header_ns"]:
                    raise ValueError(f"Non-increasing or duplicate header time on {topic}")
                if topic == LIDAR:
                    if not hasattr(msg, "timebase"):
                        raise ValueError("Livox timebase field missing")
                    timebase_ns = int(msg.timebase)
                    if timebase_ns <= 0 or abs(timebase_ns - header_ns) > MAX_TIMEBASE_DELTA_NS:
                        raise ValueError("Livox timebase and header stamp differ by more than 0.05 s")
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
                            if not 0 <= offset <= MAX_POINT_OFFSET_NS:
                                raise ValueError("Livox offset_time outside 0..1 second")
                            max_offset = max(max_offset, offset)
                            distance = math.sqrt(sum(x * x for x in xyz))
                            usable += MIN_RANGE_M < distance < MAX_RANGE_M
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
    lidar, imu = stats[LIDAR], stats[IMU]
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
    if max_offset > WARN_POINT_OFFSET_NS:
        warnings.append("Per-point offset exceeds 0.2 s; confirm scan duration for this device configuration")
    return {"bag_format": "ROS1 bag v2.0", "topics": {
        topic: {"type": EXPECTED[topic], **stat} for topic, stat in stats.items()},
        "points_checked": point_count, "invalid_points": invalid_points, "empty_frames": empty_frames,
        "point_count_mismatch_frames": mismatched_frames, "range_empty_frames": range_empty_frames,
        "max_point_offset_ns": max_offset, "warnings": warnings,
        "max_timebase_header_delta_ns": max_timebase_delta,
        "checks": {"time_order": "strict per topic for record and header timestamps",
                   "imu_coverage": "at least 95% of LiDAR header span",
                   "point_offset": "0..1 second, warning above 0.2 second",
                   "range_filter_m": [MIN_RANGE_M, MAX_RANGE_M]}}


if __name__ == "__main__":
    try:
        print(json.dumps(inspect(Path(sys.argv[1]))))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
