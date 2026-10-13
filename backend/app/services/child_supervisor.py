"""Orchestration of the children of a long-running algorithm adapter.

Both the GLIM node and the ROS1 bridge are long-running children; a cancelled or
timed-out run must terminate them, reap them and release every resource it held
(the GLIM dump lock).  That *policy* is what this module owns, and it is written
so it can be exercised with fake processes: the OS-specific part
(``process_tree.terminate_tree``) is injected.

Contract:

* ``register`` every child as soon as it is spawned;
* a SIGTERM/SIGINT (or an explicit ``request_cancel``) marks the run cancelled
  and immediately asks every registered child to stop;
* ``raise_if_cancelled`` is the cooperative checkpoint used by the run loop, so
  a cancel is honoured even if a child ignores its signal;
* ``run_cleanup`` runs the registered cleanup hooks (lock release, temporary
  state) exactly once, in LIFO order, whatever happened before.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app.services.process_tree import terminate_tree


class RunCancelled(RuntimeError):
    """A termination request arrived while the adapter was running."""


class RunTimedOut(RunCancelled):
    """The configured run timeout expired; same termination path as a cancel."""


class ChildSupervisor:
    def __init__(self, terminator: Callable[[Any, Any], None] | None = None, *,
                 grace: float = 3.0, timeout_sec: float | None = None) -> None:
        self._children: dict[str, Any] = {}
        self._terminator = terminator or (lambda process, grace=grace: terminate_tree(process, grace=grace))
        self._grace = grace
        self._cleanup_hooks: list[tuple[str, Callable[[], None]]] = []
        self.timeout_sec = timeout_sec
        self.deadline = time.monotonic() + timeout_sec if timeout_sec else None
        self.cancelled = False
        self.timed_out = False
        self.signals: list[int] = []
        self.terminated: list[str] = []
        self.cleanup_done = False

    # ------------------------------------------------------------- children
    def register(self, name: str, process: Any) -> Any:
        self._children[name] = process
        return process

    def child(self, name: str) -> Any | None:
        return self._children.get(name)

    @property
    def children(self) -> dict[str, Any]:
        return dict(self._children)

    # --------------------------------------------------------------- cancel
    def request_cancel(self, signum: int | None = None) -> None:
        """Idempotent: a second signal does not restart the termination work."""
        if signum is not None:
            self.signals.append(signum)
        if self.cancelled:
            return
        self.cancelled = True
        self.terminate_all()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            if self.timed_out:
                raise RunTimedOut(f"run timeout of {self.timeout_sec:g}s exceeded")
            raise RunCancelled("termination requested")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            # The timeout reuses the cancel path exactly: mark the run, terminate
            # every child, then let the caller's cleanup release the lock.
            self.timed_out = True
            self.request_cancel()
            raise RunTimedOut(f"run timeout of {self.timeout_sec:g}s exceeded")

    def remaining_sec(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def terminate_all(self, *, grace: float | None = None) -> list[str]:
        """Ask every registered child to stop; safe to call repeatedly."""
        terminated: list[str] = []
        for name, process in list(self._children.items()):
            self._terminator(process, self._grace if grace is None else grace)
            if name not in self.terminated:
                self.terminated.append(name)
            terminated.append(name)
        return terminated

    # -------------------------------------------------------------- cleanup
    def add_cleanup(self, name: str, hook: Callable[[], None]) -> None:
        self._cleanup_hooks.append((name, hook))

    def run_cleanup(self) -> list[str]:
        """Run cleanup hooks once, newest first, even if one of them fails."""
        if self.cleanup_done:
            return []
        self.cleanup_done = True
        done: list[str] = []
        for name, hook in reversed(self._cleanup_hooks):
            try:
                hook()
            except Exception:  # pragma: no cover - defensive
                pass
            done.append(name)
        return done
