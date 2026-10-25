#!/usr/bin/env python3
"""Per-Job MrHash-LiDAR process wrapper and artifact packager."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.models.live_progress import ProgressReporter
from app.models.progress import atomic_write_json, read_json  # noqa: E402
from app.services.mesh_preview import build_preview_glb  # noqa: E402
from app.services.surface_input_service import validate_surface_input  # noqa: E402


def progress(stage_dir: Path, phase: str, message: str, status: str = "running",
             percent: float = 0.0) -> None:
    if os.environ.get("PLATFORM_ALGORITHM_PROGRESS_PATH"):
        ProgressReporter().emit("finalizing" if status == "completed" else phase, force=True)
    else:
        # Standalone packaging remains usable without the process runner.
        atomic_write_json(stage_dir / "progress.json", {
            "stage": "surface", "backend": "mrhash_lidar", "status": status,
            "phase": phase, "progress": percent, "current": 0, "total": 0,
            "unit": "", "message": message, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })


def ply_header(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        if handle.readline().strip() != b"ply":
            raise ValueError(f"{path.name}: not a PLY file")
        result: dict[str, object] = {"vertices": 0, "faces": 0, "properties": []}
        current = ""
        for _ in range(200):
            raw = handle.readline()
            if not raw:
                raise ValueError(f"{path.name}: truncated PLY header")
            line = raw.decode("ascii", errors="strict").strip()
            if line.startswith("format "):
                result["format"] = line.split()[1]
            elif line.startswith("element "):
                _, current, count = line.split()[:3]
                if current == "vertex":
                    result["vertices"] = int(count)
                elif current == "face":
                    result["faces"] = int(count)
            elif line.startswith("property ") and current == "vertex":
                properties = result["properties"]
                assert isinstance(properties, list)
                properties.append(line.split()[-1])
            elif line == "end_header":
                result["header_bytes"] = handle.tell()
                break
        else:
            raise ValueError(f"{path.name}: PLY header is too long")
    if not result.get("format") or int(result["vertices"]) <= 0:
        raise ValueError(f"{path.name}: missing format or vertices")
    return result


def replace_config(reference: Path, output: Path, data_path: Path, results_path: Path,
                   end_frame: int, *, topic: str, start_frame: int = 1) -> None:
    text = reference.read_text(encoding="utf-8")
    replacements = {"data_path": str(data_path), "results_path": str(results_path),
                    "end_frame": str(end_frame), "rosbag_topic": json.dumps(topic)}
    for key, value in replacements.items():
        text, count = re.subn(
            rf"(?m)^([ \t]*){re.escape(key)}\s*:.*$",
            lambda match: f"{match.group(1)}{key}: {value}", text,
        )
        if count != 1:
            raise ValueError(f"reference config has {count} '{key}' fields")
    text += f"\nstart_frame: {start_frame}\n"
    output.write_text(text, encoding="utf-8")


def one_output(directory: Path, pattern: str) -> Path:
    matches = list(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one new {pattern} output, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("demo", "full"))
    parser.add_argument("--package-existing-run", type=Path,
                        help="validate and register this Job's completed raw MrHash run without rerunning fusion")
    args = parser.parse_args()
    job_dir = args.job_dir.resolve()
    job = read_json(job_dir / "job.json", None)
    if not isinstance(job, dict):
        raise ValueError("job.json is missing")
    if job.get("stages", {}).get("pose", {}).get("status") != "completed":
        raise ValueError("validated Pose import must be completed before Surface")
    input_manifest, bag_path, trajectory_path = validate_surface_input(job_dir)

    stage_dir = job_dir / "stage2_surface"
    stage_dir.mkdir(parents=True, exist_ok=True)
    if args.package_existing_run:
        run_dir = args.package_existing_run.resolve()
        if run_dir.parent != (stage_dir / "runs").resolve() or not run_dir.is_dir():
            raise ValueError("package-existing-run must be an existing run of this Job")
        run_id = run_dir.name
    else:
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        run_dir = stage_dir / "runs" / run_id
    raw_dir = run_dir / "raw"
    if not args.package_existing_run:
        raw_dir.mkdir(parents=True)
    config_path = run_dir / "mrhash.cfg"

    workspace = PROJECT_ROOT.parent
    mrhash_root = Path(os.environ.get("MRHASH_ROOT", workspace / "mrhash")).resolve()
    apps_dir = mrhash_root / "mrhash" / "apps"
    profile = input_manifest.get("mrhash_profile")
    profiles = {
        "oxford_hesai_pointcloud2": "oxford_hesai_corrected_full.cfg",
        "ins_livox_mid360_custom": "ins_livox_mid360.cfg",
    }
    if profile not in profiles or not input_manifest.get("lidar_topic"):
        raise ValueError("unregistered MrHash LiDAR reader profile or missing topic")
    reference_name = input_manifest.get("mrhash_reference_config") or profiles[profile]
    if reference_name != profiles[profile]:
        raise ValueError("MrHash reference config does not match installed reader profile")
    reference = mrhash_root / "mrhash" / "configurations" / reference_name
    if not (apps_dir / "rosbag_runner.py").is_file() or not reference.is_file():
        raise ValueError("configured MrHash repository or reference config is unavailable")
    controlled_limit = input_manifest.get("integration_end_frame")
    end_frame = int(controlled_limit) if controlled_limit is not None else (
        int(os.environ.get("MRHASH_SMOKE_END_FRAME", "100")) if args.mode == "demo" else -1)
    started = time.monotonic()
    if args.package_existing_run:
        if not config_path.is_file() or not raw_dir.is_dir():
            raise ValueError("existing run is missing its config or raw directory")
        config_text = config_path.read_text(encoding="utf-8")
        if f"rosbag_topic: {json.dumps(input_manifest['lidar_topic'])}" not in config_text or \
                f"end_frame: {end_frame}" not in config_text or "start_frame: 1" not in config_text:
            raise ValueError("existing run config does not match the controlled profile and frame range")
        print(f"[mrhash] packaging existing raw run {run_id}; fusion is not rerun", flush=True)
    else:
        pixi = shutil.which("pixi") or str(workspace / ".pixi" / "bin" / "pixi")
        if not Path(pixi).is_file():
            raise ValueError("pixi executable is unavailable")
        controlled_input = run_dir / "input"
        controlled_input.mkdir()
        (controlled_input / "source.bag").symlink_to(bag_path)
        (controlled_input / "poses.txt").symlink_to(trajectory_path)
        replace_config(reference, config_path, controlled_input, raw_dir, end_frame,
                       topic=input_manifest["lidar_topic"])
        params_path = job_dir / "input" / "effective_algorithm_params.json"
        params = read_json(params_path, {}) or {}
        params["surface_applied"] = {
            "profile": profile, "reference_config": str(reference),
            "run_config": str(config_path), "lidar_topic": input_manifest["lidar_topic"],
            "start_frame": 1, "end_frame": end_frame,
        }
        atomic_write_json(params_path, params)
        progress(stage_dir, "validating", "Validated real bag and imported Pose inputs")
        command = [pixi, "run", "--as-is", "--manifest-path", str(mrhash_root), "python",
                   str(BACKEND_ROOT / "scripts" / "mrhash_live_runner.py"), "--runner", str(apps_dir / "rosbag_runner.py"), str(config_path)]
        print(f"[mrhash] dataset={job['dataset']} profile={profile} mode={args.mode}", flush=True)
        print("[mrhash] launching pixi-managed rosbag_runner.py", flush=True)
        progress(stage_dir, "mapping", "MrHash is running; direct reader and successful compute counters are enabled")
        # MrHash writes profiler sidecars to cwd; keep every write inside this Job.
        child_env = os.environ.copy()
        child_env.setdefault("PLATFORM_ALGORITHM_PROGRESS_PATH", str(stage_dir / "algorithm_progress.json"))
        child_env.setdefault("PLATFORM_PROGRESS_RUN_ID", uuid.uuid4().hex)
        child_env.pop("OMP_NUM_THREADS", None)
        child_env.pop("OPENBLAS_NUM_THREADS", None)
        completed = subprocess.run(command, cwd=run_dir, check=False, env=child_env)
        if completed.returncode != 0:
            progress(stage_dir, "failed", f"MrHash exited with code {completed.returncode}", "failed")
            return completed.returncode

    accounting = read_json(raw_dir / "frame_accounting.json", None)
    if not isinstance(accounting, dict) or accounting.get("selected", 0) <= 0 or \
            accounting.get("matched_pose") != accounting.get("fused") or \
            accounting.get("selected") != accounting.get("fused") + accounting.get("skipped_no_pose"):
        raise ValueError("MrHash frame accounting is missing or inconsistent")

    progress(stage_dir, "validating_outputs", "Validating outputs from this run")
    mesh = one_output(raw_dir, "mesh_*.ply")
    voxels = one_output(raw_dir, "voxel_points_*.ply")
    hashes = one_output(raw_dir, "hash_points_*.ply")
    mesh_info, voxel_info, hash_info = ply_header(mesh), ply_header(voxels), ply_header(hashes)
    required_fields = {"x", "y", "z", "sdf", "weight", "red", "green", "blue", "alpha"}
    if not required_fields.issubset(set(voxel_info["properties"])):
        raise ValueError("voxel_points PLY does not contain x y z sdf weight rgba fields")

    progress(stage_dir, "building_preview", "Building a topology-preserving GLB preview")
    preview_path = stage_dir / "preview" / "surface_model.glb"
    preview_metrics = build_preview_glb(mesh, preview_path)
    runtime = time.monotonic() - started
    def rel(path: Path) -> str:
        return str(path.relative_to(stage_dir))
    manifest = {
        "schema_version": "0.1", "job_id": job["job_id"], "stage": "surface",
        "backend": "mrhash_lidar", "status": "completed", "frame_id": "world",
        "unit": "meter", "runtime_sec": round(runtime, 2),
        "artifacts": [
            {"artifact_id": "surface_model", "role": "preview", "path": rel(preview_path),
             "content_type": "model/gltf-binary",
             "note": "QEM preview; simplification may alter small components and bounds. Download surface_mesh for complete native geometry."},
            {"artifact_id": "surface_mesh", "role": "data", "path": rel(mesh),
             "content_type": "application/octet-stream", "download": True,
             "note": "Complete native MrHash mesh PLY."},
            {"artifact_id": "voxel_points", "role": "data", "path": rel(voxels),
             "content_type": "application/octet-stream", "download": True,
             "note": "Native MrHash voxel field with x y z sdf weight rgba."},
            {"artifact_id": "hash_points", "role": "data", "path": rel(hashes),
             "content_type": "application/octet-stream", "download": True},
            {"artifact_id": "run_config", "role": "data", "path": rel(config_path),
             "content_type": "text/plain", "download": True},
            {"artifact_id": "frame_accounting", "role": "data", "path": rel(raw_dir / "frame_accounting.json"),
             "content_type": "application/json", "download": True},
        ],
        "metrics": {
            "vertices": mesh_info["vertices"], "faces": mesh_info["faces"],
            "voxel_count": voxel_info["vertices"], "hash_point_count": hash_info["vertices"],
            "mesh_size_bytes": mesh.stat().st_size, "voxel_size_bytes": voxels.stat().st_size,
            "bag_lidar_frames": accounting.get("bag_lidar_messages", input_manifest.get("matching", {}).get("bag_message_count")),
            "selected_frames": accounting["selected"], "matched_pose_frames": accounting["matched_pose"],
            "skipped_no_pose_frames": accounting["skipped_no_pose"], "fused_frames": accounting["fused"],
            **preview_metrics,
        },
        "backend_details": {
            "mock_backend": False, "algorithm": "MrHash LiDAR", "dataset": job["dataset"],
            "topic": input_manifest["lidar_topic"],
            "mrhash_profile": profile,
            "pose_semantics": input_manifest["pose_semantics"],
            "pose_timestamp_semantics": input_manifest["timestamp_basis"],
            "run_id": run_id, "mode": args.mode, "entrypoint": "mrhash/apps/rosbag_runner.py",
            "packaging_resumed_from_raw_run": bool(args.package_existing_run),
            "config_artifact_id": "run_config",
            "source_pose": input_manifest.get("source_pose"),
            "preview_note": "surface_model is a QEM preview; small components and bounds may change. surface_mesh retains the complete native output.",
        },
    }
    ledger_path = raw_dir / "fused_frames.jsonl"
    if ledger_path.is_file():
        manifest["artifacts"].append({"artifact_id": "fused_frame_ledger", "role": "data",
            "path": rel(ledger_path), "content_type": "application/x-ndjson", "download": True,
            "note": "Per-frame raw bag index, timestamp and successful compute call; not an accuracy assertion."})
    atomic_write_json(stage_dir / "result_manifest.json", manifest)
    progress(stage_dir, "completed", "Real MrHash outputs validated and registered", "completed", 100.0)
    print(f"[mrhash] completed run_id={run_id}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[mrhash] ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
