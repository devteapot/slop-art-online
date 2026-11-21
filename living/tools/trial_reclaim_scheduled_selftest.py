#!/usr/bin/env python3
"""Exercise scheduled reclaim orchestration without Docker or systemd."""
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import trial_reclaim_scheduled as scheduled


class ScheduledTests(unittest.TestCase):
    def fake_ctl(self, *args, check=True):
        self.calls.append(args)
        stdout = "inactive\n" if args[0] == "is-active" else ""
        if args[0] == "list-timers":
            stdout = "\n".join(f"Fri 2026-11-20 04:00 CET 2h - - {t}" for t in scheduled.TIMERS)
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def setUp(self):
        self.calls = []

    def test_failed_guard_skips_without_hold_or_timers(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(scheduled.reclaim, "QUEUE", Path(tmp)), \
                patch.object(scheduled, "trigger", return_value="daily"), \
                patch.object(scheduled.reclaim, "maintenance_locks", return_value=nullcontext(["battle.lock is held"])), \
                patch.object(scheduled.reclaim, "blockers", return_value=[]), \
                patch.object(scheduled, "load_blockers", return_value=[]), \
                patch.object(scheduled, "systemctl", side_effect=self.fake_ctl), patch.object(scheduled, "log") as log:
            self.assertEqual(scheduled.run(2, "/wasm/unused.wasm"), 0)
            self.assertFalse((Path(tmp) / "HOLD").exists())
            self.assertEqual(self.calls, [])
            log.assert_called_once_with("skip: battle.lock is held")

    def test_preexisting_hold_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(scheduled, "systemctl", side_effect=self.fake_ctl):
            hold = Path(tmp) / "HOLD"
            hold.write_text("coordinator\n")
            with scheduled.timer_window(hold):
                self.assertEqual(hold.read_text(), "coordinator\n")
            self.assertEqual(hold.read_text(), "coordinator\n")
            self.assertEqual(self.calls[:2], [("stop", scheduled.CHECK_TIMER), ("stop", scheduled.CLEAN_TIMER)])

    def test_failure_restores_timers_in_order_and_releases_own_hold(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(scheduled, "systemctl", side_effect=self.fake_ctl):
            hold = Path(tmp) / "HOLD"
            with self.assertRaisesRegex(RuntimeError, "fixture reclaim failure"):
                with scheduled.timer_window(hold):
                    self.assertTrue(hold.exists())
                    raise RuntimeError("fixture reclaim failure")
            self.assertFalse(hold.exists())
            self.assertEqual(self.calls[:2], [("stop", scheduled.CHECK_TIMER), ("stop", scheduled.CLEAN_TIMER)])
            self.assertEqual(self.calls[-3][:2], ("start", scheduled.CLEAN_SERVICE))
            self.assertEqual(self.calls[-2], ("restart", scheduled.CLEAN_TIMER, scheduled.CHECK_TIMER))
            self.assertEqual(self.calls[-1][0], "list-timers")

    def test_threshold_uses_recent_hourly_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trial-volume.log"
            path.write_text("2026-11-20 01:00:25 trial volume 141.250 GB\n")
            self.assertIn("141.250", scheduled.trigger(datetime(2026, 11, 20, 1, 20).astimezone(), path))
            self.assertIsNone(scheduled.trigger(datetime(2026, 11, 20, 3, 20).astimezone(), path))
            self.assertEqual(scheduled.trigger(datetime(2026, 11, 20, 4, 20).astimezone(), path),
                             "daily quiet window")


if __name__ == "__main__":
    unittest.main()
