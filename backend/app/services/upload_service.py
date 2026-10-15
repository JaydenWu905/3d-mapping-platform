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
PROFILE_SHA = "b7a0e7b20e8f447ff6f49be9470b812ded678e28d96f943f7f9b97fd40250c7f"
PROFILE_SIZE = 17125894059
MAX_CHUNK = 64 * 1024 * 1024
UPLOAD_ROOT = PROJECT_ROOT / "uploads"


class UploadError(ValueError):
    pass


class UploadService:
    def __init__(self, root: Path = UPLOAD_ROOT, template: Path | None = None):
        self.root = root
        self.template = template or DATASETS_CONFIG_DIR / "ins_longcorridor01.json"
        self._locks: dict[str, asyncio.Lock] = {}

    def profiles(self) -> list[dict]:
        return [{"id": PROFILE_ID, "name": "INS / Livox MID-360 已验证原始 bag",
                 "size_bytes": PROFILE_SIZE, "sha256": PROFILE_SHA,
                 "calibration_note": "来自交接配置，原始标定及单位依据待负责人确认；仅适用于已验证的原始 INS bag。"}]

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

    def create(self, filename: str, size_bytes: int, profile_id: str) -> dict:
        if profile_id != PROFILE_ID:
            raise UploadError("Unsupported profile")
        if Path(filename).name != filename or not filename.lower().endswith(".bag"):
            raise UploadError("Upload one .bag file")
        if size_bytes != PROFILE_SIZE:
            raise UploadError(f"This controlled profile requires {PROFILE_SIZE} bytes")
        upload_id = "up_" + uuid.uuid4().hex
        meta, part = self._paths(upload_id)
        meta.parent.mkdir(parents=True, exist_ok=False)
        part.touch(exist_ok=False)
        state = {"upload_id": upload_id, "filename": filename, "size_bytes": size_bytes,
                 "profile_id": profile_id, "offset": 0, "status": "uploading", "max_chunk_bytes": MAX_CHUNK}
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
            if digest != PROFILE_SHA:
                raise UploadError("Bag SHA-256 differs from verified INS profile")
            preflight_path = meta.parent / "preflight.bag"
            preflight_path.unlink(missing_ok=True)
            os.link(part, preflight_path)
            try:
                result = await asyncio.to_thread(self._preflight, preflight_path)
            finally:
                preflight_path.unlink(missing_ok=True)
            topics = result["topics"]
            if topics["/livox_mid360/livox/lidar"]["count"] != 1539 or topics["/livox_mid360/livox/imu"]["count"] != 30770:
                raise UploadError("LiDAR/IMU count differs from verified profile")
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

    @staticmethod
    def _preflight(path: Path) -> dict:
        python = PROJECT_ROOT.parent / "envs/glim_bridge/bin/python"
        script = BACKEND_ROOT / "scripts/preflight_ins_bag.py"
        completed = subprocess.run([str(python), str(script), str(path)], capture_output=True, text=True, timeout=180)
        if completed.returncode:
            raise UploadError("Bag preflight failed: " + completed.stderr[-1000:])
        return json.loads(completed.stdout)
