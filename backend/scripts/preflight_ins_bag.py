#!/usr/bin/env python3
"""Read-only ROS1 bag inspection in the bridge environment."""
import json
import math
import sys
from pathlib import Path

from rosbags.highlevel import AnyReader

LIDAR = "/livox_mid360/livox/lidar"
IMU = "/livox_mid360/livox/imu"
EXPECTED = {LIDAR: "livox_ros_driver2/msg/CustomMsg", IMU: "sensor_msgs/msg/Imu"}


def inspect(path: Path) -> dict:
    with AnyReader([path]) as reader:
        selected = {}
        for connection in reader.connections:
            if connection.topic in EXPECTED:
                if connection.msgtype != EXPECTED[connection.topic]:
                    raise ValueError(f"Wrong type for {connection.topic}: {connection.msgtype}")
                selected[connection.topic] = connection
        if set(selected) != set(EXPECTED):
            raise ValueError(f"Missing required topics: {sorted(set(EXPECTED) - set(selected))}")
        counts = {topic: conn.msgcount for topic, conn in selected.items()}
        if min(counts.values()) <= 0:
            raise ValueError("Required topic is empty")
        sampled = {LIDAR: 0, IMU: 0}
        for connection, stamp, raw in reader.messages(connections=list(selected.values())):
            topic = connection.topic
            if sampled[topic] >= 3:
                if all(value >= 3 for value in sampled.values()):
                    break
                continue
            msg = reader.deserialize(raw, connection.msgtype)
            if topic == LIDAR:
                if not msg.points or int(msg.point_num) != len(msg.points):
                    raise ValueError("Livox point_num/points mismatch")
                if not hasattr(msg, "timebase") or not hasattr(msg.header, "stamp"):
                    raise ValueError("Livox time fields missing")
                for point in msg.points[:5]:
                    if not all(math.isfinite(float(getattr(point, field))) for field in ("x", "y", "z", "reflectivity")):
                        raise ValueError("Nonfinite Livox point")
                    if int(point.offset_time) < 0:
                        raise ValueError("Invalid Livox offset_time")
            else:
                if not hasattr(msg.header, "stamp"):
                    raise ValueError("IMU header timestamp missing")
                if not all(math.isfinite(float(getattr(msg.linear_acceleration, field))) for field in ("x", "y", "z")):
                    raise ValueError("Nonfinite IMU acceleration")
            sampled[topic] += 1
        if not all(sampled.values()):
            raise ValueError("Could not deserialize both required topics")
        return {"bag_format": "ROS1 bag v2", "topics": {topic: {"type": EXPECTED[topic], "count": counts[topic]} for topic in EXPECTED}, "sampled_messages": sampled}


if __name__ == "__main__":
    try:
        print(json.dumps(inspect(Path(sys.argv[1]))))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
