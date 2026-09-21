"""Runner Adapter interface.

Business code only ever talks to `RunnerAdapter.run_stage`. Swapping the mock
for real algorithms later = registering a different adapter, nothing else.

Phase 2 contract for the subprocess adapter (future, per spec 十九):

    run_pose.sh     --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
    run_surface.sh  --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
    run_esdf.sh     --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full

The scripts are expected to write progress.json + run.log continuously and
finish with result_manifest.json inside the stage directory.
"""
from __future__ import annotations

import abc
from typing import Any


class StageResult:
    """What a runner reports when a stage run finished."""

    def __init__(self, stage: str, status: str, error: str = "", exit_code: int = 0):
        self.stage = stage
        self.status = status  # completed | failed | cancelled
        self.error = error
        self.exit_code = exit_code


class RunnerAdapter(abc.ABC):
    """Interface each concrete adapter (mock / subprocess) must implement."""

    name: str = "runner"

    @abc.abstractmethod
    async def run_stage(self, job_id: str, stage: str, backend: str) -> StageResult:
        """Run one stage of one job. Raised as a background task."""

    @abc.abstractmethod
    def cancel(self, job_id: str, stage: str) -> None:
        """Request cancellation. The runner should stop at the next tick."""


class SubprocessRunnerAdapter(RunnerAdapter):
    """Placeholder for phase 2 real algorithms.

    Not implemented in phase 1 (no Conda / ROS / CUDA environment assumed).
    When implemented it will:

    1. locate run_{script}.sh for (stage, backend) via the registry;
    2. launch `run_{script}.sh --job-dir <job_dir> --backend <id> --mode demo`;
    3. stream stdout/stderr tail into run.log;
    4. poll progress.json / result_manifest.json produced by the subprocess;
    5. forward progress + log lines into the event service.

    APIs, job state, frontend, viewers, logs and artifacts stay unchanged.
    """

    name = "subprocess"

    def __init__(self, request_cancel):
        self._request_cancel = request_cancel

    async def run_stage(self, job_id: str, stage: str, backend: str) -> StageResult:
        raise NotImplementedError(
            "SubprocessRunnerAdapter is a phase-2 placeholder. "
            "Phase 1 always uses MockRunnerAdapter."
        )

    def cancel(self, job_id: str, stage: str) -> None:
        self._request_cancel(job_id, stage)