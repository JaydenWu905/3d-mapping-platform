# MrHash RGB-D interface preparation

Status: **contract and validation prepared; real execution unavailable and not accepted**.

This document records what is confirmed from code and what remains dependent on the real
first-module handoff. It does not claim that a real MrHash RGB-D run has succeeded.

## Read-only upstream findings

The tracked Python entry point is `mrhash/apps/rgbd_runner.py`; the processing core is exposed
through the C++/CUDA `pygeowrapper` binding. The runner parses YAML with these fields:
`data_path`, `results_path`, `end_frame`, map/streamer/mesh parameters, and sensor
`intrinsics: [fx, fy, cx, cy]`, `resolution: [width, height]`, `min_depth`, `max_depth`,
`depth_scaling`, and `hz`. Tracked Replica and ScanNet example configurations exist.

`DepthReader` confirms the native input layout rather than merely suggesting it by filename:

```text
<data_path>/
  results/*.jpg     RGB, naturally sorted
  results/*.png     depth, naturally sorted
  traj.txt          one flattened 4x4 matrix per frame
```

RGB and depth are paired solely by their natural-sort positions. The reader rejects unequal
counts, but does not read capture timestamps or an association file. Pose row `i` is used for
image pair `i`; there is no timestamp association. Depth PNG values are converted to metres as
`float32(stored_value) / depth_scaling`. RGB is decoded as RGB. The runner configures a pinhole
camera and does not consume distortion coefficients.

`DepthReader` extracts translation and SciPy quaternion `[qx,qy,qz,qw]` from each 4x4 matrix.
`GeoWrapper::setCurrPose` constructs that rotation and `compute()` installs the result through
`camera_->setCamInWorld(curr_pose_)`. Projection code maps camera points into world with that
matrix. Therefore the native matrix is `T_world_camera`, not `T_camera_world` and not a COLMAP
qvec/tvec. The code does not establish a general timestamp unit/clock domain, RGB-depth maximum
delta, missing-frame policy, distortion/rectification state, invalid stored depth value,
handedness, or named world-axis convention.

The tracked runner writes timestamped files named `mesh_*.ply`, `hash_points_*.ply`, and
`voxel_points_*.ply`, plus a copied YAML config. The filenames and artifact categories are
confirmed from upstream source. Their actual PLY encodings remain **provisional** until a real
RGB-D smoke run; the runtime adapter must inspect every produced PLY header and register its
observed encoding and field schema. An untracked local `rgbd_runner_mesh_only.py` was observed
and deliberately not treated as an upstream interface.

## Unified Surface Input Manifest 1.0 extension

RGB-D uses the existing schema/version and identity fields. `modalities` is
`["rgb","depth","pose"]`; the backend requirement `camera_pose` maps to the dataset modality
`pose` in the compatibility layer. This mirrors LiDAR's use of `["lidar","pose"]` and makes the
required trajectory explicit.
modality-specific artifacts replace the LiDAR `sensor_artifact`. This preserves one Pose-to-
Surface boundary instead of creating a second incompatible schema.

Required RGB-D fields are:

- `rgb_sequence_artifact`, `depth_sequence_artifact`, `frame_association_artifact`, and
  `trajectory_artifact`, each registry-owned and integrity described;
- `frame_count`; `timestamp.{basis,unit,clock_domain}`;
  `association.{max_rgb_depth_delta,max_rgb_pose_delta,max_depth_pose_delta}`;
  `missing_frame_policy`;
- `camera.{width,height,model,fx,fy,cx,cy,distortion_model,distortion_coefficients,images_rectified}`;
- `depth.{unit,scale_to_meters,invalid_value,min_valid_m,max_valid_m}`;
- `registration.rgb_depth_registered` and the provisional, explicitly directed `T_depth_rgb`;
- `pose.{transform_direction,source_frame,target_frame,quaternion_order,handedness,world_axis_convention}`;
- provenance containing first-module `algorithm`, `version`, `revision`, `configuration`, and
  `run_id`;
- `compatibility.{status,errors,warnings}`.

The sequence index is JSON schema `1.0` with a `frames` array. Every frame has an opaque unique
`frame_id`, `rgb_timestamp`, `depth_timestamp`, `pose_timestamp`, `pose_index`, and independent
RGB/depth records `{path,size_bytes,sha256}`. No filename pattern is meaningful. The trajectory
JSON schema `1.0` contains `poses`, each with `timestamp`, three-element `translation`, and a
four-element `quaternion` in the declared order, plus a top-level `transform_direction` that must
match the Pose contract. This platform trajectory JSON is **not**
MrHash's native `traj.txt` and must never be used by merely renaming it. The standard Surface
manifest accepts only normalized `T_world_camera`; `T_camera_world` is rejected before manifest
preparation until an explicitly tested normalization step exists.

MrHash's native `traj.txt` contains one flattened 4×4 `T_world_camera` matrix per frame. A future
runtime adapter must, transactionally inside the Job stage directory: read standard poses in
sequence-index order; convert translation plus quaternion to 4×4 `T_world_camera`; write matrices
in MrHash's required order; verify pose/RGB/depth counts; create the complete native image layout;
and atomically publish it. It must not rename or modify source handoff artifacts.

Platform depth semantics are:

```text
depth_meters = stored_depth_value * scale_to_meters
```

MrHash native configuration uses:

```text
depth_meters = stored_depth_value / depth_scaling
depth_scaling = 1 / scale_to_meters
```

Both values must be finite and positive. This mapping is implemented and unit-tested as contract
preparation only; it has not been accepted by a real RGB-D runner.

### Provisional RGB-to-Depth extrinsic

The current platform contract defines exactly one direction:

```text
p_depth = T_depth_rgb * p_rgb
```

Points are homogeneous column vectors. `source_frame` is `rgb`, `target_frame` is `depth`, JSON
matrix layout is a 4×4 row-major array, translation is in metres, and the last row is
`[0,0,0,1]`. The rotation must be orthonormal with determinant +1 within validator tolerance.
When `rgb_depth_registered` is `true`, `T_depth_rgb` must be `null`; when false it is required.
This representation is a **provisional platform contract**, not a fact confirmed from real
handoff data.

Initial registry validation resolves every path and symlink under its server-controlled dataset
root, verifies every size and SHA-256, image dimensions, counts, monotonic timestamps,
association tolerances, camera/depth declarations, and finite normalized poses. Launch-time
validation always re-hashes the small index and trajectory and checks every image's existence and
size. Successful strict results are cached for the service lifetime, so ordinary listing and
launch do not unconditionally re-hash a large image corpus; a service reload or strict audit
performs full hashing again.
The browser sends dataset/backend IDs only and cannot submit a server path.

## Pose terminology and conversion responsibility

These are distinct contracts:

- `T_world_camera`: `p_world = T_world_camera * p_camera`; this is MrHash's native expectation.
- `T_camera_world`: `p_camera = T_camera_world * p_world`; invert it before native ingestion.
- COLMAP `images.txt` qvec/tvec is world-to-camera:

  ```text
  p_camera = R_cw * p_world + t_cw
  R_wc = transpose(R_cw)
  t_wc = -transpose(R_cw) * t_cw
  T_world_camera = [[R_wc, t_wc], [0, 0, 0, 1]]
  ```

  Its quaternion convention must also be handled before declaring `T_world_camera`.

The first module owns that conversion and must declare its result. The validator explicitly
rejects an unconverted `COLMAP_qvec_tvec` source labelled `T_world_camera`. The phrase “camera
pose” alone is not a contract.

The first module also owns timestamp meaning, image decoding, calibration provenance, depth
unit/scale/invalid sentinel, distortion and rectification declarations, and RGB-depth registration
or a directed extrinsic. Surface owns validation and conversion from the standard manifest to a
backend-native layout only after that conversion is specified and accepted.

## Handoff checklist and remaining TBD

When real files arrive:

1. Confirm algorithm/version/revision/config/run ID and artifact provenance.
2. Confirm RGB/depth encodings, dimensions, calibration, distortion, rectification, depth scale,
   invalid value and valid range.
3. Confirm timestamp basis/unit/clock, association tolerances and missing-frame policy.
4. Confirm transform direction, frames, quaternion order, handedness and world axes; convert
   COLMAP world-to-camera data before registration.
5. Confirm whether RGB/depth are registered; otherwise supply a directed extrinsic.
6. Generate the sequence index and trajectory JSON, calculate sizes/hashes, add a server-controlled
   dataset registry, and pass strict validation.
7. Implement and review the lossless standard-manifest-to-native MrHash mapping; run smoke first,
   inspect only outputs that actually exist, then run the separately authorized full acceptance.
8. Only after real acceptance change `mrhash_rgbd` from disabled/unavailable to an appropriate
   runnable status.

TBD from the first module: every dataset-specific value above, image codecs beyond the confirmed
MrHash examples, timestamp association semantics, the real value or absence of the provisional
`T_depth_rgb`, and whether the delivered trajectory is already `T_world_camera`. Interface
preparation alone is not real MrHash RGB-D acceptance.

## Minimal provisional RGB-D registry example

This is valid JSON and deliberately uses only relative artifact paths:

```json
{
  "input_manifest": {
    "schema_version": "1.0",
    "dataset_id": "rgbd_example",
    "modalities": ["rgb", "depth", "pose"]
  },
  "surface": {"backend": "mrhash_rgbd"},
  "rgbd": {
    "sequence_index": {"path": "index/frames.json", "size_bytes": 1234, "sha256": "<64-hex-sha256>"},
    "trajectory": {"path": "trajectory/poses.json", "size_bytes": 5678, "sha256": "<64-hex-sha256>"},
    "frame_count": 2,
    "timestamp": {"basis": "capture", "unit": "second", "clock_domain": "camera_hardware"},
    "association": {
      "max_rgb_depth_delta": 0.01,
      "max_rgb_pose_delta": 0.01,
      "max_depth_pose_delta": 0.01
    },
    "missing_frame_policy": "reject",
    "camera": {
      "width": 640, "height": 480, "model": "pinhole",
      "fx": 500.0, "fy": 500.0, "cx": 319.5, "cy": 239.5,
      "distortion_model": "none", "distortion_coefficients": [], "images_rectified": true
    },
    "depth": {
      "unit": "millimeter", "scale_to_meters": 0.001, "invalid_value": 0,
      "min_valid_m": 0.1, "max_valid_m": 10.0
    },
    "registration": {
      "rgb_depth_registered": true, "T_depth_rgb": null,
      "source_frame": "rgb", "target_frame": "depth",
      "vector_convention": "homogeneous_column", "matrix_layout": "row_major",
      "translation_unit": "meter"
    },
    "pose": {
      "transform_direction": "T_world_camera", "source_frame": "camera", "target_frame": "world",
      "quaternion_order": "qx qy qz qw", "handedness": "right",
      "world_axis_convention": "TBD_BY_FIRST_MODULE"
    },
    "provenance": {
      "algorithm": "TBD", "version": "TBD", "revision": "TBD",
      "configuration": "TBD", "run_id": "TBD"
    }
  }
}
```
