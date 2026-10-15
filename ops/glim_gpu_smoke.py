#!/usr/bin/env python3
"""One bounded, locked INS GPU smoke run using the deployed GLIM children."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.child_supervisor import ChildSupervisor  # noqa: E402
from app.services.glim_lock import GlimExecutionLock, inspect_dump_dir  # noqa: E402
from app.services.pose_timestamp_service import (  # noqa: E402
    associate_to_bag_record_time, read_bag_frame_index, read_pose_trajectory,
    write_association_report, write_pose_trajectory,
)

RUN = Path(sys.argv[1]).resolve()
RUN.mkdir(parents=True, exist_ok=False)
CONFIG = ROOT / "ops/glim_runtime/config"
BAG = Path("/root/autodl-tmp/INS/2024-06-04-16-24-55.bag")
LOCK = ROOT / "runtime/locks/glim.lock"
DUMP = Path("/tmp/dump")
TIMEOUT = 240.0


def save(name: str, value: object) -> None:
    (RUN / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def wait_child(child: subprocess.Popen, supervisor: ChildSupervisor) -> int:
    while child.poll() is None:
        supervisor.raise_if_cancelled()
        time.sleep(0.2)
    return child.returncode


def main() -> int:
    supervisor = ChildSupervisor(timeout_sec=TIMEOUT, grace=5)
    lock = GlimExecutionLock(LOCK)
    status = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "timeout_sec": TIMEOUT, "run": str(RUN)}
    node_log = bridge_log = None
    try:
        acquired = lock.acquire(job_id=RUN.name)
        if not acquired.acquired:
            raise RuntimeError(acquired.reason)
        status["lock"] = lock.events.copy()
        status["dump_before"] = inspect_dump_dir(
            DUMP, policy="quarantine", quarantine_dir=ROOT / "runtime/quarantine",
            job_id=RUN.name)
        shutil.copytree(CONFIG, RUN / "config")
        bridge_cmd = [str(ROOT / "ops/glim-child.sh"), "bridge",
            "--bag", str(BAG), "--lidar-topic", "/livox_mid360/livox/lidar",
            "--imu-topic", "/livox_mid360/livox/imu", "--points-out", "/ins/points",
            "--imu-out", "/ins/imu", "--lidar-frame", "livox_mid360_frame",
            "--imu-frame", "livox_frame", "--bag-index", str(RUN / "bag_index.tsv"),
            "--max-lidar-frames", "250", "--progress-every", "25"]
        node_cmd = [str(ROOT / "ops/glim-child.sh"), "node"]
        status["commands"] = {"node": node_cmd, "bridge": bridge_cmd}
        status["configuration_source"] = str(CONFIG)
        status["environment"] = {"DISPLAY": os.environ.get("DISPLAY"),
            "GLIM_CONFIG_PATH": "3d-mapping-platform-deploy/ops/glim_runtime/config",
            "GLIM_ROS_SETUP": "/opt/ros/humble/setup.bash",
            "GLIM_LD_LIBRARY_PATH": "/usr/local/lib"}
        save("run_status.json", status)
        node_log = (RUN / "node.log").open("w")
        node = supervisor.register("node", subprocess.Popen(node_cmd, cwd=ROOT,
            stdout=node_log, stderr=subprocess.STDOUT))
        for _ in range(25):
            supervisor.raise_if_cancelled()
            if node.poll() is not None:
                raise RuntimeError(f"GLIM node exited during startup: {node.returncode}")
            time.sleep(0.2)
        bridge_log = (RUN / "bridge.log").open("w")
        bridge = supervisor.register("bridge", subprocess.Popen(bridge_cmd, cwd=ROOT,
            stdout=bridge_log, stderr=subprocess.STDOUT))
        status["bridge_exit_code"] = wait_child(bridge, supervisor)
        if status["bridge_exit_code"] != 0:
            raise RuntimeError("bridge failed")
        for _ in range(25):
            supervisor.raise_if_cancelled()
            time.sleep(0.2)
        if node.poll() is not None:
            raise RuntimeError(f"GLIM node exited before normal dump request: {node.returncode}")
        status["node_exit_request"] = "SIGINT (dump_on_unload=true)"
        node.send_signal(signal.SIGINT)
        dump_deadline = time.monotonic() + min(60, supervisor.remaining_sec() or 60)
        while node.poll() is None and time.monotonic() < dump_deadline:
            supervisor.raise_if_cancelled()
            time.sleep(0.2)
        if node.poll() is None:
            raise RuntimeError("GLIM node did not exit within 60 s after SIGINT")
        status["node_exit_code"] = node.returncode
        if not (DUMP / "traj_lidar.txt").is_file():
            raise RuntimeError("normal exit did not generate traj_lidar.txt")
        shutil.move(str(DUMP), str(RUN / "dump"))
        native = RUN / "dump/traj_lidar.txt"
        shutil.copy2(native, RUN / "traj_lidar.txt")
        trajectory = read_pose_trajectory(native)
        frames = read_bag_frame_index(RUN / "bag_index.tsv")
        result = associate_to_bag_record_time(frames, trajectory,
            max_delta_sec=0.05, min_matched_ratio=0.98, max_duplicate_reuse_count=0)
        write_association_report(RUN / "association.json", result.report)
        # The platform contract exposes the native clock when quality gating blocks handoff.
        rows = result.rows if result.accepted else [
            (f"{row.timestamp:.9f}", row.values) for row in trajectory]
        write_pose_trajectory(RUN / "poses.txt", rows)
        status["timestamp_basis"] = "rosbag" if result.accepted else "lidar_sensor"
        status["surface_handoff_compatible"] = result.accepted
        status["native_pose_count"] = len(trajectory)
        status["bag_frame_count"] = len(frames)
        status["success"] = True
        return 0
    except Exception as exc:
        status["error"] = str(exc)
        status["success"] = False
        return 1
    finally:
        supervisor.terminate_all()
        if node_log:
            node_log.close()
        if bridge_log:
            bridge_log.close()
        if lock._owned:
            lock.release()
        status["lock_events"] = lock.events
        status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save("run_status.json", status)


if __name__ == "__main__":
    raise SystemExit(main())
