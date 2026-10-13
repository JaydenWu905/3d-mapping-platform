from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest

from app.services.child_supervisor import ChildSupervisor, RunCancelled, RunTimedOut
from app.services.process_tree import child_popen_kwargs, terminate_tree


class FakeProcess:
    """A Popen-shaped double: lets the orchestration be tested without an OS."""

    def __init__(self, name: str = "child", returncode: int | None = None) -> None:
        self.name = name
        self.returncode = returncode
        self.terminate_calls = 0
        self.kill_calls = 0
        self.waited = 0

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited += 1
        return self.returncode


class StubbornProcess(FakeProcess):
    """Ignores terminate(): the supervisor must escalate to kill()."""

    def terminate(self) -> None:
        self.terminate_calls += 1

    def poll(self):
        if self.kill_calls:
            return self.returncode
        return self.returncode if self.returncode is not None and self.returncode >= 0 else None


class SupervisorOrchestrationTests(unittest.TestCase):
    """docs/glim-integration-acceptance.md §5-§6, orchestration half."""

    def test_terminate_all_uses_the_injected_terminator_for_every_child(self):
        calls: list[tuple[str, float]] = []

        def terminator(process, grace):
            calls.append((process.name, grace))

        supervisor = ChildSupervisor(terminator, grace=1.5)
        supervisor.register("glim", FakeProcess("glim"))
        supervisor.register("bridge", FakeProcess("bridge"))
        self.assertEqual(sorted(supervisor.terminate_all()), ["bridge", "glim"])
        self.assertEqual(calls, [("glim", 1.5), ("bridge", 1.5)])

    def test_cancel_terminates_bridge_and_glim_and_is_idempotent(self):
        supervisor = ChildSupervisor()
        glim = supervisor.register("glim", FakeProcess("glim"))
        bridge = supervisor.register("bridge", FakeProcess("bridge"))

        supervisor.request_cancel(signal.SIGTERM)
        self.assertTrue(supervisor.cancelled)
        self.assertEqual(supervisor.signals, [signal.SIGTERM])
        self.assertEqual(glim.terminate_calls, 1)
        self.assertEqual(bridge.terminate_calls, 1)
        self.assertIsNotNone(glim.poll())
        self.assertIsNotNone(bridge.poll())

        # A second signal must not restart the termination work.
        supervisor.request_cancel(signal.SIGINT)
        self.assertEqual(glim.terminate_calls, 1)
        self.assertEqual(supervisor.signals, [signal.SIGTERM, signal.SIGINT])

    def test_run_loop_checkpoint_raises_only_after_a_cancel(self):
        supervisor = ChildSupervisor()
        supervisor.register("glim", FakeProcess("glim"))
        supervisor.raise_if_cancelled()  # no-op
        supervisor.request_cancel(signal.SIGTERM)
        with self.assertRaises(RunCancelled):
            supervisor.raise_if_cancelled()

    def test_timeout_path_reuses_the_cancel_path(self):
        # A watchdog calling request_cancel(None) must behave like a signal.
        supervisor = ChildSupervisor()
        glim = supervisor.register("glim", FakeProcess("glim"))
        supervisor.request_cancel()
        self.assertTrue(supervisor.cancelled)
        self.assertEqual(glim.terminate_calls, 1)
        self.assertEqual(supervisor.signals, [])

    def test_cleanup_hooks_run_newest_first_exactly_once_and_survive_failures(self):
        order: list[str] = []
        supervisor = ChildSupervisor()
        supervisor.register("glim", FakeProcess("glim"))
        supervisor.add_cleanup("temp_state", lambda: order.append("temp_state"))

        def boom() -> None:
            order.append("boom")
            raise RuntimeError("cleanup hook failed")

        supervisor.add_cleanup("glim_lock", boom)
        # A cancelled run still releases the lock and cleans temporary state.
        supervisor.request_cancel(signal.SIGTERM)
        supervisor.terminate_all()
        self.assertEqual(supervisor.run_cleanup(), ["glim_lock", "temp_state"])
        self.assertEqual(order, ["boom", "temp_state"])
        # Idempotent: a second finally-block call does nothing.
        self.assertEqual(supervisor.run_cleanup(), [])
        self.assertEqual(order, ["boom", "temp_state"])

    def test_stubborn_child_is_escalated_to_kill(self):
        supervisor = ChildSupervisor()
        child = supervisor.register("glim", StubbornProcess("glim"))
        supervisor.request_cancel(signal.SIGTERM)
        self.assertEqual(child.terminate_calls, 1)
        self.assertEqual(child.kill_calls, 1)
        self.assertIsNotNone(child.poll())

    def test_finished_child_is_not_terminated(self):
        supervisor = ChildSupervisor()
        finished = supervisor.register("bridge", FakeProcess("bridge", returncode=0))
        supervisor.request_cancel(signal.SIGTERM)
        self.assertEqual(finished.terminate_calls, 0)


class RunTimeoutTests(unittest.TestCase):
    """`pose.run_timeout_sec` must ride the cancel path, not a second one."""

    def test_timeout_terminates_children_and_marks_the_run(self):
        supervisor = ChildSupervisor(timeout_sec=0.05)
        glim = supervisor.register("glim", FakeProcess("glim"))
        bridge = supervisor.register("bridge", FakeProcess("bridge"))
        releases: list[str] = []
        supervisor.add_cleanup("glim_lock", lambda: releases.append("lock"))
        time.sleep(0.06)
        with self.assertRaises(RunTimedOut):
            supervisor.raise_if_cancelled()
        self.assertTrue(supervisor.timed_out)
        self.assertTrue(supervisor.cancelled)
        self.assertEqual(glim.terminate_calls, 1)
        self.assertEqual(bridge.terminate_calls, 1)
        self.assertIsNotNone(glim.poll())
        self.assertIsNotNone(bridge.poll())
        # Same cleanup path as a cancel.
        self.assertEqual(supervisor.run_cleanup(), ["glim_lock"])
        self.assertEqual(releases, ["lock"])

    def test_explicit_cancel_wins_over_a_later_deadline(self):
        supervisor = ChildSupervisor(timeout_sec=0.05)
        supervisor.register("glim", FakeProcess("glim"))
        supervisor.request_cancel(signal.SIGTERM)
        time.sleep(0.06)
        with self.assertRaises(RunCancelled) as raised:
            supervisor.raise_if_cancelled()
        self.assertNotIsInstance(raised.exception, RunTimedOut)

    def test_remaining_time_is_reported_and_none_without_a_timeout(self):
        self.assertIsNone(ChildSupervisor().remaining_sec())
        supervisor = ChildSupervisor(timeout_sec=5.0)
        self.assertLessEqual(supervisor.remaining_sec(), 5.0)
        self.assertGreater(supervisor.remaining_sec(), 0.0)

    def test_no_timeout_means_no_deadline(self):
        supervisor = ChildSupervisor()
        supervisor.register("glim", FakeProcess("glim"))
        supervisor.raise_if_cancelled()  # must not raise
        self.assertIsNone(supervisor.deadline)
        self.assertFalse(supervisor.timed_out)


class ChildSpawnPolicyTests(unittest.TestCase):
    """Children must stay inside the platform-managed process group."""

    def test_spawn_kwargs_do_not_create_a_new_session(self):
        kwargs = child_popen_kwargs()
        self.assertEqual(kwargs, {})
        self.assertFalse(kwargs.get("start_new_session", False))
        self.assertNotIn("creationflags", kwargs)


def pid_exists(pid: int) -> bool:
    if os.name != "posix":
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class RealChildTerminationTests(unittest.TestCase):
    def test_terminate_tree_kills_a_real_direct_child(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(process.kill)
        self.assertIsNone(process.poll())
        terminate_tree(process, grace=5.0)
        self.assertIsNotNone(process.poll())

    def test_terminate_tree_is_a_noop_for_a_finished_process(self):
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        terminate_tree(process, grace=0.1)  # must not raise
        self.assertEqual(process.returncode, 0)

    @unittest.skipUnless(os.name == "posix",
                         "whole-process-group reaping is POSIX-only (ENVIRONMENT LIMITATION: "
                         "windows sandbox cannot prove it; production target is Linux)")
    def test_posix_process_group_reaches_descendants(self):
        process = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys, time;"
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
             "print(p.pid, flush=True); time.sleep(120)"],
            stdout=subprocess.PIPE, text=True, start_new_session=True,
        )
        self.addCleanup(process.kill)
        grandchild = int(process.stdout.readline().strip())
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and pid_exists(grandchild):
            time.sleep(0.05)
        self.assertFalse(pid_exists(grandchild))


if __name__ == "__main__":
    unittest.main()
