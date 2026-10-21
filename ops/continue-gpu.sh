#!/usr/bin/env bash
# Reference tests are CPU-only. All other actions are guarded and explicit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ ! -f ops/platform.local.env ]] || source ops/platform.local.env
ACTION="${1:-preflight}"
shift || true
case "$ACTION" in
  reference-tests)
    exec env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=backend backend/.venv/bin/python -m unittest backend.tests.test_distance_contract backend.tests.test_distance_geometry -v
    ;;
  preflight|build|native-input-tests|native-diagnostic|native-surface-tests|acceptance) ;;
  *) echo 'Usage: continue-gpu.sh reference-tests|preflight|build|native-input-tests REPORT_DIR|native-diagnostic REPORT_DIR|native-surface-tests REPORT_DIR|acceptance DATASET_ID' >&2; exit 2 ;;
esac
python3 - <<'PY'
from pathlib import Path
limit=Path('/sys/fs/cgroup/memory.max').read_text().strip()
print('cgroup memory.max:',limit)
if limit!='max' and int(limit)<8*1024**3:
    raise SystemExit('Still in restricted-memory mode; do not compile or run real mapping. Restore GPU mode first.')
PY
GPU_INFO="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)"
[[ -n "$GPU_INFO" ]] || { echo 'No GPU is visible; do not run real mapping.' >&2; exit 1; }
printf '%s\n' "$GPU_INFO"
bash ops/distance-env.sh bash backend/scripts/build_esdf.sh --preflight
backend/.venv/bin/python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0,'backend')
from app.services.distance_readiness import distance_unavailable_reason
for path in ['jobs','uploads','ops/device_runtime.json','ops/glim-runtime.env']:
    p=Path(path);print(path,'=>',p.resolve(),'exists=',p.exists())
print('Distance gate:',distance_unavailable_reason())
print('Read docs/deploy-distance.md and docs/distance-contract-audit-20261020.md before native/acceptance actions.')
PY
case "$ACTION" in
  preflight) ;;
  build) exec bash ops/distance-env.sh bash backend/scripts/build_esdf.sh --build ;;
  native-surface-tests)
    exec backend/.venv/bin/python backend/scripts/distance_surface_checks.py \
      --executable "$ROOT/../envs/distance/converter-build/voxel_points_to_esdf" \
      --reader "$ROOT/../envs/distance/converter-build/verify_esdf_layer" --report "${1:?Supply a NEW report directory}"
    ;;
  native-input-tests|native-diagnostic)
    REPORT="${1:?Supply a NEW diagnostic report directory outside historical Jobs}"
    EXTRA=()
    if [[ "$ACTION" == native-diagnostic ]]; then EXTRA=(--legacy-diagnostic --reader "$ROOT/../envs/distance/converter-build/verify_esdf_layer"); fi
    exec backend/.venv/bin/python backend/scripts/distance_native_checks.py \
      --executable "$ROOT/../envs/distance/converter-build/voxel_points_to_esdf" --report "$REPORT" "${EXTRA[@]}"
    ;;
  acceptance)
    DATASET_ID="${1:?Supply the registered dataset ID for a NEW full three-stage Job}"
    backend/.venv/bin/python - "$DATASET_ID" <<'PY'
import json, sys, urllib.request
sys.path.insert(0,'backend')
from app.services.distance_readiness import distance_unavailable_reason
reason=distance_unavailable_reason()
if reason:
    raise SystemExit('BLOCKED: '+reason+'; no Job was created. Do not remove the gate without native field acceptance.')
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def post(path,data):
    req=urllib.request.Request('http://127.0.0.1:8000'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with op.open(req,timeout=30) as response:return json.load(response)
job=post('/api/jobs',dict(dataset=sys.argv[1],run_mode='full',requested_stages=['pose','surface','distance'],
    backends={'pose':'glim','surface':'mrhash_lidar','distance':'voxel_esdf'}))
print('NEW_JOB',job['job_id'],flush=True)
print(post('/api/jobs/'+job['job_id']+'/run-planned',{}))
print('Started only; completion, native output readback, signs/unknown mask, previews/downloads and resource audit must still be verified.')
PY
    ;;
esac
