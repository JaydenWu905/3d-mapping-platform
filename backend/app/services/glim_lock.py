"""Global GLIM execution lock and dump-directory hygiene.

The GLIM ROS2 node writes its dump to a process-global path (``/tmp/dump`` when
``dump_on_unload=true``; see docs/ins-glim-dataset-profile.md §11).  Two GLIM
jobs sharing that path would mix each other's trajectories, so the initial
integration policy is:

* at most one real GLIM job at a time, enforced with an exclusive lock file;
* before starting, an existing dump directory is either moved aside
   (``quarantine`` policy, the default) or refused (``require_empty``);
* after a successful dump the native artifacts are moved into the job-local
  Pose output and the lock is released — on success, failure and cancellation
  alike.

Stale-lock policy is explicit: a lock whose owner pid is gone, or which is
older than ``stale_after_sec``, is reported as stale and taken over, with the
previous holder recorded in ``stale_taken_over_from``.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.services.process_tree import pid_is_alive


class GlimLockError(RuntimeError):
    """Another GLIM job holds the lock."""


class GlimDumpError(RuntimeError):
    """The dump directory is not in a state we are willing to start from."""


DEFAULT_STALE_AFTER_SEC = 6 * 3600


@dataclass
class LockRecord:
    pid: int
    job_id: str
    started_at: str
    host: str

    def as_dict(self) -> dict:
        return {"pid": self.pid, "job_id": self.job_id,
                "started_at": self.started_at, "host": self.host}


@dataclass
class LockStatus:
    acquired: bool
    stale: bool
    stale_taken_over_from: dict | None = None
    holder: dict | None = None
    reason: str = ""


@dataclass
class GlimExecutionLock:
    """Exclusive, cross-job lock guarding the shared GLIM dump directory."""

    path: Path
    stale_after_sec: float = DEFAULT_STALE_AFTER_SEC
    events: list[str] = field(default_factory=list)
    _record: LockRecord | None = None
    _owned: bool = False

    # ------------------------------------------------------------------ helpers
    def _read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _age_sec(self) -> float:
        try:
            return max(0.0, time.time() - self.path.stat().st_mtime)
        except OSError:
            return 0.0

    def _describe(self, data: dict | None) -> dict | None:
        if not isinstance(data, dict):
            return None
        return {
            "pid": data.get("pid"),
            "job_id": data.get("job_id"),
            "started_at": data.get("started_at"),
            "host": data.get("host"),
        }

    # -------------------------------------------------------------------- api
    def acquire(self, *, job_id: str) -> LockStatus:
        """Try to take the lock; never blocks.  Raises ``GlimLockError`` when busy."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read()
        stale = False
        taken_over_from: dict | None = None
        if self.path.exists():
            holder = self._describe(existing)
            pid = existing.get("pid") if isinstance(existing, dict) else None
            alive = pid_is_alive(int(pid)) if isinstance(pid, int) else None
            age = self._age_sec()
            if alive is not False and age <= self.stale_after_sec:
                # alive True (holder running) or None (cannot determine):
                # stealing a live GLIM run would corrupt the shared dump dir, so
                # an undecidable owner is treated as busy until the lock ages out.
                liveness = "" if alive is True else " (pid liveness could not be determined, " \
                                                    "assuming it is still running)"
                reason = (
                    "another GLIM job holds the shared dump lock "
                    f"(pid={pid}, job={holder.get('job_id') if holder else 'unknown'}, "
                    f"age={age:.0f}s){liveness}; the GLIM node dumps to a process-global "
                    "directory, so only one real GLIM job may run at a time"
                )
                self.events.append(reason)
                return LockStatus(acquired=False, stale=False, holder=holder, reason=reason)
            if alive is not False:
                stale = True
                reason = (
                    f"taking over a stale GLIM lock (the lock is {age:.0f}s old, past the "
                    f"{self.stale_after_sec:.0f}s limit; previous holder pid={pid})"
                )
            else:
                stale = True
                reason = (
                    f"taking over a stale GLIM lock (holder pid={pid} is no longer running, "
                    f"age={age:.0f}s)"
                )
            taken_over_from = holder
            self.events.append(reason)
            try:
                self.path.unlink()
            except OSError:
                pass

        record = LockRecord(
            pid=os.getpid(), job_id=job_id,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            host=socket.gethostname(),
        )
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # Lost a race with another job between the check and the create.
            holder = self._describe(self._read())
            reason = (
                "another GLIM job acquired the shared dump lock concurrently "
                f"({holder.get('job_id') if holder else 'unknown'})"
            )
            self.events.append(reason)
            return LockStatus(acquired=False, stale=False, holder=holder, reason=reason)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record.as_dict(), handle, ensure_ascii=False, indent=2)
        self._record = record
        self._owned = True
        self.events.append(f"GLIM lock acquired: {self.path}")
        return LockStatus(acquired=True, stale=stale, stale_taken_over_from=taken_over_from)

    def release(self) -> bool:
        """Release the lock if this process owns it.  Returns True when removed."""
        if not self.path.exists():
            self._owned = False
            return False
        data = self._read()
        owner_pid = data.get("pid") if isinstance(data, dict) else None
        if self._owned or owner_pid == os.getpid():
            try:
                self.path.unlink()
            except OSError as exc:  # pragma: no cover - defensive
                self.events.append(f"failed to remove GLIM lock: {exc}")
                return False
            self._owned = False
            self.events.append("GLIM lock released")
            return True
        self.events.append("GLIM lock not owned by this process; left in place")
        return False

    def __enter__(self) -> "GlimExecutionLock":  # pragma: no cover - convenience
        return self

    def __exit__(self, *_exc) -> None:  # pragma: no cover - convenience
        self.release()


def inspect_dump_dir(
    dump_dir: Path,
    *,
    policy: str,
    quarantine_dir: Path,
    job_id: str,
    dry_run: bool = False,
) -> dict:
    """Make the shared dump directory safe to start from.

    ``policy='quarantine'`` (default) moves a non-empty dump aside; the operator
    can inspect it later.  ``policy='require_empty'`` refuses to start instead,
    for machines where silently moving data is not acceptable.
    """
    info: dict = {
        "dump_dir": str(dump_dir),
        "policy": policy,
        "existed": dump_dir.exists(),
        "action": "none",
        "quarantined_to": None,
    }
    if not dump_dir.exists():
        return info
    if not dump_dir.is_dir():
        raise GlimDumpError(f"GLIM dump path exists and is not a directory: {dump_dir}")
    entries = list(dump_dir.iterdir())
    if not entries:
        info["action"] = "empty"
        return info
    if policy == "require_empty":
        raise GlimDumpError(
            f"GLIM dump directory {dump_dir} already contains {len(entries)} entrie(s) from a "
            "previous run; remove them or set runtime.glim.dump_policy=quarantine"
        )
    if dry_run:
        info["action"] = "would_quarantine"
        info["quarantined_to"] = str(quarantine_dir / f"dump-<timestamp>-{job_id}")
        return info
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = quarantine_dir / f"dump-{stamp}-{job_id}"
    shutil.move(str(dump_dir), str(target))
    info["action"] = "quarantined"
    info["quarantined_to"] = str(target)
    return info
