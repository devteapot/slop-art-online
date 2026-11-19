#!/usr/bin/env python3
"""Public-feed scoping (docs/FEED_SCOPING.md) through a scratch authority, `--seed cullet`.

A body in Cullet's brush is hidden from a player outside the patch and from a mind standing with
it: not in the player's `my_things`, not noticed, not in the mind's pending scene. Seen from inside
the patch it is in all three and remembered by both; out of sight again it leaves `my_things` and
stays in `my_remembered_things`. A gate's state reaches the player only in sight: shut while the
player is away, its copy is absent and its memory keeps the old state; back in sight, the copy and
the memory read shut. The stage moves 0 -> 1 -> 2 through the laws (`feed_scope_grace_s` 1), and at
stage 2 the legacy public rows are empty while the owner reads the held ones.

Run on a fresh `core-feed-*` world on your own scratch server, after `verify.py player join`:

    python3 .agents/skills/verify-core/scripts/feed_scope.py --run core-feed-<stamp>
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify as v  # noqa: E402
from scenes import Scene  # noqa: E402

# Cullet's brush fixture (docs/COVER_SIGHT.md, "Client edits and scratch recipe"): a viewer outside
# the patch and a spot inside it.
OUTSIDE = (608.5, 479.5)
HIDDEN = (608.5, 472.5)
AWAY = (700.5, 560.5)


def opt(x):
    """An Option as SATS JSON gives it ({"some": v} / {"none": ...}, or [tag, v]) as v or None."""
    if isinstance(x, dict):
        return x.get("some") if "some" in x else None
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], int):
        return x[1] if x[0] == 0 else None
    return x


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", required=True)
    a = p.parse_args()
    if not a.run.startswith("core-feed-"):
        p.error("use a core-feed-* run")
    s = Scene(a.run, "feed_scope")
    st = v.load(a.run)
    db, player = st["db"], st.get("token")
    if not player:
        p.error("join the run's player first (verify.py player --run RUN join Viewer)")
    out = s.out / "feed-scope-proof.jsonl"

    def save(check, ok, data=None, fatal=True):
        with out.open("a") as f:
            f.write(json.dumps(dict(check=check, passed=bool(ok), data=data)) + "\n")
        s.expect(check, ok, data, fatal=fatal)

    def psql(query, token=player):
        code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
        if code != 200:
            return None
        res = json.loads(body)[-1]
        fields = [c["name"]["some"] for c in res["schema"]["elements"]]
        return [dict(zip(fields, r)) for r in res["rows"]]

    def settle(seconds=1.6):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v.http(f"/v1/database/{db}/call/human_move", [0.0, 0.0, False], player)
            time.sleep(0.25)

    def things():
        return {r["key"]: r for r in psql("SELECT * FROM my_things") or []}

    def remembered():
        return {r["key"]: r for r in psql("SELECT * FROM my_remembered_things") or []}

    def key(cls, i):
        return cls << 56 | i

    # The test is about cover: sight all round, as `cover.py` does; cover and brush on.
    for name, val in (("fov_on", "false"), ("gaze_on", "false"), ("cover_sight_on", "true"), ("cover_brush_on", "true")):
        s.call("set_world_law", name, val)
    hour = None
    w = s.rows("SELECT epoch_ms, day_ms FROM world")[0]
    now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    hour = ((now - w["epoch_ms"] + w["day_ms"] * 7 // 24) % w["day_ms"]) / w["day_ms"] * 24
    if not 7.5 <= hour < 17.0:
        wait_s = ((7.5 - hour) % 24) / 24 * w["day_ms"] / 1000
        print(f"waiting {wait_s:.0f} s for daylight (hour {hour:.1f})", flush=True)
        time.sleep(wait_s + 5)

    # ---- the stages ---------------------------------------------------------------------------
    save("stage 0 before the law", (psql("SELECT * FROM feed_scope", None) or [{"stage": 0}])[0]["stage"] == 0)
    legacy0 = len(s.rows("SELECT id FROM structure"))
    s.call("set_world_law", "feed_scope_grace_s", "1")
    s.call("set_world_law", "feed_scope_on", "true")
    s.wait(lambda: (psql("SELECT * FROM feed_scope", None) or [{}])[0].get("stage") == 1, 15, 0.2)
    save("stage 1 keeps the legacy feeds and writes the map", bool(psql("SELECT id FROM structure", None)) and bool(psql("SELECT id FROM map_structure", None)))
    s.wait(lambda: (psql("SELECT * FROM feed_scope", None) or [{}])[0].get("stage") == 2, 15, 0.2)
    held = s.rows("SELECT id, kind FROM structure_held", "held")
    save("stage 2: the legacy structure, gate and resource rows are empty, the owner reads the held rows",
         not s.rows("SELECT id FROM structure") and not s.rows("SELECT id FROM gate") and not s.rows("SELECT id FROM resource_node")
         and len(held) == legacy0 and bool(s.rows("SELECT id FROM gate_held")), {"legacy_before": legacy0, "held": len(held)})
    kinds = {r["kind"] for r in psql("SELECT kind FROM map_structure", None)}
    save("the public map holds allowlisted architecture only", kinds and kinds <= {"shelter", "house", "hall", "workshop", "market", "inn", "smokehouse", "furnace", "gate"}, sorted(kinds))
    save("lots name no door structure at stage 2", all(r["structure"] == 0 for r in psql("SELECT structure FROM lot", None)))
    for table in ("structure_held", "gate_held", "resource_held", "thing_seen", "remembered_thing", "fuel_seen", "lot_door"):
        save(f"a player cannot select {table}", psql(f"SELECT * FROM {table}") is None)

    # ---- a body behind a hedge ----------------------------------------------------------------
    me = psql("SELECT id FROM my_characters")[0]["id"]
    victim, mind = s.people(2)
    s.graph(mind, {"wait": 600})
    s.call("place_at", victim, *HIDDEN)
    # Inside the patch, where the body can be seen: calibrated with the living victim first (the
    # same sight rule, through the player's own view).
    inside = None
    for dx, dy in ((0, 1.5), (1, 1), (-1, 1), (0, 2.5), (1, 0), (-1, 0), (0, -1.5)):
        spot = (HIDDEN[0] + dx, HIDDEN[1] + dy)
        s.call("place_at", me, *spot, check=False)
        settle(1.0)
        if any(r["id"] == victim for r in psql("SELECT id FROM seen_characters")):
            inside = spot
            break
    save("a spot inside the brush sees the hidden spot", inside is not None, inside)
    s.call("place_at", me, *OUTSIDE)
    settle(1.0)
    save("the victim is hidden from outside the brush", not any(r["id"] == victim for r in psql("SELECT id FROM seen_characters")))
    s.call("kill", victim, "feed scope fixture")
    remains = s.wait(lambda: [r for r in s.rows("SELECT * FROM structure_held WHERE kind = 'remains'") if r["owner"] == victim], 10)[0]
    rk = key(1, remains["id"])
    s.call("place_at", mind, OUTSIDE[0] + 0.5, OUTSIDE[1])
    settle(2.5)
    save("hidden: not in the player's my_things", rk not in things(), sorted(things()))
    time.sleep(2.0)
    noticed = lambda: [r for r in s.rows(f"SELECT text FROM experience WHERE observer = {mind} AND kind = 'saw'") if "remains" in r["text"]]
    save("hidden: the mind does not notice it", not noticed())
    save("hidden: not in the mind's seen ranges or memory",
         not s.rows(f"SELECT id FROM remembered_thing WHERE observer = {mind}")
         and all(not (r["ranges"] and any(r["ranges"][i] <= remains["id"] <= r["ranges"][i + 1] for i in range(0, len(r["ranges"]), 2)))
                 for r in s.rows(f"SELECT ranges FROM seen_structures_scoped WHERE actor = {mind}")))

    def scene_ids(marker):
        s.call("set_behavior", mind, json.dumps({"think": marker}))
        row = s.wait(lambda: [r for r in s.rows(f"SELECT reason, scene FROM deliberation WHERE actor = {mind}") if marker in r["reason"]], 70, 0.5)[0]
        sc = json.loads(row["scene"])
        return [x.get("id") for x in sc.get("structures", [])], sc

    ids, scene = scene_ids("I finished my plan. Verify feed hidden.")
    save("hidden: not in the mind's pending scene", remains["id"] not in ids, ids)
    s.graph(mind, {"wait": 600})

    s.call("place_at", me, *inside)
    s.call("place_at", mind, inside[0] + 0.3, inside[1])
    settle(2.5)
    t = things().get(rk)
    save("in sight: in the player's my_things, presence only", t is not None and t["kind"] == "remains" and abs(t["x"] - remains["x"]) < 0.01, t)
    s.wait(noticed, 15)
    save("in sight: the mind notices it", bool(noticed()), noticed())
    ids, scene = scene_ids("I finished my plan. Verify feed seen.")
    save("in sight: in the mind's pending scene", remains["id"] in ids, ids)
    s.graph(mind, {"wait": 600})
    save("in sight: both remember it", rk in remembered() and bool(s.rows(f"SELECT id FROM remembered_thing WHERE observer = {mind} AND target = {remains['id']}")))

    s.call("place_at", me, *OUTSIDE)
    settle(2.0)
    save("out of sight: gone from my_things", rk not in things())
    r = remembered().get(rk)
    save("out of sight: remembered as last seen", r is not None and r["kind"] == "remains" and abs(r["x"] - remains["x"]) < 0.01, r)

    # ---- a gate's state -----------------------------------------------------------------------
    gates = s.rows("SELECT * FROM gate_held")
    members = {m["member"]: m["community"] for m in s.rows("SELECT * FROM membership")}
    alive = {c["id"] for c in s.rows("SELECT id FROM character WHERE alive = true")}
    gate = next(g for g in gates if g["open"] and any(c == g["community"] and m in alive for m, c in members.items()))
    keeper = next(m for m, c in members.items() if c == gate["community"] and m in alive)
    s.graph(keeper, {"wait": 600})
    gk = key(1, gate["id"])
    centre = (gate["x"] + 0.5, gate["y"] + 0.5)
    seen_at = None
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2), (3, 0), (-3, 0), (0, 3), (0, -3)):
        spot = (centre[0] + dx, centre[1] + dy)
        if s.call("place_at", me, *spot, check=False).returncode == 0:
            settle(1.2)
            if gk in things():
                seen_at = spot
                break
    save("in sight: the gate's state is in my_things", seen_at is not None and opt(things()[gk]["open"]) is True, seen_at)
    save("in sight: the gate is remembered open", opt(remembered().get(gk, {}).get("open")) is True, remembered().get(gk))
    s.call("place_at", me, *AWAY)
    settle(1.5)
    save("away: the gate's copy is gone", gk not in things())
    tile = (gate["x"], gate["y"])
    adj = [(centre[0] + dx, centre[1] + dy) for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1))]
    for q in adj:
        if s.call("place_at", keeper, *q, check=False).returncode == 0:
            break
    time.sleep(0.6)
    s.act(keeper, {"do": "close", "target": {"id": gate["id"]}})
    s.wait(lambda: not s.rows(f"SELECT open FROM gate_held WHERE id = {gate['id']}")[0]["open"], 15)
    settle(1.0)
    save("away: shut out of sight, the copy is still absent and the memory still open",
         gk not in things() and opt(remembered().get(gk, {}).get("open")) is True, remembered().get(gk))
    s.call("place_at", keeper, *AWAY)
    s.call("place_at", me, *seen_at)
    settle(2.0)
    s.wait(lambda: opt(remembered().get(gk, {}).get("open")) is False, 10)
    save("back in sight: the copy and the memory read shut", opt(things().get(gk, {}).get("open")) is False and opt(remembered()[gk]["open"]) is False, things().get(gk))
    s.act(keeper, {"do": "open", "target": {"id": gate["id"]}})

    # ---- the law off after stage 2 --------------------------------------------------------------
    s.call("set_world_law", "feed_scope_on", "false")
    time.sleep(2.5)
    save("law off at stage 2 keeps the feeds closed", psql("SELECT * FROM feed_scope", None)[0]["stage"] == 2 and not psql("SELECT id FROM structure", None))
    (s.out / "feed-scope-results.json").write_text(json.dumps(s.results, indent=2) + "\n")
    print(f"{sum(r['passed'] for r in s.results.values())}/{len(s.results)} checks passed", flush=True)


if __name__ == "__main__":
    main()
