#!/usr/bin/env python3
"""Combat scenes for a player on a scratch island world (docs/COMBAT.md).

Drives the player's own identity through `use_skill` / `release_skill` over HTTP, sets scenes
with admin test reducers (`place_at`, `set_behavior`, `grant_items`; named in the report), and
checks the outcome in the authority's rows: `my_skill_uses`, `my_combat` and `my_readiness`
(the player's views), and `vitals`, `fighter`, `character` (public).

    combat.py --run RUN [--scene all|refusals|strike|kill|bow|bolt|block|dodge|jump|heal|wolves|death]

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
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
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


def dummy(st, near, dx, dy, graph='{"wait":60}', name_hint=None):
    """A resident to fight: a living adult other than me, set to `graph`, placed (dx, dy) from
    `near`. Adults only (`stage` 2 or more): a child's strike is refused ("too young to fight"),
    so an attacker scene with a child as the attacker saw no blow at all."""
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
        call(st, "place_at", [r["id"], near[0] + dx, near[1] + dy], "admin")
        call(st, "set_behavior", [r["id"], graph], "admin")
        return r["id"]
    raise RuntimeError("no resident to use as a dummy")


OPAQUE = {4, 7}  # rock, wall (living_rules::map::Terrain); buildings are wall tiles


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
    t = time.time() + 45
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
        if u and "too tired" in u["outcome"]:
            break
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
    landed = all(o and (o.startswith("hit for") or "killed" in o) for h, o in trail)
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


def attacker(st, cid, p, dx):
    g = json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": cid}}}, {"wait": 30}]})
    return dummy(st, p, dx, 0.0, g)


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


def scene_jump(st):
    """A jump (2026-11-11) carries the body like a dash but does not evade: jumping toward a
    resident whose strike is winding up, the blow is not dodged (it lands, or misses by reach)."""
    t0 = int(time.time() * 1000)  # the attacker is the earlier scenes' resident: their rows stay 4 s
    cid = me(st)
    p = body(st, cid)
    a = attacker(st, cid, p, 1.1)
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
    check(st, "a jump hops about 1.6 m and the blow is not dodged (HIT or MISS, never DODGED)", started and moved and 0.8 < moved < 2.2 and ev and all(e["kind"] != 5 for e in ev) and u and u["outcome"] == "made way", f"moved {moved and round(moved, 2)} m, events {[e['kind'] for e in ev]}, outcome {u and u['outcome']}")
    call(st, "set_behavior", [a, '{"wait":60}'], "admin")


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
    code, _ = call(st, "join", ["Tester Again"])
    time.sleep(0.5)
    new = me(st)
    inv = sql(st, f"SELECT item, qty FROM inventory WHERE owner = {new}") if new else []
    know = sql(st, f"SELECT technique FROM know_how WHERE actor = {new}") if new else []
    check(st, "rejoining makes a new identity with only the newcomer's kit", code == 200 and new and new != cid and {r["item"] for r in inv} <= {"bow", "arrow", "berries"}, f"{cid} -> {new}; {inv}; {[k['technique'] for k in know]}")


SCENES = {"refusals": scene_refusals, "strike": scene_strike, "kill": scene_kill, "bow": scene_bow, "bolt": scene_bolt, "block": scene_block, "dodge": scene_dodge, "jump": scene_jump, "heal": scene_heal, "wolves": scene_wolves, "death": scene_death}


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
    for n in names:
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
