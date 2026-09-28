#!/usr/bin/env python3
"""MrHash RGB-D adapter boundary.

This intentionally performs contract validation only.  The upstream runner
requires a fixed Replica/ScanNet directory layout and cannot consume the
platform sequence index directly.  Enabling execution before an accepted,
lossless mapping exists would turn an interface test into a false success.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.surface_input_service import validate_mrhash_rgbd_surface_input  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("demo", "full"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    manifest = validate_mrhash_rgbd_surface_input(args.job_dir, strict_hashes=False)
    print(f"validated Surface Input Manifest {manifest['schema_version']} for {manifest['frame_count']} RGB-D frames")
    if args.validate_only:
        return 0
    print(
        "MrHash RGB-D is NOT READY: native layout mapping and real handoff acceptance are pending.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
