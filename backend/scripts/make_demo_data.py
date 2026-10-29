"""Generate the demo_room demo job (deterministic, no real algorithms).

Produces demo_jobs/demo_room/:
  input/input_manifest.json       — dataset metadata (scanner, sensor modals)
  job.json                        — a *completed* job (seeded on backend start)
  stage1_pose/                    — trajectory_preview.json, trajectory.txt,
                                    progress.json, result_manifest.json
  stage2_surface/                 — surface_preview.glb, surface.ply,
                                    navigation_input.ply, progress.json,
                                    result_manifest.json
  stage3_esdf/                    — slices/{xy,xz,yz}.png (+ observed masks),
                                    gradient.json, slices.zip, progress.json,
                                    result_manifest.json

Every metric is a hand-built demo number; mock_runner reuses these manifests
verbatim so the boundary between "demo data" and "real algorithm output" stays
honest (backend_details.mock_backend=True).
"""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import trimesh
from trimesh import transformations as tf

ROOT = Path(__file__).resolve().parents[2]  # backend/
OUT = ROOT / "demo_jobs" / "demo_room"
KEY = {"pose": "stage1_pose", "surface": "stage2_surface", "distance": "stage3_esdf"}
STAGES = ["pose", "surface", "distance"]
BACKENDS = {"pose": "glim", "surface": "mrhash_lidar", "distance": "voxel_esdf"}

np.random.seed(20240920)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------- input
def _input_manifest() -> dict:
    return {
        "schema_version": "0.1",
        "dataset_id": "demo_room",
        "name": "Demo Room (合成房间)",
        "description": "合成室内房间点云序列:单回环,含桌椅墙壁,用于三种算法阶段的无环境演示。",
        "sensor": {"type": "lidar", "channels": 16, "fov_deg": [0, 90], "range_m": 30.0},
        "frame_count": 120,
        "trajectory_file": "trajectory.txt",
        "created_at": _now(),
        "tags": ["demo", "synthetic", "indoor"],
    }


# ---------------------------------------------------------------- pose stage
def _trajectory() -> tuple[list[dict], str]:
    """Closed loop through the room; returns preview list + TUM-style text."""
    t = np.linspace(0, 2 * np.pi, 121)[:-1]
    r = 6.0
    x = r * np.cos(t)
    y = r * np.sin(t)
    z = 1.20 + 0.25 * np.sin(3 * t)
    pts = []
    lines = []
    for i, (xi, yi, zi) in enumerate(zip(x, y, z)):
        yaw = (-t[i])  # face forward along the loop
        q = tf.quaternion_from_euler(0.0, 0.0, yaw)
        pts.append({"x": float(xi), "y": float(yi), "z": float(zi),
                    "qw": float(q[3]), "qx": float(q[0]), "qy": float(q[1]), "qz": float(q[2])})
        lines.append(f"{i} 0.0 {xi:.6f} {yi:.6f} {zi:.6f} "
                     f"{q[3]:.6f} {q[0]:.6f} {q[1]:.6f} {q[2]:.6f}")
    return pts, "\n".join(lines) + "\n"


def _make_pose() -> None:
    d = OUT / KEY["pose"]
    d.mkdir(parents=True, exist_ok=True)
    pts, txt = _trajectory()
    (d / "trajectory_preview.json").write_text(
        json.dumps({"frame_count": len(pts), "points": pts}, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "trajectory.txt").write_text(txt, encoding="utf-8")
    (d / "progress.json").write_text(json.dumps({
        "stage": "pose", "backend": BACKENDS["pose"], "status": "completed",
        "phase": "completed", "progress": 100.0, "current": 120, "total": 120,
        "unit": "frame", "message": "Completed", "elapsed_sec": 42.0,
        "updated_at": _now(),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "result_manifest.json").write_text(json.dumps({
        "schema_version": "0.1",
        "job_id": "demo",
        "stage": "pose",
        "backend": BACKENDS["pose"],
        "status": "completed",
        "runtime_sec": 42.0,
        "frame_id": "world",
        "unit": "meter",
        "metrics": {"pose_count": 120, "trajectory_length_m": 37.70, "loop_closures": 1},
        "artifacts": [
            {"artifact_id": "trajectory_model", "role": "preview", "path": "trajectory_preview.json",
             "content_type": "application/json"},
            {"artifact_id": "trajectory_raw", "role": "data", "path": "trajectory.txt",
             "content_type": "text/plain", "download": True},
        ],
        "backend_details": {
            "mock_backend": True,
            "data_source": "demo preview (not a real algorithm run)",
            "note": "Prepared demo artifacts presented as glim results for phase-1 demo.",
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------- surface stage
def _demo_scene() -> trimesh.Trimesh:
    """Small furnished room: floor, 4 walls, boxes (table/shelf/bench), a lamp sphere."""
    parts: list[trimesh.Trimesh] = []
    room_half = 8.0
    floor = trimesh.creation.box(extents=(2 * room_half, 2 * room_half, 0.2),
                                 transform=tf.translation_matrix([0, 0, -0.1]))
    parts.append(floor)
    # four walls around the 16m x 16m room: [sx, sy] selects which axis to move along.
    for sx, sy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        wall = trimesh.creation.box(extents=(0.3, 2 * room_half, 3.0),
                                    transform=tf.translation_matrix([0, 0, 1.5]))
        offset = [sx * room_half, sy * room_half, 0.0]
        wall.apply_transform(tf.translation_matrix(offset))
        parts.append(wall)
    parts.append(_box((2.5, 1.0, 0.0), (1.0, 0.8, 0.9)))       # sofa-ish box
    parts.append(_box((-3.0, -1.5, 0.0), (1.4, 0.6, 0.75)))     # table
    parts.append(_box((0.5, 3.2, 0.0), (0.6, 0.6, 1.4)))        # shelf
    parts.append(_box((-1.0, 2.2, 0.0), (1.2, 0.15, 0.15)))     # bench
    lamp = trimesh.creation.icosphere(subdivisions=2, radius=0.35)
    lamp.apply_transform(tf.translation_matrix([3.0, 2.0, 2.4]))
    parts.append(lamp)
    return trimesh.util.concatenate(parts)


def _box(center: tuple[float, float, float], extents: tuple[float, float, float]) -> trimesh.Trimesh:
    b = trimesh.creation.box(extents=extents)
    # sit on z=0
    b.apply_translation([center[0], center[1], center[2] + extents[2] / 2])
    return b


def _make_surface() -> None:
    d = OUT / KEY["surface"]
    d.mkdir(parents=True, exist_ok=True)
    scene = _demo_scene()
    scene.export(str(d / "surface.ply"))
    # simplified navigation hull: extruded footprint (boxes flattened to z=0 quad + walls)
    scene.export(str(d / "navigation_input.ply"))
    # GLB preview (binary, viewer loads via /previews)
    scene.export(str(d / "surface_preview.glb"))
    v = len(scene.vertices)
    f = len(scene.faces)
    (d / "progress.json").write_text(json.dumps({
        "stage": "surface", "backend": BACKENDS["surface"], "status": "completed",
        "phase": "completed", "progress": 100.0, "current": 120, "total": 120,
        "unit": "frame", "message": "Completed", "elapsed_sec": 118.0,
        "updated_at": _now(),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "result_manifest.json").write_text(json.dumps({
        "schema_version": "0.1",
        "job_id": "demo",
        "stage": "surface",
        "backend": BACKENDS["surface"],
        "status": "completed",
        "runtime_sec": 118.0,
        "frame_id": "world",
        "unit": "meter",
        "metrics": {"vertices": v, "faces": f, "bbox_m": [16.0, 16.0, 3.0]},
        "artifacts": [
            {"artifact_id": "surface_model", "role": "preview", "path": "surface_preview.glb",
             "content_type": "model/gltf-binary"},
            {"artifact_id": "surface_mesh", "role": "data", "path": "surface.ply",
             "content_type": "application/octet-stream", "download": True},
            {"artifact_id": "navigation_input", "role": "data", "path": "navigation_input.ply",
             "content_type": "application/octet-stream", "download": True,
             "note": "输入给下阶段(voxel_esdf)的简化点云/网格"},
        ],
        "backend_details": {
            "mock_backend": True,
            "data_source": "demo preview (not a real algorithm run)",
            "note": "Prepared demo artifacts presented as mrhash_lidar results for phase-1 demo.",
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------------------------------------------------- distance stage
def _esdf_slice(size: int = 480) -> np.ndarray:
    """Synthetic 2D slice of a signed-distance-ish field.

    Wall ring + one inner obstacle produce a smooth gradient; the same
    function is sampled for the three viewing planes with different centers
    below so the three slices aren't pixel-identical.
    """
    yv, xv = np.mgrid[0:size, 0:size]
    norm = np.sqrt(((xv / size - 0.5) * 2) ** 2 + ((yv / size - 0.5) * 2) ** 2)
    ring = np.exp(-((norm - 0.72) ** 2) / (2 * 0.10 ** 2))
    inner = np.exp(-(((xv / size - 0.62) * 2) ** 2 + ((yv / size - 0.38) * 2) ** 2) / (2 * 0.10 ** 2))
    field = np.clip(ring + 0.6 * inner, 0, 1)
    return field


def _heatmap(arr: np.ndarray) -> np.ndarray:
    """Jet-like coloring with a transparent background where ~0."""
    a = np.clip(arr, 0, 1)
    # viridis-ish ramp by hand
    r = np.zeros_like(a); g = np.zeros_like(a); b = np.zeros_like(a)
    hi = a > 0.75
    r[(a > 0.40) & (a <= 0.75)] = (a[(a > 0.40) & (a <= 0.75)] - 0.40) / 0.35 * 255
    r[hi] = 255
    g[a <= 0.40] = a[a <= 0.40] / 0.40 * 255
    g[(a > 0.40) & (a <= 0.75)] = 255
    g[hi] = (1 - (a[hi] - 0.75) / 0.25) * 255
    b[a <= 0.40] = (1 - a[a <= 0.40] / 0.40) * 255
    b[(a > 0.40)] = 0
    img = np.dstack([r, g, b]).astype(np.uint8)
    return img


def _mask_png(arr: np.ndarray, thresh: float = 0.30) -> np.ndarray:
    m = (arr > thresh).astype(np.uint8) * 255
    return np.dstack([m, m, m])


# demo 房间几何（与 _make_surface 的 16x16x3 m 房间 + 障碍保持一致）
_DEMO_SOLIDS = [
    ((0.0, 0.0, 1.5), (8.0, 8.0, 1.5)),      # 房间外壳
    ((2.5, 1.0, 0.45), (0.50, 0.40, 0.45)),  # 货箱
    ((-3.0, -1.5, 0.38), (0.70, 0.30, 0.38)),
    ((0.5, 3.2, 0.70), (0.30, 0.30, 0.70)),
    ((-1.0, 2.2, 0.08), (0.60, 0.075, 0.075)),
]
_DEMO_SPHERES = [((3.0, 2.0, 2.4), 0.35)]


def _demo_esdf_cloud(points: int = 40000, max_abs_distance: float = 1.2) -> np.ndarray:
    """合成一份"贴着表面"的 ESDF 预览点云，列格式与真实导出一致 (x y z distance r g b)。"""
    faces = []
    for center, half in _DEMO_SOLIDS:
        c = np.asarray(center, dtype=float)
        h = np.asarray(half, dtype=float)
        for axis in range(3):
            for sign in (-1, 1):
                others = [i for i in range(3) if i != axis]
                faces.append({
                    "center": c, "half": h, "axis": axis, "sign": sign,
                    "area": 4.0 * h[others[0]] * h[others[1]],
                })
    for center, radius in _DEMO_SPHERES:
        faces.append({"center": np.asarray(center, dtype=float), "radius": float(radius),
                      "area": 4.0 * np.pi * radius ** 2})

    total_area = sum(f["area"] for f in faces)
    chunks_pts, chunks_dist = [], []
    for face in faces:
        count = max(60, int(round(points * face["area"] / total_area)))
        if "radius" in face:  # 球面
            vec = np.random.normal(size=(count, 3))
            vec /= np.linalg.norm(vec, axis=1, keepdims=True)
            base = face["center"] + vec * face["radius"]
            normal = vec
        else:                 # 长方体的一个面
            axis, sign = face["axis"], face["sign"]
            base = np.tile(face["center"], (count, 1))
            base[:, axis] = face["center"][axis] + sign * face["half"][axis]
            for i in [i for i in range(3) if i != axis]:
                base[:, i] = face["center"][i] + (np.random.random(count) * 2.0 - 1.0) * face["half"][i]
            normal = np.zeros(3)
            normal[axis] = float(sign)
        offset = np.random.uniform(-max_abs_distance, max_abs_distance, size=count)
        chunks_pts.append(base + normal * offset[:, None])
        chunks_dist.append(offset)

    pts = np.vstack(chunks_pts)
    dist = np.concatenate(chunks_dist)
    norm = np.clip((dist + 1.5) / 3.0, 0.0, 1.0)
    rgb = np.column_stack([255.0 * (1.0 - norm), np.zeros_like(norm), 255.0 * norm])
    return np.hstack([pts, dist.reshape(-1, 1), rgb])


def _write_ascii_ply(path: Path, data: np.ndarray) -> None:
    """写与真实产物同格式的 ASCII PLY（x y z distance r g b），供 demo 演示"下载原始点云"。"""
    header = "\n".join([
        "ply",
        "format ascii 1.0",
        f"element vertex {data.shape[0]}",
        "property float x",
        "property float y",
        "property float z",
        "property float distance",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "end_header",
    ])
    np.savetxt(path, data, fmt="%.4f %.4f %.4f %.4f %d %d %d", header=header, comments="")


def _write_demo_clouds(stage: Path, points: int = 40000) -> dict:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from esdf_postprocess import write_web_preview

    data = _demo_esdf_cloud(points)
    info = write_web_preview(data, stage / "esdf_vis_web.ply", max_points=0)
    info["bounds_m"] = {
        axis: [float(data[:, i].min()), float(data[:, i].max())]
        for i, axis in enumerate(("x", "y", "z"))
    }
    # demo 没有真实 C++ 运行，用同一批合成点云补一份可下载的"完整 PLY"，让下载清单与真实任务一致
    _write_ascii_ply(stage / "esdf_vis.ply", data)
    return info


def _make_distance() -> None:
    d = OUT / KEY["distance"]
    sl = d / "slices"
    sl.mkdir(parents=True, exist_ok=True)
    sizes = {"xy": 0.0, "xz": 0.35, "yz": 0.6}  # per-plane gaussian centers

    slices = {}
    gradients = {}
    shift = {"xy": (0, 0), "xz": (35, 0), "yz": (0, -28)}  # per-plane roll (rows, cols)
    for name in sizes:
        arr = np.roll(_esdf_slice(), shift[name], axis=(0, 1))
        slices[name] = arr
        Image.fromarray(_heatmap(arr)).save(sl / f"{name}.png")
        Image.fromarray(_mask_png(arr)).save(sl / f"observed_{name}.png")
        gy, gx = np.gradient(arr)
        scale = 255 / 8
        gradients[name] = {
            "rows": arr.shape[0], "cols": arr.shape[1],
            "magnitude_max": round(float(np.abs(arr).max()), 3),
            "arrows": _sample_arrows(gx, gy, step=24, scale=scale),
        }

    (d / "gradient.json").write_text(json.dumps(gradients, indent=2), encoding="utf-8")
    with zipfile.ZipFile(d / "slices.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sizes:
            zf.write(sl / f"{name}.png", arcname=f"{name}.png")
            zf.write(sl / f"observed_{name}.png", arcname=f"observed_{name}.png")

    web = _write_demo_clouds(d)

    def _plane_meta(file_name: str, u_axis: str, v_axis: str, normal_axis: str,
                    u_range: list, v_range: list, center: float) -> dict:
        span = max(u_range[1] - u_range[0], v_range[1] - v_range[0])
        return {
            "file": file_name,
            "u_axis": u_axis, "v_axis": v_axis, "normal_axis": normal_axis,
            "u_range": u_range, "v_range": v_range,
            "image_size_px": [480, 480],
            "pixel_size_m": round(span / 479, 4),
            "distance_range": [-1.5, 1.5],
            "distance_range_observed": [-1.2, 1.2],
            "center_m": center, "half_thickness_m": 0.1, "thickness_m": 0.2,
            "sampled_points": 20000, "unit": "meter", "unknown_color": "white",
            "preview_abs_distance_max_m": 1.5, "image_orientation": "row0=v_max",
        }

    slices_meta = {
        "schema_version": "1.0",
        "unit": "meter",
        "image_resolution_px": 480,
        "distance_legend_range_m": [-1.5, 1.5],
        "preview_abs_distance_max_m": 1.5,
        "bounds_m": web["bounds_m"],
        "planes": {
            "xy": _plane_meta("slices/xy.png", "x", "y", "z", [-8.0, 8.0], [-8.0, 8.0], 1.5),
            "xz": _plane_meta("slices/xz.png", "x", "z", "y", [-8.0, 8.0], [0.0, 3.0], 0.0),
            "yz": _plane_meta("slices/yz.png", "y", "z", "x", [-8.0, 8.0], [0.0, 3.0], 0.0),
        },
        "web_preview": web,
    }
    (d / "slices_meta.json").write_text(json.dumps(slices_meta, indent=2), encoding="utf-8")

    (d / "progress.json").write_text(json.dumps({
        "stage": "distance", "backend": BACKENDS["distance"], "status": "completed",
        "phase": "completed", "progress": 100.0, "current": 120, "total": 120,
        "unit": "frame", "message": "Completed", "elapsed_sec": 55.0,
        "updated_at": _now(),
    }, ensure_ascii=False), encoding="utf-8")

    vox = {"xy": slices["xy"].size, "xz": slices["xz"].size, "yz": slices["yz"].size}
    (d / "result_manifest.json").write_text(json.dumps({
        "schema_version": "0.1",
        "job_id": "demo",
        "stage": "distance",
        "backend": BACKENDS["distance"],
        "status": "completed",
        "runtime_sec": 55.0,
        "frame_id": "world",
        "unit": "meter",
        "metrics": {"resolution_m": 0.1, "voxel_count": sum(vox.values()),
                    "max_distance_m": 9.0, "slices": list(slices),
                    "slices_meta": slices_meta},
        "artifacts": [
            {"artifact_id": "gradient", "role": "preview", "path": "gradient.json",
             "content_type": "application/json"},
            *[
                {"artifact_id": f"slice_{name}", "role": "preview",
                 "path": f"slices/{name}.png", "content_type": "image/png"}
                for name in slices
            ],
            *[
                {"artifact_id": f"observed_{name}", "role": "preview",
                 "path": f"slices/observed_{name}.png", "content_type": "image/png"}
                for name in slices
            ],
            {"artifact_id": "esdf_vis_ply", "role": "preview", "path": "esdf_vis.ply",
             "content_type": "application/octet-stream", "download": True,
             "note": "synthetic demo cloud, ASCII PLY (same points as the 3D preview)"},
            {"artifact_id": "esdf_web_ply", "role": "preview", "path": "esdf_vis_web.ply",
             "content_type": "application/octet-stream",
             "note": "downsampled binary point cloud for the in-page 3D viewer"},
            {"artifact_id": "slices_meta", "role": "data", "path": "slices_meta.json",
             "content_type": "application/json", "download": True},
            {"artifact_id": "slices_archive", "role": "data", "path": "slices.zip",
             "content_type": "application/zip", "download": True},
        ],
        "backend_details": {
            "mock_backend": True,
            "data_source": "demo preview (not a real algorithm run)",
            "note": "Prepared demo artifacts presented as voxel_esdf results for phase-1 demo.",
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _sample_arrows(gx: np.ndarray, gy: np.ndarray, step: int = 24, scale: float = 1.0) -> list[dict]:
    out = []
    h, w = gx.shape
    for i in range(0, h, step):
        for j in range(0, w, step):
            dx, dy = float(gx[i, j]) * scale, float(gy[i, j]) * scale
            out.append({"x": j, "y": i, "dx": round(dx, 2), "dy": round(dy, 2)})
    return out


# --------------------------------------------------------------------- job.json (completed seed)
def _job_json() -> dict:
    st = _now()
    stages = {}
    for s in STAGES:
        stages[s] = {
            "stage": s, "backend": BACKENDS[s], "status": "completed",
            "started_at": st, "finished_at": st,
        }
    return {
        "job_id": "demo",
        "dataset": "demo_room",
        "created_at": st,
        "preview_job": True,
        "fail_stage": None,
        "backends": dict(BACKENDS),
        "stages": stages,
    }


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "input").mkdir(parents=True, exist_ok=True)
    (OUT / "input" / "input_manifest.json").write_text(
        json.dumps(_input_manifest(), ensure_ascii=False, indent=2), encoding="utf-8")
    _make_pose()
    _make_surface()
    _make_distance()
    (OUT / "job.json").write_text(json.dumps(_job_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Demo job written to {OUT}")

    # smoke checks
    from app.models.manifest import load_manifest
    for s in STAGES:
        m = load_manifest(OUT / KEY[s]) or {}
        assert m.get("status") == "completed", s
        for a in m.get("artifacts", []):
            p = OUT / KEY[s] / a["path"]
            assert p.exists(), f"{a['artifact_id']} missing: {p}"


if __name__ == "__main__":
    main()