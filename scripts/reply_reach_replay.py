#!/usr/bin/env python3
"""Replay three directed conversation patterns on one checkout with the real authority and a fake model."""

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import traceback


def load_driver(checkout):
    path = checkout / ".agents/skills/verify-minds/scripts/verify_minds.py"
    spec = importlib.util.spec_from_file_location("verify_minds", path)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    return driver


PATTERNS = (
    ("both-walk", "Morning, all. Baldwin, would you stir yourself? Fires want lighting, and I'll want wood stacked before the week's out?", (0.482, 0.60, 0.72, 4.8)),
    ("addressee-walks", "Morning, father. Mother. I'll be at the hall with the rolls after I've eaten, will you?", (0.539, 0.65, 0.848, 4.8)),
    ("resident-walks", "Good morning. What is your name?", (0.49, 0.572, 0.66, 4.8)),
)
FOLLOW = "# What came of your last words"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class Scene:
    def __init__(self, driver, run):
        self.run = run
        self.last_greeting = {}
        self.api = driver.shared
        self.driver = driver
        run.harness("launch")
        run.harness("doctor")
        state = json.loads((run.directory / "state.json").read_text())
        self.endpoint = f"{self.api.STDB_URL}/v1/database/{state['database_identity']}"
        login = subprocess.run(
            [str(driver.ROOT / "living/tools/stdb"), "login", "show", "--token"],
            capture_output=True, text=True, timeout=20,
        )
        tokens = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", login.stdout)
        if login.returncode or len(tokens) != 1:
            raise RuntimeError("could not obtain the scratch server's admin token")
        self.token = tokens[0]
        self.line = driver.open_line(run, 40)
        prior = {row["id"] for row in self.sql("SELECT id FROM character")}
        run.admin("spawn_crowd", 14, True)
        made = sorted(row["id"] for row in self.sql("SELECT id FROM character") if row["id"] not in prior)
        assert len(made) == 14, made
        self.actors = made[:12]
        self.speakers = made[12:]
        for who in made:
            self.behavior(who)
        run.harness("player", "join", "ReplyReachPlayer")
        self.player = self.sql("SELECT id FROM character WHERE name = 'ReplyReachPlayer'")[0]["id"]
        self.player_token = json.loads((run.directory / "state.json").read_text())["token"]

    def sql(self, query):
        status, body = self.api.world_guard.request(self.endpoint + "/sql", self.token, query.encode())
        if status != 200:
            raise RuntimeError(f"SQL {status}: {query}")
        result = json.loads(body)[-1]
        names = [column["name"].get("some", "?") for column in result["schema"]["elements"]]
        return [dict(zip(names, values)) for values in result["rows"]]

    def call(self, reducer, *args, player=False):
        token = self.player_token if player else self.token
        status, _ = self.api.world_guard.request(
            f"{self.endpoint}/call/{reducer}", token, json.dumps(args).encode(), json_body=True
        )
        self.run.note(f"{reducer} {args!r} ({'player' if player else 'admin'}) -> {status}")
        if status != 200:
            raise RuntimeError(f"{reducer} returned HTTP {status}")

    def behavior(self, actor, goal=None, running=False):
        graph = {"wait": 300}
        if goal is not None:
            graph = {"seq": [{"do": {"skill": "goto", "target": {"at": list(goal)}, "run": running}}, graph]}
        self.call("set_behavior", actor, json.dumps(graph))

    def body(self, actor, other):
        rows = self.sql(
            f"SELECT id, x, y, vx, vy, t_ms, next_ms, turn FROM body WHERE id = {actor} OR id = {other}"
        )
        return {"at_ms": time.time_ns() // 1_000_000, "bodies": {row["id"]: row for row in rows}}

    @staticmethod
    def gap(sample, actor, other, at=None):
        at = sample["at_ms"] if at is None else at
        positions = []
        for who in (actor, other):
            body = sample["bodies"][who]
            dt = max(0, min(at, body["next_ms"]) - body["t_ms"]) / 1000
            positions.append((body["x"] + dt * body["vx"], body["y"] + dt * body["vy"]))
        return math.dist(*positions)

    def setup(self, pattern, actor, other, variant):
        human_speaker = pattern == "resident-walks"
        both_walk = pattern == "both-walk"
        for who in (actor, other):
            if who != self.player:
                self.behavior(who)
        start = 4
        actor_tile, other_tile = (start, start + 4) if both_walk else (
            (start + 4, start) if human_speaker else (start, start + 1)
        )
        self.call("place_at", actor, *self.line[actor_tile])
        self.call("place_at", other, *self.line[other_tile])
        time.sleep(0.55)
        if both_walk or human_speaker:
            self.behavior(actor, self.line[-2])
        if not human_speaker:
            self.behavior(other, self.line[-2], running=both_walk)
        movers = {actor} if human_speaker else {actor, other} if both_walk else {other}
        minimum = (5.35 + variant * 0.10 if human_speaker else 4.8 if both_walk else 2.1)
        maximum = 6.45 if human_speaker else 7.0 if both_walk else 4.2

        def ready():
            bodies = self.body(actor, other)
            gap = self.gap(bodies, actor, other)
            if all(bodies["bodies"][who]["vx"] > 0.75 and not bodies["bodies"][who]["turn"] for who in movers):
                if gap > maximum:
                    raise RuntimeError(f"staging overshot: {pattern} at {gap:.2f} m")
                if gap >= minimum:
                    assert all(not bodies["bodies"][who]["vx"] for who in {actor, other} - movers)
                    return bodies
            time.sleep(0.025)
            return None

        # Poll faster than the shortest staging window. No calls are issued outside
        # the validated world, and the enclosing harness refreshes its lease.
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if sample := ready():
                return sample
        raise RuntimeError(f"movement did not reach the staging window for {pattern}")

    def move_offstage(self, actor):
        self.behavior(actor)
        x, y = self.line[0]
        self.call("place_at", actor, x, y + 12)

    def make_trials(self):
        for group, (pattern, greeting, delays) in enumerate(PATTERNS):
            other = self.player if group == 2 else self.speakers[group]
            for variant, delay in enumerate(delays):
                key = f"rr-{group}-{variant}"
                # Keep the play-test 10 trigger exactly six words including its unique marker.
                incoming = greeting.replace("name?", f"name-{key}?") if group == 2 else f"{greeting} ({key})"
                yield {
                    "pattern": pattern, "variant": variant, "actor": self.actors[group * 4 + variant],
                    "other": other, "key": key, "delay": delay, "incoming": incoming,
                }

    def play(self):
        trials = list(self.make_trials())
        default = {"thought": "I continue.", "say": "", "acts": [], "end": True}
        rules = []
        for trial in trials:
            key, other = trial["key"], trial["other"]
            call = trial["pattern"] != "resident-walks"
            rules.extend([
                {"purpose": "talk", "contains": f"Reply {key}.", "times": -1,
                 "reply": {**default, "say": f"Retry {key}.", "to": other,
                           "way": "call" if call else "say", "end": False}},
                {"purpose": "talk", "contains": key, "times": -1, "delay_s": trial["delay"],
                 "reply": {**default, "say": f"Reply {key}.", "to": other, "way": "say", "end": False}},
            ])
        config = self.driver.model(self.run, {
            "replies": {"think": {**default, "intend": ["wait"]}, "deliberate": self.driver.basic_reply(), "talk": default},
            "rules": rules,
        })
        self.run.start(config, self.actors)
        time.sleep(2)
        records = []
        for trial in trials:
            record = self.measure(trial)
            records.append(record)
            write(self.run.directory / "replay.json", records)
            print(f"{trial['key']} {trial['pattern']}: {record['first']} / {record['follow_up']}", flush=True)
            if trial is not trials[-1]:
                self.move_offstage(trial["actor"])
        self.run.harness("doctor")
        return records

    def measure(self, trial):
        actor, other, key = (trial[field] for field in ("actor", "other", "key"))
        # Stage after the prior greeting's own speaker gap. Fast replies can
        # otherwise make a reused addressee start the next trial too soon.
        since_last = time.monotonic() - self.last_greeting.get(other, 0)
        time.sleep(max(0, 2.2 - since_last))
        staged = self.setup(trial["pattern"], actor, other, trial["variant"])
        if other == self.player:
            self.call("human_speak", trial["incoming"], actor, "say", player=True)
        else:
            self.call("mind_say", other, trial["incoming"], actor, "say", 0, self.driver.TALK_THOUGHT)
        self.last_greeting[other] = time.monotonic()
        # Both the success and failure of the original delivery come from the authority.
        # Keep polling while the one permitted follow-up may be waiting on the speech gap.
        samples = [staged]
        timeout = time.monotonic() + 16.0
        first = follow_result = None
        stop_at = None
        observed = {}
        query = "SELECT id, at_ms, kind, observer, subject, object, text FROM experience WHERE observer ="
        # An NPC can consolidate the greeting out of its inbox before its reply.
        # Preserve each sampled row once so it remains available for the join.

        while time.monotonic() < timeout:
            samples.append(self.body(actor, other))
            for who in (actor, other):
                observed.update((row["id"], row) for row in self.sql(f"{query} {who}"))
            rows = list(observed.values())
            greeted = next((r for r in rows if r["kind"] == "speech" and r["observer"] == actor
                            and r["subject"] == other and key in r["text"]), None)
            said = sorted((r for r in rows if r["kind"] == "said" and r["observer"] == actor
                           and key in r["text"]), key=lambda r: r["at_ms"])
            if greeted and said:
                silence_times = {r["at_ms"] for r in rows if r["kind"] == "silence"
                                 and r["observer"] == actor and r["subject"] == other}
                heard_times = {r["at_ms"] for r in rows if r["kind"] == "speech" and r["observer"] == other
                               and r["subject"] == actor and key in r["text"]}
                outcome = lambda r: "miss" if r["at_ms"] in silence_times else "heard" if r["at_ms"] in heard_times else None
                first = outcome(said[0])
                if len(said) > 1:
                    follow_result = outcome(said[1])
                if first == "heard" or follow_result:
                    break
                if first and stop_at is None:
                    stop_at = time.monotonic() + 5.4
                if stop_at is not None and time.monotonic() >= stop_at:
                    break
            time.sleep(0.13)
        exchanges = [row for row in self.run.exchanges() if row["purpose"] == "talk"
                     and any(key in (message.get("content") or "") for message in row["request"]["messages"])]
        follow = [row for row in exchanges if any(FOLLOW in (m.get("content") or "") for m in row["request"]["messages"])]
        write(self.run.directory / f"{key}-body.json", samples)
        write(self.run.directory / f"{key}-experience.json",
              [r for r in rows if key in r["text"] or (r["kind"] == "silence" and r["observer"] == actor)])
        assert greeted and first and exchanges, (trial, greeted, first, len(exchanges))
        assert len(follow) <= 1 and len(said) <= 2, (trial, len(follow), len(said))
        assert not follow or follow_result, (trial, len(follow), follow_result)
        def distance_at(at):
            candidates = [s for s in samples if s["at_ms"] <= at]
            sample = candidates[-1] if candidates else samples[0]
            return round(self.gap(sample, actor, other, at), 2)

        ready = exchanges[0]["at_ms"]
        return {**trial, "first": first, "follow_up": follow_result, "follow_prompts": len(follow),
                "heard_ms": greeted["at_ms"], "ready_ms": ready, "said_ms": said[0]["at_ms"],
                "model_ms": exchanges[0]["latency_ms"], "queue_ms": exchanges[0]["queue_wait_ms"],
                "distance_at_greeting_m": distance_at(greeted["at_ms"]),
                "distance_at_ready_m": distance_at(ready),
                "distance_at_submission_m": distance_at(said[0]["at_ms"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("binary", type=Path)
    parser.add_argument("run")
    args = parser.parse_args()
    if not (2 * 60 <= time.localtime().tm_hour * 60 + time.localtime().tm_min < 23 * 60 + 15):
        parser.error("outside the Spark trial window")
    if os.environ.get("LIVING_STDB_CONTAINER") != "slop-replyreach-stdb" or os.environ.get("LIVING_STDB_URL") != "http://127.0.0.1:3337":
        parser.error("set the explicit reply-reach scratch server")
    driver = load_driver(args.checkout.resolve())
    driver.shared.MIND_BIN = args.binary.resolve()
    run = driver.Run(args.run)
    print(f"Evidence: {run.directory}", flush=True)
    try:
        Scene(driver, run).play()
    except Exception:
        (run.directory / "failure.txt").write_text(traceback.format_exc())
        raise
    finally:
        run.finish_cleanup()


if __name__ == "__main__":
    main()
