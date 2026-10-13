from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

import glim_ros1_bridge as bridge  # noqa: E402
from app.services import pose_timestamp_service as ts  # noqa: E402


class FakePublisher:
    def __init__(self, subscribers: int):
        self.subscribers = subscribers

    def get_subscription_count(self) -> int:
        return self.subscribers


class BagIndexFormatTests(unittest.TestCase):
    """docs/pose-timestamp-contract.md §2: record/sensor time per LiDAR frame."""

    def test_header_is_a_comment_and_rows_are_tab_separated(self):
        self.assertTrue(bridge.BAG_INDEX_HEADER.startswith("#"))
        row = bridge.format_bag_index_row(1_717_493_096_002_225_000,
                                          1_717_493_096_000_000_000, 20160)
        self.assertTrue(row.endswith("\n"))
        self.assertEqual(row.strip().split("\t"),
                         ["1717493096002225000", "1717493096000000000", "20160"])

    def test_written_index_is_readable_by_the_timestamp_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bag_index.tsv"
            path.write_text(
                bridge.BAG_INDEX_HEADER
                + bridge.format_bag_index_row(2_000_000_000, 1_900_000_000, 20160)
                + bridge.format_bag_index_row(2_100_000_000, 2_000_000_000, 20160),
                encoding="utf-8",
            )
            frames = ts.read_bag_frame_index(path)
        self.assertEqual(frames[0].record_time_ns, 2_000_000_000)
        self.assertEqual(frames[0].sensor_time_ns, 1_900_000_000)
        self.assertEqual(frames[0].point_count, 20160)

    def test_point_packing_matches_the_documented_pointcloud2_layout(self):
        points = [
            SimpleNamespace(x=1.0, y=2.0, z=3.0, reflectivity=7.0, offset_time=12345),
            SimpleNamespace(x=-1.0, y=0.5, z=0.25, reflectivity=0.0, offset_time=100329213),
        ]
        data = bridge.pack_points(points)
        self.assertEqual(len(data), 2 * bridge.POINT_STEP)
        self.assertEqual(struct.unpack_from("<ffffI", data, 0),
                         (1.0, 2.0, 3.0, 7.0, 12345))
        self.assertEqual(struct.unpack_from("<ffffI", data, bridge.POINT_STEP),
                         (-1.0, 0.5, 0.25, 0.0, 100329213))

    def test_subscriber_wait_returns_as_soon_as_glim_subscribes(self):
        messages: list[str] = []
        self.assertTrue(bridge.wait_for_subscriber(FakePublisher(1), 1.0, messages.append))
        self.assertEqual(messages, [])

    def test_subscriber_wait_times_out_without_a_subscriber(self):
        messages: list[str] = []
        self.assertFalse(bridge.wait_for_subscriber(FakePublisher(0), 0.0, messages.append))
        self.assertEqual(len(messages), 1)
        self.assertIn("no subscriber", messages[0])


class BridgeArgumentTests(unittest.TestCase):
    """The bridge must fail before touching ROS2 when its inputs are wrong."""

    def base_args(self, **overrides) -> list[str]:
        args = {
            "--bag": "does-not-exist.bag",
            "--lidar-topic": "/lidar",
            "--imu-topic": "/imu",
            "--points-out": "/out/points",
            "--imu-out": "/out/imu",
            "--lidar-frame": "lidar_frame",
            "--imu-frame": "imu_frame",
            "--bag-index": "bag_index.tsv",
        }
        args.update(overrides)
        argv: list[str] = []
        for key, value in args.items():
            argv.extend([key, str(value)])
        return argv

    def test_missing_bag_fails_without_importing_ros(self):
        self.assertEqual(bridge.main(self.base_args()), 2)

    def test_non_positive_playback_rate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bag = Path(tmp) / "source.bag"
            bag.write_bytes(b"bag")
            self.assertEqual(bridge.main(self.base_args(**{"--bag": str(bag), "--rate": "0"})), 2)

    def test_cli_contract_matches_the_adapter_builder(self):
        parsed = bridge.build_parser().parse_args(self.base_args())
        self.assertEqual(parsed.lidar_topic, "/lidar")
        self.assertEqual(parsed.imu_topic, "/imu")
        self.assertEqual(parsed.lidar_frame, "lidar_frame")
        self.assertEqual(parsed.imu_frame, "imu_frame")
        self.assertEqual(parsed.max_lidar_frames, 0)
        self.assertEqual(parsed.max_duration_sec, 0.0)
        self.assertEqual(parsed.rate, 1.0)


if __name__ == "__main__":
    unittest.main()
