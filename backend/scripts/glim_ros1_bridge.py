#!/usr/bin/env python3
"""Stream a ROS1 Livox bag into ROS2 topics for GLIM, recording a frame index.

Responsibilities (docs/pose-timestamp-contract.md §2):

* ROS1 ``livox_ros_driver2/msg/CustomMsg`` + ``sensor_msgs/msg/Imu``
  ->  ROS2 ``sensor_msgs/msg/PointCloud2`` + ``sensor_msgs/msg/Imu``;
* ``PointCloud2`` fields ``x y z`` (FLOAT32), ``intensity`` (FLOAT32) and
  ``t`` (UINT32, nanoseconds, ``t = Livox CustomPoint.offset_time``);
* ``bag_index.tsv`` — one row per LiDAR frame with
  ``record_timestamp_ns  sensor_timestamp_ns  point_count``.  This file is the
  only legitimate basis for the Pose/Surface timestamp association: it comes
  from the real bag, never from a fixed offset such as "-0.1 s".

ROS2 and ``rosbags`` are imported inside :func:`main` so that the pure helpers
stay importable (and unit testable) without a ROS installation.
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

#: PointCloud2 layout published to GLIM: 5 fields, 20 bytes per point.
POINT_STEP = 20
BAG_INDEX_HEADER = "# record_timestamp_ns\tsensor_timestamp_ns\tpoint_count\n"


def format_bag_index_row(record_time_ns: int, sensor_time_ns: int, point_count: int) -> str:
    """One ``bag_index.tsv`` row (tab separated, trailing newline)."""
    return f"{int(record_time_ns)}\t{int(sensor_time_ns)}\t{int(point_count)}\n"


def pack_points(points) -> bytes:
    """Pack Livox CustomPoints into the ``x y z intensity t`` buffer."""
    buffer = bytearray(len(points) * POINT_STEP)
    for index, point in enumerate(points):
        struct.pack_into(
            "<ffffI", buffer, index * POINT_STEP,
            float(point.x), float(point.y), float(point.z),
            float(point.reflectivity), int(point.offset_time),
        )
    return bytes(buffer)


def wait_for_subscriber(publisher, timeout_sec: float, log) -> bool:
    """Wait until GLIM subscribes to the points topic (or the timeout expires)."""
    deadline = time.monotonic() + max(timeout_sec, 0.0)
    while time.monotonic() < deadline:
        if publisher.get_subscription_count() > 0:
            return True
        time.sleep(0.2)
    log(f"no subscriber appeared within {timeout_sec:.1f}s; streaming anyway "
        "(GLIM may still be starting up)")
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    parser.add_argument("--lidar-topic", required=True)
    parser.add_argument("--imu-topic", required=True)
    parser.add_argument("--points-out", required=True)
    parser.add_argument("--imu-out", required=True)
    parser.add_argument("--lidar-frame", required=True)
    parser.add_argument("--imu-frame", required=True)
    parser.add_argument("--bag-index", type=Path, required=True,
                        help="where to write the record/sensor timestamp index")
    parser.add_argument("--rate", type=float, default=1.0,
                        help="playback rate multiplier (1.0 = real time)")
    parser.add_argument("--max-lidar-frames", type=int, default=0,
                        help="stop after N LiDAR frames (0 = no limit)")
    parser.add_argument("--max-duration-sec", type=float, default=0.0,
                        help="stop after N seconds of bag time (0 = no limit)")
    parser.add_argument("--expected-lidar-frames", type=int, default=0,
                        help="hint used only to render progress percentages")
    parser.add_argument("--subscriber-wait-sec", type=float, default=15.0)
    parser.add_argument("--progress-every", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate <= 0:
        print("bridge: --rate must be positive", file=sys.stderr, flush=True)
        return 2
    if not args.bag.is_file():
        print(f"bridge: bag not found: {args.bag}", file=sys.stderr, flush=True)
        return 2

    # ROS2 / rosbags are only needed for a real run.
    import rclpy  # noqa: PLC0415
    from rclpy.node import Node  # noqa: PLC0415
    from rclpy.qos import qos_profile_sensor_data  # noqa: PLC0415
    from rosbags.highlevel import AnyReader  # noqa: PLC0415
    from sensor_msgs.msg import Imu, PointCloud2, PointField  # noqa: PLC0415

    def log(message: str) -> None:
        print(f"[bridge] {message}", flush=True)

    class Bridge(Node):
        def __init__(self) -> None:
            super().__init__("mapping_glim_ros1_bridge")
            self.pub_points = self.create_publisher(
                PointCloud2, args.points_out, qos_profile_sensor_data
            )
            self.pub_imu = self.create_publisher(Imu, args.imu_out, qos_profile_sensor_data)
            self.lidar_count = 0
            self.imu_count = 0

        @staticmethod
        def copy_stamp(dst, src) -> None:
            dst.sec = int(src.sec)
            dst.nanosec = int(src.nanosec)

        def publish_imu(self, message) -> None:
            out = Imu()
            self.copy_stamp(out.header.stamp, message.header.stamp)
            out.header.frame_id = args.imu_frame
            out.orientation.x = float(message.orientation.x)
            out.orientation.y = float(message.orientation.y)
            out.orientation.z = float(message.orientation.z)
            out.orientation.w = float(message.orientation.w)
            out.angular_velocity.x = float(message.angular_velocity.x)
            out.angular_velocity.y = float(message.angular_velocity.y)
            out.angular_velocity.z = float(message.angular_velocity.z)
            # Raw MID-360 acceleration is kept in g; GLIM applies acc_scale.
            out.linear_acceleration.x = float(message.linear_acceleration.x)
            out.linear_acceleration.y = float(message.linear_acceleration.y)
            out.linear_acceleration.z = float(message.linear_acceleration.z)
            out.orientation_covariance = list(message.orientation_covariance)
            out.angular_velocity_covariance = list(message.angular_velocity_covariance)
            out.linear_acceleration_covariance = list(message.linear_acceleration_covariance)
            self.pub_imu.publish(out)
            self.imu_count += 1

        def publish_lidar(self, message) -> None:
            count = len(message.points)
            out = PointCloud2()
            self.copy_stamp(out.header.stamp, message.header.stamp)
            out.header.frame_id = args.lidar_frame
            out.height = 1
            out.width = count
            out.fields = [
                PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
                PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
                PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
                PointField(name="intensity", offset=12, datatype=PointField.FLOAT32, count=1),
                PointField(name="t", offset=16, datatype=PointField.UINT32, count=1),
            ]
            out.is_bigendian = False
            out.point_step = POINT_STEP
            out.row_step = POINT_STEP * count
            out.data = pack_points(message.points)
            out.is_dense = True
            self.pub_points.publish(out)
            self.lidar_count += 1

    rclpy.init()
    node = Bridge()
    exit_code = 0
    try:
        if not args.bag_index.parent.exists():
            args.bag_index.parent.mkdir(parents=True, exist_ok=True)
        with args.bag_index.open("w", encoding="utf-8", newline="\n") as index_file:
            index_file.write(BAG_INDEX_HEADER)
            with AnyReader([args.bag]) as reader:
                connections = [
                    connection for connection in reader.connections
                    if connection.topic in (args.lidar_topic, args.imu_topic)
                ]
                found = {connection.topic for connection in connections}
                if found != {args.lidar_topic, args.imu_topic}:
                    missing = sorted({args.lidar_topic, args.imu_topic} - found)
                    print(
                        "bridge: configured topic(s) not present in the bag: "
                        + ", ".join(missing),
                        file=sys.stderr, flush=True,
                    )
                    return 2
                log(f"bag={args.bag.name} topics={len(connections)} rate={args.rate}")
                wait_for_subscriber(node.pub_points, args.subscriber_wait_sec, log)
                first_time = None
                wall_start = None
                last_lidar_time = None
                for connection, record_time, raw in reader.messages(connections=connections):
                    if first_time is None:
                        first_time = record_time
                        wall_start = time.monotonic()
                    if args.max_duration_sec and (record_time - first_time) / 1e9 > args.max_duration_sec:
                        log("reached --max-duration-sec, stopping")
                        break
                    delay = ((record_time - first_time) / 1e9 / args.rate) - (time.monotonic() - wall_start)
                    if delay > 0:
                        time.sleep(delay)
                    message = reader.deserialize(raw, connection.msgtype)
                    if connection.topic == args.imu_topic:
                        node.publish_imu(message)
                        continue
                    node.publish_lidar(message)
                    sensor_time = message.header.stamp
                    sensor_time_ns = int(sensor_time.sec) * 1_000_000_000 + int(sensor_time.nanosec)
                    index_file.write(format_bag_index_row(record_time, sensor_time_ns, len(message.points)))
                    last_lidar_time = record_time
                    if node.lidar_count % max(args.progress_every, 1) == 0:
                        index_file.flush()
                        elapsed = (record_time - first_time) / 1e9
                        if args.expected_lidar_frames > 0:
                            percent = min(99, int(node.lidar_count * 100 / args.expected_lidar_frames))
                            print(
                                f"processing: {percent:3d}%|bridge| "
                                f"{node.lidar_count}/{args.expected_lidar_frames} "
                                f"imu={node.imu_count} t={elapsed:.1f}s",
                                flush=True,
                            )
                        else:
                            log(f"lidar={node.lidar_count} imu={node.imu_count} t={elapsed:.1f}s")
                    if args.max_lidar_frames and node.lidar_count >= args.max_lidar_frames:
                        log(f"reached --max-lidar-frames ({args.max_lidar_frames}), stopping")
                        break
            index_file.flush()
        log(f"done lidar={node.lidar_count} imu={node.imu_count}")
        if node.lidar_count == 0:
            print("bridge: no LiDAR frame was published", file=sys.stderr, flush=True)
            exit_code = 1
        if last_lidar_time is None and exit_code == 0:
            log("warning: no LiDAR frame timestamp recorded in the bag index")
    finally:
        try:
            node.destroy_node()
        finally:
            if rclpy.ok():
                rclpy.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
