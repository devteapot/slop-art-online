#!/usr/bin/env python3
"""Track the wall clock and judged sheets for one capped head session."""

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time


def finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError("expected a finite number")
    return value


def rules(state, now):
    scores = [entry["score"] for entry in state["scores"]]
    elapsed = now - state["started_at"]
    return {
        "wall clock limit reached": elapsed >= state["hours"] * 3600,
        "iteration limit reached": len(scores) >= state["max_iters"],
        "no gain on the last two sheets": len(scores) >= 3
        and max(scores[-2:]) <= max(scores[:-2]),
    }


def save(path, state):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temp:
        name = Path(temp.name)
        try:
            json.dump(state, temp, indent=2, allow_nan=False)
            temp.write("\n")
            temp.close()
            os.replace(name, path)
        finally:
            name.unlink(missing_ok=True)


def run(args, now):
    if args.command == "start":
        if args.hours <= 0 or args.max_iters <= 0:
            raise ValueError("hours and max-iters must be positive")
        args.dir.mkdir(parents=True, exist_ok=True)
    path = args.dir / "session.json"
    if args.command != "start" and not path.is_file():
        raise ValueError(f"no session at {path}; run start first")
    with (args.dir / "session.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "start":
            if path.exists():
                raise ValueError(f"session already started at {path}")
            save(path, dict(started_at=now, hours=args.hours, max_iters=args.max_iters, scores=[]))
            print(f"Started session at {path}")
            return 0

        state = json.loads(path.read_text())
        active = rules(state, now)
        if args.command == "status":
            scores = [entry["score"] for entry in state["scores"]]
            print(f"Elapsed: {now - state['started_at']:.1f}s / {state['hours']:g}h")
            print(f"Iterations: {len(scores)} / {state['max_iters']}")
            print(f"Scores: {scores}")
            print(f"Best score: {max(scores) if scores else 'none'}")
            for rule, fired in active.items():
                print(f"{rule}: {'stop' if fired else 'clear'}")
            return 0

        if args.command == "record":
            # A sheet started in time can finish after the clock limit.
            active.pop("wall clock limit reached")
        stopped = [rule for rule, fired in active.items() if fired]
        if stopped:
            print("Stop: " + ", ".join(stopped), file=sys.stderr)
            return 1
        if args.command == "record":
            state["scores"].append(dict(score=args.score, note=args.note, recorded_at=now))
            save(path, state)
            print(f"Recorded iteration {len(state['scores'])}: {args.score:g}")
        else:
            print("Session may continue")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "check", "record", "status"):
        sub = commands.add_parser(command)
        sub.add_argument("--dir", required=True, type=Path)
        sub.add_argument("--now", type=finite, help="override Unix time for a dry run")
        if command == "start":
            sub.add_argument("--hours", type=finite, default=2)
            sub.add_argument("--max-iters", type=int, default=6)
        if command == "record":
            sub.add_argument("--score", type=finite, required=True)
            sub.add_argument("--note", default="")
    args = parser.parse_args()
    try:
        return run(args, time.time() if args.now is None else args.now)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"session_guard: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
