# GLIM Pose Integration Acceptance Criteria

## 0. Purpose

This document defines when the GLIM Pose integration may be considered:

```text
code complete
```

and when it may be considered:

```text
end-to-end verified
```

The two claims are intentionally different.

---

## 1. Required architectural behavior

The integration MUST satisfy all of the following:

- real datasets can select GLIM when compatible
- incompatible datasets show an explicit reason
- `registered_pose_import` still works
- existing mock execution still works
- existing MrHash LiDAR execution still works
- existing MrHash RGB-D execution still works
- datasets without precomputed Pose can be valid for GLIM
- real datasets still require their raw bag
- GLIM adapter reads dataset/runtime configuration rather than hard-coding INS
- GLIM produces canonical Pose artifacts
- Surface consumes canonical Pose artifacts
- Surface does not depend on GLIM-native filenames
- Pose timestamp basis is explicit
- Surface timestamp requirement is explicit
- timestamp mismatch blocks Surface
- Run All respects the Pose → Surface gate

---

## 2. Dataset validation tests

Tests MUST cover:

### Valid GLIM dataset

Has:

```text
bag
lidar
imu
GLIM pose config
```

May omit:

```text
precomputed poses
```

Expected:

```text
dataset available
GLIM selectable
```

### Missing bag

Expected:

```text
dataset unavailable
```

Important:

> `bag` MUST remain required even after `poses` becomes optional.

### Missing LiDAR

Expected:

```text
GLIM unavailable with explicit reason
```

### Missing IMU

Expected:

```text
GLIM unavailable with explicit reason
```

### Invalid GLIM sensor config

Examples:

- malformed `T_lidar_imu`
- non-positive `acc_scale`
- invalid time scale

Expected:

```text
dataset/GLIM unavailable with explicit reason
```

---

## 3. Runner dispatch tests

Tests MUST confirm:

```text
(real, pose, registered_pose_import)
```

still dispatches correctly.

Tests MUST confirm:

```text
(real, pose, glim)
```

dispatches to the real GLIM adapter.

Tests MUST confirm unsupported real stage/backend combinations fail explicitly.

Backend runtime capability lists SHOULD have one source of truth where practical.

---

## 4. GLIM adapter dry-run tests

Without GPU/ROS2, the adapter MUST still be testable for:

- configuration parsing
- command construction
- environment construction
- job-local path construction
- required input validation
- output discovery logic
- failure messages
- timestamp normalization logic
- manifest construction
- cleanup plan

Dry-run tests MUST NOT claim GLIM actually executed.

---

## 5. Process lifecycle tests

GLIM integration introduces at least two long-running children:

```text
bridge
GLIM
```

Cancellation and timeout MUST terminate both.

Tests SHOULD verify:

- adapter receives termination
- bridge terminates
- GLIM terminates
- no orphan process remains
- job status becomes cancelled/failed as appropriate
- lock is released after abnormal termination

A child process MUST NOT escape into an unmanaged process group.

---

## 6. `/tmp/dump` concurrency protection

Current GLIM ROS2 dump path:

```text
/tmp/dump
```

This is shared process-global state.

Initial platform policy MUST enforce:

```text
at most one real GLIM job running at a time
```

Tests MUST cover:

- first GLIM job acquires lock
- second GLIM job is blocked or rejected clearly
- stale lock recovery policy is explicit
- `/tmp/dump` is checked before execution
- successful native dump is moved/copied to job-local storage
- lock is released on success
- lock is released on failure
- lock is released on cancellation

Do not implement fake concurrency by letting multiple jobs share `/tmp/dump`.

---

## 7. Timestamp association tests

Unit tests MUST cover:

### Perfect one-to-one match

Expected:

```text
matched_ratio = 1.0
surface_handoff.compatible = true
```

### Normal GLIM initialization gap

Small unmatched head frames.

Expected:

```text
association succeeds if matched_ratio >= threshold
head_unmatched_count > 0
```

### Residual exceeds tolerance

Expected:

```text
affected frames skipped
statistics updated
```

If ratio falls below threshold:

```text
Surface-compatible artifact rejected
```

### Non-monotonic association

Expected:

```text
hard failure
```

### Duplicate native Pose reuse

Expected:

```text
duplicate count reported
```

Suspicious reuse must not be hidden.

### Low matched ratio

Default:

```text
min_matched_ratio = 0.98
```

Anything below threshold:

```text
surface_handoff.compatible = false
```

No default of `0.50` is acceptable.

---

## 8. Surface handoff tests

For MrHash LiDAR:

Required Pose lookup key:

```text
ROS bag record timestamp
```

Tests MUST confirm:

### Matching timestamp basis

Expected:

```text
Surface input preparation succeeds
```

### Mismatched timestamp basis

Expected:

```text
Surface input preparation fails before MrHash starts
```

### Pose valid but Surface incompatible

Expected:

```text
Pose stage = completed
Surface stage = blocked
Run All stops with explicit reason
```

This distinction is required.

---

## 9. Manifest integrity tests

Canonical Pose artifact validation MUST preserve existing checks:

- file existence
- relative path containment
- size
- SHA-256
- Pose row validation
- timestamp monotonicity
- quaternion norm

GLIM integration MUST NOT weaken existing artifact integrity checks.

---

## 10. Frontend acceptance

The New Job page MUST:

- show GLIM for compatible real datasets
- disable GLIM for incompatible datasets
- display the incompatibility reason
- preserve `registered_pose_import`
- avoid hard-coding INS dataset ids
- avoid spreading GLIM-specific conditionals across unrelated UI code

Frontend typecheck MUST pass.

Frontend build SHOULD pass if the environment supports it.

---

## 11. Required static/code tests

At minimum run:

```text
Python syntax/compile check
shell bash -n
backend tests
frontend typecheck
configuration parsing tests
GLIM adapter dry-run tests
timestamp association unit tests
```

If possible also run:

```text
frontend production build
```

Any existing baseline test failures caused solely by the local OS/environment MUST be reported separately.

Do not hide them.

---

## 12. Reference AutoDL runtime

Real end-to-end verification requires an environment equivalent to:

```text
Ubuntu 22.04
ROS2 Humble
GLIM 1.2.2 CUDA
RTX 4090
INS raw ROS1 bag
```

Known successful runtime environment included:

```bash
source /opt/ros/humble/setup.bash
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
unset OMP_NUM_THREADS
```

Headless viewer issues must be avoided.

---

## 13. Real end-to-end test

The platform must execute:

```text
registered INS dataset
    ↓
Create Job
    ↓
Pose backend = GLIM
    ↓
Run Pose
    ↓
bridge starts
    ↓
GLIM starts
    ↓
GLIM receives LiDAR + IMU
    ↓
GLIM dumps native result
    ↓
native trajectory discovered
    ↓
timestamp normalization
    ↓
canonical poses.txt
    ↓
trajectory_preview.json
    ↓
result_manifest.json
```

Then, if timestamp normalization is valid:

```text
Run Surface
    ↓
prepare Surface input
    ↓
MrHash starts
```

---

## 14. Reference numerical results

The previous standalone reproduction on INS `indoor_long_corridor01` produced:

```text
GLIM trajectory:
1527 poses
```

Reference evaluation:

```text
ATE translation RMSE:
0.094382 m
```

```text
RPE translation RMSE @ 1m:
0.023593 m
```

```text
RPE rotation RMSE @ 1m:
0.150735 deg
```

These values are references, not exact bitwise pass/fail thresholds.

The integrated platform should produce a trajectory of similar coverage and quality.

Large deviations require investigation.

---

## 15. Claim policy

### Allowed claim: CODE TESTED

May be used when:

- source changes are complete
- static checks pass
- backend tests pass
- frontend typecheck passes
- adapter dry-run passes
- timestamp unit tests pass

but no real ROS2/GPU GLIM run was performed.

### Required label without real GPU run

```text
GPU INTEGRATION NOT VERIFIED
```

### Allowed claim: END-TO-END VERIFIED

Only after a real registered dataset is run through the platform on a machine with:

- ROS2
- GLIM
- CUDA/GPU
- raw bag

and the canonical Pose artifacts are produced successfully.

### Forbidden claims

Do NOT claim:

```text
real GLIM verified
Run All verified
MrHash handoff verified
```

if those paths were not actually executed.

---

## 16. Delivery checklist

Final implementation handoff MUST include:

1. modified file list
2. purpose of each modification
3. final Pose/GLIM call chain
4. dataset example
5. runtime instructions
6. test instructions
7. actual test output summary
8. unverified items
9. timestamp handling explanation
10. docs/README
11. `git diff --stat`
12. unexpected/non-intentional changes called out explicitly

Unrelated changes, such as accidental lock-file rewrites, MUST be reverted before delivery unless intentionally required.
