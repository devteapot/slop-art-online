#!/usr/bin/env python3
"""Dry-run the head session guard through its CLI with a fake clock."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


GUARD = Path(__file__).with_name("session_guard.py")


class SessionGuardTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name) / "session"

    def command(self, cmd, *options, now=1000, code=0, contains=""):
        result = subprocess.run(
            [sys.executable, str(GUARD), cmd, "--dir", str(self.directory),
             "--now", str(now), *options],
            capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, code, output)
        self.assertIn(contains, output)

    def record(self, score):
        self.command("record", "--score", str(score))

    def test_wall_clock(self):
        self.command("start")
        self.command("check", now=8199.999)
        self.command("check", now=8200, code=1, contains="wall clock")
        self.command("check", now=8201, code=1, contains="wall clock")
        self.command("record", "--score", "30", now=8201)
        self.command("status", now=8202, contains="wall clock limit reached: stop")

    def test_iteration_cap(self):
        self.command("start")
        for score in range(6):
            self.command("check")
            self.record(score)
        self.command("check", code=1, contains="iteration limit")
        self.command("record", "--score", "9", code=1, contains="iteration limit")

    def test_ties_and_first_two_scores(self):
        self.command("start")
        self.record(30)
        self.command("check")
        self.record(30)
        self.command("check")
        self.record(30)
        self.command("check", code=1, contains="no gain")

    def test_gain_resets_streak_and_prior_best_matters(self):
        self.command("start", "--max-iters", "8")
        for score in (30, 29, 31, 28, 29):
            self.command("check")
            self.record(score)
        self.command("check", code=1, contains="no gain")
        self.command("status", contains="Best score: 31")

    def test_errors_and_persisted_note(self):
        self.command("check", code=2, contains="run start first")
        self.command("start", "--hours", "0", code=2, contains="positive")
        self.command("start", "--hours", "0.5", "--max-iters", "4")
        self.command("start", code=2, contains="already started")
        self.command("record", "--score", "nan", code=2, contains="finite")
        self.command("record", "--score", "24.5", "--note", "first sheet")
        self.command("status", contains="Iterations: 1 / 4")
        state = json.loads((self.directory / "session.json").read_text())
        self.assertEqual(state["scores"], [dict(score=24.5, note="first sheet", recorded_at=1000)])
        self.command("check", now=2799, code=0)
        self.command("check", now=2800, code=1, contains="wall clock")


if __name__ == "__main__":
    unittest.main(verbosity=2)
