#!/usr/bin/env python3
"""The fast-lane frame trial's report (docs/FAST_LANE_FRAME.md): saved battle_diag.py run
directories of the frame arms (`--law fast_frame=1|2`), by arm and by persona cohort.

  flf_report.py RUN_DIR [RUN_DIR ...] > report.json

Per run, per arm (its runs pooled) and per persona cohort within each arm: the six exposure
measures of flb_report.py (attacks attempted, time in contact, engagements, retreats with
re-engagement, damage taken and dealt, idle or away share), timed defence, the installed patches
classified as in docs/FAST_LANE_WHY_TABLES.md ("Direction of the edits"), cost and the host's
load. The arm is read from each run's laws (`fast_frame`), the cohort from `persona_of`.
"""
import argparse
from bisect import bisect_left
from collections import defaultdict
import gzip
import json
from pathlib import Path
from statistics import mean

from flb_report import ATTACKS, DEFENCES, combat_samples, read_json, read_lines, recorded_cost

RETREATS = {"flee", "back_off"}
OFFENCE = ATTACKS | {"close_in"}
COUNTED = ("attacks_attempted", "engagements_started", "retreats", "retreats_reengaged",
           "retreats_no_reengagement", "retreats_censored", "damage_taken", "damage_dealt")
TIMES = ("observed", "contact", "away", "idle", "idle_or_away")


def frame_of(head):
    for law in head.get("laws") or []:
        name, _, value = law.partition("=")
        if name == "fast_frame":
            return f"v{int(float(value))}"
    return "v2"


def skill_of(node):
    do = node.get("do")
    if isinstance(do, dict):
        do = do.get("skill")
    return do if isinstance(do, str) else None


def children(node):
    for key in ("first", "seq"):
        if key in node:
            v = node[key]
            if isinstance(v, dict):
                v = v.get("children", [])
            return [c for c in v if isinstance(c, dict)] if isinstance(v, list) else []
    if "desires" in node and isinstance(node["desires"], list):
        return [d["do"] for d in node["desires"] if isinstance(d, dict) and isinstance(d.get("do"), dict)]
    return []


def guarded(node):
    """(the guard's condition, its then and else children) of an `if` node in either grammar."""
    if "if" not in node:
        return None
    if isinstance(node["if"], dict) and "cond" in node["if"]:
        inner = node["if"]
        return inner["cond"], [x for x in (inner.get("then"), inner.get("else")) if isinstance(x, dict)]
    return node["if"], [x for x in (node.get("then"), node.get("else")) if isinstance(x, dict)]


def mentions(cond, words):
    text = json.dumps(cond)
    return any(w in text for w in words)


def walk(node, conds=()):
    """Action nodes in graph traversal order, with the conditions enclosing each."""
    if not isinstance(node, dict):
        return
    g = guarded(node)
    if g is not None:
        cond, branches = g
        for b in branches:
            yield from walk(b, conds + (cond,))
        return
    skill = skill_of(node)
    if skill:
        yield skill, conds
        return
    if "routine" in node and isinstance(node["routine"], str):
        yield f"routine:{node['routine']}", conds
        return
    for c in children(node):
        yield from walk(c, conds)


def classify(reply):
    """A reply's graph by the WHY tables' direction flags; a switch is its own kind."""
    if reply.get("switch"):
        return {"kind": "switch"}
    graph = (reply.get("patch") or {}).get("graph") if reply.get("patch") else (reply.get("routine") or {}).get("graph")
    kind = "patch" if reply.get("patch") else "routine"
    acts = list(walk(graph or {}))
    retreats = [i for i, (s, _) in enumerate(acts) if s in RETREATS]
    bare = [i for i in retreats if not acts[i][1]]
    attacks = [i for i, (s, _) in enumerate(acts) if s in ATTACKS]
    first_attack = attacks[0] if attacks else len(acts)
    press = any(s == "close_in" or (s in ATTACKS and any(mentions(c, ("recovering", "releasing", "about to release", "winding up", "health_of")) for c in conds))
                for s, conds in acts)
    return {
        "kind": kind,
        "retreat": bool(retreats),
        "unconditioned_retreat": bool(bare),
        "retreat_ahead_of_attack": bool(retreats) and retreats[0] < first_attack,
        "unconditioned_retreat_ahead_of_attack": bool(bare) and bare[0] < first_attack,
        "conditioned_retreat_only": bool(retreats) and not bare,
        "any_attack_or_close_in": any(s in OFFENCE for s, _ in acts),
        "explicit_press": press,
    }


def patches(path):
    """Installed fast replies (thought rows of kind fast neither kept nor refused), from the
    final export (else the last window's)."""
    file = path / "fast-final.json"
    if file.exists():
        rows = read_json(file)
    else:
        # Runs before fast-final: the windows' exports hold the detail, fast-patched.json the
        # actor and summary; joined by time where one detail matches (as flb_report does).
        detail = defaultdict(list)
        for w in sorted(path.glob("fast-[0-9][0-9].json")):
            seen = defaultdict(list)
            for row in read_json(w):
                seen[row["at_ms"]].append(row["detail"])
            detail.update(seen)
        patched = path / "fast-patched.json"
        rows = [{**r, "detail": detail[r["at_ms"]][0]} for r in (read_json(patched) if patched.exists() else []) if len(detail.get(r["at_ms"], [])) == 1]
    out = []
    for row in rows:
        summary = str(row.get("summary", ""))
        if not summary or summary.startswith(("kept", "refused")):
            continue
        try:
            detail = json.loads(row["detail"])
        except (ValueError, TypeError, KeyError):
            continue
        out.append({"actor": row.get("actor"), "at_ms": row["at_ms"], **classify(detail.get("reply") or {})})
    return out


def patch_table(rows):
    n = len(rows)
    flags = ("retreat", "unconditioned_retreat", "retreat_ahead_of_attack", "unconditioned_retreat_ahead_of_attack",
             "conditioned_retreat_only", "any_attack_or_close_in", "explicit_press")
    kinds = defaultdict(int)
    for r in rows:
        kinds[r["kind"]] += 1
    graphs = [r for r in rows if r["kind"] != "switch"]
    return {"installs": n, "by_kind": dict(kinds),
            **{f: {"n": sum(bool(r.get(f)) for r in graphs), "pct": 100 * sum(bool(r.get(f)) for r in graphs) / n if n else None} for f in flags}}


def defence_by_target(path, fighters):
    """Timed defence from the combat samples: each accepted attack at a fighter, met when the
    target's dodge, block or jump was accepted between the attack's acceptance and its outcome
    (+50 ms). -> {target: [met, blows]}"""
    uses = {}
    with gzip.open(path / "combat-samples.jsonl.gz", "rt") as stream:
        for line in stream:
            sample = json.loads(line)
            for u in sample.get("uses", []):
                uses[u["id"]] = u
    defended = defaultdict(list)
    for u in uses.values():
        if u["skill"] in DEFENCES and u["accepted_ms"]:
            defended[u["actor"]].append(u["accepted_ms"])
    for v in defended.values():
        v.sort()
    out = defaultdict(lambda: [0, 0])
    for u in uses.values():
        if u["skill"] not in ATTACKS or not u["accepted_ms"] or u["target"] not in fighters or u["target"] == u["actor"]:
            continue
        end = (u.get("outcome_ms") or u["accepted_ms"] + 750) + 50
        times = defended.get(u["target"], [])
        i = bisect_left(times, u["accepted_ms"])
        out[u["target"]][0] += i < len(times) and times[i] <= end
        out[u["target"]][1] += 1
    return out


def cost(path):
    calls = [row for file in sorted((path / "journal").glob("*.jsonl")) for row in read_lines(file) if row.get("purpose") == "fast"]
    costs = [recorded_cost(c) for c in calls]
    return {"calls": len(calls), "failures": sum(bool(c.get("error")) for c in calls), "unpriced": costs.count(None),
            "usd": sum(c for c in costs if c is not None),
            "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls), "cached_tokens": sum(c.get("cached_tokens") or 0 for c in calls),
            "completion_tokens": sum(c.get("completion_tokens") or 0 for c in calls)}


def measures(fighters, actors, defence):
    """The six exposure measures (and timed defence) over a set of fighter ids."""
    counts = defaultdict(float)
    seconds = defaultdict(float)
    met = blows = 0
    for a in actors:
        f = fighters.get(a)
        if not f:
            continue
        seconds["observed"] += f["observed_seconds"]
        for k in TIMES[1:]:
            seconds[k] += f.get(f"{k}_seconds") or 0
        for k, v in f["events"].items():
            counts[k] += v
        m, b = defence.get(a, (0, 0))
        met, blows = met + m, blows + b
    minutes = seconds["observed"] / 60
    per_min = lambda k: counts[k] / minutes if minutes else None
    return {
        "fighters": sum(1 for a in actors if a in fighters), "observed_fighter_minutes": minutes,
        "attacks_attempted": counts["attacks_attempted"], "attacks_per_fighter_minute": per_min("attacks_attempted"),
        "attacks_per_contact_minute": 60 * counts["attacks_attempted"] / seconds["contact"] if seconds["contact"] else None,
        "contact_share": seconds["contact"] / seconds["observed"] if seconds["observed"] else None,
        "engagements_started": counts["engagements_started"], "engagements_per_fighter_minute": per_min("engagements_started"),
        "retreats": counts["retreats"], "retreats_reengaged": counts["retreats_reengaged"],
        "retreats_no_reengagement": counts["retreats_no_reengagement"], "retreats_censored": counts["retreats_censored"],
        "reengaged_share": counts["retreats_reengaged"] / counts["retreats"] if counts["retreats"] else None,
        "damage_taken": counts["damage_taken"], "damage_taken_per_fighter_minute": per_min("damage_taken"),
        "damage_dealt": counts["damage_dealt"], "damage_dealt_per_fighter_minute": per_min("damage_dealt"),
        "idle_share": seconds["idle"] / seconds["observed"] if seconds["observed"] else None,
        "away_share": seconds["away"] / seconds["observed"] if seconds["observed"] else None,
        "idle_or_away_share": seconds["idle_or_away"] / seconds["observed"] if seconds["observed"] else None,
        "timed_defence": {"met": met, "blows": blows, "pct": 100 * met / blows if blows else None},
    }


def run_report(path):
    head = read_json(path / "diag-result.json")
    rows = list(read_lines(path / "diag.jsonl"))
    combat = combat_samples(path, head)
    if not combat.get("available"):
        raise ValueError(f"{path}: {combat.get('reason')}")
    fighters = {int(k): v for k, v in combat["fighters"].items()}
    persona_of = {int(k): v for k, v in (head.get("persona_of") or {}).items()}
    cohort = {a: p.rsplit("-", 1)[0] for a, p in persona_of.items()}
    defence = defence_by_target(path, set(fighters))
    installed = patches(path)
    by_cohort = defaultdict(list)
    for a in fighters:
        by_cohort[cohort.get(a, "none")].append(a)
    loads = [x for r in rows for x in r.get("load_1m", [])]
    return {
        "run": path.name, "arm": frame_of(head), "status": head.get("status"), "minutes": head.get("minutes"),
        "battle": head.get("battle"), "world_seed": head.get("world_seed"), "site": head.get("site"),
        "laws": head.get("laws"), "personas": head.get("personas"),
        "layout": [x["at"] for x in head.get("layout", [])], "layout_personas": [x.get("persona") for x in head.get("layout", [])],
        "deaths": rows[-1]["fighter_deaths"] if rows else None, "respawns": rows[-1]["respawns"] if rows else None,
        "ticks_per_s": mean(r["ticks_per_s"] for r in rows if r["t_min"] >= 2) if any(r["t_min"] >= 2 for r in rows) else None,
        "load_1m": {"min": min(loads), "mean": mean(loads), "max": max(loads)} if loads else None,
        "window_defence": {"met": sum(r["defence"]["met"] for r in rows), "blows": sum(r["defence"]["blows"] for r in rows),
                           "patched_met": sum(r["defence"]["patched_met"] for r in rows), "patched_blows": sum(r["defence"]["patched_blows"] for r in rows)},
        "all": measures(fighters, list(fighters), defence),
        "by_persona": {c: measures(fighters, ids, defence) for c, ids in sorted(by_cohort.items())},
        "patches": patch_table(installed),
        "patches_by_persona": {c: patch_table([p for p in installed if cohort.get(p["actor"], "none") == c]) for c in sorted(by_cohort)},
        "cost": cost(path),
        "_fighters": fighters, "_defence": defence, "_cohort": cohort, "_installed": installed,
    }


def pooled(runs):
    fighters, defence, cohort, installed = {}, {}, {}, []
    for i, r in enumerate(runs):
        # Fighter ids are per world: key them by run.
        fighters.update({(i, a): v for a, v in r["_fighters"].items()})
        defence.update({(i, a): v for a, v in r["_defence"].items()})
        cohort.update({(i, a): c for a, c in r["_cohort"].items()})
        installed.extend({**p, "actor": (i, p["actor"])} for p in r["_installed"])
    groups = defaultdict(list)
    for a in fighters:
        groups[cohort.get(a, "none")].append(a)
    usd = sum(r["cost"]["usd"] for r in runs)
    return {
        "runs": [r["run"] for r in runs],
        "all": measures(fighters, list(fighters), defence),
        "by_persona": {c: measures(fighters, ids, defence) for c, ids in sorted(groups.items())},
        "patches": patch_table(installed),
        "patches_by_persona": {c: patch_table([p for p in installed if cohort.get(p["actor"], "none") == c]) for c in sorted(groups)},
        "cost_usd": usd, "fast_calls": sum(r["cost"]["calls"] for r in runs), "fast_failures": sum(r["cost"]["failures"] for r in runs),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", type=Path, nargs="+")
    args = parser.parse_args()
    runs = [run_report(p) for p in args.runs]
    arms = defaultdict(list)
    for r in runs:
        arms[r["arm"]].append(r)
    same = {k: len({json.dumps(r[k]) for r in runs}) == 1 for k in ("world_seed", "site", "layout", "layout_personas", "battle", "minutes")}
    result = {"same_setup": same, "runs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in runs],
              "arms": {arm: pooled(rs) for arm, rs in sorted(arms.items())},
              "total_usd": sum(r["cost"]["usd"] for r in runs)}
    print(json.dumps(result, indent=1, allow_nan=False, default=str))


if __name__ == "__main__":
    main()
