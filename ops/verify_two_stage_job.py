#!/usr/bin/env python3
"""Independent finite-geometry, timestamp and platform artifact checks."""
import argparse
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import trimesh


def point_ply(path: Path, fields: list[str]) -> dict:
    with path.open("rb") as handle:
        header = []
        while True:
            line = handle.readline().decode("ascii").strip()
            header.append(line)
            if line == "end_header":
                break
        if "format binary_little_endian 1.0" not in header:
            raise ValueError(f"Expected binary PLY: {path}")
        count = int(next(line.split()[2] for line in header if line.startswith("element vertex ")))
        props = [line.split()[2] for line in header if line.startswith("property ")]
        if props[:len(fields)] != fields:
            raise ValueError(f"Unexpected PLY fields: {props}")
        dtype = np.dtype([(name, "<f4") for name in fields] +
                         [(name, "u1") for name in props[len(fields):]])
        values = np.fromfile(handle, dtype=dtype, count=count)
    if len(values) != count or count == 0:
        raise ValueError("PLY vertex count mismatch")
    for name in fields:
        if not np.isfinite(values[name]).all():
            raise ValueError(f"Nonfinite {name} in {path}")
    xyz = np.column_stack([values[name] for name in ("x", "y", "z")])
    result = {"count": count, "bounds": [xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()]}
    for name in fields[3:]:
        result[name + "_min_max"] = [float(values[name].min()), float(values[name].max())]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api")
    args = parser.parse_args()
    job_dir = args.job_dir.resolve()
    job = json.loads((job_dir / "job.json").read_text())
    if job["status"] != "completed" or job["stages"]["distance"]["status"] != "not_integrated":
        raise ValueError("Two-stage job has not completed cleanly")
    pose_dir = job_dir / "stage1_pose"
    surface_dir = job_dir / "stage2_surface"
    pose_manifest = json.loads((pose_dir / "result_manifest.json").read_text())
    surface_manifest = json.loads((surface_dir / "result_manifest.json").read_text())
    association = json.loads((pose_dir / "native/association.json").read_text())
    if not association["accepted"] or association["matched_ratio"] < 0.98:
        raise ValueError("Pose association gate did not pass")
    native = np.loadtxt(pose_dir / "native/traj_lidar.txt")
    canonical = np.loadtxt(pose_dir / "poses.txt")
    if native.shape[0] != association["native_pose_count"] or canonical.shape[0] != association["matched_count"]:
        raise ValueError("Pose row count differs from association")
    for name, values in (("native", native), ("canonical", canonical)):
        if not np.isfinite(values).all() or not np.all(np.diff(values[:, 0]) > 0):
            raise ValueError(f"Invalid {name} pose values or timestamps")
        if not np.allclose(np.linalg.norm(values[:, -4:], axis=1), 1, atol=1e-3):
            raise ValueError(f"Invalid {name} quaternion norm")
    index = np.loadtxt(pose_dir / "native/bag_index.tsv", comments="#", dtype=np.int64)
    if index.shape[0] != association["bag_frame_count"]:
        raise ValueError("Bag index row count differs from association")
    artifacts = {item["artifact_id"]: item for item in surface_manifest["artifacts"]}
    mesh = trimesh.load_mesh(surface_dir / artifacts["surface_mesh"]["path"], process=False)
    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty or not np.isfinite(mesh.vertices).all():
        raise ValueError("Native mesh is empty or nonfinite")
    preview = trimesh.load(surface_dir / artifacts["surface_model"]["path"], file_type="glb", process=False)
    preview_meshes = list(preview.geometry.values()) if isinstance(preview, trimesh.Scene) else [preview]
    if not preview_meshes or not all(np.isfinite(item.vertices).all() for item in preview_meshes):
        raise ValueError("GLB preview geometry is invalid")
    voxel = point_ply(surface_dir / artifacts["voxel_points"]["path"], ["x", "y", "z", "sdf", "weight"])
    hashes = point_ply(surface_dir / artifacts["hash_points"]["path"], ["x", "y", "z", "weight"])
    geometry = {
        "pose": {"bag_frames": len(index), "native_rows": len(native), "canonical_rows": len(canonical),
                 "native_first_last": [float(native[0, 0]), float(native[-1, 0])],
                 "canonical_first_last": [float(canonical[0, 0]), float(canonical[-1, 0])],
                 "bag_record_first_last_ns": [int(index[0, 0]), int(index[-1, 0])],
                 "bag_sensor_first_last_ns": [int(index[0, 1]), int(index[-1, 1])]},
        "mesh": {"vertices": len(mesh.vertices), "faces": len(mesh.faces), "bounds": mesh.bounds.tolist()},
        "voxel_points": voxel, "hash_points": hashes,
        "glb": {"vertices": sum(len(item.vertices) for item in preview_meshes),
                "faces": sum(len(item.faces) for item in preview_meshes)},
    }
    (job_dir / "geometry_checks.json").write_text(json.dumps(geometry, indent=2) + "\n")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks = {}
    for stage, manifest in (("pose", pose_manifest), ("surface", surface_manifest)):
        for artifact in manifest["artifacts"]:
            role = "previews" if artifact["role"] == "preview" else "artifacts"
            url = f"{args.api}/jobs/{job['job_id']}/stages/{stage}/{role}/{artifact['artifact_id']}"
            with opener.open(url, timeout=90) as response:
                count = 0
                while block := response.read(1024 * 1024):
                    count += len(block)
                if response.status != 200 or count <= 0:
                    raise ValueError(f"Artifact HTTP check failed: {url}")
                checks[f"{stage}/{artifact['artifact_id']}"] = {"status": response.status, "bytes": count}
    (job_dir / "api_access_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps({"job_id": job["job_id"], "geometry": geometry, "api_checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
