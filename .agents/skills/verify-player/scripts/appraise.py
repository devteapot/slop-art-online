#!/usr/bin/env python3
"""What one player perceives of another character: the `perceived_of` projection
(docs/PERCEPTION.md, "What an observer perceives of a target").

Two player identities (the run's player, the appraiser, and a second one, the bystander) stand
by a resident. Each reads the resident through its own `seen_characters` view: a label, not the
name, and health as a band. The appraiser uses `appraise` (a skill declared in skills.rhai, run
through `human_act` like any act) and sees the resident's exact health for the reveal's 20 s; the
bystander, beside it, still sees a band. Then the reveal ends. Last, the appraiser says its own
name and the bystander, who heard it, perceives the appraiser by name from then on.

    appraise.py --run RUN

Needs `verify.py launch --run RUN --seed island` (best with LIVING_PERCEPTION=scoped, so the
views are the only way in); joins both players if needed. Admin `place_at` sets the scene.
Writes `RUN/appraise.json`. Python standard library only.
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

RESULTS = []


class P:
    def __init__(self, run):
        self.st = V.load(run)
        self.db = self.st["db"]
        self.admin = V.admin_token()
        for key in ("token", "token2"):
            if not self.st.get(key):
                code, body = V.http("/v1/identity", {})
                j = json.loads(body)
                self.st[key] = j["token"]
                self.st["identity" if key == "token" else "identity2"] = j["identity"]
                V.save(self.st)

    def token(self, who):
        return {"admin": self.admin, "player": self.st["token"], "bystander": self.st["token2"]}[who]

    def sql(self, q, who="admin"):
        code, body = V.http(f"/v1/database/{self.db}/sql", q, self.token(who), raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, reducer, args, who="player"):
        code, body = V.http(f"/v1/database/{self.db}/call/{reducer}", args, self.token(who))
        V.log(self.st, f"call {reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}", sys.stderr)
        return code, body

    def me(self, who, name):
        mine = [c for c in self.sql("SELECT id, alive FROM my_characters", who) if c["alive"]]
        if not mine:
            self.call("join", [name], who)
            mine = [c for c in self.sql("SELECT id, alive FROM my_characters", who) if c["alive"]]
        return mine[0]["id"]

    def seen(self, who, id):
        rows = [r for r in self.sql("SELECT * FROM seen_characters", who) if r["id"] == id]
        return rows[0] if rows else None


def check(p, name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    V.log(p.st, f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


def wait_for(fn, secs=8.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        r = fn()
        if r:
            return r
        time.sleep(0.4)
    return fn()


def resident(p, exclude):
    """A grown resident in the open (not under a roof), standing still."""
    ppl = {c["id"]: c for c in p.sql("SELECT id, name, stage, alive FROM character WHERE kind = 'person'") if c["alive"] and c["stage"] >= 2 and c["id"] not in exclude}
    for b in p.sql("SELECT id, x, y, next_ms FROM body"):
        if b["id"] in ppl and b["next_ms"] > 10**18:
            return {"id": b["id"], "name": ppl[b["id"]]["name"], "at": (b["x"], b["y"])}
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = P(a.run)
    me = p.me("player", "Appraiser")
    other = p.me("bystander", "Onlooker")
    my_name = p.sql(f"SELECT name FROM character WHERE id = {me}")[0]["name"]
    r = wait_for(lambda: resident(p, {me, other}), 60)
    if not r:
        check(p, "a resident stands still", False, "none found within 60 s")
        return finish(p)
    x, y = r["at"]
    # Hold the resident (a short wait) and set the scene: both players within 3 m of it.
    p.call("set_behavior", [r["id"], json.dumps({"wait": 120})], "admin")
    p.call("place_at", [me, x + 2.0, y], "admin")
    p.call("place_at", [other, x - 2.0, y], "admin")
    p.call("grant_items", [r["id"], "berries", 1], "admin")

    # 1. Before: a stranger with a health band, to both.
    a0 = wait_for(lambda: p.seen("player", r["id"]), 4)
    b0 = wait_for(lambda: p.seen("bystander", r["id"]), 4)
    check(p, "the resident is perceived by its label, not its name, by a newcomer", a0 and a0["name"] == "" and a0["label"] != r["name"] and b0 and b0["name"] == "", f"appraiser {a0}; bystander {b0}")
    check(p, "health is a band, no exact value, before appraising", a0 and a0["band"] <= 4 and a0["hp"] < 0 and b0 and b0["hp"] < 0, f"band {a0 and a0['band']}, hp {a0 and a0['hp']}")
    check(p, "seen_characters carries no controller, home or parents", a0 and not {"controller", "home_x", "home_y", "parent_a", "ai"} & set(a0), f"columns {sorted(a0) if a0 else None}")

    # 2. Appraise: exact health to the appraiser, a band to the bystander.
    since = int(time.time() * 1000)
    code, body = p.call("human_act", [json.dumps({"do": "appraise", "target": {"id": r["id"]}})])
    use = wait_for(lambda: next((u for u in p.sql(f"SELECT * FROM skill_use WHERE actor = {me}") if u["skill"] == "appraise" and u["at_ms"] >= since and u["outcome"]), None), 6)
    check(p, "human_act appraise is accepted and carried out (skill_use outcome)", code == 200 and use and "health" in use["outcome"], f"{code} {use}")
    truth = p.sql(f"SELECT max_hp FROM vitals WHERE id = {r['id']}")[0]["max_hp"]
    a1 = wait_for(lambda: (lambda s: s if s and s["hp"] >= 0 else None)(p.seen("player", r["id"])), 3)
    b1 = p.seen("bystander", r["id"])
    check(p, "the appraiser sees the resident's exact health", a1 and a1["hp"] >= 0 and abs(a1["max_hp"] - round(truth)) < 1, f"appraiser {a1 and (a1['hp'], a1['max_hp'])}; vitals max {truth}")
    check(p, "the bystander does not", b1 and b1["hp"] < 0 and b1["band"] <= 4, f"bystander {b1 and (b1['hp'], b1['band'])}")
    told = [e["text"] for e in p.sql("SELECT text, at_ms, kind FROM my_experience", "player") if e["kind"] == "appraise" and e["at_ms"] >= since]
    check(p, "the appraiser perceives what the look showed (an experience)", any("of" in t and "health" in t for t in told), f"{told}")

    # 3. The reveal ends.
    a2 = wait_for(lambda: (lambda s: s if s and s["hp"] < 0 else None)(p.seen("player", r["id"])), 26)
    check(p, "after the reveal's 20 s the appraiser sees a band again", a2 and a2["hp"] < 0, f"{a2 and (a2['hp'], a2['band'])}")

    # 4. An introduction: the bystander hears the appraiser's name and perceives it by name.
    n0 = p.seen("bystander", me)
    p.call("human_say", [f"Hello, I am {my_name}.", 0])
    n1 = wait_for(lambda: (lambda s: s if s and s["name"] == my_name else None)(p.seen("bystander", me)), 4)
    check(p, "a name said by its owner is known to who heard it", n0 and n0["name"] == "" and n1 and n1["label"] == my_name, f"before {n0 and n0['label']}; after {n1 and n1['label']}")
    heard = [e["text"] for e in p.sql("SELECT text, kind FROM my_experience", "bystander") if e["kind"] == "speech"]
    check(p, "the bystander's experience names the speaker", any(t.startswith(f"{my_name} said") for t in heard), f"{heard[-2:]}")
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "appraise.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
