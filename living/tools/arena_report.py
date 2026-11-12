#!/usr/bin/env python3
"""Arena trials against a scripted opponent: does a mind's fighting change within one fight
after it has seen the opponent's pattern? (docs/COMBAT_MIND.md §4.2, Measure 1; R2)

    living/tools/arena_report.py .local/living/trials/r2 [--json OUT] [--md OUT]

Reads each instance's evidence (`uses.jsonl` from the trial's `record.uses`, `positions.jsonl`,
`experiences.jsonl`, `thoughts.jsonl`, `graphs.jsonl`, `chronicle.jsonl`, the journal). Read only.

Exposures are the opponent's pattern moves aimed at the subject, from `skill_use`:
- `arena-heavy`: each heavy blow (`attack`, a 750 ms windup). It is **answered** when it did not
  land in full: dodged, guarded (blocked, part got through) or out of reach ("missed"). A
  defence is the subject's dodge, guard or jump accepted during the windup; a counter is the
  subject's blow or shot accepted within 2.5 s after the release (the opponent's pause).
- `arena-kiter`: each arrow loosed at the subject (`bowshot` released). It is answered when it
  did not strike the subject. Return fire is the subject's bow shots and fire bolts at the
  opponent; closing is the subject coming within 6 m of it (positions, every 2 s).

Per instance it reports the answered share by exposure index, the first exposure after which
three in a row were answered (K), the subject's responses before and after its first exposure,
the mind's revisions and words between exposures (thoughts naming the pattern, own timings and
outcome lines used), lines it spoke that carry an internal id (`#123`), and model calls, latency
and estimated cost per fight; and, per routine install (`mind_rows.jsonl`'s `routine` rows; not
`graphs.jsonl`, which holds only the desires wrapper), each `doing` condition that leads to a
dodge, with its `is`, `phase`, `at_me` and `within`, the install time and the exposure index then. The word lists are shown with their matches; they are a reader's
aid, not a classifier the mind depends on.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trials import PRICES  # noqa: E402

PATTERN_WORDS = {
    "arena-heavy": re.compile(r"\b(heavy|slow|windup|wind(?:s|ing)? up|telegraph\w*|swing\w*|lunge\w*|thrust\w*|step(?:ping)? back|out of (?:its |her |his |their )?reach|pause\w*|between (?:blows|swings)|after (?:it|she|he|they) (?:swing|strike)s?|every time|each time|rhythm|spear)\b", re.I),
    "arena-kiter": re.compile(r"\b(arrows?|bow|shoot\w*|shot|range|distance|keeps? (?:away|back|its distance)|runs? (?:off|away)|flee\w*|backs? off|cover|behind|wall|tree|close (?:in|the distance)|charge|out of (?:its |her |his )?sight|line of sight)\b", re.I),
}
TIMING = re.compile(r"\b(\d{2,4} ?ms|0\.\d+ ?s|winds? up \d|ready again|cooldown|recover\w*)\b", re.I)
OWN_LINE = re.compile(r"^You (finished: |failed to )(strike|attack|bowshot|firebolt|throw|shoot|block|dodge|heal)")
IDS = re.compile(r"#\d+")


def rows(p):
    return [json.loads(l) for l in open(p)] if p.exists() else []


def last_uses(d):
    out = {}
    for r in rows(d / "uses.jsonl"):
        out[r["id"]] = r
    return sorted(out.values(), key=lambda r: (r.get("accepted_ms") or r.get("attempt_ms") or 0, r["id"]))


def classify(o):
    o = (o or "").lower()
    if o.startswith("hit for") or "killed" in o or re.search(r"struck [^:]*: hit for", o):
        return "hit"
    if "got through" in o or o.startswith("blocked"):
        return "guarded"
    if "dodged" in o:
        return "dodged"
    # Out of reach: missed at the release, or refused at it because the target had moved away.
    if "missed" in o or "out of reach" in o or "moved away" in o or "hit nothing" in o or "struck a wall" in o:
        return "evaded"
    if "broken off" in o:
        return "broken"
    if o.startswith("struck "):
        return "struck_other"
    return o[:30] or "pending"


def dodges_in(node):
    """Whether a graph (sub)tree makes a dodge: a `do` of `dodge`, short or long form."""
    if isinstance(node, dict):
        d = node.get("do")
        if d == "dodge" or (isinstance(d, dict) and d.get("skill") == "dodge"):
            return True
        return any(dodges_in(v) for v in node.values())
    if isinstance(node, list):
        return any(dodges_in(v) for v in node)
    return False


def doing_conds(cond):
    """The `doing` conditions in a condition (through `all`, `any`, `not`)."""
    if isinstance(cond, dict):
        if "doing" in cond:
            return [cond["doing"]]
        return [c for v in cond.values() for c in doing_conds(v)]
    if isinstance(cond, list):
        return [c for v in cond for c in doing_conds(v)]
    return []


def doing_to_dodge(graph):
    """Each `doing` condition of an `if` whose `then` makes a dodge, anywhere in the graph."""
    out = []
    def walk(n):
        if isinstance(n, dict):
            i = n.get("if")
            if isinstance(i, dict) and dodges_in(i.get("then")):
                out.extend(doing_conds(i.get("cond")))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(graph)
    return out


def dodge_conditions(d, k_at, t0_ms):
    """The installed routines (`mind_rows.jsonl`, `routine` rows; `graphs.jsonl` holds only the
    desires wrapper) whose `doing` conditions lead to a dodge: per install, its time, the
    exposure index then, the routine and each condition's `is`, `phase`, `at_me`, `within`.
    Shows whether a mind's conditions move (from "winding up" toward "about to release", say)."""
    out, prev = [], {}
    for x in rows(d / "mind_rows.jsonl"):
        if x.get("table") != "routine":
            continue
        for r in x.get("rows") or []:
            g = r.get("graph") or ""
            if prev.get(r.get("id")) == g:
                continue
            prev[r.get("id")] = g
            try:
                conds = doing_to_dodge(json.loads(g))
            except (ValueError, TypeError):
                continue
            if conds:
                ms = t0_ms + x["t"] * 1000 if t0_ms else None
                out.append({"t": x["t"], "k": k_at(ms) if ms else None, "routine": r.get("name"),
                            "conds": [{k: c.get(k) for k in ("is", "phase", "at_me", "within") if c.get(k) is not None} for c in conds]})
    return out


def k_of(answered, run=3):
    for i in range(len(answered) - run + 1):
        if all(answered[i:i + run]):
            return i + 1
    return None


def instance(d: Path):
    s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    trial = s.get("trial") or d.name.rsplit("-", 2)[0]
    cast = json.loads((d / "cast.json").read_text())["roles"]
    S = cast["subject"][0]["id"]
    F = cast["foe"][0]["id"]
    uses = last_uses(d)
    heavy = trial == "arena-heavy"
    pattern = "attack" if heavy else "bowshot"
    ex = [u for u in uses if u["actor"] == F and u["skill"] == pattern and u.get("target") == S and (u.get("released_ms") if not heavy else u.get("accepted_ms"))]
    mine = [u for u in uses if u["actor"] == S and u.get("accepted_ms")]
    exposures = []
    for k, u in enumerate(ex, 1):
        acc, rel = u["accepted_ms"], u.get("released_ms") or (u["accepted_ms"] + 750)
        cls = classify(u.get("outcome"))
        defence = [m["skill"] for m in mine if m["skill"] in ("dodge", "block", "jump") and acc <= m["accepted_ms"] <= rel + 50]
        counter = [m["skill"] for m in mine if m["skill"] in ("strike", "attack", "bowshot", "firebolt", "throw", "shoot") and rel <= m["accepted_ms"] <= rel + 2500]
        ans = cls in ("guarded", "dodged", "evaded") if heavy else cls not in ("hit",)
        exposures.append({"k": k, "at_ms": acc, "outcome": u.get("outcome"), "class": cls, "answered": ans, "defence": defence, "counter": counter})
    first_ms = exposures[0]["at_ms"] if exposures else None
    # The subject's responses before and after its first exposure (all its accepted uses).
    def mix(us):
        m = {}
        for u in us:
            m[u["skill"]] = m.get(u["skill"], 0) + 1
        return m
    before = mix([u for u in mine if first_ms and u["accepted_ms"] < first_ms])
    after = mix([u for u in mine if first_ms and u["accepted_ms"] >= first_ms])
    # Fight span: the first exposure to the last exposure, or the subject's death.
    death_ms = None
    for e in rows(d / "experiences.jsonl"):
        pass
    end_ms = exposures[-1]["at_ms"] if exposures else None
    # Positions: distance subject-foe each sample (kiter: closing within 6 m).
    dist = []
    for p in rows(d / "positions.jsonl"):
        a, b = p["pos"].get(str(S)), p["pos"].get(str(F))
        if a and b:
            dist.append((p["ms"], ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5))
    closing = sum(1 for (t0, d0), (t1, d1) in zip(dist, dist[1:]) if first_ms and t1 >= first_ms and d1 < 6.0 <= d0)
    ret_fire = [u for u in mine if u["skill"] in ("bowshot", "firebolt", "throw", "shoot") and u.get("target") == F]
    ret_hits = sum(classify(u.get("outcome")) == "hit" for u in ret_fire)
    # The mind: graph revisions and deliberations, by exposure index.
    t0_ms = None
    thoughts = rows(d / "thoughts.jsonl")
    graphs = rows(d / "graphs.jsonl")
    if thoughts:
        t0_ms = max(x["at_ms"] - x["t"] * 1000 for x in thoughts)
    def k_at(ms):
        return sum(1 for e in exposures if e["at_ms"] <= ms)
    delib = [x for x in thoughts if x["kind"] == "deliberate" and first_ms and x["at_ms"] >= first_ms - 5000]
    revisions = [{"k": k_at(t0_ms + g["t"] * 1000), "t": g["t"]} for g in graphs if t0_ms and first_ms and t0_ms + g["t"] * 1000 >= first_ms]
    words = PATTERN_WORDS[trial]
    noticed = [{"k": k_at(x["at_ms"]), "words": sorted({m.group(0).lower() for m in words.finditer(x["summary"])}), "thought": x["summary"][:260]}
               for x in delib if words.search(x["summary"])]
    journal = []
    for f in (d / "journal").glob("*.jsonl"):
        journal += rows(f)
    calls = [j for j in journal if j.get("purpose") in ("think", "deliberate", "talk", "consolidate") and (not first_ms or j["at_ms"] >= first_ms - 5000)]
    replies = " ".join((j.get("reply") or "") for j in calls if j.get("purpose") in ("think", "deliberate"))
    timing_used = sorted({m.group(0).lower() for m in TIMING.finditer(replies)})
    own_lines = [e["text"] for e in rows(d / "experiences.jsonl") if e["kind"] == "own" and OWN_LINE.match(e["text"])]
    spoken = [c.get("text", "") for c in rows(d / "chronicle.jsonl") if c.get("a") == S and c.get("kind") in ("speech", "write")]
    said_ids = [t for t in spoken if IDS.search(t)]
    cost = 0.0
    for j in journal:
        pr = PRICES.get(j.get("model"))
        if pr:
            p, c, cached = j.get("prompt_tokens") or 0, j.get("completion_tokens") or 0, j.get("cached_tokens") or 0
            cost += ((p - cached) * pr[0] + c * pr[1] + cached * pr[2]) / 1e6
    lat = sorted(j.get("latency_ms", 0) / 1000 for j in calls if j.get("purpose") in ("think", "deliberate"))
    ans = [e["answered"] for e in exposures]
    return {
        "run": d.name, "trial": trial, "survived": s.get("survived"), "died_min": s.get("died_min"), "hp_min": s.get("hp_min"),
        "exposures": len(exposures), "answered": sum(ans),
        "answered_first3": f"{sum(ans[:3])}/{len(ans[:3])}", "answered_after3": f"{sum(ans[3:])}/{len(ans[3:])}",
        "K": k_of(ans), "by_k": [(e["k"], e["class"], "+".join(e["defence"]) or "-", "+".join(e["counter"]) or "-") for e in exposures],
        "subject_before_first": before, "subject_after_first": after,
        "closing_within_6m": closing if not heavy else None, "return_fire": len(ret_fire), "return_fire_hits": ret_hits,
        "deliberations_in_fight": len(delib), "revisions_in_fight": len(revisions), "revision_ks": [r["k"] for r in revisions],
        "noticed": noticed, "timing_words_in_replies": timing_used, "own_outcome_lines": len(own_lines), "own_outcome_examples": own_lines[:4],
        "spoken": len(spoken), "spoken_with_id": said_ids,
        "calls": len(calls), "latency_s_p50": round(statistics.median(lat), 1) if lat else None, "latency_s_max": round(max(lat), 1) if lat else None,
        "cost_usd": round(cost, 4),
        "dodge_conditions": dodge_conditions(d, k_at, t0_ms),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--json")
    a = ap.parse_args()
    out = [instance(d) for d in sorted(Path(a.batch).iterdir()) if d.is_dir() and (d / "cast.json").exists() and d.name.startswith("arena-")]
    text = json.dumps(out, indent=1, ensure_ascii=False)
    if a.json:
        Path(a.json).write_text(text + "\n")
    for r in out:
        print(f"{r['run']}: survived {r['survived']} hp_min {r['hp_min']} exposures {r['exposures']} answered {r['answered']} (first3 {r['answered_first3']}, after {r['answered_after3']}) K {r['K']} "
              f"delib {r['deliberations_in_fight']} revs {r['revision_ks']} noticed {len(r['noticed'])} timing {r['timing_words_in_replies'][:6]} own_lines {r['own_outcome_lines']} "
              f"ret_fire {r['return_fire']}/{r['return_fire_hits']} closing {r['closing_within_6m']} ids {len(r['spoken_with_id'])}/{r['spoken']} calls {r['calls']} lat {r['latency_s_p50']} ${r['cost_usd']}")
        for c in r["dodge_conditions"]:
            print(f"  doing -> dodge at {c['t']:.0f} s (exposure {c['k']}), {c['routine']}: " + "; ".join(", ".join(f"{k} {v}" for k, v in x.items()) for x in c["conds"]))


if __name__ == "__main__":
    main()
