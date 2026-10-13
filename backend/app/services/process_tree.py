"""OS-specific child-process handling for multi-process algorithm adapters.

This module is deliberately small: it contains only what differs between
operating systems.  The *policy* (which children exist, when a run is cancelled,
what cleanup must happen) lives in ``child_supervisor`` and is tested with fake
processes, so the orchestration is verified independently of the OS.

Production target is Ubuntu 22.04 / ROS2 Humble.  There, an adapter such as the
GLIM Pose backend starts (a) the ROS2 GLIM node and (b) the ROS1 bridge, and the
following two rules keep both inside a tree the platform can always reap:

1. children are spawned **without** creating their own session, so they inherit
   the adapter's process group.  The platform's existing cancel path
   (``os.killpg`` on the adapter process group, see ``runner_adapter.py``) then
   reaches every descendant.  Children MUST NOT be given an unmanaged session;
2. the adapter installs SIGTERM/SIGINT handlers that terminate its children and
   release its lock, so a direct signal never leaves an orphan holding the GPU.

``terminate_tree`` is the local escalation used by both paths: SIGTERM then
SIGKILL on POSIX, ``Popen.terminate`` then ``Popen.kill`` elsewhere.  It acts on
the direct child only; whole-group coverage is the platform's ``killpg``, which
is why rule 1 matters.
"""
from __future__ import annotations

import os
import signal
import time
from typing import Any

IS_WINDOWS = os.name == "nt"


def child_popen_kwargs() -> dict[str, Any]:
    """Return Popen kwargs for long-running algorithm children.

    Deliberately empty: see rule 1 in the module docstring.  Kept as a function
    so the policy is stated in exactly one place instead of at every call site.
    """
    return {}


def pid_is_alive(pid: int) -> bool | None:
    """Liveness probe for the GLIM lock.  ``None`` means "could not determine".

    Callers MUST treat ``None`` as "assume alive": taking over the lock of a live
    GLIM run would corrupt the shared dump directory.  Only POSIX is probed; on
    other platforms the answer is unknown, and lock staleness is then decided by
    the lock's age (see ``glim_lock``).
    """
    if pid <= 0:
        return False
    if os.name != "posix":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def terminate_tree(process: Any | None, *, grace: float = 8.0) -> None:
    """Terminate the direct child within a bounded grace period.

    POSIX siblings in the same process group are terminated by the platform's
    ``killpg``; this function is the adapter-local escalation.
    """
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    deadline = time.monotonic() + max(grace, 0.0)
    while time.monotonic() < deadline and process.poll() is None:
        time.sleep(0.05)
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except Exception:  # pragma: no cover - defensive
            pass


def install_termination_handler(handler) -> None:
    """Install SIGTERM/SIGINT handlers (no-op when unsupported)."""
    def _handle(signum, _frame):  # pragma: no cover - exercised via subprocesses
        handler(signum)

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            # Not the main thread (or unsupported platform): the platform's
            # process-group kill remains the fallback.
            pass
