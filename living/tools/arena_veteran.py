#!/usr/bin/env python3
"""Write R3's trial files (docs/COMBAT_MIND.md §5.4) from `living/trials/arena-heavy.json`, so
the heavy-blow fixture stays the one R2 measured, byte for byte:

    living/tools/arena_veteran.py            # writes the three files
    living/tools/arena_veteran.py --check    # fails when the files differ from what it would write

- `arena-veteran-same`: the fixture A meets the subject four times over two world days, by day,
  then a fifth time;
- `arena-veteran-new`: the same four meetings with A, then B, a different person with the same
  pattern;
- `arena-fresh`: the same 30 minutes of life without A's meetings, then B;
- `arena-heavy-r2fov`, `arena-kiter-r2fov`: R2's arenas as they are, with 5 Hz facing samples
  (`record.bodies`) for the windup-seen estimate.

A world hour is 30 real seconds and day is 06:00–20:00 (the shipped `night_hours`), so a meeting
is 2 real minutes (4 world hours) and the last 3. Each meeting sets the subject and its fixture to
full health (`vitals`, the admin reducer `admin_set_vitals`: R3's fake run lost its subject in the
second meeting, mending being far slower than a meeting's blows), places its fixture 6 m from the
subject, gives it the heavy-blow graph and lets it walk back to the subject (arena-heavy's own
re-approach trigger, bounded by `after_min` and `before_min`). At its end the fixture is set
to wait and placed 60 m off, whatever anyone's health. Nothing here is installed into any
character: a fixture is a resident whose graph the trial sets (§4.1).
"""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIALS = ROOT / "living/trials"

MEETING_MIN = 2.0
LAST_MIN = 3.0
# (minute, world time): the world starts at 10:00 on day 1; 2 world hours a real minute.
A_MEETINGS = [(1.0, "day 1 12:00"), (11.0, "day 2 08:00"), (14.0, "day 2 14:00"), (23.0, "day 3 08:00")]
LAST = (26.0, "day 3 14:00")
MINUTES = 30
AWAY = [60, 0]


def heavy():
    base = json.loads((TRIALS / "arena-heavy.json").read_text())
    fixture = next(s["graph"] for e in base["timeline"] if e.get("at") == 1 for s in e["steps"] if s.get("do") == "graph")
    approach = next(e for e in base["timeline"] if e.get("when"))
    setup = [e for e in base["timeline"] if e.get("at") in ("prepare", "start")]
    return base, fixture, approach, setup


def meeting(role, label, start, length, fixture, approach, k):
    """The steps of one meeting of `role` with the subject, and its bounded re-approach."""
    begin = {"at": start, "steps": [
        # Every meeting starts at full health, the subject's and the fixture's (`admin_set_vitals`,
        # an admin event in the run record): mending between meetings is far slower than a
        # meeting's blows, and a fixture the subject killed would miss its later meetings.
        {"do": "vitals", "who": "subject", "hp": "max"},
        {"do": "vitals", "who": role, "hp": "max"},
        {"do": "place", "who": role, "to": {"who": "subject", "offset": [6, 0]}},
        {"do": "note", "text": f"meeting {k}: {role} ({label})"},
        {"do": "graph", "who": role, "graph": copy.deepcopy(fixture)},
    ]}
    walk = copy.deepcopy(approach)
    walk["when"]["near"]["who"] = role
    walk["after_min"] = start + 0.05
    walk["before_min"] = start + length
    for s in walk["steps"]:
        s["who"] = role
    end = {"at": start + length, "steps": [
        {"do": "graph", "who": role, "graph": {"wait": 600}},
        {"do": "place", "who": role, "to": {"who": "subject", "offset": AWAY}},
        {"do": "note", "text": f"meeting {k} ends: {role}"},
    ]}
    return [begin, walk, end]


def build(arm):
    base, fixture, approach, setup = heavy()
    t = {k: v for k, v in base.items() if k not in ("timeline", "title", "about", "minutes", "budget", "cast")}
    roles = {"foe": copy.deepcopy(base["cast"]["foe"])}
    if arm != "same":
        roles["foe_b"] = copy.deepcopy(base["cast"]["foe"])
    timeline = copy.deepcopy(setup)
    # The second fixture is given what the first is (a spear, wound tending), kept off and still.
    if "foe_b" in roles:
        for e in setup:
            if e.get("who") == "foe":
                b = copy.deepcopy(e)
                b["who"] = "foe_b"
                if b.get("do") == "place":
                    b["to"] = {"who": "subject", "offset": [AWAY[0], 20]}
                timeline.append(b)
    # A fixture between its meetings (and B until its own) stands still: a trial fixture lives no
    # life of its own in an arena.
    for role in roles:
        timeline.append({"at": "start", "do": "graph", "who": role, "graph": {"wait": 1800}})
    k = 0
    if arm != "fresh":
        for start, label in A_MEETINGS:
            k += 1
            timeline += meeting("foe", label, start, MEETING_MIN, fixture, approach, k)
    last_role = "foe" if arm == "same" else "foe_b"
    timeline += meeting(last_role, LAST[1], LAST[0], LAST_MIN, fixture, approach, k + 1)
    what = {
        "same": "A meets the subject four times over two world days (day 1 12:00, day 2 08:00 and 14:00, day 3 08:00; 2 minutes each), then a fifth time (day 3 14:00, 3 minutes)",
        "new": "A meets the subject four times over two world days (day 1 12:00, day 2 08:00 and 14:00, day 3 08:00; 2 minutes each), then B, a different person with the same pattern (day 3 14:00, 3 minutes)",
        "fresh": "the subject lives the same 30 minutes without A's meetings, then meets B (day 3 14:00, 3 minutes)",
    }[arm]
    t = {
        "title": {"same": "Arena R3: a veteran meets A again", "new": "Arena R3: a veteran meets B", "fresh": "Arena R3: a fresh subject meets B"}[arm],
        "about": f"R3 (docs/COMBAT_MIND.md §5.4), written by living/tools/arena_veteran.py from arena-heavy (the same fixture graph): {what}. "
                 "Each meeting places the fixture 6 m from the subject with arena-heavy's heavy-blow graph and lets it walk back to the subject while the meeting lasts; at its end it waits, 60 m off. "
                 "The fixture is a trial fixture, never game content: nothing here is installed into any character, and the subject's mind is told nothing about it. Subject, kit and world as arena-heavy.",
        **t,
        "record": {**base.get("record", {}), "bodies": {"hz": 5}},
        "minutes": MINUTES,
        "budget": {"tokens": 2_500_000},
        "cast": roles,
        "arena": {"pattern": "attack", "foes": list(roles)},
        "timeline": timeline,
    }
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    bad = []
    files = {name: build(arm) for arm, name in (("same", "arena-veteran-same"), ("new", "arena-veteran-new"), ("fresh", "arena-fresh"))}
    # R2-fov: r2e's two arenas unchanged but for 5 Hz facing samples (`record.bodies`), which the
    # windup-seen estimate reads (arena_report.py).
    for base in ("arena-heavy", "arena-kiter"):
        files[f"{base}-r2fov"] = {"extends": base, "title": f"{json.loads((TRIALS / f'{base}.json').read_text())['title']} (R2-fov)",
                                  "about": f"`{base}` as r2e ran it, with 5 Hz facing samples for the windup-seen estimate (docs/COMBAT_MIND.md §5.4, R2-fov); written by living/tools/arena_veteran.py.",
                                  "record": {"bodies": {"hz": 5}}}
    for name, t in files.items():
        text = json.dumps(t, indent=1, ensure_ascii=False) + "\n"
        path = TRIALS / f"{name}.json"
        if a.check:
            if not path.exists() or path.read_text() != text:
                bad.append(name)
        else:
            path.write_text(text)
            print(path.relative_to(ROOT))
    if bad:
        print("differs from arena_veteran.py's output: " + ", ".join(bad), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
