# INS `indoor_long_corridor01` GLIM Dataset Profile

## 0. Purpose

This document is a **dataset-specific profile and example configuration** for integrating the INS `indoor_long_corridor01` sequence with the platform's GLIM Pose backend.

This is not a platform-global contract.

The platform core MUST NOT hard-code these values.

---

## 1. Dataset identity

Dataset:

```text
INS
```

Sequence:

```text
indoor_long_corridor01
```

Raw ROS1 bag:

```text
2024-06-04-16-24-55.bag
```

Verified full size:

```text
17125894059 bytes
```

The raw bag is intentionally not expected to live inside the source repository.

The platform dataset registry should reference it through the repository's existing dataset workspace mechanism.

---

## 2. Sensor topics

### LiDAR

```text
/livox_mid360/livox/lidar
```

Message type:

```text
livox_ros_driver2/msg/CustomMsg
```

### MID-360 internal IMU

```text
/livox_mid360/livox/imu
```

Message type:

```text
sensor_msgs/msg/Imu
```

### D455 RGB

```text
/camera_D455/color/image_raw
```

### D455 Depth

```text
/camera_D455/depth/image_rect_raw
```

### D455 IMU

```text
/camera_D455/imu
```

The GLIM Pose backend currently uses only MID-360 LiDAR + MID-360 IMU.

RGB-D remains available for other modules and future Pose backends.

---

## 3. Livox CustomMsg fields

The raw LiDAR message contains:

```text
uint64 timebase
uint32 point_num
CustomPoint[] points
```

Each point contains:

```text
uint32 offset_time
float32 x
float32 y
float32 z
uint8 reflectivity
uint8 tag
uint8 line
```

Observed first-frame values:

```text
point_num = 20160
offset_time min = 0
offset_time max = 100329213 ns
```

This confirms per-point timing is preserved in the raw bag.

---

## 4. ROS1 → ROS2 bridge contract

The bridge publishes:

```text
PointCloud2
```

with fields:

```text
x          FLOAT32
y          FLOAT32
z          FLOAT32
intensity  FLOAT32
t          UINT32
```

Where:

```text
t = Livox CustomPoint.offset_time
```

Unit:

```text
nanoseconds
```

The bridge also publishes MID-360 IMU as:

```text
sensor_msgs/Imu
```

The bridge SHOULD also write:

```text
bag_index.tsv
```

with the record-time ↔ sensor-time mapping required by the timestamp contract.

---

## 5. Frame ids

Observed/used frame ids:

LiDAR:

```text
livox_mid360_frame
```

IMU:

```text
livox_frame
```

---

## 6. GLIM sensor parameters

MID-360 IMU acceleration is treated as being in units of `g`.

Use:

```text
acc_scale = 9.80665
```

Per-point timing:

```text
perpoint_relative_time = true
perpoint_time_scale = 1e-9
```

LiDAR ↔ IMU transform used in the successful reproduction:

```text
T_lidar_imu =
[0.011, 0.02329, -0.04412, 0, 0, 0, 1]
```

Interpretation MUST follow GLIM's definition:

```text
T_lidar_imu transforms a point in the IMU frame into the LiDAR frame.
```

---

## 7. Successful GLIM reference run

Environment:

```text
Ubuntu 22.04
ROS2 Humble
GLIM 1.2.2 CUDA
RTX 4090
```

Successful GLIM native trajectory:

```text
1527 poses
```

Native trajectory time span:

```text
1717493096.801825047
→
1717493249.402045488
```

Ground truth:

```text
1537 poses
```

GT time span:

```text
1717493096.002225
→
1717493249.602266
```

---

## 8. Reference evaluation

Using:

```text
evo
TUM trajectory format
SE(3) Umeyama alignment
```

Reference metrics:

```text
ATE translation RMSE
0.094382 m
```

```text
RPE translation RMSE @ 1 m
0.023593 m
```

```text
RPE rotation RMSE @ 1 m
0.150735 deg
```

These values are **reference reproduction results**, not hard pass/fail thresholds for the platform adapter.

The platform integration may introduce small numerical differences due to startup timing, association rules, or runtime environment.

Large deviations require investigation.

---

## 9. Runtime environment notes

### GTSAM library selection

On the successful AutoDL machine, both of the following existed:

```text
/usr/local/lib
GTSAM 4.3
```

and:

```text
ROS Humble
GTSAM 4.2
```

GLIM/gtsam_points required the `/usr/local/lib` version.

Successful runtime setup:

```bash
source /opt/ros/humble/setup.bash
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
unset OMP_NUM_THREADS
```

The platform adapter SHOULD make runtime library/environment configuration explicit and configurable.

It MUST NOT hard-code the INS dataset path into the platform core.

---

## 10. Headless operation

AutoDL does not provide a normal desktop DISPLAY.

Viewer modules requiring GLFW/X11 caused startup failure.

Headless GLIM execution MUST avoid loading unnecessary viewer modules.

The dataset profile may reference a headless-compatible GLIM config, but headless behavior is a runtime/backend responsibility, not an INS-specific special case.

---

## 11. GLIM dump path

The current GLIM ROS2 node with:

```text
dump_on_unload=true
```

uses:

```text
/tmp/dump
```

as its dump destination.

Because this path is process-global, concurrent GLIM jobs MUST NOT share it.

Initial integration policy:

```text
Only one real GLIM job may execute at a time.
```

The runtime MUST use a global GLIM execution lock.

Before start:

1. acquire lock
2. verify or safely clear stale `/tmp/dump`
3. launch GLIM

After successful dump:

1. move/copy native artifacts into the job-local Pose output
2. verify required files
3. release lock

---

## 12. Example dataset configuration

The repository's existing dataset schema takes precedence.

The following is an intended semantic example, not a demand to replace the current schema verbatim:

```json
{
  "id": "ins_longcorridor01",
  "execution": "real",

  "modalities": [
    "lidar",
    "imu",
    "rgb",
    "depth"
  ],

  "files": {
    "bag": "INS/2024-06-04-16-24-55.bag"
  },

  "pose": {
    "backend": "glim",

    "lidar_topic": "/livox_mid360/livox/lidar",
    "imu_topic": "/livox_mid360/livox/imu",

    "lidar_frame_id": "livox_mid360_frame",
    "imu_frame_id": "livox_frame",

    "acc_scale": 9.80665,
    "perpoint_relative_time": true,
    "perpoint_time_scale": 1e-9,

    "T_lidar_imu": [
      0.011,
      0.02329,
      -0.04412,
      0.0,
      0.0,
      0.0,
      1.0
    ],

    "timestamp": {
      "native_lookup_key": "physical LiDAR sensor/header timestamp",
      "surface_lookup_key": "ROS bag record timestamp",
      "max_delta_sec": 0.05,
      "min_matched_ratio": 0.98
    }
  },

  "surface": {
    "backend": "mrhash_lidar",
    "pose_semantics": "T_world_lidar",
    "pose_lookup_key": "ROS bag record timestamp"
  }
}
```

---

## 13. Schema adaptation rule

If the repository already has different field names or nesting:

- preserve the existing repository structure
- map the semantics above into that structure
- do not invent a parallel dataset registration system
- document any unavoidable schema extension

Fields that are dataset-specific MUST stay in the dataset registry or job input manifest, not in generic GLIM runner code.

---

## 14. Expected platform flow

```text
INS raw bag
    ↓
dataset registry
    ↓
Pose backend = GLIM
    ↓
ROS1 Livox bridge
    ↓
ROS2 PointCloud2 + Imu
    ↓
GLIM
    ↓
native traj_lidar.txt
    ↓
timestamp normalization
    ↓
canonical stage1_pose/poses.txt
    ↓
trajectory_preview.json
    ↓
result_manifest.json
    ↓
MrHash Surface, only if timestamp-compatible
```
