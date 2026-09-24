#!/usr/bin/env python3
"""Thin CLI for the shared registered Pose import service."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.job_service import JobService  # noqa: E402
from app.services.pose_import_service import import_registered_pose  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--job-id")
    group.add_argument("--job-dir", type=Path)
    args = parser.parse_args()
    jobs = JobService(jobs_dir=args.job_dir.resolve().parent) if args.job_dir else JobService()
    job_id = args.job_dir.name if args.job_dir else args.job_id
    try:
        manifest = import_registered_pose(job_id, jobs)
    except Exception as exc:
        print(f"Pose import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"job_id": job_id, "status": "completed",
                      "pose_count": manifest["metrics"]["pose_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
