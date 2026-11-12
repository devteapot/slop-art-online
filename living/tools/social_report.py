#!/usr/bin/env python3
"""What a newcomer asked of residents and what came of it (docs/TRIALS.md, the social
preset and "Fast iterations" 8).

  social_report.py BATCH [BATCH...]

Per run, from the journals, chronicle and experiences: the newcomer's lines that name food, a
lesson or a bed and are addressed to someone (asks), how many no one heard (its "No answer
from" percept), the give/teach/host acts residents decided toward it (in talk turns or
deliberations) and how each went (finished, or the rule's refusal), what reached it (food
given, techniques learned from a person, lodging), and whether talk prompts carried the
pack/know-how lines (iteration 8's mechanism). A mean (range) per variant. Read-only; the ask
classifier is a keyword match on the newcomer's own words, so read the examples it prints.
"""
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (prices: trials.cost)
from journal_io import restore  # noqa: E402

# The speaker's `silence` row: the one a line was said to could not have heard it. Its words since
# `speech_truth` ("Bram is too far away: they could not have heard you.", "… is out of earshot: …",
# a planned line not said, and "Nobody was near enough to hear you." for a line to the room), speech-2's ("… is too far to hear you; …") and the first ("No answer from …").
UNHEARD = re.compile(r"^No answer from|could not have heard you|^Nobody was near enough to hear you|is too far to hear you")

OUT = Path(__file__).resolve().parents[2] / ".local/living/trials"
ASK = {
    "food": re.compile(r"\b(food|eat|hungry|starv|berr|bread|meal|share|spare)", re.I),
    "lesson": re.compile(r"\b(teach|show me|learn|how (do|to)|lesson)", re.I),
    "bed": re.compile(r"\b(bed|sleep|shelter|roof|the night|lodg|hearth|put me up|corner)", re.I),
}
HELP = ("give", "teach", "host", "offer_terms", "demand", "accept")
# What the world tells a party of its dealings (rules-2, skills.rhai: offer_terms, accept, demand).
TOLD = {
    "proposed_to_it": r"proposes an agreement", "it_proposed": r"^proposed to ", "agreed": r"accepted your terms|^agreed with ",
    "kept": r"kept on both sides", "broken": r"broke your agreement", "lapsed": r"has lapsed at dusk|did not take up your terms",
    "demanded_of_it": r"demand(s|ed) .* of you|you demanded", "paid": r"paid (the|what)",
}


def jl(p):
    out = []
    if not p.exists():
        return out
    for line in p.read_bytes().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def reply(r):
    rep = r.get("reply")
    if not isinstance(rep, str):
        return {}
    m = re.search(r"\{.*\}", rep, re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def request_text(r):
    q = r.get("request") or {}
    msgs = q.get("messages") if isinstance(q, dict) else None
    return "\n".join(str(m.get("content", "")) for m in msgs) if msgs else json.dumps(q)


def run(d):
    s = json.loads((d / "summary.json").read_text())
    S = int(s["subject"].split("#")[1])
    chron = jl(d / "chronicle.jsonl")
    exps = jl(d / "experiences.jsonl")
    silence = [e for e in exps if UNHEARD.search(e.get("text", ""))]
    asks = heard = 0
    for c in chron:
        if c.get("kind") != "speech" or c.get("a") != S or not c.get("b"):
            continue
        words = c["text"].split("“", 1)[-1]
        if not any(rx.search(words) for rx in ASK.values()):
            continue
        asks += 1
        if not any(abs(e["at_ms"] - c["at_ms"]) < 3000 and e.get("subject") == c["b"] for e in silence):
            heard += 1
    decided, done, refused = Counter(), Counter(), Counter()
    talk_turns = talk_with_means = 0
    why = Counter()
    for f in sorted((d / "journal").glob("*.jsonl")):
        if f.stem == s["subject"].split("#")[0]:
            continue
        rows = [restore(r, f.parent) for r in jl(f)]
        text = ""
        for r in rows:
            if r.get("purpose") == "talk":
                talk_turns += 1
                if "You know how to:" in request_text(r) or "You know no technique yet." in request_text(r):
                    talk_with_means += 1
            for a in reply(r).get("acts") or []:
                if isinstance(a, dict) and a.get("do") in HELP and isinstance(a.get("target"), dict) and a["target"].get("id") == S:
                    decided[a["do"]] += 1
            if r.get("purpose") in ("think", "deliberate"):
                text += request_text(r)
        for m in set(re.findall(r"did not work out: ((give|teach|host|offer_terms|demand|accept)[^:\n]*?→ #%d: [^.\n\\]*)" % S, text)):
            refused[m[1]] += 1
            why[re.sub(r"\d+", "#", m[0].split(": ", 1)[1])[:70]] += 1
    reached = [e["text"] for e in exps if e.get("kind") not in ("said", "repeat") and re.search(r"gave you|takes you in as their guest|taught you", e.get("text", ""))]
    for e in reached:
        done["food" if "gave you" in e else "lodging" if "guest" in e else "lesson"] += 1
    # Techniques the newcomer was taught by someone (not worked out alone by experimenting).
    told = Counter(k for e in exps if e.get("kind") not in ("said", "repeat", "speech") for k, rx in TOLD.items() if re.search(rx, e.get("text", "")))
    own = Counter(a.get("do") for r in jl(d / "journal" / f"{s['subject'].split('#')[0]}.jsonl") for a in (reply(r).get("acts") or []) if isinstance(a, dict) and a.get("do") in ("offer_terms", "demand", "accept", "give", "teach"))
    learned = [c["text"] for c in chron if c.get("kind") == "learn" and c.get("a") == S and "worked out" not in c["text"]]
    return {
        "run": d.name, "variant": s["variant"], "min": round(s["minutes_run"]), "tokens": s["tokens"],
        "residents_thinking": s.get("residents_thinking"), "cost": round(sum(trials.cost(m, b["prompt"], b["completion"], b["cached"]) or 0 for m, b in (s.get("by_model") or {}).items()), 2),
        "asks": asks, "heard": heard,
        "decided_give": decided["give"], "decided_teach": decided["teach"], "decided_host": decided["host"],
        "decided_terms": decided["offer_terms"], "decided_demand": decided["demand"], "decided_accept": decided["accept"],
        "it_offered_terms": own["offer_terms"], "it_accepted": own["accept"], **{k: told[k] for k in TOLD},
        "refused": sum(refused.values()), "got_food": done["food"], "got_lodging": done["lodging"], "got_lesson": done["lesson"],
        "taught_to_it": len(learned), "talk_turns": talk_turns, "talk_with_means": talk_with_means,
        "_why": why, "_reached": reached[:3], "_learned": learned[:3],
    }


def main():
    rows = [run(p.parent) for b in sys.argv[1:] for p in sorted((OUT / b).glob("*/summary.json"))]
    keys = [k for k in rows[0] if k not in ("run", "variant") and not k.startswith("_")]
    print("| run | " + " | ".join(keys) + " |")
    print("| --- |" + " --- |" * len(keys))
    for r in rows:
        print(f"| {r['run']} | " + " | ".join(str(r.get(k)) for k in keys) + " |")
    by = defaultdict(list)
    for r in rows:
        by[r["variant"]].append(r)
    print()
    for v, rs in by.items():
        parts = []
        for k in keys:
            xs = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
            if xs:
                parts.append(f"{k} {statistics.mean(xs):.1f} ({min(xs):g}-{max(xs):g})")
        print(f"{v} (n={len(rs)}): " + "; ".join(parts))
        why = sum((r["_why"] for r in rs), Counter())
        if why:
            print("   refusals:", dict(why.most_common(6)))
        for r in rs:
            if r["_reached"] or r["_learned"]:
                print(f"   {r['run']}: {r['_reached']} {r['_learned']}")


if __name__ == "__main__":
    main()
