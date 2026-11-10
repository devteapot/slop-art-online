#!/usr/bin/env python3
"""Read-only evidence digest of a trial batch (docs/TRIALS.md): per instance, how the subject
died, what it did around each scripted event, and the model's first replies after it, with
journal references. Reported reasons are the model's own words, not causal evidence.

Usage: living/tools/trial_evidence.py BATCH [--quotes 2]
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".local/living/trials"


def jsonl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def reply_of(r):
    text = r.get("reply")
    if isinstance(text, dict):
        return text
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def spread(vals, fmt="{:.1f}"):
    v = [x for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not v:
        return "–"
    if len(v) == 1:
        return fmt.format(v[0])
    return f"{fmt.format(sum(v) / len(v))} ({fmt.format(min(v))}–{fmt.format(max(v))})"


def table(batches):
    """One row per trial x variant: replicates side by side as counts, means and ranges."""
    groups = {}
    for b in batches:
        for p in sorted((OUT / b).glob("*/summary.json")):
            s = json.loads(p.read_text())
            if s.get("stopped_by", "").startswith("error"):
                continue
            groups.setdefault((b, s["trial"], s["variant"]), []).append((p.parent, s))
    print("| Batch | Trial | Variant | n | Survived | Died at min | Lowest hp | First meal min | Lines said | Graph revisions | Calls | Tokens per game day | Trial-specific |")
    print("| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for (b, trial, variant), runs in groups.items():
        ss = [s for _, s in runs]
        n = len(ss)
        extra = ""
        if trial.startswith("teacher"):
            extra = f"learned cloak {sum('cloak' in s.get('learned', []) for s in ss)}/{n}; crafted {sum(s.get('skills', {}).get('craft', 0) > 0 for s in ss)}/{n}"
        elif trial.startswith("theft"):
            took = [any(e.get("kind") == "took" for e in jsonl(d / "experiences.jsonl")) for d, _ in runs]
            spoke = sum(1 for d, s in runs if any(k for k in s.get("said_to", {}) if k in {m["name"] for m in json.loads((d / "cast.json").read_text())["roles"]["thief"]}))
            extra = f"theft perceived {sum(took)}/{n}; spoke to thief {spoke}/{n}"
        elif trial.startswith("wolves"):
            extra = f"moved in 2 min after release {spread([s.get('fled_m', {}).get('pack') for s in ss])} m; struck at a wolf {sum(1 for s in ss if s.get('skills', {}).get('attack') or s.get('skills', {}).get('shoot'))}/{n}"
        elif trial.startswith("hungry"):
            given = sum(1 for s in ss if any('(idle)' in k or '(wait)' in k for k in s.get('food_gained', {})))
            extra = f"peak hunger {spread([s.get('hunger_max') for s in ss])}; received food {given}/{n}"
        print(f"| {b} | {trial} | {variant} | {n} | {sum(1 for s in ss if s.get('survived'))}/{n} | {', '.join(str(s['died_min']) for s in ss if s.get('died_min')) or '–'} | "
              f"{spread([s.get('hp_min') for s in ss], '{:.0f}')} | {spread([s.get('first_eat_min') for s in ss], '{:.2f}')} | {spread([s.get('lines_said') for s in ss])} | "
              f"{spread([s.get('graph_revisions') for s in ss])} | {spread([s.get('calls') for s in ss], '{:.0f}')} | {spread([s.get('tokens_per_game_day') for s in ss], '{:,.0f}')} | {extra} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch", nargs="+")
    ap.add_argument("--quotes", type=int, default=2)
    ap.add_argument("--table", action="store_true", help="one row per trial x variant across the batches")
    a = ap.parse_args()
    if a.table:
        return table(a.batch)
    a.batch = a.batch[0]
    for d in sorted(p.parent for p in (OUT / a.batch).glob("*/summary.json")):
        s = json.loads((d / "summary.json").read_text())
        cast = json.loads((d / "cast.json").read_text())["roles"] if (d / "cast.json").exists() else {}
        S = cast.get("subject", [{}])[0].get("id")
        names = {m["id"]: m["name"] for ms in cast.values() for m in ms}
        events = jsonl(d / "events.jsonl")
        exps = jsonl(d / "experiences.jsonl")
        chron = jsonl(d / "chronicle.jsonl")
        print(f"\n## {d.name}: {s.get('subject')} — {s.get('stopped_by')}")
        for c in chron:
            if c.get("kind") == "death" and c.get("a") == S:
                print(f"- death at {c['t'] / 60:.1f} min: {c['text'][:160]}")
        for role, ms in cast.items():
            if role == "subject":
                continue
            ids = {m["id"] for m in ms}
            lines = [c for c in chron if c.get("kind") == "speech" and c.get("a") == S and c.get("b") in ids]
            if lines:
                print(f"- said to {role}: " + " / ".join(f"{c['t'] / 60:.1f}m “{c['text'][:90]}”" for c in lines[:4]))
            acts = [c for c in chron if c.get("a") == S and c.get("b") in ids and c.get("kind") != "speech"]
            for c in acts[:4]:
                print(f"- toward {role}: {c['t'] / 60:.1f}m {c['kind']}: {c['text'][:120]}")
            felt = [e for e in exps if e.get("subject") in ids and e.get("kind") in ("took", "learned", "gift", "speech", "fight", "death")]
            for e in felt[:5]:
                print(f"- perceived from {role}: {e['t'] / 60:.1f}m {e['kind']}: {e['text'][:140]}")
        for e in exps:
            if e.get("kind") in ("act",) and re.search(r"did not work out|You failed", e.get("text", "")):
                print(f"- own failure {e['t'] / 60:.1f}m: {e['text'][:150]}")
                break
        marks = [e["t"] for e in events if e.get("do") in ("place", "act", "say") and e.get("t") and e["t"] > 1]
        j = []
        for f in sorted((d / "journal").glob("*.jsonl")) if (d / "journal").exists() else []:
            for n, line in enumerate(f.read_text().splitlines(), 1):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                r["_ref"] = f"{d.relative_to(OUT)}/{f.relative_to(d)}:{n}"
                j.append(r)
        j.sort(key=lambda r: r.get("at_ms", 0))
        t0 = j[0]["at_ms"] if j else 0
        shown = 0
        mark = marks[0] if marks else None
        start_ms = None
        samples = jsonl(d / "samples.jsonl")
        for r in j:
            if r.get("purpose") not in ("think", "deliberate", "talk"):
                continue
            rep = reply_of(r)
            text = rep.get("thought") or ""
            if not text:
                continue
            tm = (r["at_ms"] - t0) / 60000
            if mark is not None and shown == 0 and tm * 60 < mark - 30:
                continue
            say = rep.get("say")
            say = say.get("text") if isinstance(say, dict) else say
            print(f"- [{r['purpose']}] ~{tm:.1f}m after first call ({r['_ref']}): “{text[:260]}”" + (f" says: “{say[:120]}”" if say else "") + (f" plan: {rep.get('plan', '')[:100]}" if rep.get("plan") else ""))
            shown += 1
            if shown >= a.quotes:
                break


if __name__ == "__main__":
    main()
