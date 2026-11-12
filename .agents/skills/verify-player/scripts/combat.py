#!/usr/bin/env python3
"""Combat scenes for a player on a scratch island world (docs/COMBAT.md).

Drives the player's own identity through `use_skill` / `release_skill` over HTTP, sets scenes
with admin test reducers (`place_at`, `set_behavior`, `grant_items`; named in the report), and
checks the outcome in the authority's rows: `my_skill_uses`, `my_combat` and `my_readiness`
(the player's views), and `vitals`, `fighter`, `character` (public).

    combat.py --run RUN [--scene all|refusals|strike|kill|bow|shot|bolt|block|dodge|jump|committed|breath|heal|early_dodge|wolves|death]

Needs `verify.py launch --run RUN --seed island` and `verify.py player --run RUN join NAME`
first (the death scene rejoins with the same identity). Writes `RUN/combat.json`.
Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

RESULTS = []
ADMIN = None
SCENE = None  # the scene running, named on each result (the scene gate's per-scene red-on-main list)


def admin():
    global ADMIN
    if ADMIN is None:
        ADMIN = V.admin_token()
    return ADMIN


def sql(st, q, who="admin"):
    token = admin() if who == "admin" else st.get("token") if who == "player" else None
    code, body = V.http(f"/v1/database/{st['db']}/sql", q, token, raw=True)
    if code != 200:
        raise RuntimeError(f"sql {q}: {code} {body}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def call(st, reducer, args, who="player"):
    token = admin() if who == "admin" else st["token"]
    code, body = V.http(f"/v1/database/{st['db']}/call/{reducer}", args, token)
    V.log(st, f"call {reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}", sys.stderr)
    return code, body


def check(st, name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail, "scene": SCENE})
    V.log(st, f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


def me(st):
    rows = sql(st, "SELECT id, name, alive, cause FROM my_characters", "player")
    alive = [r for r in rows if r["alive"]]
    return alive[0]["id"] if alive else None


def body(st, cid):
    r = sql(st, f"SELECT x, y FROM body WHERE id = {cid}")
    return (r[0]["x"], r[0]["y"]) if r else None


def hp(st, cid):
    r = sql(st, f"SELECT hp, max_hp FROM vitals WHERE id = {cid}")
    return r[0]["hp"] if r else None


def uses(st):
    return sorted(sql(st, "SELECT * FROM my_skill_uses", "player"), key=lambda u: u["id"])


def last_use(st, skill):
    u = [u for u in uses(st) if u["skill"] == skill]
    return u[-1] if u else None


def seen(st):
    return sorted(sql(st, "SELECT * FROM my_combat", "player"), key=lambda r: r["id"])


def wait_outcome(st, skill, secs=4.0, final=True):
    t = time.time() + secs
    while time.time() < t:
        u = last_use(st, skill)
        if u and u["outcome"] and (not final or u["outcome"] != "in flight"):
            return u
        time.sleep(0.15)
    return last_use(st, skill)


def ready(st, skill):
    """Wait out the skill's cooldown and any recovery (my_readiness)."""
    for _ in range(80):
        r = sql(st, "SELECT * FROM my_readiness", "player")
        now = int(time.time() * 1000)
        if not r:
            return
        busy = r[0]["busy_until"] > now
        # `Ready` rows come back positional over SQL: [skill, from_ms, at_ms].
        cd = [x for x in r[0]["ready"] if x[0] == skill and x[2] > now]
        if not busy and not cd:
            return
        time.sleep(0.25)


def code_of(st, skill):
    """The presentation code `fighter.act` and `combat_seen.skill` carry for a skill: its
    `skill_card.code` (the world's stable code for it, kept in the private `skill_code` table)."""
    c = [r["code"] for r in sql(st, "SELECT skill, code FROM skill_card") if r["skill"] == skill]
    return c[0] if c else 0


def dummy(st, near, dx, dy, graph='{"wait":60}', name_hint=None, room=0.0):
    """A resident to fight: a living adult other than me, set to `graph`, placed (dx, dy) from
    `near`. Adults only (`stage` 2 or more): a child's strike is refused ("too young to fight"),
    so an attacker scene with a child as the attacker saw no blow at all. Staged on a tile
    `free_spots` knows is free (with `room` metres of open ground beyond it), and read back:
    `place_at` takes the nearest free walkable tile, which can be out of reach when the tile
    asked for is taken."""
    mine = me(st)
    rows = sql(st, "SELECT id, stage FROM character WHERE kind = 'person' AND alive = true")
    for r in rows:
        if r["id"] == mine or r["stage"] < 2:
            continue
        b = body(st, r["id"])
        h = hp(st, r["id"])
        if b is None or h is None or h < 50:
            continue
        # Placed first: a teleport drops whatever approach the new graph had started.
        spots = free_spots(st, near, dx, dy, skip={r["id"]}, room=room) or [(near[0] + dx, near[1] + dy)]
        for at in spots[:4]:
            call(st, "place_at", [r["id"], at[0], at[1]], "admin")
            got = body(st, r["id"])
            if got and math.dist(got, at) < 0.05:
                break
        call(st, "set_behavior", [r["id"], graph], "admin")
        return r["id"]
    raise RuntimeError("no resident to use as a dummy")


WALK_BLOCKED = {2, 4, 7, 8, 9}  # water, rock, wall, drop, low: not walkable (`Terrain::walkable`)


def free_spots(st, near, dx, dy, skip=(), room=0.0):
    """Tile centres to stage a body (dx, dy) from `near` on, nearest the asked point first:
    walkable, no body but those in `skip` on the tile (so `place_at`, which since 2026-11-11
    takes the nearest free walkable tile, keeps the body there), and as far from `near` as the
    offset within 0.6 m (a strike's reach is 1.6 m and its lunge 0.6 m). With `room`, the
    ground from `near` through the spot is walkable for `room` metres (0.2 m clearance), so a
    jump or a dash toward it has somewhere to land."""
    want, length = (near[0] + dx, near[1] + dy), math.hypot(dx, dy)
    span = max(length, room) + 2
    t = tiles(st, (near[0] - span, near[0] + span), (near[1] - span, near[1] + span))
    walk = lambda x, y: t.get((math.floor(x), math.floor(y)), 4) not in WALK_BLOCKED
    taken = {(math.floor(r["x"]), math.floor(r["y"])) for r in sql(st, "SELECT id, x, y FROM body") if r["id"] not in skip}
    out = []
    for ty in range(math.floor(near[1] - span), math.floor(near[1] + span) + 1):
        for tx in range(math.floor(near[0] - span), math.floor(near[0] + span) + 1):
            c = (tx + .5, ty + .5)
            d = math.dist(c, near)
            if d < 0.5 or abs(d - length) > 0.6 or not walk(*c) or (tx, ty) in taken:
                continue
            u = ((c[0] - near[0]) / d, (c[1] - near[1]) / d)
            if room and not all(walk(near[0] + u[0] * k / 4 + ox, near[1] + u[1] * k / 4 + oy)
                                for k in range(1, int(room * 4) + 1) for ox, oy in ((0, 0), (.2, .2), (-.2, .2), (.2, -.2), (-.2, -.2))):
                continue
            out.append(c)
    return sorted(out, key=lambda c: math.dist(c, want))


OPAQUE = {4, 7}  # rock, wall (living_rules::map::Terrain): a building where it is solid at eye height; a drop (8) and a low or open thing (9: a cart, an open stall, a well, a building's overhang) are see-through


def tiles(st, xs, ys):
    """Terrain of the tiles in the box (public `terrain_chunk` rows, 16 x 16 tiles each)."""
    out = {}
    for cy in range(int(min(ys)) // 16, int(max(ys)) // 16 + 1):
        for cx in range(int(min(xs)) // 16, int(max(xs)) // 16 + 1):
            row = sql(st, f"SELECT tiles FROM terrain_chunk WHERE id = {(cy << 16) | cx}")
            if not row:
                continue
            t = row[0]["tiles"]
            t = bytes.fromhex(t) if isinstance(t, str) else bytes(t)
            for k, v in enumerate(t):
                out[(cx * 16 + k % 16, cy * 16 + k // 16)] = v
    return out


def open_line(st, a, b):
    """No rock or wall on the straight line from a to b (sampled every 0.25 m)."""
    t = tiles(st, (a[0], b[0]), (a[1], b[1]))
    n = int(math.dist(a, b) * 4) + 1
    return all(t.get((int(a[0] + (b[0] - a[0]) * i / n), int(a[1] + (b[1] - a[1]) * i / n))) not in OPAQUE for i in range(n + 1))


def free_of_bodies(st, a, b, skip):
    """No body but those in `skip` within 1 m of the segment a-b (where each stands now)."""
    for r in sql(st, "SELECT id, x, y FROM body"):
        if r["id"] in skip:
            continue
        q = (r["x"], r["y"])
        ab = (b[0] - a[0], b[1] - a[1])
        n = ab[0] ** 2 + ab[1] ** 2 or 1.0
        k = max(0.0, min(1.0, ((q[0] - a[0]) * ab[0] + (q[1] - a[1]) * ab[1]) / n))
        if math.dist(q, (a[0] + ab[0] * k, a[1] + ab[1] * k)) < 1.0:
            return False
    return True


def shot_dummy(st, p, offsets):
    """A dummy for a missile: placed at the first of `offsets` from p whose line from p is clear
    of wall, rock and every other body (the arrival spot is in a town; a building and residents
    at their posts stood in fixed lines), and the point to aim at: where it actually stands
    (`place_at` takes the nearest walkable tile). Falls back to the first offset."""
    cid = me(st)
    for dx, dy in offsets:
        if not open_line(st, p, (p[0] + dx, p[1] + dy)):
            continue
        d = dummy(st, p, dx, dy)
        time.sleep(0.4)
        at = body(st, d)
        if at and open_line(st, p, at) and free_of_bodies(st, p, at, {cid, d}):
            return d, at
    d = dummy(st, p, *offsets[0])
    time.sleep(0.4)
    return d, body(st, d) or (p[0] + offsets[0][0], p[1] + offsets[0][1])


def struck(st, cid, t0, d, before):
    """The body a missile of mine struck since t0 (its impact's target; the dummy if none was
    seen) and its health before and now (0 once it died and its vitals went)."""
    met = [e["target"] for e in seen(st) if e["kind"] == 11 and e["actor"] == cid and e["at_ms"] >= t0]
    hit = met[-1] if met else d
    alive = sql(st, f"SELECT alive FROM character WHERE id = {hit}")
    h1 = hp(st, hit)
    if h1 is None and alive and not alive[0]["alive"]:
        h1 = 0.0
    return hit, before.get(hit), h1


def wolves(st):
    rows = sql(st, "SELECT id, text FROM background")
    return [r["id"] for r in rows if '"bold":true' in r["text"]]


# ---- scenes --------------------------------------------------------------------------------


def scene_refusals(st):
    cid = me(st)
    p = body(st, cid)
    code, body_ = call(st, "use_skill", ["fly", 0, p[0], p[1]])
    check(st, "unknown skill is a reducer error", code != 200 and "not on the skill bar" in body_, f"{code} {body_.strip()}")
    call(st, "use_skill", ["strike", 0, p[0] + 1, p[1]])
    u = wait_outcome(st, "strike", 2)
    check(st, "strike with no target is recorded as refused", u and u["accepted_ms"] == 0 and "no one there" in u["outcome"], u and u["outcome"])
    d = dummy(st, p, 6.0, 0.0)
    time.sleep(0.4)
    call(st, "use_skill", ["strike", d, p[0] + 6, p[1]])
    u = wait_outcome(st, "strike", 2)
    check(st, "strike out of reach is refused (no walking into reach)", u and u["accepted_ms"] == 0 and "out of reach" in u["outcome"], u and u["outcome"])
    r = [e for e in seen(st) if e["kind"] == 9]
    check(st, "the refusal is told to the player (my_combat REFUSED)", any("out of reach" in e["note"] for e in r), [e["note"] for e in r][-3:])
    call(st, "use_skill", ["heal", 0, p[0], p[1]])
    u = wait_outcome(st, "heal", 2)
    check(st, "heal unhurt is refused", u and "not hurt" in u["outcome"], u and u["outcome"])
    ready(st, "firebolt")
    call(st, "use_skill", ["firebolt", 0, p[0], p[1] + 10])
    time.sleep(0.15)
    call(st, "use_skill", ["firebolt", 0, p[0], p[1] + 10])
    us = [u for u in uses(st) if u["skill"] == "firebolt"][-2:]
    check(st, "a second fire bolt within the cooldown is refused", len(us) == 2 and us[0]["accepted_ms"] > 0 and us[1]["accepted_ms"] == 0 and ("not ready" in us[1]["outcome"] or "middle of" in us[1]["outcome"]), [u["outcome"] for u in us])


def told(st, cid, skill, t0_ms, secs=4.0):
    """How the player's own `skill` came out, as its character is told it (the `force_outcomes`
    law, docs/COMBAT.md "The outcome of one's own blow or shot"): its `own` lines in
    `my_experience` since `t0_ms`, each with its `my_act_outcomes` row, and, read as the admin,
    every such line and row in the world (to show they reach the one who made the move only)."""
    t = time.time() + secs
    lines = []
    while time.time() < t:
        lines = [e for e in sql(st, "SELECT id, kind, text, at_ms FROM my_experience", "player")
                 if e["kind"] == "own" and e["at_ms"] >= t0_ms and (e["text"].startswith(f"You finished: {skill}") or e["text"].startswith(f"You failed to {skill}"))]
        if lines:
            break
        time.sleep(0.2)
    rows = {o["id"]: o for o in sql(st, "SELECT * FROM my_act_outcomes", "player")}
    everyone = [e for e in sql(st, f"SELECT id, observer, kind, text FROM experience WHERE at_ms >= {t0_ms}")
                if e["kind"] == "own" and (e["text"].startswith(f"You finished: {skill}") or e["text"].startswith(f"You failed to {skill}"))]
    outcomes = [o for o in sql(st, f"SELECT id, observer, skill FROM act_outcome WHERE at_ms >= {t0_ms}") if o["skill"] == skill]
    return lines, [rows.get(l["id"]) for l in lines], everyone, outcomes


def scene_strike(st):
    cid = me(st)
    p = body(st, cid)
    d = dummy(st, p, 1.2, 0.0)
    time.sleep(0.4)
    h0 = hp(st, d)
    ready(st, "strike")
    t0 = time.time()
    call(st, "use_skill", ["strike", d, p[0] + 1.2, p[1]])
    f = sql(st, f"SELECT * FROM fighter WHERE id = {cid}")
    code = code_of(st, "strike")
    check(st, "the windup is visible to others (fighter.act = strike)", f and code > 0 and f[0]["act"] == code and f[0]["release_ms"] > f[0]["act_ms"], (f, code))
    u = wait_outcome(st, "strike", 3)
    h1 = hp(st, d)
    check(st, "strike lands: accepted, released, damage dealt", u and u["accepted_ms"] > 0 and u["released_ms"] >= u["accepted_ms"] + 300 and h1 is not None and h0 is not None and h1 < h0, f"{u and u['outcome']} hp {h0}->{h1} in {time.time()-t0:.2f}s")
    ev = seen(st)
    kinds = {e["kind"] for e in ev if e["actor"] == cid}
    hits = [e for e in ev if e["kind"] == 2 and e["actor"] == cid and e["target"] == d]
    check(st, "the player perceives release and hit, with the amount", 1 in kinds and hits and hits[-1]["amount"] > 0, [(e["kind"], round(e["amount"], 1)) for e in ev[-4:]])
    fd = sql(st, f"SELECT band FROM fighter WHERE id = {d}")
    check(st, "the target's band is public, not its health", fd and 0 <= fd[0]["band"] <= 4, fd)
    lines, rows, everyone, outcomes = told(st, cid, "strike", int(t0 * 1000))
    check(st, "the player is told its strike's outcome as a mind is: 'You finished: strike → … hit for N', with its my_act_outcomes row",
          lines and "hit for" in lines[-1]["text"] and rows[-1] and rows[-1]["kind"] == "own" and rows[-1]["ok"] and rows[-1]["skill"] == "strike" and rows[-1]["code"] == "done",
          {"lines": [l["text"] for l in lines], "rows": rows})
    check(st, "the strike's line and row reach the striker only", everyone and {e["observer"] for e in everyone} == {cid} and {o["observer"] for o in outcomes} <= {cid},
          {"lines_to": sorted({e["observer"] for e in everyone}), "rows_to": sorted({o["observer"] for o in outcomes})})
    return d


def scene_kill(st):
    """A blow does its damage: the player's strikes go on past a beaten resident's 40% and 10%
    (the old hurt mode's stop and floor), and the strike that exceeds its health kills it."""
    cid = me(st)
    p = body(st, cid)
    d = dummy(st, p, 1.2, 0.0)
    time.sleep(0.4)
    trail = []
    final = None
    # About twenty strikes at the stamina-1 blows (5), paced by breath: two minutes at most.
    t = time.time() + 120
    while time.time() < t:
        live = sql(st, f"SELECT alive FROM character WHERE id = {d}")
        if not live or not live[0]["alive"]:
            break
        h = hp(st, d)
        dp = body(st, d)
        ready(st, "strike")
        call(st, "use_skill", ["strike", d, dp[0], dp[1]])
        u = wait_outcome(st, "strike", 3)
        trail.append((round(h, 1), u and u["outcome"]))
        if u and "killed" in u["outcome"]:
            final = (h, u)
            break
        if u and "out of breath" in u["outcome"]:
            # Ten strikes take a bar of breath (10 each): wait for it to come back.
            time.sleep(3)
            continue
    dead = sql(st, f"SELECT alive, cause FROM character WHERE id = {d}")
    mine = sql(st, f"SELECT name FROM character WHERE id = {cid}")[0]["name"]
    # The death record names the killer as the victim knew them (perceived_of): the player's
    # name only if it told the victim (an acquaintance row), else "a stranger". The chronicle's
    # killing row keeps real names.
    knew = sql(st, f"SELECT * FROM acquaintance WHERE observer = {d} AND known = {cid}")
    as_known = mine if knew else "a stranger"
    hits = [e for e in seen(st) if e["kind"] == 2 and e["actor"] == cid and e["target"] == d]
    killing = sql(st, f"SELECT kind, a, b, text FROM chronicle WHERE kind = 'killing' AND a = {cid} AND b = {d}")
    mh = sql(st, f"SELECT max_hp FROM vitals WHERE id = {d}")
    mh = mh[0]["max_hp"] if mh else 100.0
    low = [h for h, o in trail if h < 0.4 * mh]
    # A strike refused for breath waits and goes on (since stamina-1); every one made lands.
    landed = all(o and (o.startswith("hit for") or "killed" in o) for h, o in trail if o and "out of breath" not in o)
    check(st, "strikes keep landing below 40% health (no beating stops short)", len(low) >= 1 and landed, {"max_hp": round(mh, 1), "trail": trail})
    # Health was read before the strike's wait; vitals settle to the blow's instant, so allow a
    # small drift.
    check(st, "a strike that exceeds health kills a person",
          final is not None and hits and hits[-1]["amount"] >= final[0] - 1.0 and dead and not dead[0]["alive"] and dead[0]["cause"] == f"killed by {as_known}" and killing and mine in killing[0]["text"],
          {"as_known": as_known, "hp_before_last": final and round(final[0], 2), "last_hit": hits and round(hits[-1]["amount"], 2), "outcome": final and final[1]["outcome"], "character": dead, "chronicle": killing})


def scene_bow(st):
    cid = me(st)
    p = body(st, cid)
    d, at = shot_dummy(st, p, [(0.0, -8.0), (0.0, 8.0), (-8.0, 0.0), (8.0, 0.0)])
    before = {r["id"]: r["hp"] for r in sql(st, "SELECT id, hp FROM vitals")}
    t0 = int(time.time() * 1000)
    ready(st, "bowshot")
    arrows0 = sum(r["qty"] for r in sql(st, f"SELECT qty FROM inventory WHERE owner = {cid} AND item = 'arrow'"))
    call(st, "use_skill", ["bowshot", 0, at[0], at[1]])
    u = wait_outcome(st, "bowshot", 3)
    hit, h0, h1 = struck(st, cid, t0, d, before)
    arrows1 = sum(r["qty"] for r in sql(st, f"SELECT qty FROM inventory WHERE owner = {cid} AND item = 'arrow'"))
    ev = seen(st)
    launch = [e for e in ev if e["kind"] == 10 and e["actor"] == cid]
    impact = [e for e in ev if e["kind"] == 11 and e["actor"] == cid]
    check(st, "an arrow flies (launch and impact perceived) and strikes the first body in its path", launch and impact and h0 is not None and h1 is not None and h1 < h0, f"{u and u['outcome']} (#{hit}{', the dummy' if hit == d else ', in the path'}) hp {h0}->{h1} launch speed {launch and launch[-1]['amount']}")
    check(st, "the arrow is spent", arrows1 == arrows0 - 1, f"{arrows0}->{arrows1}")
    lines, rows, everyone, outcomes = told(st, cid, "bowshot", t0)
    check(st, "the player is told where its arrow went as a mind is: 'You finished: bowshot → … struck …: hit for N', with its my_act_outcomes row",
          lines and "struck" in lines[-1]["text"] and ("hit for" in lines[-1]["text"] or "got through" in lines[-1]["text"] or "killed" in lines[-1]["text"]) and rows[-1] and rows[-1]["kind"] == "own" and rows[-1]["skill"] == "bowshot",
          {"lines": [l["text"] for l in lines], "rows": rows})
    check(st, "the arrow's line and row reach the shooter only", everyone and {e["observer"] for e in everyone} == {cid} and {o["observer"] for o in outcomes} <= {cid},
          {"lines_to": sorted({e["observer"] for e in everyone}), "rows_to": sorted({o["observer"] for o in outcomes})})


def scene_shot(st):
    """The player shot (fix-missile-told): told as a mind is, as a shot, never "attacked". A
    resident 6 m off with a clear line shoots the player: its `my_experience` line is "<the
    shooter as the player sees them> shot you with an arrow: hit for N" and its feed's hit names
    the shooter. A resident past the player's sight (18-20 m, within the bow's 22) looses at the
    player's spot: "An arrow struck you from somewhere you could not see: hit for N", and the
    feed's hit and impact carry no shooter (actor 0).

    The player's own rows carry an unseen shooter's id nowhere (fix-unseen-killer-id):
    `my_vitals.hurt_by` is the seen shooter after the near hit and 0 after the far one; the far
    archer then shoots until the player dies: its death row (`my_act_outcomes`, kind death) has
    `other` 0, its feed's death `target` 0, its line "You were killed by an arrow from someone
    unseen.", while the chronicle keeps the real killer. After a rejoin the near archer shoots
    until the player dies again: that death row's `other` and the feed's `target` are the
    archer. The player rejoins after each death."""
    cid = me(st)
    p = body(st, cid)

    def shot_lines(t0):
        return [e for e in sql(st, "SELECT id, kind, subject, text, at_ms FROM my_experience", "player") if e["kind"] == "attacked" and e["at_ms"] >= t0]

    def wait_line(t0, secs=12.0):
        t = time.time() + secs
        while time.time() < t:
            got = shot_lines(t0)
            if got:
                return got
            time.sleep(0.3)
        return []

    d, at = shot_dummy(st, p, [(0.0, -6.0), (0.0, 6.0), (-6.0, 0.0), (6.0, 0.0)])
    call(st, "grant_items", [d, "bow", 1], "admin")
    call(st, "grant_items", [d, "arrow", 10], "admin")
    t0 = int(time.time() * 1000)
    call(st, "set_behavior", [d, json.dumps({"seq": [{"do": {"skill": "bowshot", "target": {"id": cid}}}, {"wait": 60}]})], "admin")
    got = wait_line(t0)
    call(st, "set_behavior", [d, '{"wait":60}'], "admin")
    hits = [e for e in seen(st) if e["kind"] in (2, 4) and e["target"] == cid and e["at_ms"] >= t0]
    near_hurt_by = (sql(st, "SELECT hurt_by FROM my_vitals", "player") or [{}])[0].get("hurt_by")
    check(st, "shot by someone it sees, the player is told '… shot you with an arrow: hit for N', and its feed names the shooter",
          got and all("attacked" not in e["text"] for e in got) and any(" shot you with an arrow: " in e["text"] and e["subject"] == d for e in got) and any(h["actor"] == d for h in hits),
          {"lines": [e["text"] for e in got], "hits": [(h["kind"], h["actor"]) for h in hits]})
    # Far: past sight, a clear line, no body in the way.
    far = None
    for dx, dy in [(0.0, -19.0), (0.0, 19.0), (-19.0, 0.0), (19.0, 0.0), (13.5, 13.5), (-13.5, 13.5), (13.5, -13.5), (-13.5, -13.5)]:
        if open_line(st, p, (p[0] + dx, p[1] + dy)):
            far = dummy(st, p, dx, dy)
            time.sleep(0.4)
            fa = body(st, far)
            if fa and 17.5 <= math.dist(fa, p) <= 21.0 and open_line(st, fa, p) and free_of_bodies(st, fa, p, {cid, far}):
                break
            far = None
    if far is None:
        check(st, "a clear line 18-20 m long to stage the unseen archer", False, "none found round the player")
        return
    call(st, "grant_items", [far, "bow", 1], "admin")
    call(st, "grant_items", [far, "arrow", 10], "admin")
    t1 = int(time.time() * 1000)
    call(st, "set_behavior", [far, json.dumps({"seq": [{"do": {"skill": "bowshot", "target": {"at": [p[0], p[1]]}}}, {"wait": 60}]})], "admin")
    got = wait_line(t1)
    call(st, "set_behavior", [far, '{"wait":60}'], "admin")
    far_hurt_by = (sql(st, "SELECT hurt_by FROM my_vitals", "player") or [{}])[0].get("hurt_by")
    ev = [e for e in seen(st) if e["at_ms"] >= t1 and (e["target"] == cid or e["kind"] == 11)]
    hits = [e for e in ev if e["kind"] in (2, 4) and e["target"] == cid]
    check(st, "shot by someone it cannot see, the player is told only 'An arrow struck you from somewhere you could not see: …', and its feed carries no shooter",
          got and any(e["text"].startswith("An arrow struck you from somewhere you could not see: ") and e["subject"] == 0 for e in got) and all("attacked" not in e["text"] for e in got)
          and hits and all(e["actor"] != far for e in ev),
          {"distance": round(math.dist(body(st, far) or p, p), 1), "lines": [e["text"] for e in got], "feed": [(e["kind"], e["actor"], e["target"]) for e in ev]})
    check(st, "my_vitals.hurt_by is the shooter it saw, and 0 for one it did not see", near_hurt_by == d and far_hurt_by == 0,
          {"after_near_hit": near_hurt_by, "near_archer": d, "after_far_hit": far_hurt_by, "far_archer": far})

    def shot_dead(archer, target, secs=120):
        """The archer shoots (`target`) until the player's character dies; its death row, feed
        death and line."""
        call(st, "grant_items", [archer, "arrow", 60], "admin")
        call(st, "set_behavior", [archer, json.dumps({"first": [{"do": {"skill": "bowshot", "target": target}}]})], "admin")
        t = time.time() + secs
        while time.time() < t and me(st) == cid_now[0]:
            time.sleep(0.5)
        call(st, "set_behavior", [archer, '{"wait":60}'], "admin")
        dead = cid_now[0]
        outs = [o for o in sql(st, "SELECT * FROM my_act_outcomes", "player") if o["kind"] == "death" and o["observer"] == dead]
        feed = [e for e in seen(st) if e["kind"] == 7 and e["actor"] == dead]
        line = [e["text"] for e in sql(st, "SELECT id, kind, text FROM my_experience", "player") if e["kind"] == "death"]
        cause = sql(st, f"SELECT alive, cause FROM character WHERE id = {dead}")
        chron = sql(st, f"SELECT kind, a, b FROM chronicle WHERE kind = 'killing' AND b = {dead}")
        return dead, outs, feed, line, cause, chron

    cid_now = [cid]
    dead, outs, feed, line, cause, chron = shot_dead(far, {"at": [p[0], p[1]]})
    check(st, "killed by a shooter it did not see: the death row's `other` and the feed's death `target` are 0, the line names no one; the chronicle keeps the killer",
          cause and not cause[0]["alive"] and outs and outs[-1]["other"] == 0 and feed and feed[-1]["target"] == 0
          and line and line[-1] == "You were killed by an arrow from someone unseen." and chron and chron[-1]["a"] == far,
          {"cause": cause, "row": outs[-1] if outs else None, "feed": [(e["actor"], e["target"]) for e in feed], "line": line[-1:], "chronicle": chron})
    # Back, and shot dead by the one it sees.
    call(st, "join", ["Tester"])
    time.sleep(1.0)
    cid_now[0] = me(st)
    if cid_now[0] is None:
        check(st, "rejoined after the unseen kill", False, "no living character")
        return
    q = body(st, cid_now[0])
    d2, at2 = shot_dummy(st, q, [(0.0, -6.0), (0.0, 6.0), (-6.0, 0.0), (6.0, 0.0)])
    call(st, "grant_items", [d2, "bow", 1], "admin")
    dead, outs, feed, line, cause, chron = shot_dead(d2, {"id": cid_now[0]})
    check(st, "killed by a shooter it saw: the death row's `other` and the feed's death `target` are the shooter",
          cause and not cause[0]["alive"] and outs and outs[-1]["other"] == d2 and feed and feed[-1]["target"] == d2,
          {"shooter": d2, "cause": cause, "row": outs[-1] if outs else None, "feed": [(e["actor"], e["target"]) for e in feed], "line": line[-1:]})
    call(st, "join", ["Tester"])
    time.sleep(1.0)


def scene_bolt(st):
    cid = me(st)
    p = body(st, cid)
    # Diagonals, off the strike and bow scenes' lines; shot_dummy keeps the line clear.
    d, at = shot_dummy(st, p, [(4.5, 4.5), (-4.5, 4.5), (4.5, -4.5), (-4.5, -4.5)])
    before = {r["id"]: r["hp"] for r in sql(st, "SELECT id, hp FROM vitals")}
    t0 = int(time.time() * 1000)
    ready(st, "firebolt")
    call(st, "use_skill", ["firebolt", 0, at[0], at[1]])
    u = wait_outcome(st, "firebolt", 3)
    hit, h0, h1 = struck(st, cid, t0, d, before)
    check(st, "a fire bolt burns the creature it meets", u and "struck" in u["outcome"] and h0 is not None and h1 is not None and h1 < h0, f"{u and u['outcome']} (#{hit}{', the dummy' if hit == d else ', in the path'}) hp {h0}->{h1}")


def attacker(st, cid, p, dx, room=0.0):
    g = json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": cid}}}, {"wait": 30}]})
    return dummy(st, p, dx, 0.0, g, room=room)


def guard_then_strike(st, cid, toward):
    """An adult resident beside me (placed first, waiting), my guard raised toward it
    (`toward` 1) or away from it (-1) by where it actually stands (`place_at` takes the
    nearest walkable tile, which can be beside the spot asked for), then its strike. Returns
    the attacker and the time the guard went up."""
    p = body(st, cid)
    a = dummy(st, p, 1.1, 0.0)
    time.sleep(0.4)
    q = body(st, a) or (p[0] + 1.1, p[1])
    d = math.dist(p, q) or 1.0
    ready(st, "block")
    t0 = int(time.time() * 1000)
    call(st, "use_skill", ["block", 0, p[0] + toward * 3.0 * (q[0] - p[0]) / d, p[1] + toward * 3.0 * (q[1] - p[1]) / d])
    call(st, "set_behavior", [a, json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": cid}}}, {"wait": 30}]})], "admin")
    return a, t0


def scene_block(st):
    cid = me(st)
    # Facing the attacker: the guard takes most of the blow.
    call(st, "set_behavior", [cid, '{"wait":60}'], "admin")
    a, t0 = guard_then_strike(st, cid, 1)
    t = time.time() + 4
    ev = []
    while time.time() < t and not any(e["kind"] in (2, 4) for e in ev):
        time.sleep(0.2)
        ev = [e for e in seen(st) if e["target"] == cid and e["actor"] == a and e["at_ms"] >= t0]
    blocked = [e for e in ev if e["kind"] == 4]
    check(st, "a guard facing the blow blocks it (BLOCKED, reduced)", blocked, [(e["kind"], round(e["amount"], 1)) for e in ev])
    call(st, "release_skill", ["block"])
    time.sleep(0.3)
    u = last_use(st, "block")
    check(st, "letting go ends the held guard", u and u["outcome"] != "" and u["outcome_ms"] - u["accepted_ms"] < 8000, u and u["outcome"])
    # Facing away: the blow comes from behind and lands in full.
    call(st, "set_behavior", [a, '{"wait":60}'], "admin")
    a, t0 = guard_then_strike(st, cid, -1)
    t = time.time() + 4
    ev = []
    while time.time() < t and not ev:
        time.sleep(0.2)
        ev = [e for e in seen(st) if e["target"] == cid and e["actor"] == a and e["kind"] in (2, 4) and e["at_ms"] >= t0]
    check(st, "a guard facing away does not help (HIT, not BLOCKED)", ev and ev[-1]["kind"] == 2, [(e["kind"], round(e["amount"], 1)) for e in ev])
    call(st, "release_skill", ["block"])
    call(st, "set_behavior", [a, '{"wait":60}'], "admin")


def scene_dodge(st):
    t0 = int(time.time() * 1000)
    cid = me(st)
    p = body(st, cid)
    a = attacker(st, cid, p, 1.1)
    # Dodge once the windup has begun (strike windup 350 ms).
    strike = code_of(st, "strike")
    t = time.time() + 3
    started = False
    while time.time() < t:
        f = sql(st, f"SELECT act, release_ms FROM fighter WHERE id = {a}")
        if f and f[0]["act"] == strike and f[0]["release_ms"] > time.time() * 1000:
            started = True
            break
        time.sleep(0.03)
    ready(st, "dodge")
    call(st, "use_skill", ["dodge", 0, p[0], p[1] + 3.0])
    time.sleep(1.0)
    p2 = body(st, cid)
    ev = [e for e in seen(st) if e["target"] == cid and e["actor"] == a and e["kind"] in (2, 3, 5) and e["at_ms"] >= t0]
    moved = p2 and math.dist(p, p2)
    check(st, "a dodge dashes (moves ~2.6 m) and the blow misses or is dodged", started and moved and moved > 1.5 and ev and ev[-1]["kind"] in (3, 5), f"moved {moved and round(moved, 2)} m, events {[e['kind'] for e in ev]}")
    call(st, "set_behavior", [a, '{"wait":60}'], "admin")


def wall_by(st, near):
    """Near `near`: a walkable tile, the next one along an axis walkable and the one after it
    wall or rock, the tile beside the first (a quarter turn) walkable and free of bodies: the
    tile, the axis toward the wall, the side."""
    t = tiles(st, (near[0] - 40, near[0] + 40), (near[1] - 40, near[1] + 40))
    walk = lambda x, y: t.get((x, y), 4) not in WALK_BLOCKED
    taken = {(math.floor(r["x"]), math.floor(r["y"])) for r in sql(st, "SELECT x, y FROM body")}
    spots = sorted(t, key=lambda k: math.dist((k[0] + .5, k[1] + .5), near))
    for x, y in spots:
        if not walk(x, y) or (x, y) in taken:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sx, sy = -dy, dx
            if walk(x + dx, y + dy) and t.get((x + 2 * dx, y + 2 * dy)) in OPAQUE and walk(x + sx, y + sy) and (x + sx, y + sy) not in taken:
                return (x, y), (dx, dy), (sx, sy)
    return None


def scene_early_dodge(st):
    """A dodge over before the blow came is told so to the player, as to a mind (fix-dodge-told):
    the player two tiles short of a wall, a resident beside it with a spear. The resident's heavy
    blow (`attack`) winds up; the player dodges toward the wall at once, which has room for half
    the dash, so the dash is over, still within reach, before the blow releases and lands. The
    player's `my_experience` holds "You failed to dodge: it was over before the blow came", its
    `my_act_outcomes` row (kind own, skill dodge, not ok), and its `my_skill_uses` dodge says
    "made way: it was over before the blow came"."""
    cid = me(st)
    spot = wall_by(st, body(st, cid))
    if not spot:
        check(st, "a wall two tiles off to dodge toward", False, "none near the player")
        return
    (x, y), (dx, dy), (sx, sy) = spot
    at = (x + .5, y + .5)
    call(st, "place_at", [cid, at[0], at[1]], "admin")
    d = dummy(st, (at[0], at[1]), sx, sy)
    call(st, "grant_items", [d, "spear", 1], "admin")
    call(st, "place_at", [d, at[0] + sx, at[1] + sy], "admin")
    time.sleep(0.6)
    ready(st, "dodge")
    t0 = int(time.time() * 1000)
    call(st, "set_behavior", [d, json.dumps({"seq": [{"do": {"skill": "attack", "target": {"id": cid}}}, {"wait": 60}]})], "admin")
    time.sleep(0.12)
    call(st, "use_skill", ["dodge", 0, at[0] + 3 * dx, at[1] + 3 * dy])
    lines = []
    t = time.time() + 5
    while time.time() < t and not lines:
        lines = [e for e in sql(st, "SELECT id, kind, text, at_ms FROM my_experience", "player") if e["at_ms"] >= t0 and "it was over before the blow came" in e["text"]]
        time.sleep(0.3)
    call(st, "set_behavior", [d, '{"wait":60}'], "admin")
    rows = [o for o in sql(st, "SELECT * FROM my_act_outcomes", "player") if lines and o["id"] == lines[-1]["id"]]
    u = last_use(st, "dodge")
    blow = [r for r in sql(st, f"SELECT outcome FROM skill_use WHERE actor = {d} AND skill = 'attack'") if r["outcome"]]
    check(st, "a dodge over before the blow came: the player is told 'You failed to dodge: it was over before the blow came', with its row, as a mind is",
          lines and lines[-1]["text"] == "You failed to dodge: it was over before the blow came" and rows and rows[-1]["kind"] == "own" and rows[-1]["skill"] == "dodge" and not rows[-1]["ok"]
          and u and u["outcome"] == "made way: it was over before the blow came",
          {"lines": [e["text"] for e in lines], "row": rows[-1] if rows else None, "dodge": u and u["outcome"], "blow": blow[-1:]})


def scene_jump(st):
    """A jump (2026-11-11) carries the body like a dash but does not evade: jumping toward a
    resident whose strike is winding up, the blow is not dodged (it lands, or misses by reach)."""
    t0 = int(time.time() * 1000)  # the attacker is the earlier scenes' resident: their rows stay 4 s
    cid = me(st)
    p = body(st, cid)
    a = attacker(st, cid, p, 1.1, room=2.0)  # the hop (1.6 m) lands on open ground
    strike = code_of(st, "strike")
    t = time.time() + 3
    started = False
    while time.time() < t:
        f = sql(st, f"SELECT act, release_ms FROM fighter WHERE id = {a}")
        if f and f[0]["act"] == strike and f[0]["release_ms"] > time.time() * 1000:
            started = True
            break
        time.sleep(0.03)
    q = body(st, a) or (p[0] + 1.1, p[1])
    ready(st, "jump")
    call(st, "use_skill", ["jump", 0, q[0], q[1]])
    time.sleep(1.0)
    p2 = body(st, cid)
    ev = [e for e in seen(st) if e["target"] == cid and e["actor"] == a and e["kind"] in (2, 3, 5) and e["at_ms"] >= t0]
    moved = p2 and math.dist(p, p2)
    u = last_use(st, "jump")
    check(st, "a jump hops about 1.6 m and the blow is not dodged (HIT or MISS, never DODGED)", started and moved and 0.8 < moved < 2.2 and ev and all(e["kind"] != 5 for e in ev) and u and u["outcome"] == "made way", f"windup seen {started}, attacker at {q and (round(q[0] - p[0], 2), round(q[1] - p[1], 2))}, moved {moved and round(moved, 2)} m, events {[e['kind'] for e in ev]}, outcome {u and u['outcome']}")
    call(st, "set_behavior", [a, '{"wait":60}'], "admin")


def full_breath(st, secs=12.0):
    """Wait until the player's breath is full (earlier scenes on a reused world spend it)."""
    end = time.time() + secs
    while time.time() < end:
        v = my_vitals(st)
        if v and breath_of(v, int(time.time() * 1000)) >= v["stamina_max"] - 0.5:
            return True
        time.sleep(0.3)
    return False


def scene_committed(st):
    """A committed move runs its course for a player as for a graph (committed-moves, the
    `committed` trait of `<skill>_combat()`): a guard pressed in the middle of a dodge is refused
    ("in the middle of a dodge") and the dodge covers its whole length, where before the guard
    broke the dash off; a dash still cuts in on a committed windup (a strike), as before; movement
    keys during a throw's windup wait for it; and in a world whose laws make the dodge uncommitted
    (`committed: false` in an overlay), a guard breaks the dodge off again.

    Staging (fix-committed-staging): the world's script is the shipped one first (an interrupted
    run leaves its overlay), and each part waits out its cooldowns and for full breath."""
    shipped_src = (V.ROOT / "living/scripts/skills.rhai").read_text()
    if sql(st, "SELECT source FROM script WHERE name = 'skills'")[0]["source"].strip() != shipped_src.strip():
        call(st, "install_script", [shipped_src], "admin")
        time.sleep(1.5)
    full_breath(st)
    cid = me(st)
    p = body(st, cid)
    ready(st, "dodge")
    ready(st, "block")
    call(st, "use_skill", ["dodge", 0, p[0], p[1] + 3.0])
    call(st, "use_skill", ["block", 0, p[0] + 1.0, p[1]])
    time.sleep(1.0)
    p2 = body(st, cid)
    moved = p2 and math.dist(p, p2)
    d, b = last_use(st, "dodge"), last_use(st, "block")
    check(st, "a guard pressed mid-dodge is refused and the dodge runs its course",
          d and d["outcome"] == "made way" and moved and moved > 2.2 and b and b["outcome"].startswith("refused: in the middle of a dodge"),
          {"dodge": d and d["outcome"], "block": b and b["outcome"], "moved": moved and round(moved, 2)})
    call(st, "place_at", [cid, p[0], p[1]], "admin")
    time.sleep(0.3)
    p = body(st, cid)
    t = dummy(st, p, 1.2, 0.0)
    time.sleep(0.4)
    ready(st, "strike")
    ready(st, "dodge")
    full_breath(st)
    call(st, "use_skill", ["strike", t, p[0] + 1.2, p[1]])
    call(st, "use_skill", ["dodge", 0, p[0], p[1] + 3.0])
    time.sleep(1.0)
    s_, d = last_use(st, "strike"), last_use(st, "dodge")
    check(st, "a dodge still cuts in on a committed windup (the strike is broken off)",
          s_ and s_["accepted_ms"] > 0 and s_["released_ms"] == 0 and s_["outcome"].startswith("broken off") and d and d["outcome"] == "made way",
          {"strike": s_ and s_["outcome"], "dodge": d and d["outcome"]})
    # A throw (through `human_act`: it is not on the bar) is committed too: the movement keys
    # pressed during its 800 ms windup wait for it, and the spear flies (before committed-moves
    # the keys broke it off: "you moved").
    call(st, "set_behavior", [t, '{"wait":60}'], "admin")
    call(st, "place_at", [cid, p[0], p[1]], "admin")
    time.sleep(0.3)
    p = body(st, cid)
    t = dummy(st, p, 3.0, 0.0)
    call(st, "grant_items", [cid, "spear", 1], "admin")
    time.sleep(0.4)
    ready(st, "throw")
    full_breath(st)
    before = last_use(st, "throw")
    call(st, "human_act", [json.dumps({"do": "throw", "target": {"id": t}})])
    code = code_of(st, "throw")
    wound = False
    for _ in range(40):
        f = sql(st, f"SELECT act, release_ms FROM fighter WHERE id = {cid}")
        if f and f[0]["act"] == code and f[0]["release_ms"] > time.time() * 1000:
            wound = True
            break
        time.sleep(0.03)
    at0 = body(st, cid)
    call(st, "human_move", [0.0, 1.0, False])
    time.sleep(0.25)
    mid = body(st, cid)
    time.sleep(1.5)
    call(st, "human_move", [0.0, 0.0, False])
    u = last_use(st, "throw")
    end = body(st, cid)
    check(st, "movement keys during a throw's windup wait for it: the spear flies, then the body walks",
          wound and u and u != before and u["released_ms"] > 0 and not u["outcome"].startswith("broken off") and mid and math.dist(at0, mid) < 0.2 and end and math.dist(at0, end) > 0.5,
          {"windup seen": wound, "throw": u and u["outcome"], "moved during windup": mid and round(math.dist(at0, mid), 2), "moved after": end and round(math.dist(at0, end), 2)})
    call(st, "set_behavior", [t, '{"wait":60}'], "admin")
    # The world's own laws may make a skill uncommitted (an overlay through `floors::compose`,
    # `install_script.py`'s `compose_laws`): with the dodge uncommitted, a guard pressed mid-dodge
    # breaks it off again, as before committed-moves. The shipped script is installed again after.
    spec2 = importlib.util.spec_from_file_location("install_script", V.ROOT / "living/tools/install_script.py")
    inst = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(inst)
    shipped = (V.ROOT / "living/scripts/skills.rhai").read_text()
    try:
        code_, body_ = call(st, "install_script", [inst.compose_laws(shipped, "fn dodge_combat() { let s = base_dodge_combat(); s.committed = false; s }")], "admin")
        time.sleep(1.0)
        call(st, "place_at", [cid, p[0], p[1]], "admin")
        time.sleep(0.3)
        p = body(st, cid)
        ready(st, "dodge")
        ready(st, "block")
        full_breath(st)
        call(st, "use_skill", ["dodge", 0, p[0], p[1] + 3.0])
        call(st, "use_skill", ["block", 0, p[0] + 1.0, p[1]])
        time.sleep(1.0)
        call(st, "release_skill", ["block"])
        p2 = body(st, cid)
        moved = p2 and math.dist(p, p2)
        d, b = last_use(st, "dodge"), last_use(st, "block")
        check(st, "a world whose laws make the dodge uncommitted: a guard pressed mid-dodge breaks the dodge off",
              code_ == 200 and d and d["outcome"].startswith("broken off") and moved is not None and moved < 2.0 and b and not b["outcome"].startswith("refused"),
              {"install": code_, "dodge": d and d["outcome"], "block": b and b["outcome"], "moved": moved and round(moved, 2)})
    finally:
        call(st, "install_script", [shipped], "admin")


def my_vitals(st):
    r = sql(st, "SELECT * FROM my_vitals", "player")
    return r[0] if r else None


def breath_of(v, now_ms):
    """Breath now from the row (living_rules::pools::level), as a client projects it."""
    start = max(v["at_ms"], v["stamina_from_ms"])
    return max(0.0, min(v["stamina"] + v["stamina_rate"] * max(0, now_ms - start) / 1000, v["stamina_max"]))


def scene_breath(st):
    """Breath through the player's reducers (docs/STAMINA.md): `human_move` with run drains it
    (the row's rate, written once at the start), letting go writes the refill a second on, and
    standing it comes back with no row written; a dodge takes 20 and a jump 10; dodging on
    with no time to get it back is refused "out of breath" (`my_combat` REFUSED, the use's
    outcome). Everything is read through the player's own `my_vitals` view."""
    cid = me(st)
    home = body(st, cid)
    time.sleep(2.5)
    v0 = my_vitals(st)
    check(st, "my_vitals carries breath and focus, rested and full", v0 and v0["stamina_max"] > 0 and abs(breath_of(v0, int(time.time() * 1000)) - v0["stamina_max"]) < 1.0 and v0["focus_max"] > 0, v0)
    call(st, "human_move", [1.0, 0.0, False])
    time.sleep(0.8)
    walk = sql(st, f"SELECT speed FROM body WHERE id = {cid}")[0]["speed"]
    call(st, "human_move", [1.0, 0.0, True])
    time.sleep(0.8)
    run = sql(st, f"SELECT speed FROM body WHERE id = {cid}")[0]["speed"]
    v1 = my_vitals(st)
    src = sql(st, "SELECT source FROM script WHERE name = 'skills'")[0]["source"]
    own = [r for r in sql(st, "SELECT * FROM world_law") if r["name"] == "run_share"]
    share = float(own[0]["value"]) if own else float(__import__("re").search(r"\brun_share: ([0-9.]+)", src).group(1))
    check(st, "a player's run is the run_share law times its walk and drains 4 breath a second from the row's anchor", walk and abs(run / walk - share) < 0.02 and abs(v1["stamina_rate"] + 4.0) < 1e-3 and v1["stamina_from_ms"] == v1["at_ms"], {"walk": walk, "run": run, "row": v1})
    time.sleep(1.5)
    v1b = my_vitals(st)
    # The needs may re-anchor the row meanwhile; the drain goes on from the new anchor.
    check(st, "a held run keeps draining while it lasts (no write of its own)", abs(v1b["stamina_rate"] + 4.0) < 1e-3 and v1b["stamina_from_ms"] == v1b["at_ms"], {"first": v1["at_ms"], "later": v1b["at_ms"]})
    call(st, "human_move", [0.0, 0.0, False])
    time.sleep(0.6)
    v2 = my_vitals(st)
    spent = v0["stamina_max"] - v2["stamina"]
    check(st, "letting go of the run: its breath back from a second later, at 25 a second", abs(v2["stamina_rate"] - 25.0) < 1e-3 and 0 < v2["stamina_from_ms"] - v2["at_ms"] <= 1000 and 6.0 < spent < 14.0, {"spent": spent, "row": v2})
    time.sleep(2.0)
    v3 = my_vitals(st)
    check(st, "standing, breath comes back with no row written (the client projects it)", v3 == v2 and breath_of(v3, int(time.time() * 1000)) > v2["stamina"] + 5, {"row": v3, "now": breath_of(v3, int(time.time() * 1000))})
    time.sleep(3.0)
    # Back where the scene began (the run carried the body on; a dodge needs room).
    call(st, "place_at", [cid, home[0], home[1]], "admin")
    time.sleep(0.5)
    p = body(st, cid)
    full = breath_of(my_vitals(st), int(time.time() * 1000))
    ready(st, "dodge")
    call(st, "use_skill", ["dodge", 0, p[0], p[1] + 3.0])
    wait_outcome(st, "dodge", 3)
    vd = my_vitals(st)
    check(st, "a dodge takes 20 breath", abs(full - vd["stamina"] - 20.0) < 0.6, {"before": full, "row": vd})
    time.sleep(1.5)
    p = body(st, cid)
    before = breath_of(my_vitals(st), int(time.time() * 1000))
    ready(st, "jump")
    call(st, "use_skill", ["jump", 0, p[0] + 2.0, p[1]])
    wait_outcome(st, "jump", 3)
    vj = my_vitals(st)
    check(st, "a jump takes 10 breath", abs(before - vj["stamina"] - 10.0) < 0.6, {"before": before, "row": vj})
    # Dodging on with no pause to get it back (cooldown 0.9 s, the refill starts 1 s after):
    # the sixth or so is refused.
    trail = []
    for k in range(9):
        p = body(st, cid)
        ready(st, "dodge")
        call(st, "use_skill", ["dodge", 0, p[0], p[1] + (3.0 if k % 2 else -3.0)])
        u = wait_outcome(st, "dodge", 2)
        trail.append(u and u["outcome"])
        if u and "out of breath" in u["outcome"]:
            break
    told = [e["note"] for e in seen(st) if "out of breath" in (e.get("note") or "")]
    check(st, "dodging on without a pause is refused out of breath, and told (my_combat REFUSED)", trail and trail[-1] and "out of breath" in trail[-1] and len(trail) >= 3 and told, {"outcomes": trail, "told": told[-1:]})


def scene_heal(st):
    cid = me(st)
    h0 = hp(st, cid)
    if h0 is None or h0 > 95:
        p = body(st, cid)
        attacker(st, cid, p, 1.1)
        time.sleep(1.5)
        h0 = hp(st, cid)
    ready(st, "heal")
    p = body(st, cid)
    call(st, "use_skill", ["heal", 0, p[0], p[1]])
    u = wait_outcome(st, "heal", 3)
    h1 = hp(st, cid)
    ev = [e for e in seen(st) if e["kind"] == 6 and e["target"] == cid]
    check(st, "heal mends yourself (HEALED, health up)", u and "healed" in u["outcome"] and ev and h1 is not None and h0 is not None, f"{u and u['outcome']} hp {h0:.1f}->{h1:.1f}")


def scene_wolves(st):
    cid = me(st)
    ws = wolves(st)
    check(st, "the seed placed a bold pack", len(ws) >= 3, ws)
    if not ws:
        return
    wp = body(st, ws[0])
    call(st, "place_at", [cid, wp[0] + 5.0, wp[1]], "admin")
    t = time.time() + 20
    hit = []
    while time.time() < t and not hit:
        hit = [e for e in seen(st) if e["target"] == cid and e["actor"] in ws and e["kind"] in (2, 4)]
        time.sleep(0.3)
    check(st, "bold wolves attack a healthy adult player", hit, [(e["actor"], e["kind"], round(e["amount"], 1)) for e in hit][:3])


def scene_death(st):
    cid = me(st)
    if cid is None:
        check(st, "a living character to die", False, "none")
        return
    ws = wolves(st)
    wp = body(st, ws[0]) if ws else body(st, cid)
    call(st, "place_at", [cid, wp[0] + 1.0, wp[1]], "admin")
    t = time.time() + 60
    while time.time() < t and me(st) == cid:
        time.sleep(0.5)
    rows = sql(st, f"SELECT alive, cause FROM character WHERE id = {cid}")
    check(st, "the player's character dies through the vitals and death rules", rows and not rows[0]["alive"] and rows[0]["cause"].startswith("killed by"), rows)
    ev = seen(st)
    deaths = [e for e in ev if e["kind"] == 7 and e["actor"] == cid]
    wit = [e["actor"] for e in ev if e["kind"] == 8 and e["target"] == cid]
    check(st, "the dead player is told of the death and who saw it", deaths and wit, f"killer {deaths and deaths[-1]['target']}, witnesses {wit}")
    # How it died, in codes (my_act_outcomes, since rules-senses-outcomes): a death row, code
    # killed, the killer's id; its line names the killer as the dead knew them (a label).
    outs = [o for o in sql(st, "SELECT * FROM my_act_outcomes", "player") if o["kind"] == "death"]
    lines = {e["id"]: e for e in sql(st, "SELECT id, kind, text FROM my_experience", "player")}
    killer = deaths[-1]["target"] if deaths else None
    line = lines.get(outs[-1]["id"]) if outs else None
    check(st, "the death in codes: a death row, code killed, the killer in `other`; its line 'You were killed by …'",
          outs and outs[-1]["code"] in ("killed", "killed_yielding") and outs[-1]["other"] == killer and line and line["text"].startswith("You were killed by "),
          {"row": outs[-1] if outs else None, "line": line, "killer": killer})
    code, _ = call(st, "join", ["Tester Again"])
    time.sleep(0.5)
    new = me(st)
    inv = sql(st, f"SELECT item, qty FROM inventory WHERE owner = {new}") if new else []
    know = sql(st, f"SELECT technique FROM know_how WHERE actor = {new}") if new else []
    check(st, "rejoining makes a new identity with only the newcomer's kit", code == 200 and new and new != cid and {r["item"] for r in inv} <= {"bow", "arrow", "berries"}, f"{cid} -> {new}; {inv}; {[k['technique'] for k in know]}")


SCENES = {"refusals": scene_refusals, "strike": scene_strike, "kill": scene_kill, "bow": scene_bow, "shot": scene_shot, "bolt": scene_bolt, "block": scene_block, "dodge": scene_dodge, "jump": scene_jump, "committed": scene_committed, "breath": scene_breath, "heal": scene_heal, "early_dodge": scene_early_dodge, "wolves": scene_wolves, "death": scene_death}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", default="all")
    ap.add_argument("--fresh", action="store_true", help="start with a new character")
    a = ap.parse_args()
    st = V.load(a.run)
    if "token" not in st or me(st) is None:
        sys.exit("join a player first: verify.py player --run RUN join NAME")
    # A character worn out by earlier runs would be refused as "too tired": start fresh.
    v = sql(st, f"SELECT energy FROM vitals WHERE id = {me(st)}")
    if a.fresh or (v and v[0]["energy"] < 70):
        call(st, "kill", [me(st), "worn out by testing"], "admin")
        call(st, "join", ["Tester"])
        time.sleep(1.0)
    home = body(st, me(st))
    names = list(SCENES) if a.scene == "all" else a.scene.split(",")
    global SCENE
    for n in names:
        SCENE = n
        if n not in ("wolves", "death") and home:
            call(st, "place_at", [me(st), home[0], home[1]], "admin")
            time.sleep(0.3)
        try:
            SCENES[n](st)
        except Exception as e:  # a scene that cannot run is a failure, not a crash
            check(st, f"scene {n} ran", False, repr(e))
    out = V.run_dir(a.run) / "combat.json"
    out.write_text(json.dumps(RESULTS, indent=1))
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(bad)} of {len(RESULTS)} checks pass; {out}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
