#!/usr/bin/env python3
"""An arena trial instance's fights, read from its evidence (read only): the timeline as it
happened, and the readings `arena_report.py` builds on (docs/COMBAT_MIND.md §5.4).

    living/tools/fight_timeline.py <instance dir> [...]   → markdown on stdout

- **Exposures**: the fixtures' pattern moves at the subject (a heavy `attack` from its windup, or
  a `bowshot` once loosed), each with its fixture's role, its meeting and its outcome.
- **Meetings**: the trial's notes "meeting k: <role> …" (R3's files, `arena_veteran.py`) split
  the exposures; a trial without them is one meeting.
- **In force**: the plan installed at a moment (`graphs.jsonl`), which install wrote its `combat`
  branch, and **ready**: whether the plan, with the routines it names (`mind_rows.jsonl`), holds an
  answer on a windup (an `if` on `doing` "winding up" or `threatened` whose branch dodges,
  guards, jumps, backs off, keeps its distance or flees), and whether that answer is in the
  `combat` branch. An answer elsewhere in the plan can be pre-empted by a combat branch that runs
  first: r2e heavy r1's fifth heavy landed with a windup dodge in its `current plan` routine,
  under a combat branch that held only `stay safe`.
- **Seen**: an estimate of whether the subject could see the fixture when its windup began, from
  the 5 Hz facing samples (`bodies.jsonl`, `record.bodies`) and the shipped sight laws: all round
  within `fov_near_m` (3 m; 2 m at night), `fov_focal_deg` (70°) either side out to the light's
  sight (11 m by day, 6 at night), `fov_side_deg` (110°) a third as far; with `fov_on` off, all
  round to the light's sight. Walls, the field's 10° margin for one already seen and a torch are
  not modelled, and night is taken as 20:00–06:00 (the shipped `night_hours`). `None` without
  samples within 0.5 s.

The timeline lists each exposure with what was in force, the subject's combat acts, the lines it
was told, each fast-lane call (trigger, timing, what came back, the branch it installed), the
other thoughts, installs by source, and what the subject said. Times are seconds into the trial.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIALS = ROOT / "living/trials"

COMBAT = {"dodge", "block", "jump", "attack", "strike", "bowshot", "firebolt", "throw", "shoot", "heal",
          "back_off", "keep_distance", "close_in", "circle", "flee", "yield"}
ANSWERS = {"dodge", "block", "jump", "back_off", "keep_distance", "flee"}
WORDS = ("attack", "struck", "strike", "hit", "dodge", "blow", "arrow", "shot", "block", "guard", "wound",
         "heal", "winds up", "dies", "died", "killed", "flee", "back off", "not ready", "breath")
# The shipped sight laws (living/scripts/skills.rhai `sight_in`, `fov_*`, `night_hours`).
SIGHT = {"day": 11.0, "night": 6.0}
FOV = {"focal_deg": 70.0, "side_deg": 110.0, "side_share": 1 / 3, "near_m": 3.0, "near_dark_m": 2.0}


def rows(p):
    return [json.loads(l) for l in open(p)] if p.exists() else []


def compact(v):
    return json.dumps(v, separators=(", ", ": "), ensure_ascii=False)


def branch(n, label="combat"):
    """The node labelled `label` in a graph, depth first (as `living_rules::graph::branch_of`)."""
    if isinstance(n, dict):
        if n.get("label") == label:
            return n
        n = list(n.values())
    if isinstance(n, list):
        for v in n:
            b = branch(v, label)
            if b is not None:
                return b
    return None


def windup_cond(c):
    """A condition that reads a windup at the subject: `doing` "winding up", or `threatened`."""
    s = json.dumps(c)
    return ('"doing"' in s and '"winding up"' in s) or '"threatened"' in s


def answers_in(node, routines, seen=None):
    """The (condition, skill) pairs in `node` that answer a windup, following `{"routine": name}`
    into the routines named (`routines`: name → graph)."""
    seen = seen if seen is not None else set()
    out = []
    if isinstance(node, dict):
        if "routine" in node and isinstance(node["routine"], str) and node["routine"] not in seen:
            seen.add(node["routine"])
            out += [(c, s, node["routine"]) for c, s, _ in answers_in(routines.get(node["routine"]), routines, seen)]
        cond = node.get("if", {}).get("cond") if isinstance(node.get("if"), dict) else None
        if cond is not None and windup_cond(cond):
            then = json.dumps(node["if"].get("then"))
            for skill in sorted(ANSWERS):
                if f'"{skill}"' in then:
                    out.append((compact(cond), skill, None))
        for v in node.values():
            out += answers_in(v, routines, seen)
    elif isinstance(node, list):
        for v in node:
            out += answers_in(v, routines, seen)
    # One entry per (condition, skill, routine).
    return list(dict.fromkeys(out))


def arena_of(d: Path):
    """The instance's trial, its pattern skill and its fixture roles (the trial file's `arena`;
    else by name: `arena-heavy…` the heavy blow, `arena-kiter…` the bow)."""
    s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    trial = s.get("trial") or d.name.rsplit("-", 2)[0]
    spec = {}
    f = TRIALS / f"{trial}.json"
    if f.exists():
        spec = json.loads(f.read_text()).get("arena") or {}
    heavy = spec.get("pattern", "attack" if trial.startswith("arena-heavy") or trial.startswith("arena-veteran") or trial.startswith("arena-fresh") else "bowshot") == "attack"
    return trial, ("attack" if heavy else "bowshot"), spec.get("foes", ["foe"]), s


class Fight:
    def __init__(self, d: Path):
        self.d = d
        self.trial, self.pattern, foe_roles, self.summary = arena_of(d)
        self.heavy = self.pattern == "attack"
        cast = json.loads((d / "cast.json").read_text())["roles"]
        self.S = cast["subject"][0]["id"]
        self.foes = {r: cast[r][0]["id"] for r in foe_roles if cast.get(r)}
        self.role_of = {v: k for k, v in self.foes.items()}
        last = {}
        for u in rows(d / "uses.jsonl"):
            last[u["id"]] = u  # the last row of each use carries its outcome
        self.uses = sorted(last.values(), key=lambda u: (u.get("accepted_ms") or u.get("at_ms") or 0, u["id"]))
        # Seconds into the trial on the runner's clock: a row's `t` is when the runner sampled it,
        # at or after its `at_ms`, so the latest (at_ms - t) is the closest to the trial's start.
        th = rows(d / "thoughts.jsonl")
        self.thoughts = th
        self.t0 = max((t["at_ms"] - t["t"] * 1000 for t in th if t.get("t") is not None), default=0)
        self.graphs = sorted((g for g in rows(d / "graphs.jsonl") if g["id"] == self.S and g.get("installed_ms")), key=lambda g: g["installed_ms"])
        self.fasts = [g for g in self.graphs if g.get("source") == "fast"]
        self.routine_rows = [(self.t0 + r["t"] * 1000, {x["name"]: json.loads(x["graph"]) if isinstance(x.get("graph"), str) and x["graph"] else x.get("graph") for x in r["rows"] if x.get("actor") == self.S})
                             for r in rows(d / "mind_rows.jsonl") if r["table"] == "routine"]
        self.bodies = [(b["ms"], b["b"]) for b in rows(d / "bodies.jsonl")]
        self.hours = [(self.t0 + x["t"] * 1000, x.get("hour")) for x in rows(d / "samples.jsonl") if x.get("hour") is not None]
        self.laws = self.summary.get("world_laws") or {}
        self.meeting_starts = sorted((self.t0 + e["t"] * 1000, e.get("text", "")) for e in rows(d / "events.jsonl")
                                     if e.get("do") == "note" and e.get("t") is not None and str(e.get("text", "")).startswith("meeting ") and " ends" not in e.get("text", ""))

    def T(self, ms):
        return (ms - self.t0) / 1000

    def exposures(self):
        out = []
        for u in self.uses:
            if u["actor"] in self.role_of and u["skill"] == self.pattern and u.get("target") == self.S and (u.get("accepted_ms") if self.heavy else u.get("released_ms")):
                out.append(u)
        meet = {}
        res = []
        for u in out:
            m = sum(1 for at, _ in self.meeting_starts if at <= u["accepted_ms"]) or 1
            meet[m] = meet.get(m, 0) + 1
            res.append({"use": u, "role": self.role_of[u["actor"]], "foe": u["actor"], "meeting": m, "k": meet[m], "at_ms": u["accepted_ms"],
                        "released_ms": u.get("released_ms"), "outcome": u.get("outcome")})
        return res

    def routines_at(self, ms):
        before = [r for at, r in self.routine_rows if at <= ms]
        return before[-1] if before else {}

    def plan_at(self, ms):
        before = [g for g in self.graphs if g["installed_ms"] <= ms]
        return before[-1] if before else None

    def in_force(self, ms):
        """The plan in force at `ms`: its source, its combat branch's author, ready or not (text)."""
        g = self.plan_at(ms)
        if not g:
            return "no plan recorded"
        cur = branch(json.loads(g["graph"]))
        r = self.ready(ms)
        where = "in the combat branch" if r["in_combat_branch"] else ("outside the combat branch, which runs first" if cur is not None else "in the plan")
        ready = f"ready, {where} ({'; '.join(f'{s} on a windup' + (f' in routine {rt}' if rt else '') for _, s, rt in r['answers'][:3])})" if r["answers"] else "not ready"
        if cur is None:
            return f"plan from {g['source']} at {self.T(g['installed_ms']):.1f} s, no combat branch; {ready}"
        by = "written by a slow decision"
        for i, f in enumerate(self.fasts, 1):
            if f["installed_ms"] <= ms and branch(json.loads(f["graph"])) == cur:
                by = f"fast patch {i} ({self.T(f['installed_ms']):.1f} s)"
        return f"plan from {g['source']} at {self.T(g['installed_ms']):.1f} s; combat branch {by}; {ready}"

    def ready(self, ms):
        """Whether the plan in force at `ms` (and the routines it names) answers a windup, and who
        wrote it: {answers: [(cond, skill, routine)], source, combat_by_fast, kept_routines}."""
        g = self.plan_at(ms)
        routines = self.routines_at(ms)
        if not g:
            return {"answers": [], "in_combat_branch": [], "source": None, "combat_by_fast": False, "kept_routines": []}
        graph = json.loads(g["graph"])
        cur = branch(graph)
        by_fast = cur is not None and any(f["installed_ms"] <= ms and branch(json.loads(f["graph"])) == cur for f in self.fasts)
        # Routines the plan does not name are kept, not running: listed apart.
        kept = sorted(n for n, rg in routines.items() if rg and answers_in(rg, routines))
        combat = answers_in(cur, routines) if cur is not None else []
        return {"answers": answers_in(graph, routines), "in_combat_branch": combat, "source": g.get("source"), "combat_by_fast": by_fast, "kept_routines": kept}

    def night_at(self, ms):
        h = [hr for at, hr in self.hours if at <= ms]
        hr = h[-1] if h else None
        return hr is not None and (hr % 24 >= 20 or hr % 24 < 6)

    def seen(self, ms, foe):
        """Whether the subject could see `foe` at `ms` (an estimate; see the module's notes)."""
        if not self.bodies:
            return None
        at, b = min(self.bodies, key=lambda x: abs(x[0] - ms))
        if abs(at - ms) > 500 or str(self.S) not in b or str(foe) not in b:
            return None
        sx, sy, face = b[str(self.S)][:3]
        fx, fy = b[str(foe)][:2]
        dist = math.hypot(fx - sx, fy - sy)
        light = "night" if self.night_at(ms) else "day"
        sight = SIGHT[light]
        if not self.laws.get("fov_on"):
            return dist <= sight
        near = FOV["near_dark_m"] if light == "night" else FOV["near_m"]
        if dist <= near:
            return True
        off = abs(math.degrees(math.atan2(math.sin(math.atan2(fy - sy, fx - sx) - face), math.cos(math.atan2(fy - sy, fx - sx) - face))))
        if off <= FOV["focal_deg"]:
            return dist <= sight
        if off <= FOV["side_deg"]:
            return dist <= sight * FOV["side_share"]
        return False


def timeline(d: Path):
    f = Fight(d)
    S, T = f.S, f.T
    ev = []
    ex = f.exposures()
    for e in ex:
        u = e["use"]
        ms = u["accepted_ms"] if f.heavy else u["released_ms"]
        seen = f.seen(u["accepted_ms"], e["foe"])
        meet = f" (meeting {e['meeting']}, {e['role']})" if f.meeting_starts else ""
        ev.append((ms, 0, f"**Exposure {e['k']}**{meet}: the {e['role']}'s {f.pattern} at the subject, windup at {T(u['accepted_ms']):.1f} s"
                   + (f", released {T(u['released_ms']):.1f} s" if u.get("released_ms") else "")
                   + f": **{u.get('outcome') or 'pending'}**." + ("" if seen is None else f" Seen at the windup: {'yes' if seen else 'no'} (estimate).")
                   + f" In force: {f.in_force(u['accepted_ms'])}"))
    for at, text in f.meeting_starts:
        ev.append((at, -1, f"**{text}**"))
    for u in f.uses:
        if u["actor"] == S and u["skill"] in COMBAT and u.get("accepted_ms"):
            ev.append((u["accepted_ms"], 1, f"subject {u['skill']} ({u.get('source')}): {u.get('outcome') or '–'}"))
    for e in rows(d / "experiences.jsonl"):
        if e.get("observer") == S and any(w in e.get("text", "").lower() for w in WORDS):
            ev.append((e["at_ms"], 2, f"told: “{e['text']}”"))
    for t in f.thoughts:
        if t["actor"] != S:
            continue
        if t["kind"] == "fast":
            dt = json.loads(t.get("detail") or "{}")
            rep = dt.get("reply") or {}
            timing = ""
            if dt.get("trigger_ms"):
                timing = (f" (trigger {T(dt['trigger_ms']):.1f} s, issued +{(dt['issued_ms'] - dt['trigger_ms']) / 1000:.1f} s, "
                          f"model {dt.get('model_ms', 0) / 1000:.1f} s, installed {T(t['at_ms']):.1f} s)")
            line = f"**fast call** on “{dt.get('reason')}”{timing}: {t['summary']}"
            if "patch" in rep:
                line += f"\n  - combat branch: `{compact((rep['patch'] or {}).get('graph'))}`"
            elif "switch" in rep:
                line += f"\n  - switch: `{compact(rep['switch'])}`"
            elif "routine" in rep:
                line += f"\n  - routine: `{compact(rep['routine'])}`"
            ev.append((t["at_ms"], 3, line))
        elif t["kind"] in ("deliberate", "think", "decide"):
            ev.append((t["at_ms"], 4, f"{t['kind']}: {t['summary'][:400]}"))
    for g in f.graphs:
        ev.append((g["installed_ms"], 5, f"plan installed ({g.get('source')}), plan: {(g.get('plan') or '')[:200]}"))
    for c in rows(d / "chronicle.jsonl"):
        if c.get("a") == S and c.get("kind") == "speech":
            ev.append((c["at_ms"], 6, f"said: {c['text']}"))
        elif c.get("kind") in ("death", "die", "died") and (c.get("a") == S or c.get("a") in f.role_of):
            ev.append((c["at_ms"], 7, f"**{c.get('text')}**"))
    first = ex[0]["at_ms"] if ex else None
    out = [f"## {d.name}", ""]
    if first is None:
        out.append("No exposures.")
        return "\n".join(out)
    for ms, _, s in sorted(ev):
        if ms < first - 30_000:
            continue
        out.append(f"- {T(ms):6.1f} s: {s}")
    return "\n".join(out)


if __name__ == "__main__":
    print("\n\n".join(timeline(Path(p)) for p in sys.argv[1:]))
