#!/usr/bin/env python3
"""Read-only audit: what existing minds do during fights in trial evidence (docs/COMBAT_MIND.md §2).

    living/tools/fight_mind_audit.py ROOT/BATCH/INSTANCE ... [--json OUT]

For each trial instance directory (real-model runs; `--fake` runs are skipped), it finds the
subject's fights from its own experiences (`attacked` rows; a gap of 20 s or more starts a new
fight) and reports, per fight:

- when it began and ended (the last blow taken, or death), blows taken;
- the subject's own skills during the fight, from the 2 s samples;
- model calls (think, deliberate) that started from 15 s before the first blow to the end, and
  how many of them finished before the fight ended (journal `at_ms` is taken as the finish and
  `at_ms - latency_ms` as the start), with their latencies;
- graph revisions installed during the fight;
- stances (`judgments` in think replies) whose key or reason names the opponent's kind, with
  when they were written relative to the first blow;
- whether a reply's words describe how the opponent fights (a short word list: shown verbatim
  so a reader can judge, not a classifier the mind depends on).

It reads files only; it calls no model and touches no database.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HOW_WORDS = re.compile(r"\b(lunge|leap|circl\w*|flank\w*|pack|bite\w*|keeps? (?:its|their) distance|from behind|charg\w*|feint\w*|retreat\w*|again and again|every time|each time|always|pattern|when I (?:close|step|run|turn))\b", re.I)


CARRIED = re.compile(r"\b(last time|again|before|earlier|(?:three|two|four|\d) times|every time|each time|this time|learned|lesson)\b", re.I)


RANGED_SAID = re.compile(r"\b(bow|arrow\w*|shoot\w*|shot|fire.?bolt|burn)\b", re.I)
RANGED_SKILL = re.compile(r'"(shoot|bowshot|firebolt|throw)"')


def load(p):
    return [json.loads(l) for l in open(p)] if p.exists() else []


def fights_of(exps, t0_ms, gap=20.0):
    # Exact times from at_ms (the runner's `t` is its 5 s poll time).
    hits = sorted((e["at_ms"] - t0_ms) / 1000 for e in exps if e["kind"] == "attacked")
    out = []
    for t in hits:
        if out and t - out[-1][1] < gap:
            out[-1][1] = t
            out[-1][2] += 1
        else:
            out.append([t, t, 1])
    return out


def audit(d: Path, kind_word: str):
    s = json.loads((d / "summary.json").read_text())
    if s.get("fake"):
        return None
    exps = load(d / "experiences.jsonl")
    samples = load(d / "samples.jsonl")
    graphs = load(d / "graphs.jsonl")
    # One clock for everything: the runner's `t` (seconds since the trial's start, as in
    # samples, graphs and died_min). Rows carry exact `at_ms`; the runner stamps `t` when it
    # polls (up to 5 s late), so the offset is the largest `at_ms - t` over thought rows.
    thoughts = load(d / "thoughts.jsonl")
    t0_ms = max((x["at_ms"] - x["t"] * 1000 for x in thoughts), default=None)
    journal = []
    for f in (d / "journal").glob("*.jsonl"):
        journal += load(f)
    calls = []
    for j in journal:
        if j.get("purpose") not in ("think", "deliberate") or t0_ms is None:
            continue
        end = (j["at_ms"] - t0_ms) / 1000
        calls.append({"purpose": j["purpose"], "start": end - j.get("latency_ms", 0) / 1000, "end": end, "latency_s": j.get("latency_ms", 0) / 1000, "reply": j.get("reply") or ""})
    died = s.get("died_min")
    died_t = died * 60 if died is not None else None
    res = []
    for a, b, n in fights_of(exps, t0_ms):
        end = died_t if died_t is not None and died_t - b < 30 else b
        lo = a - 15
        skills = {}
        for x in samples:
            if a <= x["t"] <= end + 2 and x.get("alive"):
                sk = (x.get("activity") or ["idle"])[0]
                skills[sk] = skills.get(sk, 0) + 1
        during = [c for c in calls if lo <= c["start"] <= end]
        finished = [c for c in during if c["end"] <= end]
        revs = [g for g in graphs if a <= g["t"] <= end]
        stances, how = [], []
        for c in calls:
            if c["purpose"] != "think" or not (lo <= c["end"] <= end + 120):
                continue
            try:
                r = json.loads(c["reply"][c["reply"].find("{"): c["reply"].rfind("}") + 1])
            except ValueError:
                continue
            for jd in r.get("judgments") or []:
                if not isinstance(jd, dict):
                    jd = {"key": str(jd)}
                txt = f"{jd.get('key','')} {jd.get('why','')}"
                if kind_word in txt.lower():
                    stances.append({"at_s_from_first_blow": round(c["end"] - a, 1), "key": jd.get("key"), "value": jd.get("value"), "why": (jd.get("why") or "")[:160]})
            th = r.get("thought") or ""
            if kind_word in th.lower() and HOW_WORDS.search(th):
                how.append({"at_s_from_first_blow": round(c["end"] - a, 1), "thought": th[:240]})
        carried = [{"at_s_from_first_blow": round((x["at_ms"] - t0_ms) / 1000 - a, 1), "thought": x["summary"][:240]}
                   for x in thoughts if x["kind"] == "deliberate" and lo <= (x["at_ms"] - t0_ms) / 1000 <= end + 30 and CARRIED.search(x["summary"])]
        res.append({
            "carried_from_before": carried,
            "first_blow_s": round(a, 1), "end_s": round(end, 1), "length_s": round(end - a, 1), "blows_taken": n,
            "died_in_it": died_t is not None and end == died_t,
            "subject_skills_2s_samples": skills,
            "calls_started": len(during), "calls_finished_in_fight": len(finished),
            "latency_s": sorted(round(c["latency_s"], 1) for c in during),
            "graph_revisions_in_fight": len(revs),
            "stances_naming_opponent": stances, "thoughts_on_how_it_fights": how,
        })
    # Intention -> compiled graph -> body, for ranged force: does a think that means to shoot
    # (bow, arrow, fire bolt) compile to a ranged skill, and does the body ever use one?
    ranged_said = ranged_compiled = melee_compiled = 0
    by_end = sorted(calls, key=lambda c: c["end"])
    for i, c in enumerate(by_end):
        if c["purpose"] != "think" or not RANGED_SAID.search(c["reply"]) or kind_word not in c["reply"].lower():
            continue
        ranged_said += 1
        nxt = next((x for x in by_end[i + 1:] if x["purpose"] == "deliberate"), None)
        if nxt:
            ranged_compiled += bool(RANGED_SKILL.search(nxt["reply"]))
            melee_compiled += bool(re.search(r'"(attack|strike)"', nxt["reply"])) and not RANGED_SKILL.search(nxt["reply"])
    # Ranged use from the subject's own experiences (the 2 s samples miss 300 ms moves):
    # refusals and "broke off to shoot" show the body tried; an outcome line would show it
    # learned how a shot went. Melee has one ("You finished: attack → wolf. hit for 7").
    own = [e["text"] for e in exps if e["kind"] in ("own", "act", "combat")]
    ranged_tried = sum(bool(re.search(r"(failed to|broke off to) (shoot|bowshot|firebolt|throw)", t)) for t in own)
    ranged_outcome = sum(bool(re.search(r"finished: (shoot|bowshot|firebolt|throw)", t)) for t in own)
    melee_outcome = sum(bool(re.search(r"finished: (attack|strike)", t)) for t in own)
    return {"intent_to_body": {"thinks_meaning_to_shoot": ranged_said, "next_compile_ranged": ranged_compiled, "next_compile_melee_only": melee_compiled,
                               "ranged_tried_lines": ranged_tried, "ranged_outcome_lines": ranged_outcome, "melee_outcome_lines": melee_outcome},
            "run": str(d), "survived": s.get("survived"), "died_min": died, "hp_min": s.get("hp_min"), "model": (s.get("variant")), "fights": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--kind", default="wolf", help="word naming the opponent's kind in stances and thoughts")
    ap.add_argument("--json")
    a = ap.parse_args()
    out = [r for r in (audit(Path(x), a.kind) for x in a.dirs) if r]
    tot = {"runs": len(out), "fights": 0, "fights_with_call_finished": 0, "calls_started": 0, "calls_finished": 0, "revisions": 0, "lengths": [], "latencies": [], "stances": 0, "how": 0, "deaths_in_fight": 0, "repeat_fights": 0, "carried": 0}
    for r in out:
        for k, f in enumerate(r["fights"]):
            tot["fights"] += 1
            tot["repeat_fights"] += k > 0
            tot["fights_with_call_finished"] += f["calls_finished_in_fight"] > 0
            tot["calls_started"] += f["calls_started"]
            tot["calls_finished"] += f["calls_finished_in_fight"]
            tot["revisions"] += f["graph_revisions_in_fight"]
            tot["lengths"].append(f["length_s"])
            tot["latencies"] += f["latency_s"]
            tot["stances"] += len(f["stances_naming_opponent"])
            tot["how"] += len(f["thoughts_on_how_it_fights"])
            tot["deaths_in_fight"] += f["died_in_it"]
            tot["carried"] += len(f["carried_from_before"])
    for k in ("thinks_meaning_to_shoot", "next_compile_ranged", "next_compile_melee_only"):
        tot[k] = sum(r["intent_to_body"][k] for r in out)
    for k in ("ranged_tried_lines", "ranged_outcome_lines", "melee_outcome_lines"):
        tot[k] = sum(r["intent_to_body"][k] for r in out)
    tot["runs_trying_ranged"] = sum(r["intent_to_body"]["ranged_tried_lines"] > 0 for r in out)
    for k in ("lengths", "latencies"):
        v = sorted(tot[k])
        tot[k] = {"n": len(v), "p50": v[len(v) // 2] if v else None, "p90": v[int(len(v) * 0.9)] if v else None, "max": v[-1] if v else None}
    report = {"totals": tot, "runs": out}
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if a.json:
        Path(a.json).write_text(text + "\n")
    print(json.dumps(tot, indent=1))


if __name__ == "__main__":
    main()
