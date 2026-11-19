#!/usr/bin/env python3
"""Why lines went unheard: each unheard line of a trial batch, matched to what wrote it.

  unheard_why.py BATCH_DIR [BATCH_DIR...] [--json OUT] [--examples N]

Read-only, no model calls (docs/TRIALS.md, "Earshot stage", "Why there was no effect"). For every
run of a batch it takes the speakers' unheard lines: `silence` experiences whose words say the
line could not have been heard (`arrive_spread.UNHEARD`; a planned line the authority did not say
is left out), from `experiences_all.jsonl`. Each is matched to its line in `speech.jsonl` by the
speaker and the moment, and the line to the model reply that wrote it: the speaker's latest think,
deliberate or talk request within 90 s before the line whose reply holds the line's opening words
(the run's journal, `.local/living/journal/verify-trial-<batch>-<run>/`). Each line is put in one
class:

- `repeat`: no row of its own in `speech.jsonl`, which merges a line repeated word for word;
- `plan or routine`: no model reply holds it (a graph's say node: a plan's queued line, a routine);
- `talk turn`: a talk reply (its prompt has no scene, so no earshot fact);
- `deliberation, no scene` / `deliberation, no fact`: a think or deliberate reply whose prompt has
  no scene, or a scene without "who would hear you now" (the `earshot` law off, or a start-up
  thought requested before the law was set);
- `deliberation: in reach then`: the addressee was within a said line in that scene's fact, and
  out of reach by the time the line was said (the model's time between: `lag_s`);
- `deliberation: only a call`: the fact listed them only under what a call would reach (a
  deliberation's `say` cannot choose a way: `mind_install` takes no way);
- `deliberation: not listed`: the fact listed them nowhere (beyond a call, or unseen);
- `room`: a line to the room that no one received ("Nobody was near enough to hear you.").

The fact's ids are the scene's (a far figure's handle), so the addressee is matched by its id or
by the silence row's subject, which carries the same handle. Python standard library only.
"""

import argparse
import collections
import glob
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arrive_spread import UNHEARD, UNSAID  # noqa: E402

EARSHOT = "who would hear you now"
SCENE = "# What you perceive right now\n"
DEC = json.JSONDecoder()


def jl(path):
    try:
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def journal_of(batch_dir, run):
    return batch_dir.parent.parent / "journal" / f"verify-trial-{batch_dir.name}-{run}"


def scene_of(request):
    """The scene a think or deliberate prompt was sent, or None."""
    for m in request.get("request", {}).get("messages", []):
        c = m.get("content") or ""
        i = c.find(SCENE)
        if i >= 0:
            try:
                return DEC.raw_decode(c, c.find("{", i))[0]
            except ValueError:
                return None
    return None


def ids(part):
    return {int(x) for x in re.findall(r"#(\d+)", part)}


def classify_run(d, journal):
    exp = jl(d / "experiences_all.jsonl")
    unheard = [r for r in exp if r.get("kind") == "silence" and UNHEARD.search(r.get("text") or "") and UNSAID not in (r.get("text") or "")]
    lines = {(r["a"], r["at_ms"]): r for r in jl(d / "speech.jsonl")}
    replies = collections.defaultdict(list)
    for f in glob.glob(str(journal / "*.jsonl")):
        for r in jl(f):
            if r.get("purpose") in ("think", "deliberate", "talk") and r.get("reply"):
                replies[r.get("actor")].append(r)
    counts, lags, examples = collections.Counter(), [], collections.defaultdict(list)
    for s in unheard:
        text = s.get("text") or ""
        if text.startswith("Nobody was near enough"):
            counts["room"] += 1
            continue
        line = lines.get((s["observer"], s["at_ms"]))
        if not line:
            counts["repeat"] += 1
            continue
        speaker = line["text"].split(" to ")[0].split(" (")[0].split(":")[0]
        q = re.search(r"“(.{8,24})", line["text"])
        cand = [r for r in replies.get(speaker, []) if s["at_ms"] - 90_000 <= r["at_ms"] <= s["at_ms"] and q and q.group(1) in (r.get("reply") or "")]
        if not cand:
            counts["plan or routine"] += 1
            continue
        r = cand[-1]
        if r["purpose"] == "talk":
            counts["talk turn"] += 1
            continue
        lag = (s["at_ms"] - r["at_ms"]) / 1000
        sc = scene_of(r)
        if sc is None:
            counts["deliberation, no scene"] += 1
            continue
        fact = sc.get(EARSHOT) or ""
        if not fact:
            counts["deliberation, no fact"] += 1
            lags.append(lag)
            continue
        parts = fact.rstrip(".").split(";")
        said, call = parts[0], next((p for p in parts if "a call would" in p), "")
        target = {line.get("b"), s.get("subject")} - {None, 0}
        if target & ids(said):
            k = "deliberation: in reach then"
        elif target & ids(call):
            k = "deliberation: only a call"
        else:
            k = "deliberation: not listed"
        counts[k] += 1
        lags.append(lag)
        examples[k].append({"speaker": speaker, "lag_s": round(lag, 1), "fact": fact, "line": line["text"][:160], "told": text})
    return {"unheard": len(unheard), "classes": dict(counts.most_common()),
            "lag_s_median": round(statistics.median(lags), 1) if lags else None, "examples": examples}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--examples", type=int, default=2)
    a = ap.parse_args()
    out = []
    for b in a.batches:
        bd = Path(b).resolve()
        for d in sorted(p for p in bd.iterdir() if p.is_dir() and (p / "experiences_all.jsonl").exists()):
            res = classify_run(d, journal_of(bd, d.name))
            out.append({"batch": bd.name, "run": d.name, **res})
            print(f"## {bd.name} {d.name}: {res['unheard']} unheard; lag median {res['lag_s_median']} s")
            for k, n in res["classes"].items():
                print(f"- {k}: {n}")
                for e in res["examples"].get(k, [])[:a.examples]:
                    print(f"  - {e['speaker']} ({e['lag_s']} s after the request): {e['line']}\n    fact: {e['fact']}")
            print()
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
