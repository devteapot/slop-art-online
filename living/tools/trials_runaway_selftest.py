#!/usr/bin/env python3
"""Self-test of the trial runner's runaway and outage guards (living/tools/trials.py
`failure_kind`, `Instance.note_call`, `Instance.runaway`, `Instance.outage`) and its
consolidation accounting (`consolidation_table`, `consolidation_report`).

A runaway is the mind repeating a failing act: the same non-provider failure 15 times in 5
minutes (or 30 failures) still stops a run. A provider outage is not: capacity or rate 429s,
5xx and connection errors count toward no failure limit while a fallback or retry answers. It
is recorded (`outages`, events) once nothing has answered for 30 s, and stops the run only when
no route has answered for 10 minutes while calls still fail. ar1's pattern (2026-11-11: 7 of 28
instances stopped over consolidation's capacity 429s) is replayed here. No server, no network.

Usage: python3 living/tools/trials_runaway_selftest.py [-v]
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trials  # noqa: E402

CAPACITY = ('HTTP 429 Too Many Requests: {"object":"error","message":"Not enough capacity available for this request, '
            'please retry later.","type":"backend_out_of_capacity","param":null,"code":"3505","raw_status_code":429}')
RATE = 'HTTP 429 Too Many Requests: {"message":"Requests rate limit exceeded"}'
BAD = 'HTTP 400 Bad Request: {"message":"Prompt contains 140000 tokens, too large for model"}'
DOWN = "request: error sending request for url (https://api.mistral.ai/v1/chat/completions): client error (Connect)"


class Guard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = time.time()
        inst = trials.Instance.__new__(trials.Instance)
        inst.trial, inst.dir, inst.t0 = {}, Path(self.dir.name), self.now - 3600
        inst.recent, inst.starts, inst.runaway_seen = [], [], []
        inst.provider_fails, inst.last_ok, inst.outage_since, inst.outages = [], None, None, []
        self.inst = inst

    def tearDown(self):
        self.dir.cleanup()

    def call(self, ago, purpose="consolidate", error=None, model="zai-glm-5-3-flash"):
        self.inst.note_call({"at_ms": int((self.now - ago) * 1000), "purpose": purpose, "model": model, "error": error})

    def events(self):
        p = Path(self.dir.name) / "events.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_failure_kinds(self):
        self.assertIsNone(trials.failure_kind(None))
        self.assertEqual(trials.failure_kind(CAPACITY), "capacity_429")
        self.assertEqual(trials.failure_kind(CAPACITY[:100]), "capacity_429")
        self.assertEqual(trials.failure_kind(RATE), "rate_429")
        self.assertEqual(trials.failure_kind("HTTP 503 Service Unavailable: upstream"), "http_5xx")
        self.assertEqual(trials.failure_kind(DOWN), "connection")
        self.assertEqual(trials.failure_kind("request: operation timed out"), "connection")
        self.assertEqual(trials.failure_kind(BAD), "mind")
        self.assertEqual(trials.failure_kind("profile glm-flash has no key"), "mind")

    def test_capacity_429s_with_a_working_fallback_do_not_stop_the_run(self):
        # ar1: 40 consolidation capacity 429s in 5 minutes, each answered by DeepSeek a second later.
        for i in range(40):
            self.call(290 - i * 7, error=CAPACITY)
            self.call(289 - i * 7, model="deepseek-v4-1-flash-1017")
        self.assertIsNone(self.inst.runaway())
        self.assertEqual(self.inst.outages, [], "a gap the fallback closes in a second is not an outage")
        self.assertFalse(any("runaway" in e or "outage" in e for e in self.events()))

    def test_capacity_429s_retried_later_do_not_stop_the_run(self):
        # No fallback: the mind retries each consolidation 20 s × failures later; other calls succeed.
        for i in range(30):
            self.call(295 - i * 9, error=CAPACITY)
            self.call(294 - i * 9, purpose="think", model="deepseek-v4-1-flash-1017")
        for i in range(20):
            self.call(150 - i, error=RATE, purpose="think")
        self.assertIsNone(self.inst.runaway())

    def test_the_same_mind_failure_still_stops_the_run(self):
        for i in range(15):
            self.call(200 - i * 10, purpose="deliberate", error=BAD)
            self.call(199 - i * 10, purpose="think")
        why = self.inst.runaway()
        self.assertIsNotNone(why)
        self.assertIn("the same failure 15 times", why)
        self.assertIn("deliberate", why)

    def test_many_mind_failures_still_stop_the_run(self):
        for i in range(30):
            self.call(250 - i * 5, purpose="think", error=f"HTTP 422 Unprocessable Entity: variant {i}")
        self.assertIn("30 failed model calls", self.inst.runaway())

    def test_a_call_storm_against_a_failing_provider_trips_the_call_rate(self):
        for i in range(70):
            self.call(55 - i * 0.5, error=CAPACITY)
        self.assertIn("model calls in one minute", self.inst.runaway())

    def test_a_short_outage_is_recorded_and_does_not_stop_the_run(self):
        self.call(400)
        for i in range(12):
            self.call(390 - i * 10, purpose="think", error=DOWN)
        self.assertIsNone(self.inst.runaway())
        self.assertTrue(any("outage" in e for e in self.events()), "an outage event once nothing answered for 30 s")
        self.call(200, purpose="think")
        self.assertIsNone(self.inst.runaway())
        self.assertEqual(len(self.inst.outages), 1, self.inst.outages)
        o = self.inst.outages[0]
        self.assertEqual((o["failed"], o["kinds"]), (12, {"connection": 12}))
        self.assertAlmostEqual(o["seconds"], 190, delta=1)
        self.assertTrue(any("outage_ended" in e for e in self.events()))
        self.assertIsNone(self.inst.runaway(), "the ended outage is recorded once")
        self.assertEqual(len(self.inst.outages), 1)

    def test_no_route_answering_for_ten_minutes_stops_the_run(self):
        self.call(800)
        for i in range(40):
            self.call(700 - i * 15, error=CAPACITY if i % 2 else "HTTP 502 Bad Gateway: no upstream",
                      model="zai-glm-5-3-flash" if i % 3 else "deepseek-v4-1-flash-1017")
        why = self.inst.runaway()
        self.assertTrue(why and why.startswith("provider outage: no route answered for 12 minutes"), why)
        self.assertIn("capacity_429 20", why)
        self.assertIsNotNone(self.inst.outage_since)

    def test_an_outage_whose_calls_stopped_does_not_stop_the_run(self):
        # Every call failing for 11 minutes, but the last one 5 minutes ago: nothing is being tried.
        for i in range(10):
            self.call(960 - i * 40, error=DOWN)
        self.assertIsNone(self.inst.runaway())


class Accounting(unittest.TestCase):
    def test_consolidation_table_and_report(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "outcomes"
            d.mkdir()
            lines = [
                {"at_ms": 1, "actor": "Mara", "outcome": "integrated", "route": "primary", "model_call": True},
                {"at_ms": 2, "actor": "Mara", "outcome": "integrated", "route": "fallback", "model_call": True},
                {"at_ms": 3, "actor": "Mara", "outcome": "failed", "model_call": True, "failure": CAPACITY},
                {"at_ms": 4, "actor": "Mara", "outcome": "integrated", "route": "fallback", "model_call": True, "trimmed": 0},
                {"at_ms": 5, "actor": "Wenna", "outcome": "failed", "model_call": True, "failure": CAPACITY},
                {"at_ms": 6, "actor": "Wenna", "outcome": "failed", "model_call": False, "failure": "neo4j: down"},
                {"at_ms": 7, "actor": "Wenna", "outcome": "integrated", "route": None, "model_call": False, "trimmed": 3},
            ]
            (d / "consolidations.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines) + "{cut")
            table = trials.consolidation_table(t)
            self.assertEqual(table["by_character"]["Mara"], {"attempted": 4, "primary": 1, "fallback": 2, "retried": 1, "lost": 0, "trimmed": 0, "capacity_429": 1})
            self.assertEqual(table["by_character"]["Wenna"], {"attempted": 2, "primary": 0, "fallback": 0, "retried": 1, "lost": 1, "trimmed": 3, "capacity_429": 1})
            self.assertEqual(table["total"]["attempted"], 6)
            self.assertIsNone(trials.consolidation_table(Path(t) / "none"))
            sums = [{"trial": "hamlet", "variant": "births", "replicate": 1, "consolidations": table,
                     "outages": [{"since_t": 10.0, "until_t": None, "failed": 9, "kinds": {"connection": 9}}]},
                    {"trial": "hamlet", "variant": "births", "replicate": 2, "consolidations": None}]
            md = "\n".join(trials.consolidation_report(sums))
            self.assertIn("| hamlet/births/r1 | 6 | 1 | 2 | 2 | 1 | 3 | 2 |", md)
            self.assertIn("| hamlet/births/r1 | Wenna | 2 | 0 | 0 | 1 | 1 | 3 | 1 |", md)
            self.assertIn("No consolidation outcomes", md)
            self.assertIn("still down at the stop", md)


if __name__ == "__main__":
    unittest.main()
