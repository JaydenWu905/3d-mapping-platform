"""Single-writer algorithm snapshots; the runner alone owns progress.json."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.progress import atomic_write_json, read_json

LIVE_FIELDS = ("progress_run_id", "progress_started_at", "progress_seq", "progress_scope",
               "selected_frames", "visited_frames", "matched_frames", "fused_frames",
               "skipped_frames", "counter_updated_at", "counter_age_sec")


def progress_identity() -> dict:
    stamp = datetime.now(timezone.utc).isoformat()
    return dict(progress_run_id=uuid.uuid4().hex, progress_started_at=stamp,
                progress_seq=0, progress_scope="none", counter_updated_at=stamp, counter_age_sec=0)


class ProgressReporter:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ["PLATFORM_ALGORITHM_PROGRESS_PATH"])
        self.run_id = os.environ["PLATFORM_PROGRESS_RUN_ID"]
        self.last_write = 0.0

    def emit(self, phase: str, current: int = 0, total: int = 0, *, scope: str = "none",
             unit: str = "", force: bool = False, **counts) -> None:
        old = read_json(self.path, {}) or {}
        if old.get("run_id") != self.run_id:
            old = {"seq": int(os.environ.get("PLATFORM_PROGRESS_SEQ", "0"))}
        now = time.monotonic()
        if not force and old.get("phase") == phase and now - self.last_write < .5:
            return
        state = {**old, **counts, "protocol": 1, "run_id": self.run_id,
                 "seq": int(old.get("seq", 0)) + 1, "phase": phase,
                 "current": current, "total": total, "progress_scope": scope,
                 "unit": unit, "counter_updated_at": datetime.now(timezone.utc).isoformat()}
        atomic_write_json(self.path, state)
        self.last_write = now


def accept_algorithm_snapshot(cached: dict, snapshot: dict) -> dict:
    """Reject old runs/sequences, malformed counts and regressing counters."""
    if not isinstance(snapshot, dict) or snapshot.get("protocol") != 1 or snapshot.get("run_id") != cached.get("progress_run_id"):
        return cached
    seq = snapshot.get("seq")
    if not isinstance(seq, int) or seq <= cached.get("progress_seq", 0):
        return cached
    phase = snapshot.get("phase")
    if not isinstance(phase, str) or not phase:
        return cached
    numeric = ("current", "total", "selected_frames", "visited_frames", "matched_frames", "fused_frames", "skipped_frames")
    for field in numeric:
        value = snapshot.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return cached
    current, total = snapshot.get("current", 0), snapshot.get("total", 0)
    if total and current > total:
        return cached
    if phase == cached.get("phase") and current < cached.get("current", 0):
        return cached
    for field in numeric[2:]:
        if field in snapshot and snapshot[field] < cached.get(field, 0):
            return cached
    if snapshot.get("fused_frames", 0) > snapshot.get("matched_frames", 0) or snapshot.get("matched_frames", 0) + snapshot.get("skipped_frames", 0) > snapshot.get("visited_frames", 0) or snapshot.get("visited_frames", 0) > snapshot.get("selected_frames", 0):
        return cached
    scope = snapshot.get("progress_scope", "none")
    if scope not in ("input", "step", "none"):
        return cached
    result = {**cached, **{key: snapshot[key] for key in numeric if key in snapshot},
              "phase": phase, "current": current, "total": total,
              "progress_scope": scope, "progress_seq": seq,
              "counter_updated_at": snapshot.get("counter_updated_at"),
              "unit": snapshot.get("unit", ""), "status": "running",
              # No invented overall fraction. Step/input percentages are derived by clients.
              "progress": 0.0, "message": ""}
    return result
