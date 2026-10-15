# Platform foundation deployment — 2026-10-14 UTC

## Source and isolation

- Directory: `/root/autodl-tmp/3d-mapping-platform-deploy`, sibling of `mrhash`, `INS`, and `oxford_mrhash`.
- GitHub default branch at deployment: `main`; HEAD `56c448d27a53f389267a2cc099e743051b8f2e7d`; remote `https://github.com/JaydenWu905/3d-mapping-platform`.
- Fresh clone, without old platform changes, old Jobs, or paused RGB-D registrations. No commit or push. Local additions: this record, process script, installed-version snapshots, and `.gitignore` entry for `.run/`.
- Existing audit read: `../deployment_audit_20261013/{audit_report.md,deployment_plan.md}`. No applicable `AGENTS.md` found in the parent chain or platform trees.

## Environment and recreation

- Host Python 3.12.3; isolated backend Python 3.12.3 and pip 24.0 in `backend/.venv`. Node v24.21.0, npm 11.19.0. Repository has no explicit Python/Node engines field; these versions installed the declared dependencies and ran the services. Frontend typecheck passed.
- Python installed versions: [`backend-installed.txt`](backend-installed.txt). Frontend direct installed versions: [`frontend-installed.json`](frontend-installed.json); complete frontend tree is governed by `frontend/package-lock.json`.
- Recreate from repository root: `python3.12 -m venv backend/.venv && backend/.venv/bin/python -m pip install -r backend/requirements.txt`; for exact current backend versions, install `-r ops/backend-installed.txt` instead. Then `cd frontend && npm ci`.
- FastAPI venv contains platform requirements only. No ROS setup, algorithm extension import, MrHash rebuild, or system CUDA change.

## Dataset and algorithm paths

- `PROJECT_ROOT.parent` and GLIM default workspace both resolve to `/root/autodl-tmp`.
- Oxford registry: `backend/config/datasets/oxford_mrhash_lidar.json` resolves to `../oxford_mrhash/mrhash_input/1710755015_2024-03-18-09-43-36_0.bag` (5,541,766,461 bytes) and `poses.txt` (359,268 bytes). Full registry `DatasetDefinition.validate()` returned `[]`, including both file hashes; poses SHA-256 is `e00c948e8df3c8d4dd2c9deedf22d6923bf3b47b4d7b1eb65bf966c3f70475af`.
- MrHash root `../mrhash`; Pixi executable `../.pixi/bin/pixi` (0.79.0), `mrhash/pixi.lock`, `mrhash/mrhash/configurations/oxford_hesai_corrected_full.cfg`, Pixi Python 3.11 environment, editable `.pth`, and installed `pygeowrapper.cpython-311-x86_64-linux-gnu.so` exist. `ldd` on the extension reported no missing libraries. Neither Pixi nor the extension was executed.
- GLIM remains blocked: `/opt/ros/humble/setup.bash`, `ros2`, `glim_rosnode`, and `INS/glim_ins_config` absent. Handoff candidate `GLIM_Handoff_INS_20261003/glim_ins_config` exists; it was not promoted into a runnable registry. Historical trajectories were not used as this deployment's GLIM output.
- Pose→Surface still needs a locally runnable, independently verified GLIM environment and sourced INS calibration/time semantics. MrHash currently reads `PointCloud2`, while the INS bag uses Livox `CustomMsg`; a verified reader or timestamp-preserving conversion and suitable Livox config are required. Per-frame match/skip accounting and two-stage product flow remain to be implemented/accepted. Oxford with precomputed poses can validate Surface separately but does not prove current GLIM.

## Checks performed

- `npm ci` succeeded. `npm run typecheck` succeeded.
- `npm run build` reached Vite `transforming...` and was killed with exit 137, including when retried alone and with a 512 MiB Node heap. A 384 MiB heap attempt failed with Node heap out-of-memory. Container memory limit is 2,147,483,648 bytes and baseline usage was about 1.6–1.8 GiB due to existing processes. This is an environment capacity blocker for the production build, not an observed TypeScript error. No unrelated services were stopped.
- `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v`: 145 tests, 144 passed, one failed. Failure: `RetryStaleArtifactTests.test_retry_with_a_failing_node_does_not_reuse_stale_artifacts`, assertion at `backend/tests/test_glim_pose_adapter.py:668`. The same test fails identically in the untouched `deployment_audit_20261013_upstream` clone at the same HEAD using this new venv, so it predates this deployment.
- Backend `GET /api/health` 200; frontend `/` 200; frontend `/api/health` proxy 200; backend `/api/backends`, `/api/datasets`, `/api/jobs` all 200.
- `POST /api/jobs` using `demo_room` returned 201; `GET /api/jobs/{id}` and list query returned the new Job. Test Job `job_1791982805_dfa467` is marked inside its Job directory with `DEPLOYMENT_TEST_JOB.txt`; status `created`, all stages `waiting`. No Run All or stage run was requested.

## Operation

- Ports were free before start. Backend listens only on `127.0.0.1:8000`; frontend Vite only on `127.0.0.1:5173`, with `/api` proxy to backend 8000.
- From repository root: `ops/platform.sh start`, `ops/platform.sh status`, `ops/platform.sh stop`, `ops/platform.sh logs`. The script refuses occupied ports and prevents duplicate starts, verifies recorded PID command and working directory before stopping, and never kills unrelated processes.
- PID files: `.run/backend.pid`, `.run/frontend.pid`. Logs: `logs/backend.log`, `logs/frontend.log`. No systemd assumption.
- Local health: `curl --noproxy '*' http://127.0.0.1:8000/api/health` and `curl --noproxy '*' http://127.0.0.1:5173/api/health`.
- From a personal computer, using the actual SSH host/user/port: `ssh -N -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 -p <SSH_PORT> <SSH_USER>@<SSH_HOST>`, then open `http://127.0.0.1:5173/`. The frontend itself only needs port 5173 forwarded because Vite proxies `/api`; 8000 is optional for direct API access. No public listener was opened.

## Next minimum work for the two modules

1. Obtain reproducible ROS2 Humble/GLIM and bridge environment, headless config, and sourced INS LiDAR→IMU extrinsic, point time units, IMU scale, and timestamp semantics; validate GLIM on a short INS segment and generate a current `traj_lidar.txt` plus `bag_index.tsv`.
2. Verify native GLIM poses against INS bag record timestamps and the platform Pose artifact contract, including frame coverage and residuals.
3. Add/verify Livox `CustomMsg` reading and a matching MrHash config (or a rigorously checked `PointCloud2` conversion), with handled/skipped frame counts; then run a small same-Job Pose→Surface acceptance before a full run.
4. Add a clear two-stage completion flow and shared GPU serialization before offering a one-click first+second module action.
