"""Single source of truth for the real (subprocess) runner capabilities.

The platform executes real algorithms through shell adapters under
``backend/scripts``.  Before this module the set of executable
``(stage, backend)`` pairs was duplicated in RunnerService, in
SubprocessRunnerAdapter and again in JobService, so it was possible to
register a backend in ``config/backends/*.json`` that could never run.

Everything that needs "can this stage/backend actually execute?" now asks
here.  Adding a backend is a two step change: publish its registry entry and
add one line below.
"""
from __future__ import annotations


#: ``(stage, backend_id) -> shell adapter file name under backend/scripts``
REAL_RUNNERS: dict[tuple[str, str], str] = {
    ("pose", "registered_pose_import"): "run_pose.sh",
    ("pose", "glim"): "run_pose.sh",
    ("surface", "mrhash_lidar"): "run_surface.sh",
    ("surface", "mrhash_rgbd"): "run_surface.sh",
}

#: Fallback adapter per stage (used only for a stage that has a real runner).
STAGE_SCRIPTS: dict[str, str] = {
    "pose": "run_pose.sh",
    "surface": "run_surface.sh",
    "distance": "run_esdf.sh",
}

#: Stages whose real runner is not integrated at all yet.
UNAVAILABLE_STAGE_REASON = {
    "distance": "No real Distance runner is integrated yet",
}


def has_real_runner(stage: str, backend: str) -> bool:
    return (stage, backend) in REAL_RUNNERS


def runner_script(stage: str, backend: str) -> str:
    script = REAL_RUNNERS.get((stage, backend)) or STAGE_SCRIPTS.get(stage)
    if script is None:  # pragma: no cover - guarded by has_real_runner
        raise KeyError(f"No real runner is available for {stage}/{backend}")
    return script


def real_backend_ids(stage: str) -> tuple[str, ...]:
    return tuple(backend for (known_stage, backend) in REAL_RUNNERS if known_stage == stage)


def missing_runner_reason(stage: str, backend: str) -> str:
    if stage in UNAVAILABLE_STAGE_REASON:
        return UNAVAILABLE_STAGE_REASON[stage]
    return f"No real runner is available for {stage}/{backend}"
