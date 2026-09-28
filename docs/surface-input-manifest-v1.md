# Pose → Surface Input Manifest v1

Status: implemented for `registered_pose_import → mrhash_lidar`.

This document defines both sides of the boundary between the Pose producer and Surface
consumer. The platform has validated this hand-off with a registered precomputed Oxford Pose.
It has **not** yet run a real GLIM backend in the platform. A real GLIM-to-Surface joint
acceptance remains a separate milestone.

## Files and ownership

The Pose producer writes `stage1_pose/result_manifest.json` and its trajectory artifact. After
Pose reaches `completed`, the platform input preparer consumes that result plus the
server-controlled dataset registry and atomically writes
`stage2_surface/input/surface_input_manifest.json`. The browser selects IDs only and cannot
supply filesystem paths. Everything under `jobs/` is runtime state and is excluded from Git.

## Pose producer contract

The result must have `status: "completed"`, the correct `job_id`, `stage: "pose"`, producing
`backend`, `frame_id`, `unit`, `metrics`, `backend_details`, and `artifacts`. The implemented
importer emits schema `0.1`.

Required `backend_details` for the v1 LiDAR hand-off are:

| Field | Meaning |
|---|---|
| `run_id` | Unique producer/import run identifier |
| `result_origin` | Honest provenance: validated import or estimate from this run |
| `timestamp_basis` | Lookup and selection time semantics |
| `pose_semantics` | Currently `T_world_lidar` |
| `translation_unit` | Currently `meter` |
| `quaternion_order` | Currently `qx qy qz qw` |

An algorithm runner should additionally register its algorithm name/version, source revision or
image identity, and configuration artifact/source. The registered importer does not claim a GLIM
version because it does not execute GLIM.

### Artifacts

| Requirement | `artifact_id` | `role` | `content_type` | Notes |
|---|---|---|---|---|
| Required for LiDAR | `registered_trajectory` | `trajectory` | `text/plain` | Eight-column Pose file with `size_bytes` and `sha256` |
| Optional preview | `trajectory_model` | `preview` | `application/json` | Browser only; never an algorithm input |

The current v1 preparer resolves exactly `registered_trajectory` plus role `trajectory`; it does
not depend on the artifact filename. A future backend using another ID needs an explicit,
versioned preparation strategy.

### Pose row and transform convention

Each non-empty, non-comment row is:

```text
lookup_timestamp tx ty tz qx qy qz qw
```

All values must be finite, timestamps strictly increasing, and quaternion norm within the current
validator tolerance `[0.98, 1.02]`.

`T_world_lidar` transforms a point from the LiDAR frame into the world frame:

```text
p_world = R(q_world_lidar) * p_lidar + t_world_lidar
```

Translation is in metres and quaternion order is `qx qy qz qw`. The broader guarantees that both
frames are right-handed, plus the precise world-axis orientation, still require confirmation from
the Pose producer before they become backend-independent guarantees.

### Timestamp basis

The first column is the **Pose lookup timestamp** used by MrHash's ROS bag reader to associate a
row with a bag message. For registered Oxford it is the ROS bag record timestamp.

The **Pose selection timestamp** is the time used earlier to select or estimate the physical Pose.
For registered Oxford, the physical LiDAR first-point timestamp was matched to the nearest
completed GLIM trajectory Pose. That selection timestamp is not a separate column in the current
file. The lookup timestamp must therefore not be called the original GLIM timestamp.

## Surface consumer contract

`surface_input_manifest.json` schema `1.0` contains job/dataset/backend identity, modalities,
sensor and trajectory references, sizes and SHA-256 digests, timestamp and Pose semantics,
LiDAR topic, matching statistics, producer provenance, preparation time, compatibility, and an
optional `camera` section. `camera` is currently `null` for LiDAR.

For Oxford, `lidar_topic` is `/hesai/pandar`. The current registry does not declare the ROS
message type, so the manifest does not guarantee one. That type must be confirmed before a generic
LiDAR contract can require it.

`source_pose.backend`, `source_pose.run_id`, and `source_pose.origin` identify the producer. A
future real runner must also carry algorithm version and configuration source; v1 will need an
explicit extension for those values.

## Validation and compatibility

Preparation and launch implement these rules:

1. Resolve the trajectory by exact artifact ID and role from a completed Pose result.
2. Reject absolute artifact paths, `..`, missing files, and resolved paths outside the declared
   stage/dataset root. Resolve symlink targets before checking containment.
3. Recompute size and SHA-256 against the Pose manifest and dataset registry.
4. Re-parse Pose rows and reject malformed columns, non-finite values, non-increasing time,
   invalid quaternion norm, missing semantics, or an empty trajectory.
5. Write with a temporary file and atomic replacement. Unchanged preparation is idempotent;
   changed input is revalidated.
6. Repeat containment, existence, size, and SHA-256 checks immediately before MrHash starts.

Errors block Surface and are reported in progress/log state. A reliable count mismatch is a
warning if registered associations remain usable. Oxford records 3,111 Pose rows for 3,123 bag
messages, with 12 missing/skipped and status `compatible_with_warnings`; it is not a perfect match.

`registry_root` is resolved by the server and exists only in the runtime Job manifest. It may be
an absolute runtime path. Job manifests and run directories are excluded from Git, and examples
must not contain a private server path.

## Future RGB-D fields

An RGB-D preparation strategy must add, without inventing unavailable calibration:

- color/depth artifacts and timestamp association;
- camera model, dimensions, intrinsics (`fx`, `fy`, `cx`, `cy`), and distortion;
- depth encoding and scale/unit converting stored values to metres;
- an unambiguously directed camera/LiDAR transform such as `T_lidar_camera`;
- calibration artifact/reference, version, size, and SHA-256;
- color/depth/Pose match and skip statistics.

## Minimal example

The symbolic root deliberately avoids a server absolute path:

```json
{
  "schema_version": "1.0",
  "job_id": "job_example",
  "dataset_id": "oxford_mrhash_lidar",
  "surface_backend": "mrhash_lidar",
  "modalities": ["lidar", "pose"],
  "sensor_artifact": {
    "artifact_id": "registered_lidar_bag",
    "role": "sensor_data",
    "reference": "sequence.bag",
    "registry_root": "<server-controlled-dataset-root>",
    "size_bytes": 123456,
    "sha256": "<64-hex-sha256>"
  },
  "trajectory_artifact": {
    "artifact_id": "registered_trajectory",
    "role": "trajectory",
    "reference": "stage1_pose/poses.txt",
    "size_bytes": 1234,
    "sha256": "<64-hex-sha256>"
  },
  "timestamp_basis": {
    "lookup_key": "ROS bag record timestamp",
    "pose_selection": "nearest Pose by physical LiDAR first-point timestamp"
  },
  "pose_semantics": "T_world_lidar",
  "translation_unit": "meter",
  "quaternion_order": "qx qy qz qw",
  "lidar_topic": "/hesai/pandar",
  "matching": {
    "bag_message_count": 3123,
    "pose_count": 3111,
    "matched_count": 3111,
    "missing_or_skipped_count": 12
  },
  "source_pose": {
    "backend": "registered_pose_import",
    "run_id": "pose_import_example",
    "origin": "validated import of dataset-registered precomputed Pose"
  },
  "camera": null,
  "prepared_at": "2026-01-01T00:00:00",
  "compatibility": {
    "status": "compatible_with_warnings",
    "errors": [],
    "warnings": [{"code": "FRAME_COUNT_MISMATCH", "message": "3111 poses for 3123 bag messages; 12 messages are unmatched/skipped"}]
  }
}
```

## Acceptance status and questions for the first module

Registered Pose hand-off, preparation, launch validation, and real MrHash-LiDAR smoke/full have
been exercised. A real GLIM Runner is not integrated.

Real GLIM → Surface joint acceptance requires one Run All to execute GLIM, record its version and
configuration, produce this Pose contract, prepare Surface input, run MrHash-LiDAR, validate
standard outputs, preserve cancellation/failure/restart behavior, and require no manual import.

The first-module owner still needs to confirm:

1. Clock/domain and units for lookup and selection timestamps, and whether both must be retained.
2. Exact frame definitions, right-handedness, world-axis orientation, and multiplication convention.
3. Quaternion normalization/tolerance and interpolation convention.
4. Authoritative ROS topic and message type for each LiDAR dataset.
5. Representation of algorithm/version/revision, run ID, configuration, and calibration artifacts.
6. Whether `registered_trajectory` remains stable or a generic Pose artifact ID is introduced.
