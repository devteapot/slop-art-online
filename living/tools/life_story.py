#!/usr/bin/env python3
"""How a long life evolved, hour by hour: the "player playing the game" view (docs/TRIALS.md).

  life_story.py BATCH [RUN...]

From each run's hourly snapshots, samples, experiences, chronicle and summary: per hour the
goals and mood the mind holds, its routines (kept, new, dropped), its people (how many, the
closest), what it owns and carries, its health and hunger; over the life its close calls
(hunger at 90 or more, health under 50), dealings (gives, offers, terms, demands and what the
world told it of them), what it built, techniques and where they came from, cost per hour, and
its failure loops (the same failed act again and again). Read-only; writes nothing.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (prices: trials.cost)

OUT = Path(__file__).resolve().parents[2] / ".local/living/trials"


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


def short(s, n=90):
    s = str(s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def story(d):
    s = json.loads((d / "summary.json").read_text())
    S = int(s["subject"].split("#")[1])
    snaps = [json.loads(p.read_text()) for p in sorted((d / "snapshots").glob("h*.json"))]
    samples = [x for x in jl(d / "samples.jsonl") if x.get("pos")]
    exps = jl(d / "experiences.jsonl")
    chron = jl(d / "chronicle.jsonl")
    hours = s["minutes_run"] / 60
    cost = sum(trials.cost(m, b["prompt"], b["completion"], b["cached"]) or 0 for m, b in (s.get("by_model") or {}).items())
    out = [f"### {d.name}", "",
           f"{s['minutes_run']:.0f} min ({s.get('game_days')} game days); stopped by {s['stopped_by']}; "
           f"{'survived' if s.get('survived') else 'died at ' + str(s.get('died_min')) + ' min: ' + str(s.get('death'))}; "
           f"{s['calls']} calls, {s['tokens'] / 1e6:.1f}M tokens, ${cost:.2f} (${cost / hours:.2f}/h, {s['tokens'] / hours / 1e6:.2f}M tokens/h)", ""]
    # Routine edits per hour of the run, by name, from the timeline ("- day D, M min name [new|changed]").
    tl = (d / "timeline.md").read_text() if (d / "timeline.md").exists() else ""
    edits = Counter()
    for m in re.finditer(r"^- day \d+, (\d+) min (.+?) \[(?:changed|new)\]", tl.split("## Routine changes", 1)[-1].split("## Stretches", 1)[0], re.M):
        edits[(int(m.group(1)) // 60, m.group(2))] += 1
    out += ["| h | goals (first two) | mood | routines (new / dropped) | rewrites that hour | people (closest) | owns, carries | hp, hunger |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    prev = set()
    for sn in snaps:
        p = (sn.get("persona") or [{}])[0]
        rs = {r["name"] for r in sn.get("routine", []) if r.get("actor") == S}
        new, gone = sorted(rs - prev), sorted(prev - rs)
        prev = rs
        rel = sorted((r for r in sn.get("relation", []) if r.get("actor") == S), key=lambda r: -(r["trust"] + r["affinity"]))
        closest = f"{rel[0]['label'] or '?'} t{rel[0]['trust']:.0f}/a{rel[0]['affinity']:.0f}" if rel else "-"
        owns = Counter(x["kind"] for x in sn.get("structure", []) if x.get("owner") == S)
        inv = {x["item"]: x["qty"] for x in sn.get("inventory", []) if x.get("owner") == S}
        v = (sn.get("vitals") or [{}])[0]
        out.append(f"| {sn.get('hour_of_run')} | {short('; '.join(p.get('goals', [])[:2]), 120)} | {short(p.get('mood'), 40)} | "
                   f"{len(rs)} (+{', '.join(new)[:60] or '-'} / -{', '.join(gone)[:60] or '-'}) | "
                   f"{', '.join(f'{n} {c}' for (h, n), c in sorted(edits.items()) if h == sn.get('hour_of_run') - 1)[:70] or '-'} | {len(rel)} ({short(closest, 40)}) | "
                   f"{', '.join(f'{k} {n}' for k, n in owns.items()) or '-'}; {', '.join(f'{k} {n}' for k, n in list(inv.items())[:5]) or '-'} | "
                   f"{v.get('hp', 0):.0f}, {v.get('hunger', 0):.0f} |")
    # Close calls: stretches of hunger 90+ or health under 50.
    def episodes(pred):
        eps, start = [], None
        for x in samples:
            if pred(x) and start is None:
                start = x["t"]
            elif not pred(x) and start is not None:
                eps.append((start, x["t"]))
                start = None
        if start is not None:
            eps.append((start, samples[-1]["t"]))
        return eps
    starving = episodes(lambda x: (x.get("hunger") or 0) >= 90)
    hurt = episodes(lambda x: (x.get("hp") or 100) < 50)
    fmt = lambda eps: ", ".join(f"{a / 60:.0f}–{b / 60:.0f}" for a, b in eps[:6]) or "none"
    out += ["", f"- **Close calls:** hunger 90+ in minutes {fmt(starving)}; health under 50 in minutes {fmt(hurt)}; lowest health {s.get('hp_min')}."]
    sk = s.get("skills") or {}
    told = Counter(k for e in exps if e.get("kind") == "record" for k, rx in
                   (("terms proposed to it", "proposes an agreement"), ("agreed", "accepted your terms|^agreed with"), ("kept", "kept on both sides"),
                    ("broken", "broke your agreement"), ("lapsed", "lapsed"), ("demanded of it", "demand")) if re.search(rx, e.get("text", "")))
    gifts_in = sum(1 for e in exps if "gave you" in e.get("text", "") and e.get("kind") not in ("said", "repeat"))
    out.append(f"- **Dealings:** gave {sk.get('give', 0)}, offered {sk.get('offer', 0)}, proposed terms {sk.get('offer_terms', 0)}, accepted {sk.get('accept', 0)}, demanded {sk.get('demand', 0)}, took from stores {sk.get('take', 0)}; received {gifts_in} gifts; told: {dict(told) or 'nothing'}.")
    built = s.get("built") or {}
    out.append(f"- **Built:** {', '.join(f'{k} {v}' for k, v in built.items()) if isinstance(built, dict) and built else '-'}; **learned:** {', '.join(s.get('learned') or []) or '-'} "
               f"({sum(1 for c in chron if c.get('kind') == 'learn' and c.get('a') == S and 'worked out' in c['text'])} worked out, "
               f"{sum(1 for c in chron if c.get('kind') == 'learn' and c.get('a') == S and 'worked out' not in c['text'])} from someone).")
    out.append(f"- **Talk:** {s.get('lines_said')} lines, to {len([k for k in (s.get('said_to') or {}) if k != 'nobody'])} people; to nobody {(s.get('said_to') or {}).get('nobody', 0)}.")
    fails = Counter(re.sub(r"#\d+|\d+(\.\d+)?", "#", e["text"])[:110] for e in exps if e.get("kind") in ("act", "own") and re.search(r"did not work out|could not act|You failed", e.get("text", "")))
    out.append(f"- **Failure loops** (the same failed act, most repeated): " + "; ".join(f"{n}× {short(t, 100)}" for t, n in fails.most_common(4)))
    loops = tl.split("## Loops", 1)[1].strip().splitlines()[:4] if "## Loops" in tl else []
    if loops:
        out.append("- **Loops the timeline found:** " + " / ".join(short(l.lstrip("- "), 120) for l in loops))
    return "\n".join(out) + "\n"


def main():
    batch = sys.argv[1]
    runs = sys.argv[2:]
    for p in sorted((OUT / batch).glob("*/summary.json")):
        if runs and p.parent.name not in runs:
            continue
        print(story(p.parent))


if __name__ == "__main__":
    main()
