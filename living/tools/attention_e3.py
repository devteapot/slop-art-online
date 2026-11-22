#!/usr/bin/env python3
"""E3, who to track, on recorded scenes (docs/ATTENTION_E3.md, docs/ATTENTION_BUDGET.md §8.1).
In code the concept is "heed" (living_rules::heed): who a character keeps track of as individuals;
the rest in sight is a throng.

Reads COPIES of the act trial's evidence (never `~/slop-evidence` in place), freezes a sample of
decision moments, rebuilds what each subject perceived around each one, and scores the
heeded sets that `living-mind heed-replay` picks with the shared selector (`living_rules::heed`). Python standard library only. Read-only on its inputs.

  attention_e3.py freeze --src DIR --out STATES.json [--battle 200] [--town 100]
                         [--battle-run DIR ...] [--town-run DIR ...] [--seed S]
  attention_e3.py fields --src DIR --states STATES.json --out FIELDS.jsonl [--step 0.2]
  attention_e3.py score  --src DIR --states STATES.json --fields FIELDS.jsonl --picks PICKS.jsonl --out SCORE.json

`--src` is the directory the act-trial archive was extracted into (it holds `.local/living/...`).
`--battle-run` / `--town-run` name other recordings instead (the Cullet recordings of
docs/ATTENTION_E3.md §8): a `battle_diag.py --all-bodies` run folder (every body and use, with
kinds), and a trials.py instance folder with `record.bodies {"all": true}` (`bodies.jsonl` at 5 Hz,
`kinds.json`). A state then carries its folder (`dir`).

What is rebuilt, and what is not (stated in the report):
- Battle (`minds-atb1-off`, `minds-atb1-on`, 200 real minds): every body's position from its
  movement segment at each second (`combat-samples.jsonl.gz`, 1 Hz rows with segments), the
  skill uses aimed at the subject and theirs (windup start = `accepted_ms`, outcomes). Sight is
  distance only (the subject's own `sight` from its prompt's scene): no facing, cover or light.
  People are the run's characters (`chars.json`); other bodies are animals of unknown species
  (kind `animal`). Fighters know no one, so no relation bits.
- Town (`at7on`, `at8off`, `at10off`, 40 real minds): the 40 subjects' positions every 2 s
  (`samples.jsonl`); the town's other residents are not sampled, so they are missing from the
  field. Family from `cast.json` households. Addressing and acting-on from act attempts naming
  an id (`say ... to`, `nod`, `wave`, `give`, ...), refused acts excluded.
"""

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
import sys
from bisect import bisect_right

BATTLE_RUNS = ["minds-atb1-off-055246", "minds-atb1-on-060222"]
# Every town arm of the act trial (40 real minds, 30 minutes each; atfa/atfs were its first smoke runs).
TOWN_RUNS = [f"{r}/act-town-act-replace-{'on' if r.endswith('on') or r in ('atfa', 'atfs') else 'off'}-r1"
             for r in ["at1off", "at2on", "at3on", "at4off", "at5off", "at6on", "at7on", "at8off", "at10off", "at11on", "atfa", "atfs"]]
SEED = "attention-e3-2026-11-22"
BEFORE_S = 10  # steps before the state's moment (so `new` and holds have a history)
WINDOW_S = 30  # the scored window after it
KEEP_M = 1.0  # a creature already in sight stays until this far beyond sight (the sweep's keep margin, `keep_seen_m`)
WINDUP_MS = 650  # a person's strike windup without a spear (skills.rhai attack_duration); the phase words follow it
HOSTILE = {"strike", "shoot", "bowshot", "firebolt", "attack", "threaten"}
FIGHT = HOSTILE | {"block", "dodge", "heal"}
SCENE_HEAD = "# What you perceive right now\n"


def battle_dir(src, run, st=None):
    if st and st.get("dir"):
        return st["dir"]
    return os.path.join(src, ".local/living/verify", run)


def town_dir(src, run, st=None):
    if st and st.get("dir"):
        return st["dir"]
    return os.path.join(src, ".local/living/trials", run)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def canonical_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scene_of(entry):
    msgs = entry.get("request", {}).get("messages", [])
    u = msgs[-1].get("content", "") if msgs else ""
    i = u.find(SCENE_HEAD)
    if i < 0:
        return None
    s = u[i + len(SCENE_HEAD):u.find("\n", i + len(SCENE_HEAD))]
    try:
        return json.loads(s)
    except ValueError:
        return None


def thinks(d):
    """Every think request of a run's journals: (at_ms, subject id, scene)."""
    out = []
    jd = os.path.join(d, "journal")
    for f in sorted(os.listdir(jd)):
        if not f.endswith(".jsonl"):
            continue
        for line in open(os.path.join(jd, f)):
            e = json.loads(line)
            if e.get("purpose") != "think" or e.get("error"):
                continue
            sc = scene_of(e)
            if not sc or not isinstance(sc.get("you"), dict) or "id" not in sc["you"]:
                continue
            out.append((e["at_ms"], int(sc["you"]["id"]), sc, f))
    return out


# --------------------------------------------------------------------------------------------
# Battle: positions along segments, uses


class Battle:
    def __init__(self, d):
        self.d = d
        self.start = int(open(os.path.join(d, "measure-start-ms.txt")).read().strip())
        self.samples = []  # (at_ms, {id: body})
        self.uses = {}  # id -> use (last seen)
        self.acts = {}  # id -> [(started_ms, skill)]
        for line in gzip.open(os.path.join(d, "combat-samples.jsonl.gz"), "rt"):
            e = json.loads(line)
            self.samples.append((e["at_ms"], {b["id"]: b for b in e["bodies"]}))
            for u in e["uses"]:
                self.uses[u["id"]] = u
            for a in e["activities"]:
                self.acts.setdefault(a["id"], set()).add((a["started_ms"], a["skill"]))
        self.times = [t for t, _ in self.samples]
        self.end = self.times[-1]
        self.people = {c["id"] for c in json.load(open(os.path.join(d, "chars.json")))}
        # A two-sided melee (battle_diag --sides): each fighter's side; one's own side is one's
        # community, known by name (the scene's `"community": "yours"`), the other side strangers.
        sp = os.path.join(d, "sides.json")
        self.side = {int(k): v for k, v in json.load(open(sp)).items()} if os.path.exists(sp) else {}
        # The age each creature is seen at, from the minds' own scenes (`form`: boy, girl, baby,
        # old woman, ...): what perception gave, not audit truth.
        self.stage = scene_stages(d)
        # With `--all-bodies`, every creature's kind (people, animals) from the samples.
        self.kinds = {}
        for line in gzip.open(os.path.join(d, "combat-samples.jsonl.gz"), "rt"):
            k = json.loads(line).get("kinds")
            if k:
                self.kinds.update({int(i): v for i, v in k.items()})
        self.by_actor = {}
        self.at_target = {}
        for u in self.uses.values():
            self.by_actor.setdefault(u["actor"], []).append(u)
            if u.get("target"):
                self.at_target.setdefault(u["target"], []).append(u)
        for v in list(self.by_actor.values()) + list(self.at_target.values()):
            v.sort(key=lambda u: u["accepted_ms"])
        self.acts = {k: sorted(v) for k, v in self.acts.items()}
        # Indexes for the per-step lookups (a dense battle has hundreds in sight).
        self.actor_times = {k: [u["accepted_ms"] for u in v] for k, v in self.by_actor.items()}
        self.pair = {}
        for u in self.uses.values():
            if u.get("target") and u.get("outcome_ms"):
                self.pair.setdefault((u["target"], u["actor"]), []).append((u["outcome_ms"], landed(u.get("outcome", "")), contact(u.get("outcome", ""))))
        for v in self.pair.values():
            v.sort()

    def bodies_at(self, t):
        """Every body's position and velocity at `t` (ms), from the latest sample at or before it."""
        i = bisect_right(self.times, t) - 1
        if i < 0:
            return {}
        out = {}
        for bid, b in self.samples[i][1].items():
            nxt = b["next_ms"] if b["next_ms"] < 1e18 else t
            dt = max(0, min(t, nxt) - b["t_ms"]) / 1000
            moving = t < nxt or b["next_ms"] >= 1e18
            vx, vy = (b["vx"], b["vy"]) if moving else (0.0, 0.0)
            out[bid] = (b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt, vx, vy)
        return out


def landed(outcome):
    return outcome.startswith("hit") or "got through" in outcome


def contact(outcome):
    """A blow that reached the subject: it landed, or the subject blocked or dodged it."""
    return bool(outcome) and outcome not in ("missed", "broken off")


FORM_STAGE = {"boy": "child", "girl": "child", "baby": "infant", "baby girl": "infant", "baby boy": "infant",
              "old woman": "elder", "old man": "elder", "man": "adult", "woman": "adult"}


def scene_stages(d):
    """id -> life stage as the run's think scenes showed it (`form`), when any scene did."""
    out = {}
    jd = os.path.join(d, "journal")
    for f in (sorted(os.listdir(jd)) if os.path.isdir(jd) else []):
        if not f.endswith(".jsonl"):
            continue
        for line in open(os.path.join(jd, f)):
            if '"think"' not in line:
                continue
            e = json.loads(line)
            if e.get("purpose") != "think":
                continue
            sc = scene_of(e)
            for c in (sc or {}).get("creatures", []):
                st = FORM_STAGE.get(str(c.get("form", "")).lower())
                if st and isinstance(c.get("id"), int):
                    out[c["id"]] = st
    return out


def battle_candidate(B, subject, t, me, other, pos, first_seen, prev_targets):
    x, y, vx, vy = pos[other]
    d = math.hypot(x - me[0], y - me[1])
    closing = 0.0
    if d > 1e-6:
        closing = -((x - me[0]) * vx + (y - me[1]) * vy) / d
    kind = B.kinds.get(other) or ("person" if other in B.people else "animal")
    c = {"id": other, "kind": kind, "dist": round(d, 2), "closing": round(closing, 2), "made_out": True,
         "in_sight_s": round((t - first_seen) / 1000, 1)}
    if kind == "person":
        # A stranger (these fighters know no one), but one's own side in a sides melee: community.
        c["relations"] = 16 if B.side and B.side.get(other) is not None and B.side.get(other) == B.side.get(subject) else 8
    if other in B.stage:
        c["stage"] = B.stage[other]
    # What it visibly does: its latest use whose windup or recovery is under way.
    i = bisect_right(B.actor_times.get(other, []), t)
    if i:
        u = B.by_actor[other][i - 1]
        age = t - u["accepted_ms"]
        if age <= 2000:
            is_ = [u["skill"]] + (["hostile"] if u["skill"] in HOSTILE else []) + (["melee"] if u["skill"] == "strike" else [])
            phase = "winding up" if age < WINDUP_MS * 0.5 else "about to release" if age < WINDUP_MS else "releasing" if age < WINDUP_MS + 150 else "recovering"
            c["doing"] = {"is": is_, "phase": phase, "at_me": u.get("target") == subject}
            c["target"] = u.get("target") or 0
            if u["skill"] in HOSTILE and u.get("target") == subject and age < WINDUP_MS:
                c["threatening"] = True
            if u["skill"] in FIGHT:
                c["fighting"] = True
    pv = B.pair.get((subject, other))
    if pv:
        j = bisect_right(pv, (t, True, True))
        hurt = [x[0] for x in pv[:j] if x[1]]
        touched = [x[0] for x in pv[:j] if x[2]]
        if hurt:
            c["hurt_me_ago_s"] = round((t - hurt[-1]) / 1000, 2)
        if touched:
            c["contact_ago_s"] = round((t - touched[-1]) / 1000, 2)
    if other in prev_targets:
        c["acted_on"] = True
    return c


def battle_fields(B, st, step_s=1.0):
    subject, t0, sight = st["subject"], st["t_ms"], st["sight"]
    steps = []
    first_seen = {}
    n = int(round((BEFORE_S + WINDOW_S) / step_s))
    for k in range(n + 1):
        rel = -BEFORE_S + k * step_s
        t = t0 + int(round(rel * 1000))
        pos = B.bodies_at(t)
        if subject not in pos:
            break
        me = pos[subject]
        my = [u for u in B.by_actor.get(subject, []) if u["accepted_ms"] <= t and t - u["accepted_ms"] <= 2000 and u.get("target")]
        targets = {u["target"] for u in my}
        cands = []
        for o in pos:
            if o == subject:
                continue
            d = math.hypot(pos[o][0] - me[0], pos[o][1] - me[1])
            if d > sight + (KEEP_M if o in first_seen else 0.0):
                first_seen.pop(o, None)
                continue
            first_seen.setdefault(o, t if k > 0 else t - 60_000)
            cands.append(battle_candidate(B, subject, t, me, o, pos, first_seen[o], targets))
        # What happened to the subject since the last step, in time order: windups aimed at it
        # start (the policy's to heed or not), and blows reach it (contact: forced).
        events = []
        lo = t - int(round(step_s * 1000))
        for u in B.at_target.get(subject, []):
            if u["skill"] not in HOSTILE or u["actor"] not in pos:
                continue
            for kind, at in (("windup", u["accepted_ms"]), ("contact", u.get("outcome_ms") if contact(u.get("outcome", "")) else None)):
                if not at or not (lo < at <= t):
                    continue
                ev_pos = B.bodies_at(at)
                if u["actor"] not in ev_pos or subject not in ev_pos:
                    continue
                c = battle_candidate(B, subject, at, ev_pos[subject], u["actor"], ev_pos, first_seen.get(u["actor"], at), targets)
                if c["dist"] > sight + (KEEP_M if u["actor"] in first_seen else 0.0):
                    continue  # out of sight (distance only): struck "from somewhere you could not see"
                if kind == "windup":
                    c["threatening"] = True
                else:
                    c["contact_ago_s"] = 0.0
                events.append({"t": round((at - t0) / 1000, 3), "kind": kind, "use": u["id"], "cand": c})
        events.sort(key=lambda e: e["t"])
        steps.append({"t": round(rel, 3), "cands": cands, "events": events})
    return steps


# --------------------------------------------------------------------------------------------
# Town


class Town:
    def __init__(self, d):
        self.d = d
        self.samples = [json.loads(l) for l in open(os.path.join(d, "samples.jsonl"))]
        st = json.load(open(os.path.join(d, "state.json")))
        self.t0 = st["t0"] * 1000  # wall ms of sample t=0
        self.times = [self.t0 + s["t"] * 1000 for s in self.samples]
        cast = json.load(open(os.path.join(d, "cast.json")))
        self.family = {}
        for r in cast.get("roles", {}).get("subject", []):
            hh = {h["id"] for h in r.get("background", {}).get("household", []) if "id" in h}
            self.family[r["id"]] = hh
        self.load_attempts(d)

    def load_attempts(self, d):
        self.attempts = []
        p = os.path.join(d, "journal/outcomes/act_attempts.jsonl")
        if os.path.exists(p):
            for line in open(p):
                a = json.loads(line)
                m = re.match(r"deliberate-(\d+)-", a.get("reference", ""))
                if not m:
                    continue
                refused = {json.dumps(r.get("act"), sort_keys=True) for r in a.get("refused", [])}
                named = set()
                for s in a.get("acts", []):
                    try:
                        act = json.loads(s)
                    except ValueError:
                        continue
                    if json.dumps(act, sort_keys=True) in refused:
                        continue
                    named |= ids_in(act)
                self.attempts.append({"actor": int(m.group(1)), "at_ms": a["at_ms"], "named": sorted(named)})
        self.attempts.sort(key=lambda a: a["at_ms"])

    def at(self, t):
        i = max(0, min(len(self.samples) - 1, bisect_right(self.times, t) - 1))
        return self.samples[i]


def ids_in(act):
    out = set()

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                if k == "id" and isinstance(x, int):
                    out.add(x)
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)

    walk(act)
    return out


def town_fields(T, st):
    subject, t0, sight = st["subject"], st["t_ms"], st["sight"]
    steps = []
    first_seen = {}
    prev = None
    for k in range(-BEFORE_S, WINDOW_S + 1, 2):
        t = t0 + k * 1000
        s = T.at(t)
        mem = s["members"]
        if str(subject) not in mem or not mem[str(subject)].get("alive", True):
            break
        me = mem[str(subject)]["pos"]
        before = T.at(t - 2000)["members"] if prev is None else prev
        cands = []
        for o, m in mem.items():
            o = int(o)
            if o == subject or not m.get("alive", True):
                continue
            x, y = m["pos"]
            d = math.hypot(x - me[0], y - me[1])
            if d > sight + (KEEP_M if o in first_seen else 0.0):
                first_seen.pop(o, None)
                continue
            first_seen.setdefault(o, t if k > -BEFORE_S else t - 60_000)
            c = {"id": o, "kind": "person", "dist": round(d, 2), "made_out": True, "in_sight_s": round((t - first_seen[o]) / 1000, 1)}
            if str(o) in before:
                bx, by = before[str(o)]["pos"]
                bd = math.hypot(bx - me[0], by - me[1])
                c["closing"] = round((bd - d) / 2.0, 2)
            if o in T.family.get(subject, set()):
                c["relations"] = 1
            addressed = [a for a in T.attempts if a["actor"] == o and subject in a["named"] and a["at_ms"] <= t]
            if addressed:
                c["addressed_me_ago_s"] = round((t - addressed[-1]["at_ms"]) / 1000, 1)
            mine = [a for a in T.attempts if a["actor"] == subject and o in a["named"] and 0 <= t - a["at_ms"] <= 10_000]
            if mine:
                c["acted_on"] = True
            cands.append(c)
        prev = mem
        steps.append({"t": float(k), "cands": cands, "events": []})
    return steps


class TownB(Town):
    """A trials.py instance with `record.bodies {"all": true}`: every creature at 5 Hz
    (`bodies.jsonl`: position, facing, the fighter row, the activity), kinds (`kinds.json`)."""

    def __init__(self, d):
        self.d = d
        self.rows = [json.loads(l) for l in open(os.path.join(d, "bodies.jsonl"))]
        self.times = [r["ms"] for r in self.rows]
        kp = os.path.join(d, "kinds.json")
        self.kinds = {int(k): v for k, v in json.load(open(kp)).items()} if os.path.exists(kp) else {}
        cast = json.load(open(os.path.join(d, "cast.json"))) if os.path.exists(os.path.join(d, "cast.json")) else {}
        self.family = {}
        for r in cast.get("roles", {}).get("subject", []):
            self.family[r["id"]] = {h["id"] for h in r.get("background", {}).get("household", []) if "id" in h}
        Town.load_attempts(self, d)

    def row(self, t):
        i = max(0, min(len(self.rows) - 1, bisect_right(self.times, t) - 1))
        return self.rows[i]


def town_fields_b(T, st, step_s=0.2):
    subject, t0, sight = st["subject"], st["t_ms"], st["sight"]
    steps = []
    first_seen = {}
    n = int(round((BEFORE_S + WINDOW_S) / step_s))
    for k in range(n + 1):
        rel = -BEFORE_S + k * step_s
        t = t0 + int(round(rel * 1000))
        r = T.row(t)
        b = r["b"]
        if str(subject) not in b or str(subject) in r.get("dead", {}):
            break
        me = b[str(subject)]
        before = T.row(t - 1000)["b"]
        mine_act = r.get("act", {}).get(str(subject))
        my_target = mine_act[1] if mine_act else 0
        cands = []
        for o, v in b.items():
            oi = int(o)
            if oi == subject or o in r.get("dead", {}):
                continue
            d = math.hypot(v[0] - me[0], v[1] - me[1])
            if d > sight + (KEEP_M if oi in first_seen else 0.0):
                first_seen.pop(oi, None)
                continue
            first_seen.setdefault(oi, t if k > 0 else t - 60_000)
            c = {"id": oi, "kind": T.kinds.get(oi, "person"), "dist": round(d, 2), "made_out": True, "in_sight_s": round((t - first_seen[oi]) / 1000, 1)}
            if o in before:
                bd = math.hypot(before[o][0] - me[0], before[o][1] - me[1])
                c["closing"] = round(bd - d, 2)
            if oi in T.family.get(subject, set()):
                c["relations"] = 1
            f = r.get("f", {}).get(o)
            if f and f[1] and f[4] > r["ms"]:
                act_ms, rel_ms, until = f[2], f[3], f[4]
                now = r["ms"]
                phase = "winding up" if now < act_ms + (rel_ms - act_ms) * 0.5 else "about to release" if now < rel_ms else "releasing" if now < rel_ms + 150 else "recovering"
                c["doing"] = {"is": ["hostile"] if f[5] else ["move"], "phase": phase, "at_me": f[5] == subject}
                c["target"] = f[5]
                c["fighting"] = True
                if f[5] == subject and now < rel_ms:
                    c["threatening"] = True
            addressed = [a for a in T.attempts if a["actor"] == oi and subject in a["named"] and a["at_ms"] <= t]
            if addressed:
                c["addressed_me_ago_s"] = round((t - addressed[-1]["at_ms"]) / 1000, 1)
            if oi == my_target or any(a["actor"] == subject and oi in a["named"] and 0 <= t - a["at_ms"] <= 10_000 for a in T.attempts):
                c["acted_on"] = True
            cands.append(c)
        steps.append({"t": round(rel, 3), "cands": cands, "events": []})
    return steps


def load_town(d):
    return TownB(d) if os.path.exists(os.path.join(d, "bodies.jsonl")) else Town(d)


def town_fields_any(T, st, step_s):
    return town_fields_b(T, st, step_s) if isinstance(T, TownB) else town_fields(T, st)


# --------------------------------------------------------------------------------------------
# freeze


def freeze(a):
    rng = random.Random(SEED)
    states = []
    inputs = {}
    custom_b = [os.path.abspath(x) for x in (a.battle_run or [])]
    custom_t = [os.path.abspath(x) for x in (a.town_run or [])]
    for run in (custom_b or BATTLE_RUNS):
        d = run if custom_b else battle_dir(a.src, run)
        B = Battle(d)
        pool = []
        for at, sid, sc, f in thinks(d):
            # Minute 2 on (the trial's measured window), and a whole window left in the samples.
            if at < B.start + 60_000 or at + WINDOW_S * 1000 > B.end:
                continue
            pos = B.bodies_at(at)
            if sid not in pos:
                continue
            sight = float(sc.get("time", {}).get("sight", 48.0))
            n = sum(1 for o, p in pos.items() if o != sid and math.hypot(p[0] - pos[sid][0], p[1] - pos[sid][1]) <= sight)
            you = sc["you"]
            pool.append({"kind": "battle", "run": os.path.basename(run), **({"dir": d} if custom_b else {}), "subject": sid, "t_ms": at, "sight": sight, "in_sight": n, "journal": f,
                         "self": {"health": you.get("health"), "energy": you.get("energy"), "hunger": you.get("hunger"), "stamina": you.get("stamina")},
                         "stage": "adult", "knows": you.get("knows_how_to", [])})
        pool.sort(key=lambda s: (s["subject"], s["t_ms"]))
        if getattr(a, "battle_all", False):
            # E5 (docs/ATTENTION_E5.md §3): every think request with a reply and at least
            # `--battle-min-sight` others in sight, not a sample.
            take = [s for s in pool if s["in_sight"] >= a.battle_min_sight]
        else:
            take = rng.sample(pool, min(len(pool), a.battle // len(custom_b or BATTLE_RUNS)))
        states += sorted(take, key=lambda s: s["t_ms"])
        inputs[os.path.basename(run)] = {"combat-samples.jsonl.gz": sha256_file(os.path.join(d, "combat-samples.jsonl.gz")), "think requests": len(pool)}
    town_pool = []
    # With --battle-run and no --town-run, --town 0 skips the act trial's towns (E5 records battles only).
    for run in (custom_t or (TOWN_RUNS if a.town else [])):
        d = run if custom_t else town_dir(a.src, run)
        T = load_town(d)
        for at, sid, sc, f in thinks(d):
            if at < T.times[0] + 60_000 or at + WINDOW_S * 1000 > T.times[-1]:
                continue
            if isinstance(T, TownB):
                r = T.row(at)
                mem = {o: {"pos": v[:2], "alive": o not in r.get("dead", {})} for o, v in r["b"].items()}
            else:
                mem = T.at(at)["members"]
            if str(sid) not in mem:
                continue
            me = mem[str(sid)]["pos"]
            sight = float(sc.get("time", {}).get("sight", 48.0))
            n = sum(1 for o, m in mem.items() if int(o) != sid and m.get("alive", True) and math.hypot(m["pos"][0] - me[0], m["pos"][1] - me[1]) <= sight)
            if n < a.town_min_sight:
                continue
            you = sc["you"]
            town_pool.append({"kind": "town", "run": os.path.relpath(run, os.path.dirname(os.path.dirname(run))) if custom_t else run, **({"dir": d} if custom_t else {}), "subject": sid, "t_ms": at, "sight": sight, "in_sight": n, "journal": f,
                              "self": {"health": you.get("health"), "energy": you.get("energy"), "hunger": you.get("hunger"), "stamina": you.get("stamina")},
                              "stage": "adult", "knows": you.get("knows_how_to", [])})
        sample_file = "bodies.jsonl" if isinstance(T, TownB) else "samples.jsonl"
        inputs[os.path.basename(run) if custom_t else run] = {sample_file: sha256_file(os.path.join(d, sample_file))}
    town_pool.sort(key=lambda s: (s["run"], s["subject"], s["t_ms"]))
    states += sorted(rng.sample(town_pool, min(len(town_pool), a.town)), key=lambda s: (s["run"], s["t_ms"]))
    for i, s in enumerate(states):
        s["state"] = f"{s['kind'][0]}{i:03d}"
    manifest = {"seed": SEED, "before_s": BEFORE_S, "window_s": WINDOW_S, "battle": a.battle, "town": a.town, "town_pool": len(town_pool),
                "inputs": inputs, "states_sha256": canonical_sha(states), "tool_sha256": sha256_file(__file__)}
    json.dump({"manifest": manifest, "states": states}, open(a.out, "w"), indent=1)
    print(json.dumps(manifest, indent=1))


# --------------------------------------------------------------------------------------------
# fields


def capacity_actor(st):
    s = st["self"]
    return {"kind": "person", "stage": st.get("stage", "adult"), "hp": s.get("health") or 100.0, "energy": s.get("energy") or 80.0,
            "stamina": s.get("stamina") if s.get("stamina") is not None else 60.0, "knows": st.get("knows", [])}


def fields(a):
    data = json.load(open(a.states))
    battles, towns = {}, {}
    with open(a.out, "w") as out:
        for st in data["states"]:
            if st["kind"] == "battle":
                B = battles.get(st["run"]) or battles.setdefault(st["run"], Battle(battle_dir(a.src, st["run"], st)))
                steps = battle_fields(B, st, a.step)
            else:
                T = towns.get(st["run"]) or towns.setdefault(st["run"], load_town(town_dir(a.src, st["run"], st)))
                steps = town_fields_any(T, st, a.town_step)
            s = st["self"]
            rec = {"state": st["state"], "kind": "person", "actor": capacity_actor(st),
                   "self": {"health": s.get("health") or 100.0, "energy": s.get("energy") or 80.0, "hunger": s.get("hunger") or 0.0, "stamina": s.get("stamina") or 60.0, "night": False},
                   "steps": steps}
            out.write(json.dumps(rec, separators=(",", ":")) + "\n")
            print(st["state"], st["kind"], len(steps), "steps", sum(len(x["cands"]) for x in steps), "candidate-steps", file=sys.stderr)


# --------------------------------------------------------------------------------------------
# score


FLICKER_S = 3.0  # a figure that turns individual and back (or back and individual) within this


def flicker_stats(series, step_s):
    """`series`: {id: [True (individual) | False (throng) | None (out of sight) per step]} over
    the window. A flicker is a stint, individual or throng, shorter than FLICKER_S with a change
    between individual and throng on both sides, the creature in sight throughout: what a player
    would see as a figure popping out of the throng and back (or dropping into it and back).
    Coming into or leaving sight is not counted here."""
    events, flickering = 0, 0
    for _, v in series.items():
        f = 0
        # Split at out-of-sight steps: each part is a stretch in sight.
        part = []
        for x in v + [None]:
            if x is None:
                if part:
                    runs = []
                    cur, n = part[0], 0
                    for y in part:
                        if y == cur:
                            n += 1
                        else:
                            runs.append((cur, n))
                            cur, n = y, 1
                    runs.append((cur, n))
                    for i, (_, n) in enumerate(runs):
                        if 0 < i < len(runs) - 1 and n * step_s < FLICKER_S:
                            f += 1
                part = []
            else:
                part.append(x)
        events += f
        flickering += 1 if f else 0
    return events, flickering


def score(a):
    data = json.load(open(a.states))
    states = {s["state"]: s for s in data["states"]}
    fld = {}
    for line in open(a.fields):
        r = json.loads(line)
        fld[r["state"]] = r
    picks = {}
    for line in open(a.picks):
        r = json.loads(line)
        picks.setdefault(r["state"], []).append(r)
    battles, towns = {}, {}
    per = []
    for sid, st in states.items():
        steps = sorted(picks.get(sid, []), key=lambda r: r["t"])
        if not steps:
            continue
        att = {r["t"]: {p[0] for p in r["picks"]} for r in steps}
        by_rule = {r["t"]: {p[0] for p in r["picks"] if p[1] >= 0} for r in steps}
        times = sorted(att)
        step_s = (times[1] - times[0]) if len(times) > 1 else 1.0
        ev = {}
        for r in steps:
            for e in r.get("events", []):
                ev[(e["kind"], e["use"])] = e

        def heeded_at(sec, who):
            ts = [x for x in times if x <= sec + 1e-9]
            return bool(ts) and who in att[ts[-1]]

        def nearest_rank(sec, who):
            f = fld[sid]["steps"]
            ss = [x for x in f if x["t"] <= sec + 1e-9]
            if not ss:
                return None
            cs = sorted(ss[-1]["cands"], key=lambda c: c["dist"])
            for i, c in enumerate(cs):
                if c["id"] == who:
                    return i
            return None

        m = {"state": sid, "kind": st["kind"], "capacity": steps[-1].get("capacity"), "in_sight": st["in_sight"], "refused": steps[-1].get("refusal")}
        win = [x for x in times if -1e-9 <= x <= WINDOW_S + 1e-9]
        mins = (win[-1] - win[0]) / 60.0 if len(win) > 1 else 0
        # M3: churn (ids entering or leaving per minute; promotions per second), and flicker.
        changes = sum(len(att[x0] ^ att[x1]) for x0, x1 in zip(win, win[1:]))
        promos = sum(len(att[x1] - att[x0]) for x0, x1 in zip(win, win[1:]))
        m["churn_per_min"] = round(changes / mins, 2) if mins else None
        m["promotions_per_s"] = round(promos / (mins * 60), 3) if mins else None
        m["heeded_mean"] = round(sum(len(att[x]) for x in win) / max(len(win), 1), 2)
        m["by_rule_mean"] = round(sum(len(by_rule[x]) for x in win) / max(len(win), 1), 2)
        ids = set().union(*(att[x] for x in win)) if win else set()
        in_sight = {}
        for x in fld[sid]["steps"]:
            in_sight[round(x["t"], 3)] = {c["id"] for c in x["cands"]}
        series = {i: [(i in att[x]) if i in in_sight.get(round(x, 3), set()) else None for x in win] for i in ids}
        sight_changes = sum(len(in_sight.get(round(x0, 3), set()) ^ in_sight.get(round(x1, 3), set())) for x0, x1 in zip(win, win[1:]))
        m["sight_changes_per_min"] = round(sight_changes / mins, 2) if mins else None
        fe, ff = flicker_stats(series, step_s)
        m["flicker_per_min"] = round(fe / mins, 2) if mins else None
        m["figures"] = len(ids)
        m["figures_flickering"] = ff
        if st["kind"] == "battle":
            B = battles.get(st["run"]) or battles.setdefault(st["run"], Battle(battle_dir(a.src, st["run"], st)))
            t0 = st["t_ms"]
            # M1: per attacker, its FIRST landed blow in the window: was it heeded when that
            # blow's windup started (heeded already, or taken by the event pass)? And later blows
            # from the same attacker landing while it was not heeded (forced contact should keep
            # these at zero within the contact window).
            first, first_un, later, later_un = 0, 0, 0, 0
            windups, windups_un = 0, 0
            seen_attackers = set()
            for u in B.at_target.get(st["subject"], []):
                rel = (u["accepted_ms"] - t0) / 1000
                if not (0 <= rel <= WINDOW_S) or u["skill"] not in HOSTILE:
                    continue
                e = ev.get(("windup", u["id"]))
                if e is None:
                    continue  # out of sight at its start (distance only), or the subject gone
                heeded = e["already"] or e["verdict"] in ("take", "replace", "forced")
                windups += 1
                windups_un += 0 if heeded else 1
                if not landed(u.get("outcome", "")):
                    continue
                if u["actor"] not in seen_attackers:
                    seen_attackers.add(u["actor"])
                    first += 1
                    first_un += 0 if heeded else 1
                else:
                    later += 1
                    later_un += 0 if heeded else 1
            m.update({"windups": windups, "windups_unheeded": windups_un, "first_blows": first, "first_blows_unheeded": first_un,
                      "later_blows": later, "later_blows_unheeded": later_un})
            acted = []
            p = os.path.join(battle_dir(a.src, st["run"], st), "journal/outcomes/act_attempts.jsonl")
            for line in (open(p) if os.path.exists(p) else []):
                x = json.loads(line)
                mm = re.match(r"deliberate-(\d+)-", x.get("reference", ""))
                if not mm or int(mm.group(1)) != st["subject"]:
                    continue
                rel = (x["at_ms"] - t0) / 1000
                if 0 <= rel <= WINDOW_S:
                    for s_ in x.get("acts", []):
                        try:
                            for i in ids_in(json.loads(s_)):
                                acted.append(("act", rel, i))
                        except ValueError:
                            pass
            for u in B.by_actor.get(st["subject"], []):
                rel = (u["accepted_ms"] - t0) / 1000
                if 0 <= rel <= WINDOW_S and u.get("target"):
                    acted.append(("use", rel, u["target"]))
        else:
            T = towns.get(st["run"]) or towns.setdefault(st["run"], load_town(town_dir(a.src, st["run"], st)))
            acted = [("act", (x["at_ms"] - st["t_ms"]) / 1000, i) for x in T.attempts if x["actor"] == st["subject"] and 0 <= (x["at_ms"] - st["t_ms"]) / 1000 <= WINDOW_S for i in x["named"]]
        rows = []
        for src, rel, who in acted:
            # Heeded just BEFORE the act (the step before it): acting on it forces it after.
            r = nearest_rank(rel, who)
            if r is None:
                continue  # not in sight then (distance only), or not a creature
            rows.append({"src": src, "heeded": heeded_at(rel - step_s, who), "beyond8": r >= 8})
        m["acted"] = rows
        per.append(m)
    agg = aggregate(per)
    json.dump({"manifest": data["manifest"], "per_state": per, "aggregate": agg}, open(a.out, "w"), indent=1)
    print(json.dumps(agg, indent=1))


def named_in_reply(reply, names):
    """The people a think reply names: `#id`s and the addressee of its `say` anywhere in its
    thought, intentions and speech, and characters' names written out (a full name, else a first
    name that only one character in the world bears). `names`: id -> name (audit truth)."""
    try:
        r = json.loads(reply[reply.find("{"):reply.rfind("}") + 1])
    except ValueError:
        return set()
    text = json.dumps({k: r.get(k) for k in ("thought", "intend", "say")}, ensure_ascii=False)
    ids = {int(x) for x in re.findall(r"#(\d+)", text)}
    say = r.get("say")
    if isinstance(say, dict) and isinstance(say.get("to"), int):
        ids.add(say["to"])
    full = {n: int(i) for i, n in names.items() if n and " " in n}
    first = {}
    for i, n in names.items():
        if n:
            first.setdefault(n.split()[0], set()).add(int(i))
    taken = set()
    for n, i in sorted(full.items(), key=lambda x: -len(x[0])):
        if re.search(r"\b" + re.escape(n) + r"\b", text):
            ids.add(i)
            taken.add(n.split()[0])
    for f, ii in first.items():
        if len(ii) == 1 and f not in taken and re.search(r"\b" + re.escape(f) + r"\b", text):
            ids |= ii
    return ids


def named(a):
    """M2' (docs/ATTENTION_E3.md §9, frozen before the real-mind run): for each state (a think
    request), the people its reply names who were in the subject's sight at the request's moment
    (the field at t = 0); the share the arm heeded at that moment, overall and beyond the 8 nearest."""
    data = json.load(open(a.states))
    fld = {json.loads(l)["state"]: json.loads(l) for l in open(a.fields)}
    picks = {}
    for line in open(a.picks):
        r = json.loads(line)
        picks.setdefault(r["state"], []).append(r)
    rows = []
    replies = {}
    for st in data["states"]:
        d = town_dir(a.src, st["run"], st)
        key = (d, st["journal"])
        if key not in replies:
            m = {}
            for line in open(os.path.join(d, "journal", st["journal"])):
                e = json.loads(line)
                if e.get("purpose") == "think" and e.get("reply"):
                    m[e["at_ms"]] = e["reply"]
            replies[key] = m
        reply = replies[key].get(st["t_ms"])
        if not reply or st["state"] not in fld:
            continue
        names = json.load(open(os.path.join(d, "names.json"))) if os.path.exists(os.path.join(d, "names.json")) else {}
        who = named_in_reply(reply, names) - {st["subject"]}
        steps = [x for x in fld[st["state"]]["steps"] if x["t"] <= 1e-9]
        if not steps:
            continue
        cands = sorted(steps[-1]["cands"], key=lambda c: c["dist"])
        rank = {c["id"]: i for i, c in enumerate(cands)}
        ps = [r for r in picks.get(st["state"], []) if r["t"] <= 1e-9]
        heeded = {p[0] for p in ps[-1]["picks"]} if ps else set()
        listed = None
        if getattr(a, "scene_only", False):
            # E5's M2'' (docs/ATTENTION_E5.md §3): only people the subject's own scene listed (the
            # authority's sight: cover, walls, the gaze band; docs/ATTENTION_E3.md §9.2). One named
            # but not listed was named from memory.
            sc = None
            for line in open(os.path.join(d, "journal", st["journal"])):
                e = json.loads(line)
                if e.get("purpose") == "think" and e.get("at_ms") == st["t_ms"]:
                    sc = scene_of(e)
                    break
            listed = {c.get("id") for c in (sc or {}).get("creatures", [])}
        for i in who:
            if i in rank and (listed is None or i in listed):
                rows.append({"state": st["state"], "id": i, "rank": rank[i], "heeded": i in heeded, "beyond8": rank[i] >= 8,
                             "beyond_capacity": rank[i] >= (ps[-1]["capacity"] if ps else 10)})
    out = {"named_in_sight": share(rows), "named_beyond8": share(rows, lambda r: r["beyond8"]), "named_beyond_capacity": share(rows, lambda r: r.get("beyond_capacity")),
           "scene_only": bool(getattr(a, "scene_only", False)), "states_with_a_named_in_sight": len({r["state"] for r in rows}),
           "states": len(data["states"]), "rows": rows}
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))


def share(rows, pred=lambda r: True):
    rs = [r for r in rows if pred(r)]
    return [round(100.0 * sum(1 for r in rs if r["heeded"]) / len(rs), 1) if rs else None, len(rs)]


def pct(v, q):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    return v[min(len(v) - 1, int(q * len(v)))]


def aggregate(per):
    out = {}
    for kind in ("battle", "town"):
        ps = [p for p in per if p["kind"] == kind]
        if not ps:
            continue
        rows = [r for p in ps for r in p["acted"]]
        minutes = len(ps) * WINDOW_S / 60.0
        o = {"states": len(ps),
             "capacity_p50": pct([p["capacity"] for p in ps], 0.5),
             "in_sight_p50_p90": [pct([p["in_sight"] for p in ps], 0.5), pct([p["in_sight"] for p in ps], 0.9)],
             "heeded_mean_p50": pct([p["heeded_mean"] for p in ps], 0.5),
             "churn_per_min_p50_p90": [pct([p["churn_per_min"] for p in ps], 0.5), pct([p["churn_per_min"] for p in ps], 0.9)],
             "promotions_per_s_mean": round(sum(p["promotions_per_s"] or 0 for p in ps) / len(ps), 3),
             "flicker_per_min_mean": round(sum(p["flicker_per_min"] or 0 for p in ps) / len(ps), 2),
             "sight_changes_per_min_mean": round(sum(p["sight_changes_per_min"] or 0 for p in ps) / len(ps), 2),
             "figures_flickering_pct": round(100.0 * sum(p["figures_flickering"] for p in ps) / max(1, sum(p["figures"] for p in ps)), 1),
             "M2_acted_heeded_pct_n": share(rows),
             "M2_acts_heeded_pct_n": share(rows, lambda r: r["src"] == "act"),
             "M2_uses_heeded_pct_n": share(rows, lambda r: r["src"] == "use"),
             "M2_beyond8_heeded_pct_n": share(rows, lambda r: r["beyond8"])}
        if kind == "battle":
            f = sum(p.get("first_blows", 0) for p in ps)
            fu = sum(p.get("first_blows_unheeded", 0) for p in ps)
            l = sum(p.get("later_blows", 0) for p in ps)
            lu = sum(p.get("later_blows_unheeded", 0) for p in ps)
            w = sum(p.get("windups", 0) for p in ps)
            wu = sum(p.get("windups_unheeded", 0) for p in ps)
            o.update({"windups": w, "windups_unheeded": wu, "first_blows": f, "first_blows_unheeded": fu, "later_blows": l, "later_blows_unheeded": lu,
                      "M1_first_blows_unheeded_per_100": round(100.0 * fu / f, 2) if f else None,
                      "M1_first_blows_unheeded_per_min": round(fu / minutes, 3),
                      "later_blows_unheeded_per_100": round(100.0 * lu / l, 2) if l else None})
        out[kind] = o
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--src", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--battle", type=int, default=200)
    f.add_argument("--town", type=int, default=100)
    f.add_argument("--town-min-sight", type=int, default=8, help="a town state needs at least this many in sight (8; §9's M2' uses 1)")
    f.add_argument("--battle-run", action="append", help="a battle_diag.py --all-bodies run folder (instead of the act trial's)")
    f.add_argument("--battle-all", action="store_true", help="every think request with --battle-min-sight others in sight, not a sample (E5)")
    f.add_argument("--battle-min-sight", type=int, default=9)
    f.add_argument("--town-run", action="append", help="a trials.py instance folder with record.bodies all (instead of the act trial's)")
    g = sub.add_parser("fields")
    g.add_argument("--src", required=True)
    g.add_argument("--states", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--step", type=float, default=0.2, help="battle step, seconds (a player's sweep is 0.2 s)")
    g.add_argument("--town-step", type=float, default=0.2, help="town step, seconds, for 5 Hz all-bodies towns (the act trial's town samples are 2 s whatever this is)")
    s = sub.add_parser("score")
    s.add_argument("--src", required=True)
    s.add_argument("--states", required=True)
    s.add_argument("--fields", required=True)
    s.add_argument("--picks", required=True)
    s.add_argument("--out", required=True)
    n = sub.add_parser("named")
    n.add_argument("--src", required=True)
    n.add_argument("--states", required=True)
    n.add_argument("--fields", required=True)
    n.add_argument("--picks", required=True)
    n.add_argument("--out", required=True)
    n.add_argument("--scene-only", action="store_true", help="count only people the subject's own scene listed (E5's M2'')")
    a = ap.parse_args()
    {"freeze": freeze, "fields": fields, "score": score, "named": named}[a.cmd](a)


if __name__ == "__main__":
    main()
