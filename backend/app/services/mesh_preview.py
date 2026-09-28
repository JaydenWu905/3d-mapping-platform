"""Topology-preserving Surface preview generation and validation."""
from __future__ import annotations

import hashlib
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial


DEFAULT_PREVIEW_FACES = 500_000


def build_preview_glb(mesh_path: Path, output: Path,
                      target_faces: int = DEFAULT_PREVIEW_FACES) -> dict[str, Any]:
    """Weld exact duplicate vertices, simplify with QEM, and write a GLB.

    Exact welding restores adjacency in MrHash's marching-cubes PLY without
    changing any coordinate. QEM then collapses edges; it does not fill holes,
    smooth the surface, or join disconnected components.
    """
    if target_faces < 1:
        raise ValueError("target_faces must be positive")
    started = time.monotonic()
    mesh = trimesh.load_mesh(mesh_path, process=False)
    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty:
        raise ValueError("surface_mesh is not a non-empty triangle mesh")
    if len(mesh.faces) == 0 or np.asarray(mesh.faces).shape[1] != 3:
        raise ValueError("surface_mesh does not contain triangle faces")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("surface_mesh contains non-finite coordinates")

    source_vertices = len(mesh.vertices)
    source_faces = len(mesh.faces)
    source_bounds = mesh.bounds.tolist()
    mesh.merge_vertices()
    welded_vertices = len(mesh.vertices)
    if len(mesh.faces) > target_faces:
        mesh = mesh.simplify_quadric_decimation(
            face_count=target_faces, aggression=7
        )
    if mesh.is_empty or len(mesh.faces) == 0:
        raise ValueError("mesh simplification produced no geometry")

    # MrHash's current mesh RGB values are all zero. A neutral PBR material
    # keeps the geometry legible while generated normals provide real shading.
    mesh.visual.material = PBRMaterial(
        name="Surface preview",
        baseColorFactor=[176, 193, 204, 255],
        metallicFactor=0.0,
        roughnessFactor=0.9,
        doubleSided=True,
    )
    glb = trimesh.exchange.gltf.export_glb(mesh, include_normals=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(glb)
    validated = validate_preview_glb(output)
    return {
        "preview_method": "exact-vertex-weld+quadric-edge-collapse",
        "preview_target_faces": target_faces,
        "preview_vertices": validated["vertices"],
        "preview_faces": validated["faces"],
        "preview_size_bytes": output.stat().st_size,
        "preview_bounds": validated["bounds"],
        "preview_source_bounds": source_bounds,
        "preview_source_vertices": source_vertices,
        "preview_source_faces": source_faces,
        "preview_welded_vertices": welded_vertices,
        "preview_build_sec": round(time.monotonic() - started, 2),
        "preview_sha256": _sha256(output),
    }


def validate_preview_glb(path: Path) -> dict[str, Any]:
    """Parse a GLB and require finite, indexed triangle geometry."""
    loaded = trimesh.load(path, file_type="glb", process=False)
    meshes = (
        list(loaded.geometry.values())
        if isinstance(loaded, trimesh.Scene)
        else [loaded]
    )
    meshes = [mesh for mesh in meshes if isinstance(mesh, trimesh.Trimesh)]
    vertices = sum(len(mesh.vertices) for mesh in meshes)
    faces = sum(len(mesh.faces) for mesh in meshes)
    if vertices == 0 or faces == 0:
        raise ValueError("generated GLB contains no triangle geometry")
    bounds = np.vstack([mesh.bounds for mesh in meshes])
    if not np.isfinite(bounds).all():
        raise ValueError("generated GLB has non-finite bounds")
    return {
        "vertices": vertices,
        "faces": faces,
        "bounds": [bounds.min(axis=0).tolist(), bounds.max(axis=0).tolist()],
    }


def atomic_replace_preview(candidate: Path, destination: Path,
                           manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Replace preview and manifest together, restoring the old GLB on error."""
    backup = destination.with_name(f".{destination.name}.backup-{os.getpid()}")
    had_old = destination.is_file()
    try:
        if had_old:
            os.replace(destination, backup)
        os.replace(candidate, destination)
        _atomic_json(manifest_path, manifest)
    except BaseException:
        if destination.exists():
            os.replace(destination, candidate)
        if had_old and backup.exists():
            os.replace(backup, destination)
        raise
    finally:
        backup.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    import json

    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
