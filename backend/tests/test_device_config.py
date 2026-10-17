from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.device_config_service import (
    DEVICE_CONFIG_DIR, DeviceConfigError, effective_pose, effective_surface,
    list_devices, load_device,
)
from app.services import glim_config_service as glim_config

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import preflight_ins_bag as preflight  # noqa: E402


class DeviceConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_dir = Path(self.temp.name)
        self.ins = load_device("ins_livox_mid360_same_rig")

    def write_variant(self, *, lidar_type: str | None = None) -> dict:
        profile = copy.deepcopy(self.ins)
        profile.pop("config_sha256", None)
        profile.pop("config_file", None)
        profile.update(id="self_capture_01", version="2.3.0", enabled=True,
                       name="self capture test")
        profile["sensor"]["lidar"].update(topic="/my/livox/points", frame_id="my_lidar",
                                          message_type=lidar_type or "livox_ros_driver2/msg/CustomMsg")
        profile["sensor"]["imu"].update(topic="/my/imu/raw", frame_id="my_imu")
        profile["calibration"]["T_lidar_imu"] = [0.12, -0.03, 0.04, 0, 0, 0, 1]
        profile["algorithms"]["glim"]["acc_scale"] = 1.0
        profile["calibration"]["imu_acceleration_input_unit"] = "m/s^2"
        (self.config_dir / "self_capture_01.json").write_text(json.dumps(profile))
        return profile

    def test_alternate_topics_frames_calibration_flow_to_preflight_and_algorithms(self) -> None:
        self.write_variant()
        device = load_device("self_capture_01", self.config_dir)
        self.assertEqual([item["id"] for item in list_devices(self.config_dir)], ["self_capture_01"])
        settings = preflight.inspection_settings(device)
        self.assertEqual(settings["expected"]["/my/livox/points"], "livox_ros_driver2/msg/CustomMsg")
        self.assertEqual(settings["frames"]["/my/imu/raw"], "my_imu")
        pose = effective_pose(device, {"timestamp": {"min_matched_ratio": 0.98}})
        surface = effective_surface(device, {})
        self.assertEqual((pose["lidar_topic"], pose["imu_topic"],
                          pose["lidar_frame_id"], pose["imu_frame_id"]),
                         ("/my/livox/points", "/my/imu/raw", "my_lidar", "my_imu"))
        self.assertEqual(pose["T_lidar_imu"][:3], [0.12, -0.03, 0.04])
        self.assertEqual(pose["acc_scale"], 1.0)
        self.assertEqual(surface["topic"], "/my/livox/points")
        self.assertEqual(surface["mrhash_reference_config"], "ins_livox_mid360.cfg")
        overrides = glim_config.build_overrides(pose, points_topic="/glim/points", imu_topic="/glim/imu")
        self.assertEqual(overrides["config_ros.json"]["glim_ros"]["lidar_frame_id"], "my_lidar")
        self.assertEqual(overrides["config_ros.json"]["glim_ros"]["imu_frame_id"], "my_imu")
        self.assertEqual(overrides["config_sensors.json"]["sensors"]["T_lidar_imu"][:3],
                         [0.12, -0.03, 0.04])

    def test_unsupported_reader_type_and_camera_claim_are_rejected(self) -> None:
        profile = self.write_variant(lidar_type="sensor_msgs/msg/PointCloud2")
        with self.assertRaisesRegex(DeviceConfigError, "Unsupported LiDAR message type"):
            load_device("self_capture_01", self.config_dir)
        profile["sensor"]["lidar"]["message_type"] = "livox_ros_driver2/msg/CustomMsg"
        profile["camera"]["depth_consumed_by_current_pipeline"] = True
        (self.config_dir / "self_capture_01.json").write_text(json.dumps(profile))
        with self.assertRaisesRegex(DeviceConfigError, "RGB/depth is not consumed"):
            load_device("self_capture_01", self.config_dir)
        profile["camera"]["depth_consumed_by_current_pipeline"] = False
        profile["algorithms"]["glim"]["config_preset"] = "missing_preset"
        (self.config_dir / "self_capture_01.json").write_text(json.dumps(profile))
        with self.assertRaisesRegex(DeviceConfigError, "GLIM config preset missing_preset"):
            load_device("self_capture_01", self.config_dir)

    def test_cpu_preflight_reads_selected_topics_and_frames(self) -> None:
        self.write_variant()
        device = load_device("self_capture_01", self.config_dir)
        lidar_topic = device["sensor"]["lidar"]["topic"]
        imu_topic = device["sensor"]["imu"]["topic"]
        lidar_conn = types.SimpleNamespace(topic=lidar_topic, msgtype="livox_ros_driver2/msg/CustomMsg")
        imu_conn = types.SimpleNamespace(topic=imu_topic, msgtype="sensor_msgs/msg/Imu")

        def stamp(ns: int, frame: str):
            return types.SimpleNamespace(header=types.SimpleNamespace(
                stamp=types.SimpleNamespace(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000),
                frame_id=frame))

        def lidar(ns: int):
            msg = stamp(ns, "my_lidar")
            msg.timebase = ns
            msg.points = [types.SimpleNamespace(x=1, y=0, z=0, reflectivity=10, offset_time=100)]
            msg.point_num = 1
            return msg

        def imu(ns: int):
            msg = stamp(ns, "my_imu")
            msg.linear_acceleration = types.SimpleNamespace(x=0, y=0, z=1)
            msg.angular_velocity = types.SimpleNamespace(x=0, y=0, z=0)
            msg.orientation_covariance = [-1]
            return msg

        messages = [(imu_conn, 500_000_000, imu(500_000_000)),
                    (lidar_conn, 1_000_000_000, lidar(1_000_000_000)),
                    (imu_conn, 1_500_000_000, imu(1_500_000_000)),
                    (lidar_conn, 2_000_000_000, lidar(2_000_000_000)),
                    (imu_conn, 2_500_000_000, imu(2_500_000_000))]

        class Reader:
            connections = [lidar_conn, imu_conn]
            def __init__(self, paths):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def messages(self, connections):
                return iter(messages)
            def deserialize(self, raw, msgtype):
                return raw

        bag = self.config_dir / "sample.bag"
        bag.write_bytes(b"#ROSBAG V2.0\n")
        highlevel = types.ModuleType("rosbags.highlevel")
        highlevel.AnyReader = Reader
        with patch.dict(sys.modules, {"rosbags": types.ModuleType("rosbags"),
                                      "rosbags.highlevel": highlevel}):
            result = preflight.inspect(bag, device)
        self.assertEqual(result["topics"][lidar_topic]["count"], 2)
        self.assertEqual(result["topics"][imu_topic]["count"], 3)

    def test_ins_profile_retains_accepted_values(self) -> None:
        self.assertEqual(self.ins["sensor"]["lidar"]["topic"], "/livox_mid360/livox/lidar")
        self.assertEqual(self.ins["sensor"]["imu"]["frame_id"], "livox_frame")
        self.assertEqual(self.ins["calibration"]["T_lidar_imu"][:3], [0.011, 0.02329, -0.04412])
        self.assertEqual(self.ins["algorithms"]["glim"]["acc_scale"], 9.80665)
        self.assertEqual(self.ins["verified_reference"], {"lidar_messages": 1539, "imu_messages": 30770})
        self.assertTrue((DEVICE_CONFIG_DIR / "ins_livox_mid360_same_rig.json").is_file())
