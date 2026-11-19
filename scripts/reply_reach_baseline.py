#!/usr/bin/env python3
"""Summarize archived reply evidence without emitting model requests or credentials."""

import argparse
import json
import math
import re
from pathlib import Path


REPLY = re.compile(r"mind::talk\] (.+?) to (.+?): “")
MISS = re.compile(r"mind::talk\] (.+?) and (.+?): out of earshot, conversation over")
CASES = {
    "play-test 8": [(13, 14, 1795038114471, 1795038114975, 1795038120412)],
    "play-test 9": [
        (1, 3, 1795073937704, 1795073938286, 1795073942327),
        (9, 14, 1795073974295, 1795073975164, 1795073981899),
    ],
}


def summarize_log(path):
    replies = []
    misses = []
    for line in path.read_text().splitlines():
        if match := REPLY.search(line):
            replies.append((line[1:20] + "Z", *match.groups()))
        if match := MISS.search(line):
            misses.append((line[1:20] + "Z", *match.groups()))
    # These archives have one submission per (second, actor, addressee) for each
    # match. Keep any unpaired notice separate for authority-side inspection.
    matched = [row for row in misses if row in replies]
    print(f"{len(matched)}/{len(replies)}")
    for row in misses:
        print("  ", " | ".join(row), "" if row in replies else "(unpaired notice)")


def summarize_positions(path, cases):
    frames = []
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["table"] == "body":
                frames.append((row["t"], {body["id"]: body for body in row["rows"]}))
    for actor, addressee, heard, ready, submitted in cases:
        print(f"  {actor} → {addressee}: heard {heard}, ready {ready}, submitted {submitted}")
        for at in (heard, ready, submitted):
            eligible = [(t, bodies) for t, bodies in frames if actor in bodies and addressee in bodies]
            lower = max((frame for frame in eligible if frame[0] <= at), key=lambda frame: frame[0])
            upper = min((frame for frame in eligible if frame[0] >= at), key=lambda frame: frame[0])
            samples = []
            for t, bodies in (lower, upper):
                start, end = bodies[actor], bodies[addressee]
                distance = math.hypot(start["x"] - end["x"], start["y"] - end["y"])
                samples.append(f"{t - at:+} ms: {distance:.2f} m")
            print(f"    {at}: " + ", ".join(samples))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incoming", type=Path)
    parser.add_argument("--staged-log", type=Path)
    args = parser.parse_args()
    missed = args.incoming / "missed-replies"
    paths = {
        "play-test 8": args.incoming / "playtest-8/session/recording/mind.log",
        "play-test 9": missed / "playtest-9/session/launcher-session/mind.log",
        "play-test 10 launch": next((missed / "playtest-10-launch/run/sessions").glob("*/mind.log")),
    }
    if args.staged_log:
        paths["bystanders-2 staged"] = args.staged_log
    for name, path in paths.items():
        print(f"{name}:", end=" ")
        summarize_log(path)
        if name in CASES:
            summarize_positions(path.parent / "capture/authority.jsonl", CASES[name])


if __name__ == "__main__":
    main()
