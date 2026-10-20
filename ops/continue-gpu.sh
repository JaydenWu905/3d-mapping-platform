#!/usr/bin/env bash
# Deliberately does not launch any algorithm or create a Job.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ "${1:-preflight}" == preflight ]] || { echo 'Usage: continue-gpu.sh preflight' >&2; exit 2; }
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
print('Read docs/deploy-distance.md and ops/INTEGRATION_20261020.md before standalone or full acceptance.')
PY
