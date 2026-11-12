#!/usr/bin/env python3
"""Which way minds speak in, and whether a call reaches: per run of trial batches.

  ways_report.py BATCH_DIR [BATCH_DIR...] [--json OUT] [--examples N]

Read-only, no model calls (docs/TRIALS.md, "Ways stage"; docs/COMMUNICATION.md §18). Per run:

- **Decided lines by way:** each decision's line (a think reply's `say`, the line a deliberation
  says) by the way it named: `say` (named or left out), `call`, `whisper`, or another word (a way
  the world lacks is said aloud). Talk replies' lines by their `way` too.
- **Lines said by way:** every line in `speech.jsonl` by the way its chronicle text names
  ("<name> (call) to …"; none named is `say`), and which of them a decision wrote (its words are
  in a think reply's `say` within 90 s before).
- **Calls that reached their listener:** each call to someone (`to` ≠ 0) whose `audience.jsonl`
  row lists the addressee among those who received the words; a call to the room is counted as
  reaching when anyone received it.
- **Called or walked over:** each decision whose scene said someone was within a call's reach and
  not a said line's (the earshot fact, "a call would also reach: … (#id)", or "a call would
  reach" when a said line reached no one; only while the `earshot` law is on). Each such person
  the decision acted toward is classed by what it did: `called` (its line to them in `call`),
  `said` (a line to them in `say`, which cannot reach), `walked` (its next deliberation's graph
  or acts move toward them: `goto`, `close_in`, `follow`, `approach` with their id), or `said and
  walked`. People listed only under a call whom the decision left alone are not counted.

Python standard library only.
"""

import argparse
import collections
import glob
import json
import re
from pathlib import Path

SCENE = "# What you perceive right now\n"
EARSHOT = "who would hear you now"
MOVES = ("goto", "close_in", "follow", "approach", "walk_to", "go_to")
DEC = json.JSONDecoder()


def jl(path):
    try:
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def parse(text):
    try:
        i = text.index("{")
        return DEC.raw_decode(text, i)[0]
    except (ValueError, AttributeError):
        return None


def scene_of(rec):
    for m in rec.get("request", {}).get("messages", []):
        c = m.get("content") or ""
        i = c.find(SCENE)
        if i >= 0:
            try:
                return DEC.raw_decode(c, c.find("{", i))[0]
            except ValueError:
                return None
    return None


def call_only(fact):
    """Ids the earshot fact lists under what a call adds (or reaches, when a said line reaches no one)."""
    part = next((p for p in fact.split(";") if "a call would" in p), "")
    if "a call would reach no one" in part:
        return set()
    return {int(x) for x in re.findall(r"#(\d+)", part)}


def moves_toward(node, out):
    """(verb, id) for every move in a graph or act list toward a creature by id."""
    if isinstance(node, dict):
        verb = node.get("do") if isinstance(node.get("do"), str) else next((k for k in MOVES if k in node), None)
        if verb in MOVES:
            tgt = node.get("target") if isinstance(node.get("target"), dict) else node.get(verb)
            if isinstance(tgt, dict) and isinstance(tgt.get("id"), int):
                out.add(tgt["id"])
            elif isinstance(tgt, int):
                out.add(tgt)
        for v in node.values():
            moves_toward(v, out)
    elif isinstance(node, list):
        for v in node:
            moves_toward(v, out)
    return out


def way_of_say(say):
    if isinstance(say, dict):
        w = (say.get("way") or "").strip().lower()
        return w or "say (not named)"
    return "say (not named)"


def say_text(say):
    if isinstance(say, dict):
        return (say.get("text") or "").strip()
    return (say or "").strip() if isinstance(say, str) else ""


def run_report(d, journal, examples):
    recs = []
    for f in glob.glob(str(journal / "*.jsonl")):
        recs += [r for r in jl(f) if r.get("purpose") in ("think", "deliberate", "talk") and r.get("reply")]
    recs.sort(key=lambda r: (r.get("actor") or "", r.get("at_ms") or 0))
    by_actor = collections.defaultdict(list)
    for r in recs:
        by_actor[r.get("actor")].append(r)
    decided, talk = collections.Counter(), collections.Counter()
    decided_words = {}  # (actor name, opening words) -> way
    choice = collections.Counter()
    ex = collections.defaultdict(list)
    for actor, rs in by_actor.items():
        for i, r in enumerate(rs):
            v = parse(r.get("reply") or "")
            if not isinstance(v, dict):
                continue
            if r["purpose"] == "talk":
                text = v.get("say") if isinstance(v.get("say"), str) else say_text(v.get("say"))
                if text:
                    w = (v.get("way") or (v.get("say") or {}).get("way") if isinstance(v.get("say"), dict) else v.get("way")) or ""
                    talk[(w or "say (not named)").lower()] += 1
                continue
            if r["purpose"] != "think":
                continue
            say = v.get("say")
            text = say_text(say)
            way = way_of_say(say)
            if text:
                decided[way] += 1
                decided_words[(actor, text[:24])] = way
            sc = scene_of(r)
            fact = (sc or {}).get(EARSHOT) or ""
            only = call_only(fact) if fact else set()
            if not only:
                continue
            to = say.get("to") if isinstance(say, dict) else None
            try:
                to = int(str(to).lstrip("#")) if to not in (None, "", 0) else None
            except ValueError:
                to = None
            nxt = next((x for x in rs[i + 1:] if x["purpose"] == "deliberate" and x.get("at_ms", 0) - r.get("at_ms", 0) <= 90_000), None)
            moved = moves_toward(parse(nxt.get("reply") or "") if nxt else None, set())
            moved |= moves_toward(v.get("acts"), set())
            for p in only:
                spoke = to == p and bool(text)
                walked = p in moved
                if not (spoke or walked):
                    continue
                if spoke and way.startswith("call"):
                    k = "called" if not walked else "called and walked"
                elif spoke and way.startswith("whisper"):
                    k = "whispered"
                elif spoke:
                    k = "said and walked" if walked else "said"
                else:
                    k = "walked"
                choice[k] += 1
                if len(ex[k]) < examples:
                    ex[k].append({"actor": actor, "to": p, "way": way, "line": text[:120], "fact": fact[:240]})
    said = collections.Counter()
    calls = collections.Counter()
    aud = {(r["speaker"], r["at_ms"]): r for r in jl(d / "audience.jsonl")}
    for s in jl(d / "speech.jsonl"):
        t = s.get("text") or ""
        head = t.split("“")[0]
        m = re.search(r" \((\w+)\)(?: to |: )", head)
        w = m.group(1) if m else "say"
        speaker = head.split(" (")[0].split(" to ")[0].split(":")[0].strip()
        q = re.search(r"“(.{1,24})", t)
        src = "decided" if q and (speaker, q.group(1)) in decided_words else "other"
        said[(w, src)] += 1
        if w == "call":
            a = aud.get((s.get("a"), s.get("at_ms")))
            hearers = {h[0] for h in (a or {}).get("hearers", [])}
            b = s.get("b") or 0
            reached = (b in hearers) if b else bool(hearers)
            key = f"{'to someone' if b else 'to the room'}, {src}"
            calls[(key, "reached" if reached else ("not reached" if a else "no audience row"))] += 1
    return {"decided_lines_by_way": dict(decided.most_common()), "talk_lines_by_way": dict(talk.most_common()),
            "lines_said_by_way": {f"{w} ({src})": n for (w, src), n in sorted(said.items())},
            "calls": {f"{k}: {r}": n for (k, r), n in sorted(calls.items())},
            "call_only_people_acted_toward": dict(choice.most_common()), "examples": ex}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--examples", type=int, default=2)
    a = ap.parse_args()
    out = []
    for b in a.batches:
        bd = Path(b).resolve()
        for d in sorted(p for p in bd.iterdir() if p.is_dir() and (p / "speech.jsonl").exists()):
            journal = bd.parent.parent / "journal" / f"verify-trial-{bd.name}-{d.name}"
            res = run_report(d, journal, a.examples)
            out.append({"batch": bd.name, "run": d.name, **res})
            print(f"## {bd.name} {d.name}")
            for k in ("decided_lines_by_way", "talk_lines_by_way", "lines_said_by_way", "calls", "call_only_people_acted_toward"):
                print(f"- {k}: {res[k]}")
            for k, es in res["examples"].items():
                for e in es:
                    print(f"  - {k}: {e['actor']} → #{e['to']} ({e['way']}): {e['line']}\n    fact: {e['fact']}")
            print()
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
