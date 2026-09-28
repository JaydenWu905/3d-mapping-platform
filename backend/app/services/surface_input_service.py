"""Versioned Pose-to-Surface contract preparation and validation."""
from __future__ import annotations

import time
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.models.progress import atomic_write_json, read_json
from app.services.pose_import_service import read_pose_rows, sha256_file


class SurfaceInputError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _registered_path(root: Path, reference: Any, *, file_label: str) -> Path:
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute() or ".." in Path(reference).parts:
        raise SurfaceInputError(f"{file_label} path must be a safe relative path")
    resolved_root = root.resolve()
    path = (resolved_root / reference).resolve()
    if resolved_root not in path.parents or not path.is_file():
        raise SurfaceInputError(f"{file_label} escapes the dataset root (including symlinks) or is missing")
    return path


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def mrhash_depth_scaling(scale_to_meters: Any) -> float:
    """Map the platform multiply-by scale to MrHash's divide-by scaling."""
    if not _finite_number(scale_to_meters) or float(scale_to_meters) <= 0:
        raise SurfaceInputError("depth scale must be finite and positive")
    scaling = 1.0 / float(scale_to_meters)
    if not math.isfinite(scaling) or scaling <= 0:
        raise SurfaceInputError("derived MrHash depth_scaling must be finite and positive")
    return scaling


def _validate_t_depth_rgb(value: Any) -> None:
    if not isinstance(value, list) or len(value) != 4 or any(
        not isinstance(row, list) or len(row) != 4 or not all(_finite_number(v) for v in row)
        for row in value
    ):
        raise SurfaceInputError("T_depth_rgb must be a finite 4x4 row-major matrix")
    if any(abs(float(value[3][i]) - expected) > 1e-6 for i, expected in enumerate((0, 0, 0, 1))):
        raise SurfaceInputError("T_depth_rgb last row must be [0, 0, 0, 1]")
    rotation = [[float(value[r][c]) for c in range(3)] for r in range(3)]
    for i in range(3):
        for j in range(3):
            dot = sum(rotation[k][i] * rotation[k][j] for k in range(3))
            expected = 1.0 if i == j else 0.0
            if abs(dot - expected) > 1e-3:
                raise SurfaceInputError("T_depth_rgb rotation must be orthonormal")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if abs(determinant - 1.0) > 1e-3:
        raise SurfaceInputError("T_depth_rgb rotation determinant must be +1")


def _validate_file_record(root: Path, record: Any, label: str, strict_hashes: bool) -> tuple[Path, str | None]:
    if not isinstance(record, dict):
        raise SurfaceInputError(f"{label} file record is missing")
    path = _registered_path(root, record.get("path"), file_label=label)
    size = record.get("size_bytes")
    digest = record.get("sha256")
    if not isinstance(size, int) or size < 0 or path.stat().st_size != size:
        raise SurfaceInputError(f"{label} size does not match the registry")
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
        raise SurfaceInputError(f"{label} SHA-256 is missing or invalid")
    if strict_hashes and _sha256(path) != digest.lower():
        raise SurfaceInputError(f"{label} SHA-256 does not match the registry")
    return path, digest.lower()


def validate_rgbd_dataset(definition, *, strict_hashes: bool) -> list[str]:
    """Validate the registry-owned RGB-D contract; never accepts browser paths."""
    try:
        root = definition.source_dir.resolve()
        if not root.is_dir():
            raise SurfaceInputError("configured RGB-D source directory is unavailable")
        spec = definition.rgbd
        if definition.input_manifest.get("modalities") != ["rgb", "depth", "pose"]:
            raise SurfaceInputError("RGB-D dataset modalities must be ['rgb', 'depth', 'pose']")
        required = {
            "sequence_index", "trajectory", "frame_count", "timestamp", "association",
            "missing_frame_policy", "camera", "depth", "registration", "pose", "provenance",
        }
        missing = sorted(required - set(spec))
        if missing:
            raise SurfaceInputError("RGB-D registry is missing: " + ", ".join(missing))
        index_path, _ = _validate_file_record(root, spec["sequence_index"], "sequence index", strict_hashes)
        trajectory_path, _ = _validate_file_record(root, spec["trajectory"], "trajectory", strict_hashes)
        index = json.loads(index_path.read_text(encoding="utf-8"))
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
        frames = index.get("frames") if isinstance(index, dict) else None
        poses = trajectory.get("poses") if isinstance(trajectory, dict) else None
        if index.get("schema_version") != "1.0" or not isinstance(frames, list) or not frames:
            raise SurfaceInputError("sequence index schema 1.0 with non-empty frames is required")
        if trajectory.get("schema_version") != "1.0" or not isinstance(poses, list):
            raise SurfaceInputError("trajectory schema 1.0 with poses is required")
        if trajectory.get("transform_direction") != "T_world_camera":
            raise SurfaceInputError("trajectory transform_direction must match normalized T_world_camera Pose contract")
        declared = spec["frame_count"]
        if not isinstance(declared, int) or declared <= 0 or len(frames) != declared:
            raise SurfaceInputError("RGB/Depth frame count does not match frame_count")
        if len(poses) != declared:
            raise SurfaceInputError("Pose is missing or Pose count does not match frame_count")

        timestamp = spec["timestamp"]
        if not all(isinstance(timestamp.get(k), str) and timestamp[k] for k in ("basis", "unit", "clock_domain")):
            raise SurfaceInputError("timestamp basis, unit, and clock_domain are required")
        association = spec["association"]
        limits = [association.get(k) for k in ("max_rgb_depth_delta", "max_rgb_pose_delta", "max_depth_pose_delta")]
        if not all(_finite_number(v) and float(v) >= 0 for v in limits):
            raise SurfaceInputError("association maximum time deltas must be finite and non-negative")
        if spec["missing_frame_policy"] not in ("reject", "skip_declared"):
            raise SurfaceInputError("missing_frame_policy must be reject or skip_declared")

        camera = spec["camera"]
        if camera.get("model") not in ("pinhole", "opencv", "fisheye"):
            raise SurfaceInputError("unsupported camera model")
        width, height = camera.get("width"), camera.get("height")
        if not isinstance(width, int) or width <= 0 or not isinstance(height, int) or height <= 0:
            raise SurfaceInputError("image width/height must be positive integers")
        intrinsics = [camera.get(k) for k in ("fx", "fy", "cx", "cy")]
        if not all(_finite_number(v) for v in intrinsics) or float(camera.get("fx", 0)) <= 0 or float(camera.get("fy", 0)) <= 0:
            raise SurfaceInputError("camera intrinsics are invalid")
        if camera.get("distortion_model") not in ("none", "opencv", "fisheye") or not isinstance(camera.get("distortion_coefficients"), list):
            raise SurfaceInputError("distortion model and coefficients are required")
        if not isinstance(camera.get("images_rectified"), bool):
            raise SurfaceInputError("images_rectified must be boolean")

        depth = spec["depth"]
        if depth.get("unit") not in ("meter", "millimeter", "raw"):
            raise SurfaceInputError("depth unit is invalid")
        mrhash_depth_scaling(depth.get("scale_to_meters"))
        if not _finite_number(depth.get("min_valid_m")) or not _finite_number(depth.get("max_valid_m")) or not 0 <= float(depth["min_valid_m"]) < float(depth["max_valid_m"]):
            raise SurfaceInputError("depth valid range is invalid")
        if "invalid_value" not in depth:
            raise SurfaceInputError("invalid depth value must be declared")
        if not _finite_number(depth["invalid_value"]):
            raise SurfaceInputError("invalid depth value must be finite")

        registration = spec["registration"]
        if not isinstance(registration.get("rgb_depth_registered"), bool):
            raise SurfaceInputError("rgb_depth_registered must be boolean")
        expected_registration = {
            "source_frame": "rgb", "target_frame": "depth",
            "vector_convention": "homogeneous_column", "matrix_layout": "row_major",
            "translation_unit": "meter",
        }
        for key, expected in expected_registration.items():
            if registration.get(key) != expected:
                raise SurfaceInputError(f"T_depth_rgb {key} must be {expected}")
        extrinsic = registration.get("T_depth_rgb")
        if registration["rgb_depth_registered"]:
            if extrinsic is not None:
                raise SurfaceInputError("T_depth_rgb must be null when RGB/Depth is registered")
        else:
            if extrinsic is None:
                raise SurfaceInputError("unregistered RGB/Depth requires T_depth_rgb")
            _validate_t_depth_rgb(extrinsic)

        pose_spec = spec["pose"]
        if pose_spec.get("transform_direction") != "T_world_camera":
            raise SurfaceInputError("Pose transform_direction must be normalized to T_world_camera")
        if not all(isinstance(pose_spec.get(k), str) and pose_spec[k] for k in ("source_frame", "target_frame", "quaternion_order", "handedness", "world_axis_convention")):
            raise SurfaceInputError("Pose frames, quaternion order, handedness, and world axis convention are required")
        if pose_spec["quaternion_order"] not in ("qx qy qz qw", "qw qx qy qz"):
            raise SurfaceInputError("unsupported quaternion order")
        if pose_spec.get("source_format") == "COLMAP_qvec_tvec" and not pose_spec.get("converted_from_world_to_camera"):
            raise SurfaceInputError("COLMAP world-to-camera qvec/tvec must be converted before it is labelled T_world_camera")
        provenance = spec["provenance"]
        if not all(isinstance(provenance.get(k), str) and provenance[k] for k in ("algorithm", "version", "revision", "configuration", "run_id")):
            raise SurfaceInputError("provenance algorithm/version/revision/configuration/run_id are required")

        previous = {"rgb": None, "depth": None, "pose": None}
        seen_ids: set[str] = set()
        from PIL import Image
        for position, frame in enumerate(frames):
            frame_id = frame.get("frame_id")
            if not isinstance(frame_id, str) or not frame_id or frame_id in seen_ids:
                raise SurfaceInputError("frame_id values must be unique non-empty strings")
            seen_ids.add(frame_id)
            times = {kind: frame.get(f"{kind}_timestamp") for kind in previous}
            if not all(_finite_number(v) for v in times.values()):
                raise SurfaceInputError(f"frame {frame_id} timestamps must be finite")
            for kind, value in times.items():
                if previous[kind] is not None and float(value) <= previous[kind]:
                    raise SurfaceInputError(f"{kind} timestamps must be strictly increasing")
                previous[kind] = float(value)
            if abs(float(times["rgb"]) - float(times["depth"])) > float(limits[0]) or abs(float(times["rgb"]) - float(times["pose"])) > float(limits[1]) or abs(float(times["depth"]) - float(times["pose"])) > float(limits[2]):
                raise SurfaceInputError(f"frame {frame_id} RGB/Depth/Pose association exceeds the allowed delta")
            if frame.get("pose_index") != position:
                raise SurfaceInputError(f"frame {frame_id} Pose association is missing or out of order")
            for kind in ("rgb", "depth"):
                image_path, _ = _validate_file_record(root, frame.get(kind), f"frame {frame_id} {kind}", strict_hashes)
                with Image.open(image_path) as image:
                    if image.size != (width, height):
                        raise SurfaceInputError(f"frame {frame_id} {kind} dimensions do not match camera")
            pose = poses[position]
            if pose.get("timestamp") != times["pose"]:
                raise SurfaceInputError(f"frame {frame_id} Pose timestamp does not match trajectory")
            translation, quaternion = pose.get("translation"), pose.get("quaternion")
            if not isinstance(translation, list) or len(translation) != 3 or not all(_finite_number(v) for v in translation):
                raise SurfaceInputError(f"frame {frame_id} Pose translation is invalid")
            if not isinstance(quaternion, list) or len(quaternion) != 4 or not all(_finite_number(v) for v in quaternion):
                raise SurfaceInputError(f"frame {frame_id} Pose quaternion is invalid")
            norm = math.sqrt(sum(float(v) ** 2 for v in quaternion))
            if not 0.98 <= norm <= 1.02:
                raise SurfaceInputError(f"frame {frame_id} Pose quaternion is not normalized")
        return []
    except (SurfaceInputError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [str(exc)]


def _artifact(manifest: dict[str, Any], artifact_id: str, role: str) -> dict[str, Any]:
    matches = [a for a in manifest.get("artifacts", []) if a.get("artifact_id") == artifact_id and a.get("role") == role]
    if len(matches) != 1:
        raise SurfaceInputError(f"required Pose artifact {artifact_id!r} with role {role!r} is missing or ambiguous")
    return matches[0]


def _resolve(stage_dir: Path, artifact: dict[str, Any]) -> Path:
    rel = artifact.get("path")
    if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise SurfaceInputError("Pose artifact path is not a safe relative path")
    root = stage_dir.resolve()
    target = (stage_dir / rel).resolve()
    if root not in target.parents or not target.is_file():
        raise SurfaceInputError("Pose artifact escapes its stage or is missing")
    size, digest = target.stat().st_size, sha256_file(target)
    if artifact.get("size_bytes") != size or artifact.get("sha256") != digest:
        raise SurfaceInputError("Pose artifact size or SHA-256 does not match its result manifest")
    return target


def prepare_mrhash_lidar_input(job_id: str, jobs) -> dict[str, Any]:
    job = jobs.load_job(job_id)
    definition = jobs.datasets.get(job["dataset"])
    pose_dir = jobs.stage_dir(job_id, "pose")
    pose = read_json(pose_dir / "result_manifest.json", None)
    if not isinstance(pose, dict) or pose.get("status") != "completed":
        raise SurfaceInputError("completed Pose result_manifest.json is required")
    details = pose.get("backend_details", {})
    missing = [key for key in ("timestamp_basis", "pose_semantics", "translation_unit", "quaternion_order") if not details.get(key)]
    if missing:
        raise SurfaceInputError("Pose manifest missing required semantics: " + ", ".join(missing))
    if not isinstance(details["timestamp_basis"], dict) or not details["timestamp_basis"].get("lookup_key"):
        raise SurfaceInputError("Pose timestamp_basis must contain a non-empty lookup_key")
    if details["pose_semantics"] != "T_world_lidar":
        raise SurfaceInputError("Pose semantics must be T_world_lidar")
    if details["translation_unit"] != "meter":
        raise SurfaceInputError("Pose translation_unit must be meter")
    if details["quaternion_order"] != "qx qy qz qw":
        raise SurfaceInputError("Pose quaternion_order must be qx qy qz qw")
    trajectory_artifact = _artifact(pose, "registered_trajectory", "trajectory")
    trajectory = _resolve(pose_dir, trajectory_artifact)
    rows = read_pose_rows(trajectory)
    bag = definition.source_file("bag").resolve()
    root = definition.source_dir.resolve()
    if root not in bag.parents or not bag.is_file():
        raise SurfaceInputError("registered sensor artifact escapes dataset root or is missing")
    bag_sha = definition.integrity.get("bag_sha256")
    if not bag_sha or definition.integrity.get("bag_size_bytes") != bag.stat().st_size or sha256_file(bag) != bag_sha:
        raise SurfaceInputError("registered sensor artifact size/SHA-256 validation failed")
    lidar_topic = definition.surface.get("topic")
    if not isinstance(lidar_topic, str) or not lidar_topic.strip():
        raise SurfaceInputError("LiDAR topic must be a non-empty string")
    declared = definition.input_manifest.get("bag_message_count")
    pose_count = len(rows)
    warnings: list[dict[str, str]] = []
    missing_count = max(int(declared) - pose_count, 0) if declared is not None else None
    if declared is not None and int(declared) != pose_count:
        warnings.append({"code": "FRAME_COUNT_MISMATCH", "message": f"{pose_count} poses for {declared} bag messages; {missing_count} messages are unmatched/skipped"})
    manifest = {
        "schema_version": "1.0", "job_id": job_id, "dataset_id": definition.id,
        "surface_backend": "mrhash_lidar", "modalities": ["lidar", "pose"],
        "sensor_artifact": {"artifact_id": "registered_lidar_bag", "role": "sensor_data", "reference": str(bag.relative_to(root)),
                            "registry_root": str(root), "size_bytes": bag.stat().st_size, "sha256": bag_sha},
        "trajectory_artifact": {"artifact_id": trajectory_artifact["artifact_id"], "role": trajectory_artifact["role"],
                                "reference": str(trajectory.relative_to(jobs.job_dir(job_id).resolve())),
                                "size_bytes": trajectory.stat().st_size, "sha256": trajectory_artifact["sha256"]},
        "timestamp_basis": details["timestamp_basis"], "pose_semantics": details["pose_semantics"],
        "translation_unit": details["translation_unit"], "quaternion_order": details["quaternion_order"],
        "lidar_topic": lidar_topic,
        "matching": {"bag_message_count": declared, "pose_count": pose_count, "matched_count": pose_count,
                     "missing_or_skipped_count": missing_count},
        "source_pose": {"backend": pose.get("backend"), "run_id": details.get("run_id"), "origin": details.get("result_origin")},
        "camera": None, "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "compatibility": {"status": "compatible_with_warnings" if warnings else "compatible", "errors": [], "warnings": warnings},
    }
    out = jobs.stage_dir(job_id, "surface") / "input" / "surface_input_manifest.json"
    existing = read_json(out, None)
    if isinstance(existing, dict):
        comparable_existing = {key: value for key, value in existing.items() if key != "prepared_at"}
        comparable_new = {key: value for key, value in manifest.items() if key != "prepared_at"}
        if comparable_existing == comparable_new:
            manifest["prepared_at"] = existing.get("prepared_at", manifest["prepared_at"])
    atomic_write_json(out, manifest)
    return manifest


def prepare_mrhash_rgbd_input(job_id: str, jobs) -> dict[str, Any]:
    job = jobs.load_job(job_id)
    definition = jobs.datasets.get(job["dataset"])
    if definition.surface.get("backend") != "mrhash_rgbd":
        raise SurfaceInputError("dataset is not registered for mrhash_rgbd")
    errors = validate_rgbd_dataset(definition, strict_hashes=False)
    if errors:
        raise SurfaceInputError("; ".join(errors))
    spec = definition.rgbd
    root = definition.source_dir.resolve()
    index_path = _registered_path(root, spec["sequence_index"]["path"], file_label="sequence index")
    trajectory_path = _registered_path(root, spec["trajectory"]["path"], file_label="trajectory")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    totals = {
        kind: sum(int(frame[kind]["size_bytes"]) for frame in index["frames"])
        for kind in ("rgb", "depth")
    }
    manifest = {
        "schema_version": "1.0", "job_id": job_id, "dataset_id": definition.id,
        "surface_backend": "mrhash_rgbd", "modalities": ["rgb", "depth", "pose"],
        "rgb_sequence_artifact": {
            "artifact_id": "registered_rgb_sequence", "role": "sensor_data",
            "index_reference": spec["sequence_index"]["path"], "registry_root": str(root),
            "frame_count": spec["frame_count"], "total_size_bytes": totals["rgb"],
            "index_size_bytes": index_path.stat().st_size, "index_sha256": spec["sequence_index"]["sha256"],
            "provenance": spec["provenance"],
        },
        "depth_sequence_artifact": {
            "artifact_id": "registered_depth_sequence", "role": "sensor_data",
            "index_reference": spec["sequence_index"]["path"], "registry_root": str(root),
            "frame_count": spec["frame_count"], "total_size_bytes": totals["depth"],
            "index_size_bytes": index_path.stat().st_size, "index_sha256": spec["sequence_index"]["sha256"],
            "provenance": spec["provenance"],
        },
        "frame_association_artifact": {
            "artifact_id": "rgbd_sequence_index", "role": "association", "reference": spec["sequence_index"]["path"],
            "registry_root": str(root), "size_bytes": index_path.stat().st_size, "sha256": spec["sequence_index"]["sha256"],
        },
        "trajectory_artifact": {
            "artifact_id": "registered_trajectory", "role": "trajectory", "reference": spec["trajectory"]["path"],
            "registry_root": str(root), "size_bytes": trajectory_path.stat().st_size, "sha256": spec["trajectory"]["sha256"],
        },
        "frame_count": spec["frame_count"], "timestamp": spec["timestamp"],
        "association": spec["association"], "missing_frame_policy": spec["missing_frame_policy"],
        "camera": spec["camera"], "depth": spec["depth"] | {"mrhash_depth_scaling": mrhash_depth_scaling(spec["depth"]["scale_to_meters"])},
        "registration": spec["registration"],
        "pose": spec["pose"], "source_pose": spec["provenance"],
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "compatibility": {"status": "contract_validated_backend_not_ready", "errors": [], "warnings": [{
            "code": "MRHASH_RGBD_NOT_ACCEPTED", "message": "Standard input is valid; real MrHash RGB-D execution has not been accepted."
        }]},
    }
    out = jobs.stage_dir(job_id, "surface") / "input" / "surface_input_manifest.json"
    existing = read_json(out, None)
    if isinstance(existing, dict) and {k: v for k, v in existing.items() if k != "prepared_at"} == {k: v for k, v in manifest.items() if k != "prepared_at"}:
        manifest["prepared_at"] = existing.get("prepared_at", manifest["prepared_at"])
    atomic_write_json(out, manifest)
    return manifest


SURFACE_INPUT_STRATEGIES = {
    "mrhash_lidar": prepare_mrhash_lidar_input,
    "mrhash_rgbd": prepare_mrhash_rgbd_input,
}


def prepare_surface_input(job_id: str, jobs) -> dict[str, Any]:
    backend = jobs.load_job(job_id).get("backends", {}).get("surface")
    strategy = SURFACE_INPUT_STRATEGIES.get(backend)
    if strategy is None:
        raise SurfaceInputError(f"no Surface input strategy for backend {backend!r}")
    return strategy(job_id, jobs)


def validate_surface_input(job_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    manifest_path = job_dir / "stage2_surface" / "input" / "surface_input_manifest.json"
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise SurfaceInputError("valid surface_input_manifest.json schema 1.0 is required")
    job_root = job_dir.resolve()
    trajectory = (job_root / manifest["trajectory_artifact"]["reference"]).resolve()
    if job_root not in trajectory.parents or not trajectory.is_file():
        raise SurfaceInputError("trajectory reference escapes Job or is missing")
    sensor = manifest["sensor_artifact"]
    registry_root = Path(sensor["registry_root"]).resolve()
    bag = (registry_root / sensor["reference"]).resolve()
    if registry_root not in bag.parents or not bag.is_file():
        raise SurfaceInputError("sensor reference escapes registered root or is missing")
    for path, artifact in ((trajectory, manifest["trajectory_artifact"]), (bag, sensor)):
        if path.stat().st_size != artifact["size_bytes"] or sha256_file(path) != artifact["sha256"]:
            raise SurfaceInputError(f"{artifact['artifact_id']} failed launch-time integrity validation")
    return manifest, bag, trajectory


def validate_mrhash_rgbd_surface_input(job_dir: Path, *, strict_hashes: bool = False) -> dict[str, Any]:
    """Launch-time revalidation: hash small indexes always; frame hashes on registry import."""
    manifest_path = job_dir / "stage2_surface" / "input" / "surface_input_manifest.json"
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0" or manifest.get("surface_backend") != "mrhash_rgbd":
        raise SurfaceInputError("valid mrhash_rgbd Surface Input Manifest 1.0 is required")
    association = manifest.get("frame_association_artifact", {})
    trajectory = manifest.get("trajectory_artifact", {})
    root = Path(association.get("registry_root", "")).resolve()
    if root != Path(trajectory.get("registry_root", "")).resolve():
        raise SurfaceInputError("RGB-D artifacts do not share the registered root")
    index_path, _ = _validate_file_record(root, {"path": association.get("reference"), "size_bytes": association.get("size_bytes"), "sha256": association.get("sha256")}, "sequence index", True)
    _validate_file_record(root, {"path": trajectory.get("reference"), "size_bytes": trajectory.get("size_bytes"), "sha256": trajectory.get("sha256")}, "trajectory", True)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if len(index.get("frames", [])) != manifest.get("frame_count"):
        raise SurfaceInputError("launch-time RGB-D frame count mismatch")
    # Cheap launch checks detect replacements by size. Full content hashing is
    # reserved for strict registry validation or explicitly requested audits.
    for frame in index["frames"]:
        for kind in ("rgb", "depth"):
            _validate_file_record(root, frame.get(kind), f"frame {frame.get('frame_id')} {kind}", strict_hashes)
    return manifest
