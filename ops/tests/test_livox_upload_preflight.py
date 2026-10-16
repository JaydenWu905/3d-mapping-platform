"""Run with the bridge Python; creates entirely synthetic ROS1 bags."""
import importlib.util
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from rosbags.rosbag1 import Writer
from rosbags.typesys import Stores, get_typestore, get_types_from_msg

SCRIPT = Path(__file__).resolve().parents[2] / "backend/scripts/preflight_ins_bag.py"
spec = importlib.util.spec_from_file_location("preflight_ins_bag", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)

CUSTOM_POINT = "uint32 offset_time\nfloat32 x\nfloat32 y\nfloat32 z\nuint8 reflectivity\nuint8 tag\nuint8 line\n"
CUSTOM_MSG = "std_msgs/Header header\nuint64 timebase\nuint32 point_num\nuint8 lidar_id\nuint8[3] rsvd\nlivox_ros_driver2/CustomPoint[] points\n"


class BagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.bag"
        self.store = get_typestore(Stores.ROS1_NOETIC)
        self.store.register(get_types_from_msg(CUSTOM_POINT, "livox_ros_driver2/msg/CustomPoint"))
        self.store.register(get_types_from_msg(CUSTOM_MSG, "livox_ros_driver2/msg/CustomMsg"))

    def make(self, *, lidar_count=4, imu_count=10, missing_imu=False, wrong_type=False,
             bad_point=False, duplicate_time=False, duplicate_header=False,
             bad_offset=False, bad_imu=False, bad_timebase=False, empty_frame=False,
             corrupt_message=False, imu_gap=False, wrong_frame=False, corrupt=False):
        t = self.store.types
        stamp = lambda ns: t["builtin_interfaces/msg/Time"](sec=ns // 10**9, nanosec=ns % 10**9)
        header = lambda ns, frame="livox_mid360_frame": t["std_msgs/msg/Header"](seq=0, stamp=stamp(ns), frame_id=frame)
        with Writer(self.path) as writer:
            lc = writer.add_connection(preflight.LIDAR,
                "sensor_msgs/msg/Imu" if wrong_type else preflight.EXPECTED[preflight.LIDAR], typestore=self.store)
            ic = None if missing_imu else writer.add_connection(preflight.IMU, preflight.EXPECTED[preflight.IMU], typestore=self.store)
            events = []
            for i in range(lidar_count):
                record_ns = 1_000_000_000 + i * 100_000_000
                ns = record_ns
                if (duplicate_time or duplicate_header) and i == 2: ns -= 100_000_000
                point = t["livox_ros_driver2/msg/CustomPoint"](offset_time=1_000_000_001 if bad_offset and i == 1 else 10_000_000, x=float("nan") if bad_point and i == 1 else 1.0,
                    y=0.0, z=0.0, reflectivity=10, tag=0, line=0)
                points = [] if empty_frame and i == 1 else [point]
                msg = t["livox_ros_driver2/msg/CustomMsg"](header=header(ns, "other_frame" if wrong_frame and i == 1 else "livox_mid360_frame"), timebase=ns + (100_000_000 if bad_timebase and i == 1 else 0),
                    point_num=len(points), lidar_id=0, rsvd=np.zeros(3, dtype=np.uint8), points=points)
                payload = b"\x00\x01" if corrupt_message and i == 1 else self.store.serialize_ros1(msg, preflight.EXPECTED[preflight.LIDAR])
                events.append(((ns if duplicate_time else record_ns) + 1, lc, payload))
            if ic:
                for i in range(imu_count):
                    if imu_gap and 5 <= i <= 34:
                        continue
                    ns = 950_000_000 + i * 50_000_000
                    msg = t["sensor_msgs/msg/Imu"](header=header(ns, "livox_frame"),
                        orientation=t["geometry_msgs/msg/Quaternion"](x=0., y=0., z=0., w=0.),
                        orientation_covariance=np.array([-1.] + [0.] * 8),
                        angular_velocity=t["geometry_msgs/msg/Vector3"](x=0., y=0., z=0.),
                        angular_velocity_covariance=np.zeros(9),
                        linear_acceleration=t["geometry_msgs/msg/Vector3"](x=float("nan") if bad_imu and i == 2 else 0., y=0., z=1.),
                        linear_acceleration_covariance=np.zeros(9))
                    events.append((ns + 1, ic, self.store.serialize_ros1(msg, preflight.EXPECTED[preflight.IMU])))
            for ns, conn, raw in sorted(events, key=lambda item: item[0]): writer.write(conn, ns, raw)
        if corrupt:
            with self.path.open("r+b") as handle: handle.write(b"broken format!")

    def test_different_counts_and_time_range_are_measured(self):
        self.make(lidar_count=4, imu_count=10)
        result = preflight.inspect(self.path)
        self.assertEqual(result["topics"][preflight.LIDAR]["count"], 4)
        self.assertEqual(result["topics"][preflight.IMU]["count"], 10)
        self.assertEqual(result["points_checked"], 4)
        self.assertEqual(result["topics"][preflight.LIDAR]["first_header_ns"], 1_000_000_000)

    def test_missing_wrong_corrupt_and_time(self):
        for options, error in [({"missing_imu": True}, "Missing required"),
                               ({"wrong_type": True}, "Wrong type"),
                               ({"bad_point": True}, "invalid_points=1"),
                               ({"bad_offset": True}, "invalid_points=1"),
                               ({"empty_frame": True}, "empty_frames=1"),
                               ({"bad_imu": True}, "Nonfinite IMU acceleration"),
                               ({"bad_timebase": True}, "timebase and header"),
                               ({"wrong_frame": True}, "Frame ID mismatch"),
                               ({"corrupt_message": True}, "lidar message 2"),
                               ({"duplicate_time": True}, "duplicate bag record time"),
                               ({"duplicate_header": True}, "duplicate header time"),
                               ({"imu_count": 3}, "covers less than 95%"),
                               ({"imu_count": 40, "imu_gap": True}, "gap over 1 second"),
                               ({"corrupt": True}, "ROS1 bag v2")]:
            with self.subTest(options=options):
                self.path.unlink(missing_ok=True)
                self.make(**options)
                with self.assertRaisesRegex(ValueError, error): preflight.inspect(self.path)

    def test_synthetic_bag_upload_registers_observed_sequence(self):
        self.make(lidar_count=5, imu_count=12)
        from sys import path as sys_path
        backend = SCRIPT.parents[1]
        sys_path.insert(0, str(backend))
        from app.services.upload_service import UploadService, NEW_PROFILE_ID
        platform = Path(self.tmp.name) / "platform"
        registry = platform / "backend/config/datasets"
        registry.mkdir(parents=True)
        template = SCRIPT.parents[1] / "config/datasets/ins_longcorridor01.json"
        device = SCRIPT.parents[1] / "config/upload_devices/ins_mid360_handoff.json"
        service = UploadService(platform / "uploads", template, device)
        raw = self.path.read_bytes()

        async def upload():
            state = service.create("new-capture.bag", len(raw), NEW_PROFILE_ID, True)
            async def stream(): yield raw
            await service.chunk(state["upload_id"], 0, hashlib.sha256(raw).hexdigest(), stream())
            return await service.finalize(state["upload_id"])

        with patch("app.services.upload_service.PROJECT_ROOT", platform), \
             patch("app.services.upload_service.DATASETS_CONFIG_DIR", registry), \
             patch.object(UploadService, "_preflight", side_effect=preflight.inspect):
            result = asyncio.run(upload())
        definition = json.loads((registry / f"{result['dataset_id']}.json").read_text())
        self.assertEqual(definition["input_manifest"]["bag_message_count"], 5)
        self.assertEqual(definition["input_manifest"]["sequence_observed"]["imu"]["count"], 12)
        self.assertEqual(definition["integrity"]["bag_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIsNone(definition["surface"]["integration_end_frame"])


if __name__ == "__main__": unittest.main()
