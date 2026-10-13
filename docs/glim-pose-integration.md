# GLIM Pose backend integration

Status of this work:

```text
CODE TESTED                 (this repository, see "Tests actually run")
GPU INTEGRATION NOT VERIFIED (no ROS2 / GLIM / CUDA / raw bag on the dev machine)
```

Contracts this implementation follows (verbatim copies live next to this file):

| Contract | File |
|---|---|
| Pose stage contract | [pose-stage-contract.md](pose-stage-contract.md) |
| Pose → Surface timestamp contract | [pose-timestamp-contract.md](pose-timestamp-contract.md) |
| INS `indoor_long_corridor01` dataset profile | [ins-glim-dataset-profile.md](ins-glim-dataset-profile.md) |
| Acceptance criteria | [glim-integration-acceptance.md](glim-integration-acceptance.md) |

---

## 1. Call chain

```text
frontend NewJobPage
  -> POST /api/jobs                      (dataset id + backend ids only, never a path)
  -> JobService.create_job               compatibility check + job.json + input/*
  -> RunnerService.start_run_all
  -> SubprocessRunnerAdapter.run_stage   -> backend/scripts/run_pose.sh --backend glim
  -> glim_pose_adapter.py
        acquire global GLIM lock, quarantine stale /tmp/dump
        materialise the effective GLIM config from the dataset registry
        launch GLIM (bash -lc: source ROS2, LD_LIBRARY_PATH=/usr/local/lib, headless)
        launch glim_ros1_bridge.py  (ROS1 Livox CustomMsg + Imu -> ROS2 + bag_index.tsv)
        wait, signal GLIM, collect /tmp/dump -> stage1_pose/native/
        timestamp normalisation (native sensor clock -> bag record clock)
        write canonical stage1_pose/poses.txt + trajectory_preview.json + result_manifest.json
        release the lock
  -> SurfaceInputService (timestamp gate)
  -> MrHash-LiDAR runner
```

The adapter is dataset agnostic: topics, frame ids, sensor scaling, extrinsic and
paths all come from the dataset registry / job input manifest. Nothing about INS
is hard-coded in the platform.

## 2. Dataset registry schema (what this repository adds)

The existing registry file gains two blocks next to `files` / `input_manifest` /
`surface` (see [ins-longcorridor01-dataset-example.json](ins-longcorridor01-dataset-example.json)):

```jsonc
{
  "root": "INS",                                  // registry root, existing field
  "files": {"bag": "2024-06-04-16-24-55.bag"},    // bag is REQUIRED, poses is optional
  "integrity": {"bag_size_bytes": ..., "bag_sha256": "..."},

  "pose": {                                       // dataset semantics
    "backend": "glim",
    "bag_path": "INS/2024-06-04-16-24-55.bag",    // optional explicit bag identity
    "lidar_topic": "/livox_mid360/livox/lidar",
    "imu_topic": "/livox_mid360/livox/imu",
    "lidar_frame_id": "livox_mid360_frame",
    "imu_frame_id": "livox_frame",
    "acc_scale": 9.80665,
    "perpoint_relative_time": true,
    "perpoint_time_scale": 1e-9,
    "T_lidar_imu": [0.011, 0.02329, -0.04412, 0, 0, 0, 1],
    "config_path": "INS/glim_ins_config",         // registered GLIM config directory
    "timestamp": {
      "native_lookup_key": "physical LiDAR sensor/header timestamp",
      "surface_lookup_key": "ROS bag record timestamp",
      "max_delta_sec": 0.05,
      "min_matched_ratio": 0.98,
      "max_duplicate_reuse_count": 0,
      "on_failure": "complete_with_blocked_handoff"   // or "fail_stage"
    },
    "run_timeout_sec": 1200,                        // default 7200
    "demo": {"max_lidar_frames": 60, "max_duration_sec": 30}
  },

  "runtime": {                                    // machine settings, NOT dataset semantics
    "glim": {
      "rosbags_python": "envs/rosbags/bin/python",
      "ros_setup": "/opt/ros/humble/setup.bash",
      "ld_library_path": "/usr/local/lib",
      "lock_path": "runtime/locks/glim.lock"
    }
  },

  "surface": {
    "backend": "mrhash_lidar",
    "topic": "/livox_mid360/livox/lidar",
    "pose_lookup_key": "ROS bag record timestamp"  // the clock Surface requires
  }
}
```

Notes on the mapping to the dataset profile document:

* the profile writes `files.bag` as `INS/2024-...bag`; in this repository
  `files` entries are relative to `root`, so the path becomes
  `root: "INS"` + `files.bag: "2024-06-04-16-24-55.bag"` (profile §13);
* `pose.timestamp.surface_lookup_key` must equal `surface.pose_lookup_key`; the
  dataset is reported unavailable if they disagree;
* every path is workspace relative, where the workspace is the directory that
  contains this repository (`PROJECT_ROOT.parent`, e.g. `/root/autodl-tmp`).

### Runtime overrides (machine has the last word)

| Variable | Meaning |
|---|---|
| `GLIM_WORKSPACE` | absolute workspace directory (defaults to `PROJECT_ROOT.parent`) |
| `GLIM_CONFIG_PATH` | override `pose.config_path` |
| `GLIM_ROSBAGS_PYTHON` | override the rosbags interpreter |
| `GLIM_ROS_SETUP` / `GLIM_LD_LIBRARY_PATH` | ROS2 setup script / library path |
| `GLIM_LOCK_PATH` / `GLIM_QUARANTINE_DIR` | lock file / stale-dump quarantine |
| `GLIM_NODE_COMMAND` | target of the real GLIM node executable (default `$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode`) |
| `GLIM_PLAYBACK_RATE`, `GLIM_FINALIZE_WAIT_SEC`, `GLIM_DUMP_WAIT_SEC` | timing knobs |

The GLIM dump directory is deliberately **not** configurable: GLIM 1.2.2 (ROS2)
always writes to `/tmp/dump` when `dump_on_unload=true`
(`pose_spec.GLIM_SHARED_DUMP_DIR`). A knob that only changed where the platform
*looks* would break discovery instead of changing GLIM, so it does not exist.

## 3. Pose artifacts

```text
stage1_pose/
├── poses.txt                  # canonical: timestamp tx ty tz qx qy qz qw, T_world_lidar
├── trajectory_preview.json    # frame_count + per-frame pose for the 3D preview
├── result_manifest.json       # manifest + backend_details (incl. surface_handoff)
├── run.log                    # platform stage log
└── native/
    ├── traj_lidar.txt         # GLIM native trajectory, physical LiDAR clock
    ├── dump/                  # complete GLIM dump moved out of the shared path
    ├── bag_index.tsv          # record_timestamp_ns  sensor_timestamp_ns  point_count
    ├── association.json       # full association statistics
    ├── config/                # effective GLIM config actually used
    ├── config_registered/     # untouched copy of the registered config
    └── run.log                # adapter log (also streamed to the stage log)
```

`registered_trajectory` / `trajectory` stays the canonical trajectory role, so
Surface keeps consuming the same artifact id. Surface never reads a
GLIM-specific filename.

## 4. Timestamp handling (the part that must not be guessed)

Two different clocks are involved:

| Producer | Clock | Declared as |
|---|---|---|
| GLIM `traj_lidar.txt` | physical LiDAR sensor/header time | `{"clock": "lidar_sensor", "lookup_key": "physical LiDAR sensor/header timestamp"}` |
| MrHash-LiDAR lookup | ROS bag record timestamp | `{"clock": "rosbag", "lookup_key": "ROS bag record timestamp"}` |

On the INS bag these differ by roughly one LiDAR frame, so the files must never be
matched by their timestamp column alone:

1. the bridge writes `bag_index.tsv` while streaming the real bag
   (one row per LiDAR frame: `record_timestamp_ns  sensor_timestamp_ns  point_count`);
2. for every bag frame the nearest native Pose sample is selected **in the sensor
   clock**, using that frame's own sensor timestamp;
3. the emitted `poses.txt` is keyed by the frame's **bag record timestamp**, while
   the transform stays the matched `T_world_lidar` (no interpolation, no shift by
   a constant);
4. the residual, the match ratio, head/tail/interior gaps, duplicate Pose reuse
   and monotonicity are recorded in `association.json`.

Default gates (strict on purpose, from the timestamp contract §4):

```text
max_delta_sec = 0.05        min_matched_ratio = 0.98
max_duplicate_reuse_count = 0
```

Hard failure: non-monotonic association, no match at all, or output timestamps
that are not strictly increasing. In that case no Surface-compatible trajectory
is produced.

If normalisation cannot be done at all (no `bag_index.tsv`, ratio below the
threshold, duplicate reuse beyond the allowance):

* the **Pose stage still completes** — the trajectory is valid and stays
  previewable/downloadable, and `poses.txt` keeps the native sensor timestamps;
* the manifest declares
  `timestamp_basis = {clock: "lidar_sensor", ...}` and
  `surface_handoff = {compatible: false, reason: "..."}`;
* `SurfaceInputService` refuses to prepare the Surface input, so Run All stops
  before MrHash with that reason in the log — a failed handoff instead of a
  silently wrong reconstruction;
* setting `pose.timestamp.on_failure = "fail_stage"` makes the Pose stage fail
  instead (fail fast for datasets that prefer it).

The Surface gate compares the Pose manifest's `timestamp_basis.lookup_key`
against `surface.pose_lookup_key` (declared per dataset, as in the INS profile
§12) and blocks MrHash when they differ.

### Acceptance: demo smoke vs full Pose run

The association gate (`matched_ratio >= 0.98` by default) is a *full-run*
criterion and is never relaxed. A short demo cannot satisfy it by construction:
GLIM drops roughly its first 10 LiDAR frames during initialisation, so

```text
full INS bag      1527 / 1537 ≈ 0.9935   -> passes the 0.98 gate
300-frame demo     290 /  300 ≈ 0.9667   -> usually below the gate
 60-frame demo      50 /   60 ≈ 0.8333   -> clearly below the gate
```

Therefore:

| Run | What it must prove | `surface_handoff.compatible` |
|---|---|---|
| **demo smoke** (`--mode demo`) | platform → runner → bridge → GLIM → native `traj_lidar.txt` → canonical `poses.txt` exists and is previewable | **not required to be true**; `false` with an explicit reason is a correct outcome and does *not* mean the integration is broken |
| **full Pose run** (`--mode full`) | the same chain **and** `matched_ratio >= 0.98` with the Surface handoff accepted | must be `true`; otherwise investigate `association.json` |

The demo limit (`pose.demo.max_lidar_frames`, the INS example uses 300) only
shortens the smoke run; it never lowers the gate. Do not read a blocked handoff
from a demo as a failure — read `association.json` (it reports
`head_unmatched_count`, `matched_ratio` and the reject reasons) and then run the
full sequence.

## 5. Concurrent GLIM jobs

GLIM's ROS2 node dumps to a process-global directory (`/tmp/dump` with
`dump_on_unload=true`). The platform therefore enforces **at most one real GLIM
job at a time**:

1. acquire an exclusive lock file (`runtime/locks/glim.lock`, pid + job + host);
2. a busy lock is reported to the user instead of being ignored; a stale lock is
   taken over explicitly and the previous holder is recorded. A lock whose owner
   liveness cannot be determined is treated as busy until it ages out;
3. **only after the lock is held**, the job's own leftovers from a previous Pose
   attempt (`stage1_pose/native/`, `stage1_pose/dump/`, `poses.txt`,
   `trajectory_preview.json`) are removed, so a retry can never reuse an earlier
   `traj_lidar.txt`, `bag_index.tsv` or `association.json`. Nothing outside this
   job's stage directory is touched;
4. a non-empty `/tmp/dump` is moved to `runtime/quarantine/` (`quarantine`
   policy, the default) or refused (`require_empty`);
5. after the run the dump is moved into the job
   (`stage1_pose/native/dump/`), the required trajectory is verified, and the
   lock is released — on success, failure and cancellation alike.

## 6. Process lifecycle

```text
uvicorn (platform)
└─ [setsid] bash run_pose.sh → exec python glim_pose_adapter.py   pid=P pgid=P
     ├─ [exec] glim_rosnode --ros-args -p config_path:=… -p dump_on_unload:=true   pid=A pgid=P
     └─ rosbags python glim_ros1_bridge.py                                        pid=B pgid=P
```

The GLIM node is started as the **real executable**, not through a `ros2 run`
wrapper: the shell payload resolves `$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode`
and `exec`s it, so the node is the adapter's direct child and the graceful
shutdown signal reaches the process that implements `dump_on_unload` — no signal
forwarding through a wrapper is assumed. Before launching, the adapter resolves
that path (`ros2 pkg prefix glim_ros`) and fails fast with an explicit message if
it cannot; an operator-provided `runtime.glim.node_command` is used as-is.

Both children run through **one** ROS runtime shell builder
(`glim_config_service.build_ros_runtime_shell`); the platform does not need to be
started from a shell that already sourced ROS2:

```bash
# GLIM
source '/opt/ros/humble/setup.bash' \
  && export LD_LIBRARY_PATH='/usr/local/lib':${LD_LIBRARY_PATH:-} \
  && unset OMP_NUM_THREADS \
  && exec "$(ros2 pkg prefix glim_ros)/lib/glim_ros/glim_rosnode" \
       '--ros-args' '-p' 'config_path:=<JOB>/stage1_pose/native/config' \
       '-p' 'dump_on_unload:=true'

# bridge (imports rclpy / sensor_msgs itself)
source '/opt/ros/humble/setup.bash' \
  && export LD_LIBRARY_PATH='/usr/local/lib':${LD_LIBRARY_PATH:-} \
  && unset OMP_NUM_THREADS \
  && exec '<WORKSPACE>/envs/rosbags/bin/python' '<REPO>/backend/scripts/glim_ros1_bridge.py' ...
```

The order is the point: ``source`` first, **then** the ``LD_LIBRARY_PATH``
override, **then** ``unset OMP_NUM_THREADS``, **then** ``exec``. Prepending the
GTSAM path to the inherited process environment would not survive ``setup.bash``
(which prepends ROS's own GTSAM 4.2 path) and would re-trigger
``undefined symbol: gtsam::NonlinearFactor::rekey(...)``. ``exec`` keeps the real
node and the real bridge Python as the adapter's direct children.

* `glim_pose_adapter.py` spawns the GLIM node and the bridge **without** a new
  session (`app/services/process_tree.py:child_popen_kwargs`), so they stay in the
  process group the platform created for `run_pose.sh`. The platform's existing
  cancel path (`os.killpg` on that group, `runner_adapter.py`) therefore reaches
  every descendant;
* `app/services/child_supervisor.py` owns the cancel/timeout/cleanup policy:
  SIGTERM/SIGINT marks the run cancelled, terminates the registered children
  (escalating to kill for a stubborn child) and runs the cleanup hooks
  (lock release) exactly once, newest first;
* `pose.run_timeout_sec` (platform default `7200`, the INS example sets `1200`) is
  enforced by the same supervisor: when the deadline passes, the run is marked
  timed out, the children are terminated through the cancel path, the lock is
  released, and the stage is reported as failed with the reason in
  `stage1_pose/run.log` and `stage1_pose/native/run.log`;
* the run loop checks the cancel/timeout state between steps, so either is honoured
  even while waiting for the GLIM startup, the bridge or the dump.

## 7. Running it on the AutoDL machine

```text
/root/autodl-tmp/                     <- workspace
├── 3d-mapping-platform/              <- this repository
├── INS/2024-06-04-16-24-55.bag       <- registry bag (files.bag)
├── INS/glim_ins_config/              <- registered GLIM config (verified headless)
├── envs/rosbags/bin/python           <- rosbags interpreter (runtime.glim.rosbags_python)
└── runtime/locks/ , runtime/quarantine/
```

1. copy the dataset example into the registry:

   ```bash
   cp docs/ins-longcorridor01-dataset-example.json backend/config/datasets/ins_longcorridor01.json
   sha256sum /root/autodl-tmp/INS/2024-06-04-16-24-55.bag   # paste into integrity.bag_sha256
   ```

2. start the platform (`backend/run_backend.bat` / uvicorn on 127.0.0.1:8000 and
   the Vite dev server), pick the dataset on the New Job page;
3. `Pose = GLIM`, `Surface = MrHash (LiDAR)`, then **Run All**, or run the Pose
   stage alone first. `MAPPING_SURFACE_MODE=demo` limits GLIM to
   `pose.demo.max_lidar_frames` / `max_duration_sec` — a pipeline smoke test that
   does **not** have to satisfy the timestamp gate (see §4);
4. dry-run the adapter without touching the GPU:

   ```bash
   backend/scripts/run_pose.sh --job-dir <JOB_DIR> --backend glim --mode demo
   python3 backend/scripts/glim_pose_adapter.py --job-dir <JOB_DIR> --backend glim --dry-run
   ```

## 8. Tests actually run (dev machine)

| Check | Command | Result |
|---|---|---|
| python compile | `python -m compileall -q backend/app backend/scripts` | pass |
| shell syntax | `bash -n backend/scripts/run_pose.sh run_surface.sh run_esdf.sh` | pass |
| backend tests | `python -m unittest discover -s tests -t .` | 145 tests; Windows dev box: 4 baseline errors + 3 POSIX-only skips; Linux: 2 baseline failures, 0 skips (see below) |
| frontend typecheck | `npm run typecheck` | pass |
| frontend build | `npm run build` | pass |

GLIM-specific coverage: dataset validation and backend dispatch, runner dispatch and
command construction, adapter dry-run (config/command/environment/plan), canonical
artifacts + manifest + Surface gate, timestamp association (perfect match, head gap,
residual, low ratio, non-monotonic, duplicate reuse), GLIM lock and dump policy,
stale-run-state cleanup on retry, run timeout and its cleanup/lock release, graceful
shutdown targeting the real node, the shared ROS runtime shell for GLIM and the bridge
(source → LD_LIBRARY_PATH override → unset OMP_NUM_THREADS → exec), and cancel/terminate
orchestration with injected fake processes.

### BASELINE FAILURE vs GLIM INTEGRATION REGRESSION

Every entry below fails on the **unmodified original repository** with the same
command, so it is a `BASELINE FAILURE` of the existing runner tests — not a
regression of this integration. No unrelated runner behaviour was changed to make
the suite green.

```text
Windows dev box  (4 errors, 3 POSIX-only skips)
  os.symlink needs a privilege            test_valid_oxford_mrhash_lidar_returns_201   BASELINE
                                          test_symlink_escape                       BASELINE
  os.killpg does not exist on Windows     test_cancel_reaps_process_group            BASELINE
                                          test_event_failure_reaps_process_group     BASELINE

Linux sandbox    (2 failures, 0 skips)
  process-group reaping of the original   test_cancel_reaps_process_group            BASELINE
  runner subprocess tests                 test_event_failure_reaps_process_group     BASELINE

GLIM INTEGRATION REGRESSION: none
```

The three POSIX-only tests of this integration (`cancel` → SIGTERM/lock release,
whole-process-group reaping, POSIX pid liveness) are skipped on Windows with an
explicit `ENVIRONMENT LIMITATION` reason and execute on Linux.

## 9. Not verified here (GPU INTEGRATION NOT VERIFIED)

* no ROS2 Humble, no GLIM 1.2.2, no CUDA/RTX 4090 and no INS raw bag on the dev
  machine: GLIM was never started, so the Pose → Surface chain has not been
  executed end to end;
* the exact GLIM dump location is confirmed on the first real run: discovery
  accepts `/tmp/dump` (the documented GLIM 1.2.2 behaviour) and a job-local
  `stage1_pose/dump/` (GLIM started with `cwd=stage1_pose`). If GLIM turns out to
  write elsewhere, the run fails with the searched paths listed — add the path to
  `dump_candidates` rather than reintroducing a setting that cannot change GLIM;
* the default node command resolves the executable through
  `ros2 pkg prefix glim_ros` and expects
  `<prefix>/lib/glim_ros/glim_rosnode`; confirm this on the real
  `ros-humble-glim-ros-cuda12.6` install (a different layout needs
  `GLIM_NODE_COMMAND`);
* MrHash's `Ros1Reader` lookup key/tolerance is taken from the registered Oxford
  dataset contract, not from MrHash source (the MrHash repository is not part of
  this workspace);
* the association statistics for the real INS bag (residual, head gap, duplicate
  reuse) are unknown until the first real run; inspect
  `stage1_pose/native/association.json`.
