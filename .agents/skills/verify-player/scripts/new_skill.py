#!/usr/bin/env python3
"""A skill added only in the script is everyone's (docs/WORLD_RULES.md).

Installs the tree's skills.rhai with a throwaway `whittle` appended (its spec and rules, no
Rust change, the same authority module), then: the player does it with `human_act`; a scene
walker does it as a behaviour graph leaf (`set_behavior`) and as a deliberate act (`mind_act`,
as a mind decides). Each takes a wood and is recorded as the act's outcome. Without the spec an
install is refused. The tree's script is installed again at the end.

    new_skill.py --run RUN

Needs `verify.py launch --run RUN`; joins a player if the run has none. Writes
`RUN/new_skill.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gesture", HERE / "gesture.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
V = G.V
RESULTS = G.RESULTS
check, wait_for, now_ms = G.check, G.wait_for, G.now_ms
SKILLS = (HERE.parents[3] / "living/scripts/skills.rhai").read_text()
WHITTLE = '''
fn whittle_spec() { #{ item: true, items: ["wood"], about: "Carve a piece of wood while you sit (a test skill).", takes: "1 wood", gives: "shavings" } }
fn whittle_check(a) { if inv(a, "wood") < 1 { return "no wood to whittle"; } "" }
fn whittle_duration(a) { 1500 }
fn whittle_done(a) { [#{ op: "remove", item: "wood", qty: 1 }] }
'''


def wood(p, who):
    return next((r["qty"] for r in p.sql(f"SELECT item, qty FROM inventory WHERE owner = {who}") if r["item"] == "wood"), 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = G.P(a.run)
    if not p.st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        p.st["token"], p.st["identity"] = j["token"], j["identity"]
        V.save(p.st)
    alive = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not alive:
        p.call("join", ["Wren"])
        alive = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = alive[0]["id"]
    bare = SKILLS + "\n" + "\n".join(l for l in WHITTLE.splitlines() if "whittle_spec" not in l)
    code, body = p.call("install_script", [bare], "admin")
    check(p, "rules without the skill's spec are refused at install", code != 200 and "whittle_spec" in body, f"{code} {body[:160]}")
    code, body = p.call("install_script", [SKILLS + "\n" + WHITTLE], "admin")
    check(p, "the script with the new skill installs (no Rust change, same module)", code == 200, f"{code} {body[:160]}")
    before = {c["id"] for c in p.sql("SELECT id FROM character")}
    p.call("spawn_crowd", [1, True], "admin")
    walker = next(c["id"] for c in p.sql("SELECT id FROM character") if c["id"] not in before)
    for who in (me, walker):
        p.call("grant_items", [who, "wood", 3], "admin")

    # The player, through the act path the client uses.
    since = now_ms()
    p.act({"do": "whittle", "item": "wood"})
    done = wait_for(lambda: [t for t in p.told(me, since) if "whittle wood" in t and "did what you had decided" in t], 10)
    check(p, "a player does it with human_act", done and wood(p, me) == 2, f"{done}; wood {wood(p, me)}")
    # A behaviour graph leaf.
    p.call("set_behavior", [walker, json.dumps({"seq": [{"do": {"skill": "whittle", "item": "wood"}}, {"wait": 120}]})], "admin")
    g = wait_for(lambda: wood(p, walker) == 2, 12)
    check(p, "a graph leaf does it", g, f"walker wood {wood(p, walker)}")
    # A deliberate act, as a mind decides it.
    since = now_ms()
    p.call("mind_act", [walker, [json.dumps({"do": "whittle", "item": "wood"})], "verify-player"], "admin")
    m = wait_for(lambda: [t for t in p.told(walker, since) if "whittle wood" in t], 12)
    check(p, "a mind's act does it", m and wood(p, walker) == 1, f"{m}; walker wood {wood(p, walker)}")
    code, _ = p.call("install_script", [SKILLS], "admin")
    check(p, "the tree's script is installed again", code == 200, f"{code}")
    (V.run_dir(p.st["run"]) / "new_skill.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
