# Pose Timestamp Contract

## 0. Purpose

This document defines the time convention boundary between:

```text
Pose estimation
```

and:

```text
Surface reconstruction
```

The purpose is to prevent a silent but severe failure mode:

> A Pose file and a LiDAR frame stream may both contain timestamps while using different clocks or lookup conventions.

Matching them as if they were identical can associate the wrong Pose to a LiDAR frame.

---

## 1. Known conventions in the current system

### 1.1 GLIM native trajectory

GLIM's native LiDAR trajectory uses a physical LiDAR timestamp.

For the current INS reproduction:

```text
traj_lidar.txt
timestamp tx ty tz qx qy qz qw
```

The native timestamp corresponds to the physical LiDAR sensor/header time.

Canonical description:

```json
{
  "clock": "lidar_sensor",
  "lookup_key": "physical LiDAR sensor/header timestamp"
}
```

The native GLIM trajectory MUST be preserved as a native artifact.

---

### 1.2 MrHash LiDAR lookup

The current MrHash LiDAR pipeline uses the ROS bag record timestamp as the frame lookup key.

Canonical description:

```json
{
  "clock": "rosbag",
  "lookup_key": "ROS bag record timestamp"
}
```

The platform MUST NOT assume this timestamp is numerically identical to the physical LiDAR timestamp.

In the INS run, the bag record time may be approximately one LiDAR frame later than the LiDAR header time.

---

## 2. Required explicit mapping

The Pose runner MUST create an explicit mapping between:

```text
ROS bag record timestamp
```

and:

```text
physical LiDAR sensor/header timestamp
```

For ROS1 Livox bags, the bridge SHOULD emit:

```text
bag_index.tsv
```

Each LiDAR frame row SHOULD contain:

```text
record_timestamp_ns    sensor_timestamp_ns    point_count
```

Additional columns MAY be added, but these three fields are the minimum contract.

---

## 3. Canonical association algorithm

For each LiDAR frame in `bag_index.tsv`:

1. Read the frame's `sensor_timestamp_ns`.
2. Find the nearest native Pose sample by native timestamp.
3. Require timestamp residual to be less than or equal to `max_delta_sec`.
4. Preserve the matched `T_world_lidar`.
5. Write the output Pose row using the frame's `record_timestamp_ns` converted to seconds.
6. Keep output timestamps strictly increasing.

Important rule:

> The association changes the lookup timestamp used by Surface. It MUST NOT silently alter the Pose transform itself.

No interpolation is allowed unless the platform later introduces an explicit, documented interpolation mode.

The initial GLIM integration should use nearest-neighbor association only.

---

## 4. Default thresholds

Recommended defaults:

```text
max_delta_sec = 0.05
min_matched_ratio = 0.98
```

The previous idea of accepting `0.50` matched ratio is too weak for production handoff and MUST NOT be used as the default.

Dataset-specific configuration MAY tighten these thresholds.

Relaxing them below the defaults requires an explicit documented reason.

---

## 5. Required association statistics

The adapter MUST produce an audit artifact:

```text
association.json
```

It MUST contain at least:

```json
{
  "method": "nearest_native_pose_by_sensor_timestamp",
  "native_lookup_key": "physical LiDAR sensor/header timestamp",
  "output_lookup_key": "ROS bag record timestamp",

  "bag_frame_count": 0,
  "native_pose_count": 0,
  "matched_count": 0,
  "skipped_count": 0,
  "matched_ratio": 0.0,

  "mean_delta_sec": 0.0,
  "max_delta_sec_observed": 0.0,

  "head_unmatched_count": 0,
  "tail_unmatched_count": 0,

  "duplicate_pose_reuse_count": 0,
  "non_monotonic_match_count": 0
}
```

The exact JSON field names may follow the repository's style, but the information above MUST remain available.

---

## 6. Duplicate reuse

The system MUST detect whether multiple bag frames were associated to the same native Pose sample.

`duplicate_pose_reuse_count` MUST be reported.

Duplicate reuse is not automatically fatal in every future backend, but for the initial GLIM LiDAR path it SHOULD be treated as suspicious and surfaced clearly.

If duplicate reuse indicates a one-frame time shift or frame-rate mismatch, the Surface handoff MUST be rejected until understood.

---

## 7. Monotonicity

Association MUST preserve temporal ordering.

If native Pose indices move backward while bag record timestamps move forward:

```text
non_monotonic_match_count > 0
```

the Surface-compatible trajectory MUST NOT be produced.

This is a hard failure.

---

## 8. Head and tail gaps

GLIM may intentionally omit initial frames during initialization.

Therefore a small number of unmatched frames at the beginning or end may be acceptable.

The system MUST distinguish:

- unmatched frames at head
- unmatched frames at tail
- unmatched frames inside the sequence

Interior gaps are more suspicious than initialization/finalization gaps and SHOULD be reported separately if implementation cost is reasonable.

---

## 9. Failure conditions

Surface-compatible `poses.txt` MUST NOT be produced if:

- `bag_index.tsv` is missing
- bag index is empty
- native Pose trajectory is missing
- native Pose trajectory is empty
- no matches are found
- `matched_ratio < min_matched_ratio`
- timestamp residual exceeds configured limits for too many frames
- matching is non-monotonic
- output timestamps are not strictly increasing
- timestamp basis is unknown
- input timestamp basis is inconsistent with declared metadata

No silent fallback is allowed.

---

## 10. Manifest contract

If timestamp normalization succeeds:

```json
{
  "timestamp_basis": {
    "clock": "rosbag",
    "lookup_key": "ROS bag record timestamp"
  },
  "surface_handoff": {
    "compatible": true,
    "reason": null
  }
}
```

If native Pose is valid but normalization fails:

```json
{
  "timestamp_basis": {
    "clock": "lidar_sensor",
    "lookup_key": "physical LiDAR sensor/header timestamp"
  },
  "surface_handoff": {
    "compatible": false,
    "reason": "timestamp normalization failed: ..."
  }
}
```

The Pose stage MAY remain completed in this second case.

Surface MUST be blocked.

---

## 11. Surface gate

A Surface backend that requires a specific Pose lookup convention SHOULD declare it.

For MrHash LiDAR:

```text
required pose lookup key:
ROS bag record timestamp
```

Before preparing Surface input, the platform MUST compare:

```text
Pose result timestamp_basis.lookup_key
```

against:

```text
Surface required pose_lookup_key
```

If they differ, Surface MUST NOT start.

The error shown to the user MUST explain the incompatible timestamp conventions.

---

## 12. No synthetic success

The platform MUST NOT:

- relabel a physical LiDAR timestamp as a ROS bag record timestamp
- change only the manifest string while leaving the numeric timestamp unchanged
- force `surface_handoff.compatible=true` to allow Run All
- skip the association quality check
- accept a low matching ratio merely to produce an artifact

A failed timestamp handoff is preferable to a silently wrong reconstruction.
