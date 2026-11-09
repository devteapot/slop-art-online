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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--quotes", type=int, default=2)
    a = ap.parse_args()
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
