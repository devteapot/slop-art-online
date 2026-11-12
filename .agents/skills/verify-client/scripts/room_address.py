#!/usr/bin/env python3
"""How a line to the room was said, as a real client receives it (speech-address).

    room_address.py --run client-...      (a run launched with verify.py launch, any seed)

The player joins (its own identity). The admin spawns two minded strangers, K and S, holds them
still and places them beside the player. S says to the room a line naming K and the player
(admin `mind_say`): the player's own speech row (`my_experience`, read through the Rust SDK
probe) reads "A stranger said to the room, naming a stranger and you: …", with no name the player
does not know. K then tells its name ("I'm K."), and S says to the room a line naming K: the row
now reads "naming <K>". Then S says a line to K and a line to the room: "while talking with <K>".
Admin calls (`spawn_crowd`, `set_behavior`, `place_at`, `mind_say`) set the scene; they are not
something a player can do. Writes `RUN/address-*.jsonl` and `RUN/room_address.json`. Python
standard library only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V = ROOT / ".agents/skills/verify/scripts/verify.py"
DRIVE = ROOT / ".agents/skills/verify-client/scripts/drive.py"
THOUGHT = {"kind": "talk", "summary": "verify-client room-address line", "detail": "", "latency_ms": 0, "tokens": 0, "model": "", "reference": ""}


def run(*args, check=True):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-400:] or r.stdout[-400:]}")
    return r.stdout


def sql(rid, query, *flags):
    out = run(V, "sql", "--run", rid, query, *flags)
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def call(rid, reducer, args):
    run(V, "call", "--run", rid, reducer, json.dumps(args), "--as-admin")


def speech_rows(rid, name, me, speaker):
    """The player's speech rows from `speaker`, through the SDK probe."""
    run(DRIVE, "--run", rid, "--query", f"SELECT * FROM my_experience WHERE observer = {me}", "--as-player", "--seconds", 4, "--save", name)
    rows = {}
    for line in (ROOT / ".local/living/verify" / rid / f"{name}.jsonl").read_text().splitlines():
        ev = json.loads(line)
        for r in (ev.get("tables") or {}).get("my_experience", []):
            if isinstance(r, dict) and r.get("kind") == "speech" and r.get("subject") == speaker:
                rows[r["id"]] = r["text"]
    return [rows[k] for k in sorted(rows)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    out = ROOT / ".local/living/verify" / rid
    run(V, "player", "--run", rid, "join", "Mara Quill")
    me = sql(rid, "SELECT * FROM my_characters", "--as-player")[0]["id"]
    before = {c["id"] for c in sql(rid, "SELECT id FROM character")}
    call(rid, "spawn_crowd", [2, True])
    k, s = sorted(c["id"] for c in sql(rid, "SELECT id FROM character") if c["id"] not in before)
    names = {c["id"]: c["name"] for c in sql(rid, "SELECT id, name FROM character")}
    kn = names[k]
    for x in (k, s):
        call(rid, "set_behavior", [x, json.dumps({"wait": 300})])
    body = sql(rid, "SELECT * FROM my_body", "--as-player")[0]
    call(rid, "place_at", [k, body["x"] + 1.5, body["y"]])
    call(rid, "place_at", [s, body["x"] - 1.5, body["y"]])
    time.sleep(2)
    say = lambda who, text, to: (call(rid, "mind_say", [who, text, to, "say", 0, THOUGHT]), time.sleep(2.6))
    say(s, f"{kn.split()[0]}! Mara! Come and look at this.", 0)
    say(k, f"I'm {kn}.", 0)
    say(s, f"{kn.split()[0]}, the tide is turning.", 0)
    say(s, f"Good morning, {kn.split()[0]}.", k)
    say(s, "Has anyone seen the cart?", 0)
    rows = speech_rows(rid, "address-seen", me, s)
    first = next((t for t in rows if "Come and look" in t), "")
    known = next((t for t in rows if "tide is turning" in t), "")
    talking = next((t for t in rows if "seen the cart" in t), "")
    checks = {
        "unknown named is a stranger, the player is you": first.startswith("A stranger said to the room, naming a stranger and you:"),
        "no name the player does not know before the words": kn not in first.split("“")[0],
        "once introduced, K is named": known.startswith(f"A stranger said to the room, naming {kn}:"),
        "while talking with K": talking.startswith(f"A stranger said to the room while talking with {kn}:"),
    }
    (out / "room_address.json").write_text(json.dumps({"player": me, "k": kn, "rows": rows, "checks": checks}, indent=1, ensure_ascii=False) + "\n")
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
