# Pose Stage Contract

## 0. Status and scope

This document defines the **canonical contract of the Pose stage** in the 3D Mapping Platform.

It is intentionally backend-agnostic. GLIM is the first real SLAM backend to be integrated, but downstream stages MUST consume the same Pose contract regardless of whether the producer is:

- `registered_pose_import`
- `glim`
- `mola`
- `orb_slam3`
- any future Pose backend

This document is a contract, not a GLIM implementation guide.

---

## 1. Canonical Pose semantics

The canonical Pose semantic is:

```text
T_world_lidar
```

Meaning:

> `T_world_lidar` maps a 3D point expressed in the LiDAR frame into the world frame.

Mathematically:

```text
p_world = T_world_lidar * p_lidar
```

The platform MUST NOT silently reinterpret this as `T_lidar_world`.

If a backend natively produces another convention, that backend adapter MUST convert it before creating the canonical Pose artifact.

---

## 2. Canonical trajectory format

The canonical trajectory file is:

```text
stage1_pose/poses.txt
```

Each row MUST contain exactly 8 columns:

```text
timestamp tx ty tz qx qy qz qw
```

Definitions:

- `timestamp`: seconds, decimal floating-point representation
- `tx ty tz`: translation in meters
- `qx qy qz qw`: quaternion in xyzw order
- pose semantic: `T_world_lidar`

Validation requirements:

1. Every row has exactly 8 numeric values.
2. Every value is finite.
3. Timestamps are strictly increasing.
4. Quaternion norm is approximately 1.
5. The file contains at least one valid Pose row.
6. Translation unit is meter.
7. Quaternion order is `qx qy qz qw`.

The canonical trajectory timestamp basis is **not implied by the file format**. It MUST be declared explicitly in the result manifest.

---

## 3. Required Pose artifacts

A completed Pose stage MUST produce:

```text
stage1_pose/
├── poses.txt
├── trajectory_preview.json
└── result_manifest.json
```

A backend MAY additionally keep backend-native artifacts under:

```text
stage1_pose/native/
```

Examples for GLIM:

```text
stage1_pose/native/traj_lidar.txt
stage1_pose/native/traj_imu.txt
stage1_pose/native/odom_lidar.txt
stage1_pose/native/odom_imu.txt
stage1_pose/native/graph.bin
stage1_pose/native/config/
stage1_pose/native/run.log
stage1_pose/native/association.json
stage1_pose/native/bag_index.tsv
```

Downstream stages MUST NOT depend on backend-native filenames.

In particular, Surface MUST consume the canonical `poses.txt` artifact, not GLIM-specific `traj_lidar.txt`.

---

## 4. trajectory_preview.json

The preview artifact SHOULD follow the platform's existing preview contract.

At minimum it must contain enough information for the UI to render a trajectory.

Recommended structure:

```json
{
  "frame_count": 1527,
  "points": [
    {
      "x": 0.0,
      "y": 0.0,
      "z": 0.0,
      "qx": 0.0,
      "qy": 0.0,
      "qz": 0.0,
      "qw": 1.0
    }
  ]
}
```

If the existing repository already defines a stricter schema, the existing schema takes precedence.

---

## 5. result_manifest.json requirements

The Pose result manifest MUST use the platform's existing manifest mechanism.

It MUST declare at least:

- stage status
- backend id
- metrics
- artifacts
- backend details

The Pose-specific `backend_details` MUST contain:

```json
{
  "pose_semantics": "T_world_lidar",
  "translation_unit": "meter",
  "quaternion_order": "qx qy qz qw",
  "timestamp_basis": {
    "clock": "...",
    "lookup_key": "..."
  },
  "surface_handoff": {
    "compatible": true,
    "reason": null
  }
}
```

For a Surface-incompatible Pose result:

```json
{
  "surface_handoff": {
    "compatible": false,
    "reason": "human-readable reason"
  }
}
```

The Pose stage MAY still be considered successfully completed if the trajectory itself is valid but cannot be safely converted into the Surface timestamp convention.

That situation MUST NOT be represented as a successful Surface handoff.

---

## 6. Artifact roles

The canonical trajectory artifact SHOULD retain the existing platform role:

```text
artifact_id: registered_trajectory
role: trajectory
```

or the repository's existing equivalent.

Do not invent a GLIM-specific artifact role if the existing canonical trajectory role already satisfies the downstream contract.

The manifest SHOULD include:

- relative path
- size in bytes
- SHA-256
- download flag where appropriate

Existing manifest and artifact integrity mechanisms MUST be reused.

---

## 7. Backend abstraction

The platform MUST distinguish:

```text
Pose contract
```

from:

```text
Pose backend implementation
```

A backend is responsible for:

1. validating its dataset/runtime prerequisites
2. launching its algorithm
3. collecting native results
4. converting native output into the canonical Pose contract
5. writing the canonical manifest and preview

A backend MUST NOT require downstream stages to understand its internal files.

Expected backends include:

```text
registered_pose_import
glim
mola
orb_slam3
future adapters
```

The platform SHOULD express backend capabilities explicitly instead of using backend-id special cases wherever feasible.

---

## 8. Dataset relationship

A real dataset MUST have its sensor input artifact, such as the ROS bag.

For a SLAM-producing Pose backend:

```text
files.bag
```

is required.

A precomputed Pose file:

```text
files.poses
```

is optional.

Important invariant:

> Making `poses` optional MUST NOT accidentally make `bag` optional.

For `registered_pose_import`, a registered Pose source remains required.

For `glim`, Pose may be generated at runtime from LiDAR + IMU without a precomputed `files.poses`.

---

## 9. Failure rules

The Pose stage MUST fail explicitly if any of the following occurs:

- required dataset input is missing
- dataset integrity check fails
- backend configuration is invalid
- required LiDAR/IMU modality is unavailable
- backend subprocess cannot start
- backend subprocess exits unsuccessfully
- output trajectory is missing
- output trajectory is empty
- output Pose format is invalid
- timestamps are non-monotonic
- quaternion validation fails
- canonical artifacts cannot be produced
- required manifest cannot be created

A Pose stage MUST NOT produce a "completed" manifest merely because a subprocess returned exit code 0.

The platform's existing rule that completion requires both successful process exit and a completed result manifest SHOULD be preserved.

---

## 10. Run All behavior

For:

```text
Pose = GLIM
Surface = MrHash
```

the intended high-level flow is:

```text
registered dataset
    ↓
GLIM Pose runner
    ↓
validate canonical Pose
    ↓
validate timestamp compatibility
    ↓
prepare Surface input
    ↓
MrHash Surface runner
```

Surface MUST NOT start if the Pose result is valid but `surface_handoff.compatible == false`.

---

## 11. Backward compatibility

Integration of GLIM MUST preserve:

- `registered_pose_import`
- existing mock jobs
- existing MrHash LiDAR path
- existing MrHash RGB-D path
- existing artifact validation
- existing manifest validation
- existing cancellation semantics unless intentionally improved

No GLIM integration change may silently weaken an existing integrity check.

---

## 12. Non-goals

This contract does not define:

- GLIM-specific ROS topic names
- GLIM-specific file paths
- INS-specific calibration
- AutoDL filesystem paths
- a single hard-coded ROS distribution
- a single hard-coded GPU model

Those belong to runtime or dataset-specific configuration.
