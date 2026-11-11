#!/usr/bin/env python3
"""A player speaks through `human_say` and `human_speak` in each way of speaking the world's
rules list (`speech_card`), is refused in the world's words, and reads who heard its lines in
`my_heard` (docs/COMMUNICATION.md).

- `human_say(text, to)` and `human_speak(text, to, "say")` (and `""`): spoken, a `said` row in
  the player's `my_experience`, a `my_heard` row joined to it by `line`, listing the resident
  beside it;
- refused: an unknown way ("no way of speaking called `shout`"), a second line within 2 s
  ("speaking too fast"); for each way on the card that needs someone (`needs_to`), a line to the
  room ("a <way> needs someone to <way> to"); for each way with a reach, a line to someone
  beyond it ("too far to <way>: step closer"); for each way with a gap beyond 2 s, a second line
  within it ("too soon to <way> again"). A refused line writes nothing.

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

    def refused(label, args, words):
        before = len(said_since(t0))
        code, body = call("human_speak", args, me_token)
        time.sleep(0.5)
        ok = code != 200 and words in body and len(said_since(t0)) == before
        expect(f"refused: {label} ({words})", ok, body[:200])

    refused("an unknown way", ["verify speak: shout.", 0, "shout"], "no way of speaking called `shout`")
    call("human_speak", ["verify speak: quick one.", 0, "say"], me_token)
    # Its row reaches my_experience at the next frame; count after it, still within 2 s.
    time.sleep(0.8)
    refused("a second line within 2 s", ["verify speak: quick two.", 0, "say"], "speaking too fast")
    time.sleep(2.6)
    for c in cards:
        way = c["name"]
        if c["needs_to"]:
            refused(f"a {way} to no one", ["verify speak: to no one.", 0, way], f"a {way} needs someone to {way} to")
            time.sleep(2.6)
        if c["reach_m"] > 0:
            call("place_at", [resident] + list(next((b["x"] + c["reach_m"] + 2.0, b["y"]) for b in sql(f"SELECT * FROM body WHERE id = {me}", admin))), admin)
            time.sleep(0.5)
            refused(f"a {way} beyond its reach", ["verify speak: too far.", resident, way], f"too far to {way}: step closer")
            call("place_near", [me, resident], admin)
            time.sleep(2.6)
        if c["gap_ms"] > 2000:
            code, body = call("human_speak", ["verify speak: once.", resident if c["needs_to"] else 0, way], me_token)
            expect(f"a {way} is spoken", code == 200, body[:200])
            time.sleep(2.6)
            refused(f"a second {way} within {c['gap_ms'] / 1000:g} s", ["verify speak: twice.", resident if c["needs_to"] else 0, way], f"too soon to {way} again")
            time.sleep(c["gap_ms"] / 1000)
    out = Path(V.run_dir(a.run)) / "speak.json"
    out.write_text(json.dumps({"db": db, "me": me, "resident": resident, "cards": cards, "checks": checks}, indent=2) + "\n")
    print(out)
    return 0 if all(c["passed"] for c in checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
