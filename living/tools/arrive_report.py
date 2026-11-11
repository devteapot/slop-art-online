#!/usr/bin/env python3
"""What residents do about a newcomer who says nothing (docs/TRIALS.md, "Arrivals").

  arrive_report.py BATCH [BATCH...] [--root DIR] [--examples N] [--json OUT]
  arrive_report.py --journal DIR --subject ID --from-ms MS --to-ms MS [--examples N]

Read-only, no model calls. For each run of the `arrive` trial (trials.py evidence with
`record.speech`, `talk`, `experiences`, `gestures` and `positions`), the newcomer is the joined
player (`cast.json` subject) and its silent stands are the `human_stand` .. `human_stand_end`
events. The `greet` trial's runs read the same way, with its `human_listen` windows as the
stands (the player has spoken by then, so contact there is not unprompted).

Per resident (a person other than the newcomer) who was **in range**, within RANGE_M (12 m,
Cullet's speech) of the newcomer at some position sample during a stand:

- `seen`: the newcomer appears in the resident's experiences (`experiences_all.jsonl`, rows with
  the newcomer as subject or object); `first`: the first-sight percept ("For the first time you
  see ...") with its time from the first stand's start (s) and its salience; `crowd`: in range
  but no first-sight percept at all (a crowd hides people one has no feelings about);
- `asked`: thoughts (journal `think`) whose reason ("# Why you are thinking now") holds one of
  the resident's experiences about the newcomer: the newcomer asked for them. A pending request
  keeps its other reasons when plan reasons arrive during a call (`clear_deliberation`), so one
  feeling can be the reason of many thoughts; per run, `asked` counts residents asked at least
  once;
- `thinks`: thoughts during the stands, and `in_prompt` how many of them, and of the
  resident's talk turns, had the newcomer in the prompt (its id in the scene or an experience);
  `marked`: how many showed the newcomer's scene entry with `"new to you"` (`newcomer_scene_min`);
- `mention`: replies (thought, intentions, speech; talk replies) naming the newcomer by id;
  `words`: replies with stranger/newcomer/traveller words (noisy: neighbours whose names are out
  of range are "a stranger" too; read the examples);
- `approach`: during a stand, the resident's distance to the (standing) newcomer fell by
  APPROACH_M (3 m) or more and ended within APPROACH_END_M (4 m): they came up to them; counted
  again only after they went back beyond LEAVE_M (8 m). Residents' routines also bring them
  past, so read it beside `aimed`: samples whose activity was aimed at the newcomer (a goto,
  follow, gesture or act with the newcomer as its target; `positions.jsonl` `act`); `close`:
  came within 3 m after being farther than 4 m during the stands (not the newcomer walking up);
- `gesture`: wave, nod, face or appraise aimed at the newcomer (`gestures.jsonl`, accepted);
- `to_them`: lines said to the newcomer (`speech.jsonl` with `b` = the newcomer);
- `about_them`: lines to others or to no one that use stranger/newcomer/traveller words, or the
  newcomer's name, while the newcomer was within RANGE_M of the speaker (heuristic; examples).

Per run: residents in range, the share of them who made deliberate contact (`acted`: an
activity aimed at them, a gesture or a line to them; `any`: also a line about them or a reply
naming them; `approach` and `close` are left out, since routines bring residents past), the
time from the newcomer's arrival (its first walk; `first_stand_s` is when the first stand began)
to the first such contact (`first_contact_s`) and to the first approach or close pass
(`first_close_s`), thoughts per resident-minute during the stands,
and cost: model calls and tokens per minute and dollars per hour at trials.py's prices (fake
runs: 0). A mean (range) per batch x variant follows.

`--journal` reads a play-test record instead (a journal directory of `<Name>.jsonl`, no
positions): only `asked`, `thinks`, `in_prompt`, `mention` and `words`, per journal, for model
calls between `--from-ms` and `--to-ms` (Unix ms).
"""
import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trials  # noqa: E402  (prices: trials.cost)

OUT = Path(__file__).resolve().parents[2] / ".local/living/trials"
RANGE_M = 12.0
APPROACH_M = 3.0
APPROACH_END_M = 4.0
LEAVE_M = 8.0
CLOSE_M = 3.0
WORDS = re.compile(r"\b(stranger|strangers|newcomer|new arrival|traveller|traveler|visitor|outsider|new face|someone new|just arrived|wanderer)\b", re.I)


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


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def section(text, head):
    """The text of a prompt section `# head` up to the next `# ` heading."""
    i = text.find(f"# {head}")
    if i < 0:
        return ""
    j = text.find("\n# ", i + 2)
    return text[i + len(head) + 2: j if j > 0 else len(text)].strip()


def user_text(entry):
    return "".join(m.get("content", "") for m in (entry.get("request") or {}).get("messages", []) if m.get("role") == "user")


def names_id(text, sid):
    """Whether a prompt or reply refers to the newcomer by id."""
    return bool(re.search(rf'(#{sid}\b|"id": ?{sid}\b|"to": ?"?#?{sid}\b|=#{sid}\b|\(#{sid}\))', text))


def reply_text(entry):
    """A reply's own words: thought, intentions and speech (think), or the talk reply."""
    raw = entry.get("reply") or ""
    try:
        v = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(v, dict):
        return raw
    parts = [str(v.get("thought") or "")]
    parts += [str(x) for x in (v.get("intend") or [])]
    say = v.get("say")
    if isinstance(say, dict):
        parts.append(f"{say.get('text') or ''} (to {say.get('to')})")
    elif say:
        parts.append(f"{say} (to {v.get('to')})")
    return " | ".join(p for p in parts if p)


def journal_columns(jdir, sid, windows, exp_texts=None):
    """Per journal file (a resident): thoughts in the windows, how many had the newcomer in the
    prompt, were asked by an experience about them, and replies naming them."""
    exp_texts = exp_texts or {}
    out = {}
    for f in sorted(Path(jdir).glob("*.jsonl")):
        name = f.stem.replace("_", " ")
        col = {"thinks": 0, "in_prompt": 0, "marked": 0, "asked": 0, "mention": 0, "words": 0, "talk": 0, "examples": [], "reasons": []}
        for e in jl(f):
            at = e.get("at_ms") or 0
            if not any(a <= at <= b for a, b in windows) or e.get("purpose") not in ("think", "talk"):
                continue
            u = user_text(e)
            rep = reply_text(e)
            seen = names_id(u, sid)
            if e["purpose"] == "think":
                col["thinks"] += 1
                reason = section(u, "Why you are thinking now")
                mine = exp_texts.get(name, [])
                if any(t and t[:60] in reason for t in mine) or names_id(reason, sid):
                    col["asked"] += 1
                    if len(col["reasons"]) < 3:
                        col["reasons"].append(f"reason at {at}: {reason[:200]}")
            else:
                col["talk"] += 1
            col["in_prompt"] += seen
            # The scene's own mark (`newcomer_scene_min`): "new to you" in the newcomer's entry.
            col["marked"] += bool(re.search(r'\{[^{}]*"id": ?%d\b[^{}]*"new to you"|\{[^{}]*"new to you"[^{}]*"id": ?%d\b' % (sid, sid), u))
            m = names_id(rep, sid)
            col["mention"] += m
            w = bool(WORDS.search(rep))
            col["words"] += w
            if (m or w) and len(col["examples"]) < 4:
                col["examples"].append(f"{e['purpose']} at {at}: {rep[:300]}")
        if col["thinks"] or col["talk"]:
            out[name] = col
    return out


def windows_of(events):
    """The silent stands (arrive) or listening windows (greet) as [(from_ms, to_ms)]."""
    out, opened = [], {}
    for e in events:
        for key, end in (("human_stand", "human_stand_end"), ("human_listen", "human_listen_end")):
            if key in e:
                opened[(key, e[key].get("stand", e[key].get("cycle")))] = e[key]["from_ms"]
            if end in e:
                k = (key, e[end].get("stand", e[end].get("cycle")))
                if k in opened:
                    out.append((opened.pop(k), e[end]["to_ms"]))
    return out


def run_report(d):
    cast = json.loads((d / "cast.json").read_text()) if (d / "cast.json").exists() else {}
    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    sid = (cast.get("roles", {}).get("subject") or [None])[0]
    if isinstance(sid, dict):
        sid = sid.get("id")
    if sid is None:
        m = re.search(r"#(\d+)", str(summary.get("subject", "")))
        sid = int(m.group(1)) if m else None
    events = jl(d / "events.jsonl")
    wins = windows_of(events)
    if sid is None or not wins:
        return None
    t0 = wins[0][0]
    # The newcomer's arrival: its `join` call (human.jsonl), else the first stand.
    walk = next((e["human_walk"]["from_ms"] for e in events if "human_walk" in e), None)
    t_arrive = walk or t0
    inwin = lambda ms: any(a <= ms <= b for a, b in wins)
    names = {}
    for c in jl(d / "census.jsonl"):
        for p in c.get("people", []):
            names[p["id"]] = p["name"]
    prow = jl(d / "positions.jsonl")
    pos = [(r["ms"], {int(k): v for k, v in r["pos"].items()}) for r in prow]
    aimed = defaultdict(list)
    for r in prow:
        for k, (skill, target) in (r.get("act") or {}).items():
            if target == sid:
                aimed[int(k)].append((r["ms"], skill))
    if not pos:
        # Runs without `record.positions` (the greet trial): the census, every `census_s`.
        pos = [(c["now_ms"], {p["id"]: p["pos"] for p in c.get("people", []) if p.get("pos") and p.get("alive")}) for c in jl(d / "census.jsonl")]
    # In range: within RANGE_M of the newcomer at a sample during a stand.
    in_range, track = set(), defaultdict(list)
    for ms, ps in pos:
        if not inwin(ms) or sid not in ps:
            continue
        me = ps[sid]
        for i, p in ps.items():
            if i == sid:
                continue
            dd = dist(me, p)
            track[i].append((ms, dd))
            if dd <= RANGE_M:
                in_range.add(i)
    exps = defaultdict(list)
    for r in jl(d / "experiences_all.jsonl"):
        if r.get("subject") == sid or r.get("object") == sid:
            exps[r["observer"]].append(r)
    jcols = journal_columns(d / "journal", sid, wins, {names.get(i, ""): [x["text"] for x in xs] for i, xs in exps.items()})
    # Asked at any time (a first sight on the walk in can ask for a thought before the stand).
    jall = journal_columns(d / "journal", sid, [(0, 1 << 62)], {names.get(i, ""): [x["text"] for x in xs] for i, xs in exps.items()})
    speech = jl(d / "speech.jsonl")
    gestures = [g for g in jl(d / "gestures.jsonl") if g.get("target") == sid and g.get("accepted_ms")]

    def near_at(i, ms):
        best = None
        for t, ps in pos:
            if abs(t - ms) <= 3000 and sid in ps and i in ps:
                best = dist(ps[sid], ps[i])
        return best

    rows, contacts, passes = [], [], []
    for i in sorted(in_range):
        mine = sorted(exps.get(i, []), key=lambda r: r["at_ms"])
        first = next((r for r in mine if "first time you see" in r["text"]), None)
        # Approaches: falls of APPROACH_M from the highest distance since the last approach.
        appr, close, hi, armed, far_since = 0, 0, None, True, False
        for ms, dd in track.get(i, []):
            if dd > CLOSE_M + 1:
                far_since = True
            hi = dd if hi is None else max(hi, dd)
            if dd > LEAVE_M:
                armed = True
            if armed and hi - dd >= APPROACH_M and dd <= APPROACH_END_M:
                appr += 1
                hi, armed = dd, False
                passes.append((ms, "approach", i))
            # Within 3 m having been farther during the stands: they came, not the newcomer.
            if dd <= CLOSE_M and far_since:
                if not close:
                    passes.append((ms, "close", i))
                close = 1
        to_them = [s for s in speech if s.get("a") == i and s.get("b") == sid]
        for s in to_them:
            contacts.append((s["at_ms"], "line", i))
        about = [s for s in speech if s.get("a") == i and s.get("b") != sid and inwin(s["at_ms"]) and WORDS.search(s.get("text", "")) and (near_at(i, s["at_ms"]) or 99) <= RANGE_M]
        aim = aimed.get(i, [])
        if aim:
            contacts.append((aim[0][0], "aimed:" + aim[0][1], i))
        g = [x for x in gestures if x.get("actor") == i]
        for x in g:
            contacts.append((x["at_ms"], "gesture:" + x["skill"], i))
        name = names.get(i, f"#{i}")
        jc = jcols.get(name, {})
        ja = jall.get(name, {})
        rows.append({
            "id": i, "name": name, "seen": len(mine),
            "first_s": round((first["at_ms"] - t0) / 1000, 1) if first else None,
            "first_sal": first["salience"] if first else None, "crowd": first is None,
            "asked": ja.get("asked", 0), "thinks": jc.get("thinks", 0), "in_prompt": jc.get("in_prompt", 0), "marked": jc.get("marked", 0),
            "mention": jc.get("mention", 0), "words": jc.get("words", 0),
            "approach": appr, "aimed": len(aim), "aimed_skills": sorted({x[1] for x in aim}), "close": close, "gesture": len(g), "to_them": len(to_them), "about_them": len(about),
            "examples": (ja.get("reasons") or [])[:1] + (jc.get("examples") or [])[:2] + [s["text"][:200] for s in (to_them + about)[:2]],
        })
    contacts.sort()
    minutes = sum(b - a for a, b in wins) / 60000
    fake = bool(summary.get("fake"))
    usd = 0.0
    if not fake:
        for model, m in (summary.get("by_model") or {}).items():
            usd += trials.cost(model, m.get("prompt", 0), m.get("completion", 0), m.get("cached", 0)) or 0
    run_min = summary.get("minutes_run") or 0
    acted = [r for r in rows if r["aimed"] or r["gesture"] or r["to_them"]]
    anyx = [r for r in rows if r["aimed"] or r["gesture"] or r["to_them"] or r["about_them"] or r["mention"]]
    passes.sort()
    thinks = sum(r["thinks"] for r in rows)
    return {
        "run": d.name, "variant": summary.get("variant", "?"), "fake": fake, "newcomer": sid, "stands": len(wins),
        "stand_min": round(minutes, 1), "in_range": len(rows), "acted": len(acted), "any": len(anyx),
        "acted_share": round(len(acted) / len(rows), 2) if rows else None,
        "first_stand_s": round((t0 - t_arrive) / 1000, 1),
        "first_contact_s": round((contacts[0][0] - t_arrive) / 1000, 1) if contacts else None,
        "first_contact": contacts[0][1] + " by " + names.get(contacts[0][2], "?") if contacts else None,
        "first_close_s": round((passes[0][0] - t_arrive) / 1000, 1) if passes else None,
        "first_sight": sum(1 for r in rows if not r["crowd"]), "asked": sum(1 for r in rows if r["asked"]),
        "in_prompt": sum(r["in_prompt"] for r in rows), "marked": sum(r["marked"] for r in rows), "mention": sum(r["mention"] for r in rows),
        "thinks_per_res_min": round(thinks / max(1, len(rows)) / max(minutes, 1e-9), 2),
        "approaches": sum(r["approach"] for r in rows), "aimed": sum(1 for r in rows if r["aimed"]), "gestures": sum(r["gesture"] for r in rows),
        "lines_to": sum(r["to_them"] for r in rows), "lines_about": sum(r["about_them"] for r in rows),
        "calls_min": round((summary.get("calls") or 0) / run_min, 1) if run_min else None,
        "tok_min": round((summary.get("tokens") or 0) / run_min) if run_min else None,
        "usd_h": round(usd / run_min * 60, 2) if run_min else None,
        "residents": rows,
    }


COLS = ["run", "variant", "stand_min", "in_range", "first_sight", "asked", "in_prompt", "marked", "mention", "thinks_per_res_min",
        "approaches", "aimed", "gestures", "lines_to", "lines_about", "acted", "acted_share", "first_contact_s", "first_contact", "first_close_s", "calls_min", "tok_min", "usd_h"]


def table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join("–" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="*")
    ap.add_argument("--root", default=str(OUT))
    ap.add_argument("--examples", type=int, default=2)
    ap.add_argument("--json")
    ap.add_argument("--journal")
    ap.add_argument("--subject", type=int)
    ap.add_argument("--from-ms", type=int)
    ap.add_argument("--to-ms", type=int)
    a = ap.parse_args()
    if a.journal:
        cols = journal_columns(Path(a.journal), a.subject, [(a.from_ms, a.to_ms)])
        print(f"# Journals in {a.journal}, newcomer #{a.subject}, {a.from_ms}..{a.to_ms} ({(a.to_ms - a.from_ms) / 1000:.0f} s)\n")
        rows = [{"name": n, **{k: v for k, v in c.items() if k != "examples"}} for n, c in cols.items()]
        print(table(rows, ["name", "thinks", "talk", "in_prompt", "asked", "mention", "words"]))
        for n, c in cols.items():
            for e in c["examples"][:a.examples]:
                print(f"- {n}: {e}")
        return
    runs = []
    for b in a.batches:
        bdir = Path(b) if Path(b).is_dir() else Path(a.root) / b
        for d in sorted(p for p in bdir.iterdir() if p.is_dir()):
            r = run_report(d)
            if r:
                r["batch"] = bdir.name
                runs.append(r)
    if not runs:
        print("no runs with stands found")
        return
    print(table(runs, COLS))
    groups = defaultdict(list)
    for r in runs:
        groups[(r["batch"], r["variant"])].append(r)
    print("\n## Mean (range) per batch x variant\n")
    agg = []
    for (b, v), rs in sorted(groups.items()):
        row = {"batch": b, "variant": v, "n": len(rs)}
        for c in ["in_range", "first_sight", "asked", "in_prompt", "marked", "mention", "approaches", "aimed", "gestures", "lines_to", "lines_about", "acted_share", "first_contact_s", "thinks_per_res_min", "usd_h"]:
            xs = [r[c] for r in rs if r.get(c) is not None]
            row[c] = f"{statistics.mean(xs):.2f} ({min(xs)}–{max(xs)})" if xs else None
        row["no_contact"] = sum(1 for r in rs if r["first_contact_s"] is None)
        agg.append(row)
    print(table(agg, ["batch", "variant", "n", "in_range", "first_sight", "asked", "in_prompt", "marked", "mention", "approaches", "aimed", "gestures", "lines_to", "lines_about", "acted_share", "first_contact_s", "no_contact", "thinks_per_res_min", "usd_h"]))
    print("\n## Residents in range\n")
    for r in runs:
        print(f"### {r['batch']} {r['run']}\n")
        print(table(r["residents"], ["id", "name", "seen", "first_s", "first_sal", "crowd", "asked", "thinks", "in_prompt", "marked", "mention", "words", "approach", "aimed", "close", "gesture", "to_them", "about_them"]))
        for x in r["residents"]:
            for e in x["examples"][:a.examples]:
                print(f"- {x['name']}: {e}")
        print()
    if a.json:
        Path(a.json).write_text(json.dumps(runs, indent=1))


if __name__ == "__main__":
    main()
