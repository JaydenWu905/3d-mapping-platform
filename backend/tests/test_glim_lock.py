from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app.services.glim_lock import (
    GlimDumpError,
    GlimExecutionLock,
    inspect_dump_dir,
)


class GlimLockTests(unittest.TestCase):
    """docs/glim-integration-acceptance.md §6."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lock_path = self.root / "runtime" / "locks" / "glim.lock"

    def write_lock(self, pid: int, job_id: str, age_sec: float = 0.0) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps({
            "pid": pid, "job_id": job_id, "started_at": "2026-10-03T00:00:00", "host": "test",
        }), encoding="utf-8")
        if age_sec:
            stamp = time.time() - age_sec
            os.utime(self.lock_path, (stamp, stamp))

    def test_first_acquires_and_second_is_blocked_with_the_holder_named(self):
        # Liveness is injected so this stays a pure policy test on any OS.
        with mock.patch("app.services.glim_lock.pid_is_alive", return_value=True):
            first = GlimExecutionLock(self.lock_path)
            self.assertTrue(first.acquire(job_id="job-a").acquired)
            self.assertTrue(self.lock_path.is_file())

            second = GlimExecutionLock(self.lock_path)
            blocked = second.acquire(job_id="job-b")
            self.assertFalse(blocked.acquired)
            self.assertFalse(blocked.stale)
            self.assertEqual(blocked.holder["job_id"], "job-a")
            self.assertIn("only one real GLIM job", blocked.reason)
            self.assertEqual(blocked.stale_taken_over_from, None)

        self.assertTrue(first.release())
        self.assertFalse(self.lock_path.exists())

    def test_undeterminable_owner_is_treated_as_busy(self):
        # ENVIRONMENT LIMITATION: the windows sandbox cannot probe pid liveness,
        # so the policy under test is "unknown means assume alive".
        self.write_lock(pid=os.getpid(), job_id="job-live")
        with mock.patch("app.services.glim_lock.pid_is_alive", return_value=None):
            status = GlimExecutionLock(self.lock_path).acquire(job_id="job-b")
        self.assertFalse(status.acquired)
        self.assertIn("could not be determined", status.reason)
        self.assertTrue(self.lock_path.is_file())

    def test_dead_owner_is_taken_over_and_reported(self):
        self.write_lock(pid=999_999, job_id="job-dead")
        with mock.patch("app.services.glim_lock.pid_is_alive", return_value=False):
            lock = GlimExecutionLock(self.lock_path)
            status = lock.acquire(job_id="job-live")
        self.assertTrue(status.acquired)
        self.assertTrue(status.stale)
        self.assertEqual(status.stale_taken_over_from["job_id"], "job-dead")
        self.assertTrue(any("stale" in event for event in lock.events))
        lock.release()

    @unittest.skipIf(os.name != "posix",
                     "pid liveness probing is POSIX-only by design "
                     "(ENVIRONMENT LIMITATION: windows sandbox cannot prove it)")
    def test_real_dead_pid_is_detected_on_posix(self):
        import subprocess
        import sys

        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.write_lock(pid=child.pid, job_id="job-dead")
        lock = GlimExecutionLock(self.lock_path)
        status = lock.acquire(job_id="job-live")
        self.assertTrue(status.stale)
        lock.release()

    def test_aged_lock_is_taken_over_even_if_the_holder_still_lives(self):
        self.write_lock(pid=os.getpid(), job_id="job-old", age_sec=7200)
        with mock.patch("app.services.glim_lock.pid_is_alive", return_value=True):
            lock = GlimExecutionLock(self.lock_path, stale_after_sec=3600)
            status = lock.acquire(job_id="job-new")
        self.assertTrue(status.acquired)
        self.assertTrue(status.stale)
        self.assertEqual(status.stale_taken_over_from["job_id"], "job-old")
        lock.release()

    def test_foreign_lock_is_not_removed_by_a_non_owner(self):
        self.write_lock(pid=1, job_id="job-other")
        lock = GlimExecutionLock(self.lock_path)
        self.assertFalse(lock.release())
        self.assertTrue(self.lock_path.is_file())


class DumpDirectoryTests(unittest.TestCase):
    """The shared GLIM dump path must never be reused by two jobs."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dump = self.root / "dump"
        self.quarantine = self.root / "quarantine"

    def test_missing_and_empty_dump_directories_need_no_action(self):
        self.assertEqual(
            inspect_dump_dir(self.dump, policy="quarantine",
                             quarantine_dir=self.quarantine, job_id="j")["action"],
            "none",
        )
        self.dump.mkdir()
        self.assertEqual(
            inspect_dump_dir(self.dump, policy="quarantine",
                             quarantine_dir=self.quarantine, job_id="j")["action"],
            "empty",
        )

    def test_non_empty_dump_is_quarantined_and_removed_from_the_shared_path(self):
        self.dump.mkdir()
        (self.dump / "traj_lidar.txt").write_text("1 0 0 0 0 0 0 1\n", encoding="utf-8")
        info = inspect_dump_dir(self.dump, policy="quarantine",
                                quarantine_dir=self.quarantine, job_id="job-7")
        self.assertEqual(info["action"], "quarantined")
        self.assertFalse(self.dump.exists())
        moved = Path(info["quarantined_to"])
        self.assertTrue(moved.is_dir())
        self.assertTrue((moved / "traj_lidar.txt").is_file())
        self.assertIn("job-7", moved.name)

    def test_require_empty_policy_refuses_instead_of_moving_data(self):
        self.dump.mkdir()
        (self.dump / "leftover.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(GlimDumpError, "dump_policy=quarantine"):
            inspect_dump_dir(self.dump, policy="require_empty",
                             quarantine_dir=self.quarantine, job_id="job-8")
        self.assertTrue((self.dump / "leftover.txt").is_file())

    def test_dry_run_reports_the_plan_without_touching_the_dump(self):
        self.dump.mkdir()
        (self.dump / "traj_lidar.txt").write_text("x", encoding="utf-8")
        info = inspect_dump_dir(self.dump, policy="quarantine",
                                quarantine_dir=self.quarantine, job_id="job-9", dry_run=True)
        self.assertEqual(info["action"], "would_quarantine")
        self.assertTrue((self.dump / "traj_lidar.txt").is_file())
        self.assertFalse(self.quarantine.exists())


if __name__ == "__main__":
    unittest.main()
