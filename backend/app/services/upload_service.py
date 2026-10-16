"""Strict, resumable single-bag upload and atomic server-owned registration."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from app.config import BACKEND_ROOT, DATASETS_CONFIG_DIR, PROJECT_ROOT
from app.models.progress import atomic_write_json, read_json

PROFILE_ID = "ins_livox_mid360_verified_bag"
NEW_PROFILE_ID = "ins_livox_mid360_same_rig"
PROFILE_SHA = "b7a0e7b20e8f447ff6f49be9470b812ded678e28d96f943f7f9b97fd40250c7f"
PROFILE_SIZE = 17125894059
MAX_UPLOAD_BYTES = 64 * 1024 ** 3
MAX_CHUNK = 64 * 1024 * 1024
UPLOAD_ROOT = PROJECT_ROOT / "uploads"
DEVICE_CONFIG = DATASETS_CONFIG_DIR.parent / "upload_devices/ins_mid360_handoff.json"


class UploadError(ValueError):
    pass


class UploadService:
    def __init__(self, root: Path = UPLOAD_ROOT, template: Path | None = None, device_config: Path | None = None):
        self.root = root
        self.template = template or DATASETS_CONFIG_DIR / "ins_longcorridor01.json"
        self.device_config = device_config or DEVICE_CONFIG
        self._locks: dict[str, asyncio.Lock] = {}

    def _device(self) -> dict:
        device = json.loads(self.device_config.read_text(encoding="utf-8"))
        expected = (NEW_PROFILE_ID, "/livox_mid360/livox/lidar", "livox_ros_driver2/msg/CustomMsg",
                    "/livox_mid360/livox/imu", "sensor_msgs/msg/Imu", "ins_livox_mid360_custom")
        actual = (device.get("id"), device.get("lidar_topic"), device.get("lidar_type"),
                  device.get("imu_topic"), device.get("imu_type"), device.get("surface", {}).get("mrhash_profile"))
        if actual != expected:
            raise UploadError("Server device profile does not match the installed Livox bridge and MrHash reader")
        if (device.get("pose", {}).get("max_point_offset_ns") != 1_000_000_000 or
                device.get("pose", {}).get("warn_point_offset_ns") != 200_000_000 or
                device.get("pose", {}).get("max_timebase_header_delta_ns") != 50_000_000 or
                device.get("pose", {}).get("lidar_frame_id") != "livox_mid360_frame" or
                device.get("pose", {}).get("imu_frame_id") != "livox_frame" or
                device.get("surface", {}).get("min_range_m") != 0.2 or
                device.get("surface", {}).get("max_range_m") != 100.0):
            raise UploadError("Server device profile preflight bounds differ from the installed runner")
        return device

    def profiles(self) -> list[dict]:
        device = self._device()
        return [{"id": PROFILE_ID, "name": "INS / Livox MID-360 已验证原始 bag",
                 "size_bytes": PROFILE_SIZE, "sha256": PROFILE_SHA,
                 "calibration_note": "来自交接配置，原始标定及单位依据待负责人确认；仅适用于已验证的原始 INS bag。"},
                {"id": NEW_PROFILE_ID, "name": device["name"], "max_size_bytes": MAX_UPLOAD_BYTES,
                 "scope": device["scope"], "calibration_note": device["calibration_status"],
                 "bag_format": device["bag_format"], "lidar_topic": device["lidar_topic"],
                 "imu_topic": device["imu_topic"]}]

    def _paths(self, upload_id: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"up_[0-9a-f]{32}", upload_id):
            raise UploadError("Invalid upload ID")
        folder = self.root / "sessions" / upload_id
        return folder / "session.json", folder / "source.bag.part"

    def status(self, upload_id: str) -> dict:
        meta, part = self._paths(upload_id)
        state = read_json(meta, None)
        if not isinstance(state, dict):
            raise UploadError("Unknown upload")
        if state["status"] == "uploading" and (not part.exists() or part.stat().st_size < state["offset"]):
            raise UploadError("Upload data is shorter than committed offset")
        return state

    def create(self, filename: str, size_bytes: int, profile_id: str, attested_same_rig: bool = False) -> dict:
        if profile_id not in (PROFILE_ID, NEW_PROFILE_ID):
            raise UploadError("Unsupported profile")
        if Path(filename).name != filename or not filename.lower().endswith(".bag"):
            raise UploadError("Upload one .bag file")
        if profile_id == PROFILE_ID and size_bytes != PROFILE_SIZE:
            raise UploadError(f"This controlled profile requires {PROFILE_SIZE} bytes")
        if profile_id == NEW_PROFILE_ID and attested_same_rig is not True:
            raise UploadError("Confirm the same physical device, installation and acquisition configuration")
        if profile_id == NEW_PROFILE_ID:
            self._device()
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 < size_bytes <= MAX_UPLOAD_BYTES:
            raise UploadError(f"Bag size must be 1..{MAX_UPLOAD_BYTES} bytes")
        upload_id = "up_" + uuid.uuid4().hex
        meta, part = self._paths(upload_id)
        meta.parent.mkdir(parents=True, exist_ok=False)
        part.touch(exist_ok=False)
        state = {"upload_id": upload_id, "filename": filename, "size_bytes": size_bytes,
                 "profile_id": profile_id, "offset": 0, "status": "uploading", "max_chunk_bytes": MAX_CHUNK}
        if profile_id == NEW_PROFILE_ID:
            state["device_config_sha256"] = self._sha256(self.device_config)
            state["same_rig_attested"] = True
        atomic_write_json(meta, state)
        return state

    async def chunk(self, upload_id: str, offset: int, expected_sha: str, stream) -> dict:
        lock = self._locks.setdefault(upload_id, asyncio.Lock())
        async with lock:
            state = self.status(upload_id)
            if state["status"] != "uploading" or offset != state["offset"]:
                raise UploadError(f"Offset mismatch; server offset is {state['offset']}")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                raise UploadError("X-Chunk-Sha256 is required")
            meta, part = self._paths(upload_id)
            digest = hashlib.sha256()
            count = 0
            try:
                with part.open("r+b") as out:
                    out.truncate(offset)
                    out.seek(offset)
                    async for block in stream:
                        count += len(block)
                        if count > MAX_CHUNK or offset + count > state["size_bytes"]:
                            raise UploadError("Chunk exceeds allowed size")
                        out.write(block)
                        digest.update(block)
                    if not count or digest.hexdigest() != expected_sha:
                        raise UploadError("Chunk checksum mismatch or empty chunk")
                    out.flush()
                    os.fsync(out.fileno())
            except Exception:
                with part.open("r+b") as out:
                    out.truncate(offset)
                raise
            state["offset"] += count
            atomic_write_json(meta, state)
            return state

    async def finalize(self, upload_id: str) -> dict:
        lock = self._locks.setdefault(upload_id, asyncio.Lock())
        async with lock:
            state = self.status(upload_id)
            if state["status"] == "registered":
                return state
            if state["status"] != "uploading" or state["offset"] != state["size_bytes"]:
                raise UploadError("Upload is incomplete")
            meta, part = self._paths(upload_id)
            if part.stat().st_size != state["size_bytes"]:
                raise UploadError("Upload file size differs from committed offset")
            digest = await asyncio.to_thread(self._sha256, part)
            legacy = state["profile_id"] == PROFILE_ID
            if not legacy and self._sha256(self.device_config) != state.get("device_config_sha256"):
                raise UploadError("Server device profile changed since upload creation; start a new upload")
            if legacy and digest != PROFILE_SHA:
                raise UploadError("Bag SHA-256 differs from verified INS profile")
            if not legacy and digest == PROFILE_SHA:
                raise UploadError("This is the verified legacy bag; select the verified-bag profile")
            if not legacy:
                duplicate = self._existing_upload(digest, state, part, meta)
                if duplicate is not None:
                    return duplicate
            preflight_path = meta.parent / "preflight.bag"
            preflight_path.unlink(missing_ok=True)
            os.link(part, preflight_path)
            try:
                try:
                    result = await asyncio.to_thread(self._preflight, preflight_path)
                except UploadError as exc:
                    if not legacy:
                        state.update(status="rejected", preflight_error=str(exc))
                        atomic_write_json(meta, state)
                    raise
            finally:
                preflight_path.unlink(missing_ok=True)
            topics = result["topics"]
            if legacy and (topics["/livox_mid360/livox/lidar"]["count"] != 1539 or topics["/livox_mid360/livox/imu"]["count"] != 30770):
                raise UploadError("LiDAR/IMU count differs from verified profile")
            if not legacy:
                # No await follows this second check through registry publication, so
                # concurrent finalize calls in the single-worker service cannot race.
                duplicate = self._existing_upload(digest, state, part, meta)
                if duplicate is not None:
                    return duplicate
            dataset_id = "ins_upload_" + uuid.uuid4().hex[:12]
            target_dir = self.root / "datasets" / dataset_id
            target_dir.mkdir(parents=True, exist_ok=False)
            target_bag = target_dir / "source.bag"
            os.replace(part, target_bag)
            # Registry is published last; no incomplete upload can appear in dataset listing.
            definition = json.loads(self.template.read_text(encoding="utf-8"))
            definition.update(id=dataset_id, name=f"INS Livox 上传 {dataset_id}",
                              description="受控 INS profile；标定和 IMU 单位来自交接配置，原始依据待负责人确认。",
                              root=str(target_dir.relative_to(PROJECT_ROOT.parent)), files={"bag": "source.bag"})
            definition["pose"]["bag_path"] = str(target_bag.relative_to(PROJECT_ROOT.parent))
            definition["integrity"] = {"bag_size_bytes": PROFILE_SIZE, "bag_sha256": digest}
            definition["input_manifest"]["dataset_id"] = dataset_id
            definition["input_manifest"]["profile_id"] = PROFILE_ID
            definition["input_manifest"]["preflight"] = result
            definition["input_manifest"]["calibration_note"] = self.profiles()[0]["calibration_note"]
            if not legacy:
                device = self._device()
                definition["name"] = f"MID-360 新序列 {dataset_id}"
                definition["description"] = device["scope"] + " " + device["calibration_status"]
                definition["input_manifest"].update(
                    modalities=["lidar", "imu"], bag_message_count=topics[device["lidar_topic"]]["count"],
                    profile_id=NEW_PROFILE_ID, device_profile_id=NEW_PROFILE_ID,
                    device_config_sha256=state["device_config_sha256"],
                    same_rig_attested=state["same_rig_attested"],
                    calibration_status=device["calibration_status"],
                    calibration_note=device["scope"])
                definition["input_manifest"]["sequence_observed"] = {
                    "size_bytes": state["size_bytes"], "sha256": digest,
                    "lidar": topics[device["lidar_topic"]], "imu": topics[device["imu_topic"]]}
                definition["pose"].update(device["pose"])
                definition["pose"]["backend"] = "glim"
                definition["pose"].pop("imu_acceleration_input_unit", None)
                definition["pose"].pop("perpoint_time_unit", None)
                definition["pose"].pop("max_point_offset_ns", None)
                definition["pose"].pop("warn_point_offset_ns", None)
                definition["pose"].pop("max_timebase_header_delta_ns", None)
                definition["pose"]["lidar_topic"] = device["lidar_topic"]
                definition["pose"]["imu_topic"] = device["imu_topic"]
                definition["surface"].update(backend="mrhash_lidar", topic=device["lidar_topic"], mrhash_profile=device["surface"]["mrhash_profile"],
                                             integration_end_frame=None)
                definition["integrity"] = {"bag_size_bytes": state["size_bytes"], "bag_sha256": digest}
            DATASETS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            atomic_write_json(DATASETS_CONFIG_DIR / f"{dataset_id}.json", definition)
            state.update(status="registered", dataset_id=dataset_id, sha256=digest, preflight=result)
            atomic_write_json(meta, state)
            return state

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _existing_upload(self, digest: str, state: dict, part: Path, meta: Path) -> dict | None:
        """Reuse identical content registered with the same device snapshot."""
        for registry_path in DATASETS_CONFIG_DIR.glob("ins_upload_*.json"):
            existing = read_json(registry_path, {})
            if existing.get("integrity", {}).get("bag_sha256") != digest:
                continue
            if existing.get("input_manifest", {}).get("device_config_sha256") != state["device_config_sha256"]:
                raise UploadError("Duplicate bag was registered under a different device configuration")
            existing_bag = PROJECT_ROOT.parent / existing.get("root", "") / existing.get("files", {}).get("bag", "")
            if not existing_bag.is_file() or existing_bag.stat().st_size != state["size_bytes"]:
                raise UploadError("Duplicate registry entry has no valid source bag")
            state.update(status="registered", dataset_id=existing["id"], sha256=digest,
                         duplicate_of=existing["id"], preflight=existing["input_manifest"].get("preflight"))
            part.unlink()
            atomic_write_json(meta, state)
            return state
        return None

    @staticmethod
    def _preflight(path: Path) -> dict:
        python = PROJECT_ROOT.parent / "envs/glim_bridge/bin/python"
        script = BACKEND_ROOT / "scripts/preflight_ins_bag.py"
        try:
            completed = subprocess.run([str(python), str(script), str(path)], capture_output=True, text=True, timeout=3600)
        except subprocess.TimeoutExpired as exc:
            raise UploadError("Bag CPU preflight exceeded its 3600-second limit") from exc
        if completed.returncode:
            raise UploadError("Bag preflight failed: " + completed.stderr[-1000:])
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise UploadError("Bag preflight returned invalid JSON") from exc
