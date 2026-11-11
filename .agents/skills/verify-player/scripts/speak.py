#!/usr/bin/env python3
"""A player speaks through `human_say` and `human_speak` in each way of speaking the world's
rules list (`speech_card`), is refused in the world's words, and reads who heard its lines in
`my_heard` (docs/COMMUNICATION.md).

- `human_say(text, to)` and `human_speak(text, to, "say")` (and `""`): spoken, a `said` row in
  the player's `my_experience`, a `my_heard` row joined to it by `line`, listing the resident
  beside it;
- refused by the engine: an unknown way ("no way of speaking called `shout`"), a second line
  within 2 s ("speaking too fast");
- refused by the way's own rules: for each way on the card that needs someone (`needs_to`), a
  line to the room; for each way with a reach, a line to someone beyond it; for each way with a
  gap beyond 2 s, a second line within it. The words are the script's `<way>_check`: the
  reducer's error must be exactly what that check says on the same facts, run outside the
  authority the way a client runs it before sending (`living-rules` example `way_check`, the
  installed script, `speech::check_way`). A refused line writes nothing.

    speak.py --run RUN

Needs `verify.py launch --run RUN` on a seed with AI people. Admin reducers set the scene only:
`place_near`, `place_at`, `set_behavior`. Writes `RUN/speak.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    st = V.load(a.run)
    db = st["db"]
    admin = V.admin_token()
    if not st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        st["token"], st["identity"] = j["token"], j["identity"]
        V.save(st)
    me_token = st["token"]

    def sql(q, token):
        code, body = V.http(f"/v1/database/{db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(reducer, args, token):
        code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, token)
        V.log(st, f"{reducer}{json.dumps(args)} -> {code} {body.strip()[:200]}")
        return code, body

    checks = {}

    def expect(name, ok, detail=None):
        checks[name] = {"passed": bool(ok), "detail": detail}
        print(("PASS " if ok else "FAIL ") + name, flush=True)

    if not sql("SELECT * FROM my_characters", me_token):
        call("join", ["Speaker"], me_token)
    me = sql("SELECT * FROM my_characters", me_token)[0]["id"]
    world = sql("SELECT * FROM world", admin)[0]
    resident = next(c for c in sql("SELECT * FROM character WHERE kind = 'person'", admin) if c["ai"] and c["alive"] and c["stage"] == 2 and c["controller"] == world["admin"])["id"]
    call("set_behavior", [resident, json.dumps({"wait": 120})], admin)
    call("place_near", [me, resident], admin)
    time.sleep(1)
    cards = sql("SELECT * FROM speech_card", None)
    expect("speech_card is readable without an identity", any(c["name"] == "say" for c in cards), [c["name"] for c in cards])

    def said_since(t):
        return sorted((r for r in sql("SELECT * FROM my_experience", me_token) if r["kind"] == "said" and r["at_ms"] >= t), key=lambda r: r["id"])

    t0 = sql("SELECT last_ms FROM clock", admin)[0]["last_ms"]
    spoken = []
    for label, reducer, args in (("human_say", "human_say", ["verify speak: say.", resident]),
                                 ("human_speak say", "human_speak", ["verify speak: speak.", resident, "say"]),
                                 ("human_speak with no way", "human_speak", ["verify speak: no way.", 0, ""])):
        code, body = call(reducer, args, me_token)
        expect(f"{label} is spoken", code == 200, body[:200])
        spoken.append(args[0])
        time.sleep(2.6)
    time.sleep(1.5)
    mine = said_since(t0)
    expect("each line is a `said` row in my_experience", [r["text"].split("“")[-1].rstrip("”") for r in mine] == spoken, [r["text"] for r in mine])
    heard = {h["line"]: h for h in sql("SELECT * FROM my_heard", me_token)}
    expect("my_heard has a row per line, joined by `line`, listing the resident beside me",
           all(r["id"] in heard and resident in heard[r["id"]]["hearers"] and heard[r["id"]]["way"] == "say" for r in mine), list(heard.values())[-3:])

    def refused(label, args, words, exact=False):
        before = len(said_since(t0))
        code, body = call("human_speak", args, me_token)
        time.sleep(0.5)
        ok = code != 200 and (body.strip() == words if exact else words in body) and len(said_since(t0)) == before
        expect(f"refused: {label} ({words})", ok, body[:200])

    # The way's check as a client runs it: the installed script, the same context builder.
    import os, subprocess
    target = Path(os.environ.get("CARGO_TARGET_DIR") or V.LIVING / "target")
    subprocess.run(["cargo", "build", "-q", "-p", "living-rules", "--example", "way_check"], cwd=V.LIVING, check=True)
    script = Path(V.run_dir(a.run)) / "speak-script.rhai"
    script.write_text(sql("SELECT source FROM script WHERE name = 'skills'", admin)[0]["source"])
    day_ms = world["day_ms"]

    def client_check(facts):
        out = subprocess.run([str(target / "debug/examples/way_check"), str(script), str(day_ms), json.dumps(facts)], capture_output=True, text=True, check=True).stdout
        return json.loads(out)["refused"]

    def body_of(who):
        return next(b for b in sql(f"SELECT * FROM body WHERE id = {who}", admin))

    refused("an unknown way", ["verify speak: shout.", 0, "shout"], "no way of speaking called `shout`")
    call("human_speak", ["verify speak: quick one.", 0, "say"], me_token)
    # Its row reaches my_experience at the next frame; count after it, still within 2 s.
    time.sleep(0.8)
    refused("a second line within 2 s", ["verify speak: quick two.", 0, "say"], "speaking too fast")
    time.sleep(2.6)
    for c in cards:
        way = c["name"]
        if c["needs_to"]:
            words = client_check({"way": way, "text": "verify speak: to no one.", "to": None})
            expect(f"the client's check refuses a {way} to no one", words, words)
            refused(f"a {way} to no one, in its check's words", ["verify speak: to no one.", 0, way], words or "?", exact=True)
            time.sleep(2.6)
        if c["reach_m"] > 0:
            mine = body_of(me)
            call("place_at", [resident, mine["x"] + c["reach_m"] + 2.0, mine["y"]], admin)
            time.sleep(0.5)
            there = body_of(resident)
            dist = ((there["x"] - mine["x"]) ** 2 + (there["y"] - mine["y"]) ** 2) ** 0.5
            words = client_check({"way": way, "text": "verify speak: too far.", "to": {"id": resident, "alive": True, "dist": dist}})
            expect(f"the client's check refuses a {way} {dist:.1f} m away", words, words)
            refused(f"a {way} beyond its reach, in its check's words", ["verify speak: too far.", resident, way], words or "?", exact=True)
            call("place_near", [me, resident], admin)
            time.sleep(2.6)
        if c["gap_ms"] > 2000:
            code, body = call("human_speak", ["verify speak: once.", resident if c["needs_to"] else 0, way], me_token)
            expect(f"a {way} is spoken", code == 200, body[:200])
            # Past the 2 s limit, well inside the way's gap: send at once, then ask the client's
            # check about the same moment (the first line's time from my_heard).
            time.sleep(2.2)
            sent = int(time.time() * 1000)
            before = len(said_since(t0))
            code, body = call("human_speak", ["verify speak: twice.", resident if c["needs_to"] else 0, way], me_token)
            time.sleep(0.5)
            last = max(h["at_ms"] for h in sql("SELECT * FROM my_heard", me_token) if h["way"] == way and h["at_ms"] < sent)
            words = client_check({"way": way, "text": "verify speak: twice.", "to": None, "since_ms": sent - last})
            expect(f"the client's check refuses a second {way} {sent - last} ms after the first", words, words)
            expect(f"refused: a second {way} within {c['gap_ms'] / 1000:g} s, in its check's words ({words})",
                   code != 200 and body.strip() == words and len(said_since(t0)) == before, body[:200])
            time.sleep(c["gap_ms"] / 1000)
    out = Path(V.run_dir(a.run)) / "speak.json"
    out.write_text(json.dumps({"db": db, "me": me, "resident": resident, "cards": cards, "checks": checks}, indent=2) + "\n")
    print(out)
    return 0 if all(c["passed"] for c in checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
