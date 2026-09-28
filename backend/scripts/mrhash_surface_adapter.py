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

from app.models.progress import atomic_write_json, read_json  # noqa: E402
from app.services.mesh_preview import build_preview_glb  # noqa: E402
from app.services.surface_input_service import validate_surface_input  # noqa: E402


def progress(stage_dir: Path, phase: str, message: str, status: str = "running",
             percent: float = 0.0) -> None:
    atomic_write_json(stage_dir / "progress.json", {
        "stage": "surface", "backend": "mrhash_lidar", "status": status,
        "phase": phase, "progress": percent, "current": 0, "total": 0,
        "unit": "", "message": message,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
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
                   end_frame: int) -> None:
    text = reference.read_text(encoding="utf-8")
    replacements = {"data_path": str(data_path), "results_path": str(results_path),
                    "end_frame": str(end_frame)}
    for key, value in replacements.items():
        text, count = re.subn(rf"(?m)^{re.escape(key)}\s*:.*$", f"{key}: {value}", text)
        if count != 1:
            raise ValueError(f"reference config has {count} '{key}' fields")
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
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_dir = stage_dir / "runs" / run_id
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True)
    config_path = run_dir / "mrhash.cfg"

    workspace = PROJECT_ROOT.parent
    mrhash_root = Path(os.environ.get("MRHASH_ROOT", workspace / "mrhash")).resolve()
    apps_dir = mrhash_root / "mrhash" / "apps"
    reference = mrhash_root / "mrhash" / "configurations" / "oxford_hesai_corrected_full.cfg"
    if not (apps_dir / "rosbag_runner.py").is_file() or not reference.is_file():
        raise ValueError("configured MrHash repository or reference config is unavailable")
    pixi = shutil.which("pixi") or str(workspace / ".pixi" / "bin" / "pixi")
    if not Path(pixi).is_file():
        raise ValueError("pixi executable is unavailable")
    end_frame = int(os.environ.get("MRHASH_SMOKE_END_FRAME", "100")) if args.mode == "demo" else -1
    controlled_input = run_dir / "input"
    controlled_input.mkdir()
    (controlled_input / "source.bag").symlink_to(bag_path)
    (controlled_input / "poses.txt").symlink_to(trajectory_path)
    replace_config(reference, config_path, controlled_input, raw_dir, end_frame)

    progress(stage_dir, "validating", "Validated real bag and imported Pose inputs")
    command = [pixi, "run", "--manifest-path", str(mrhash_root), "python",
               str(apps_dir / "rosbag_runner.py"), str(config_path)]
    print("[mrhash] dataset=oxford_mrhash_lidar mode=" + args.mode, flush=True)
    print("[mrhash] launching pixi-managed rosbag_runner.py", flush=True)
    progress(stage_dir, "mapping", "MrHash is running; algorithm does not expose reliable progress")
    started = time.monotonic()
    # MrHash writes profiler sidecars to cwd; keep every write inside this Job.
    completed = subprocess.run(command, cwd=run_dir, check=False)
    if completed.returncode != 0:
        progress(stage_dir, "failed", f"MrHash exited with code {completed.returncode}", "failed")
        return completed.returncode

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
             "note": "Topology-preserving simplified preview; not the full algorithm mesh."},
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
        ],
        "metrics": {
            "vertices": mesh_info["vertices"], "faces": mesh_info["faces"],
            "voxel_count": voxel_info["vertices"], "hash_point_count": hash_info["vertices"],
            "mesh_size_bytes": mesh.stat().st_size, "voxel_size_bytes": voxels.stat().st_size,
            **preview_metrics,
        },
        "backend_details": {
            "mock_backend": False, "algorithm": "MrHash LiDAR", "dataset": job["dataset"],
            "topic": input_manifest["lidar_topic"],
            "pose_semantics": input_manifest["pose_semantics"],
            "pose_timestamp_semantics": input_manifest["timestamp_basis"],
            "run_id": run_id, "mode": args.mode, "entrypoint": "mrhash/apps/rosbag_runner.py",
            "config_artifact_id": "run_config",
            "preview_note": "surface_model is a sampled GLB preview; surface_mesh is the complete native output.",
        },
    }
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
