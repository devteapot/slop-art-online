#!/usr/bin/env python3
"""A walker with stale gate memory must reach town by another entrance."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "living/tools"))
import nav_arena  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="fresh verify-core scratch world with the island seed")
    args = parser.parse_args()
    world = nav_arena.World(args.run)
    world.road = float(world.law_value("road_speed"))
    world.unknown = float(world.law_value("unknown_cost"))
    world.light = None
    out = world.s.out / "closed-gate"
    try:
        walks = nav_arena.n2(world, out, "b", "on", "body", 1)
        phase = json.loads((out / "n2-b-on-body" / "phase.json").read_text())
        checks = {
            "warmup_crossed_twice": phase["warmups_arrived"] == phase["warmups"] == 2,
            "gate_physically_closed": phase["gate_a_shut_at_test_start"] is True,
            "walker_remembered_open_gate": 1 in phase["remembered_a_states_at_order"][str(walks[0]["subject"])],
            "walker_reached_town": walks[0]["outcome"] == "arrived",
        }
        (out / "results.json").write_text(json.dumps(checks, indent=2) + "\n")
        for name, ok in checks.items():
            print(f"{'PASS' if ok else 'FAIL'} {name}")
        return 0 if all(checks.values()) else 1
    finally:
        world.law("nav_belief", False)


if __name__ == "__main__":
    sys.exit(main())
