#!/usr/bin/env python3
"""Blind excerpts of lives for the owner to rate (docs/TRIALS.md, "Owner-tuned player score").

  feel_excerpts.py build [--source LABEL=DIR ...] [--quota LABEL=N ...] [--skip LABEL:VARIANT ...]
                         [--window 10] [--seed 1] [--out .local/living/feel]
  feel_excerpts.py show [--out DIR] [--key]   print the blind excerpts as the page shows them
                                               (--key adds each one's source: not for the rater)
  feel_excerpts.py rescore [--key K] [--out-key K2]   the key's window columns again, with the
                                               current life_feel (new columns), same windows and ids

`build` reads trial evidence (read-only), cuts candidate windows of `--window` real minutes from
each run's thinking characters, scores every candidate with life_feel.py's own column definitions
on just that window, draws `--quota` excerpts per source spread across its arms, trials, early and
late windows and a provisional composite (`feel0`, below), renders each as a plain second-person
timeline in neutral words, shuffles them and writes:

- `<out>/excerpts.json`: what the rating page shows, and nothing else: per excerpt an opaque id,
  a title ("Excerpt N", in shuffled order), an intro (the part of the day) and its lines. No run,
  batch, model, variant or arm name, no ids, coordinates or day numbers; the focal character's
  own name is replaced by a pseudonym.
- `<out>/excerpts_key.json`: PRIVATE. Excerpt id -> source label, batch directory, run, variant,
  character, window (minutes of the run), life_feel columns on the window (`feel_window`) and on
  the whole run so far (`feel_run`), `feel0`, and leak-check flags. Never serve it with the page.
  The default out directory is under the git-ignored `.local/living/`.

Who an excerpt follows. A run whose subject has a mind (a journal with replies) is followed through
the subject: its percepts (`experiences.jsonl`, which include what it said and heard), its decided
plans (journal replies) and its body (`samples.jsonl`). A run whose subject is a scripted human (the
greeting trials) is followed through one thinking resident: speech it said or heard comes from
`speech.jsonl` joined to `audience.jsonl` (who heard each line), named as the resident knows people
(names it has met, else "a stranger", "a child", "an old stranger" by life stage); its other percepts
are the "Recent experiences" lines of its journal requests, placed on the run's clock through the
census (world hour against real time); its plans come from its replies, its body from
`census.jsonl`. Both render through the same filters.

What a line is. Lines fall in categories, and a window's lines are drawn round-robin across them
(at most `MAX_LINES`, then put back in time order), so no one kind fills the excerpt: events
(learned, given, received, hosted, read, agreed, deaths, fights), speech addressed to the character,
its own speech, its plan (the plan it held at the start, then changes), struggles (failures, cold,
hunger, danger, going in circles, unanswered calls), other percepts, overheard speech. A line said
again, or nearly (word Jaccard 0.6+), and a repeated percept or failure is one line with a count.
Speech is verbatim, cut at `QUOTE` characters. A closing line gives how the body spent the window
and how hunger and health moved.

feel0, the stratifying composite, is provisional and NOT a calibrated score: the mean percentile
(among all candidates) of plans_other, acts_other, self_started, cells_h, addressed, people and
answered, and of minus fail_repeats_h and plan_repeats_h (a missing value counts as the median).
It only spreads the draw across the range; feel_tune.py fits the real weights from the owner's
ratings. A rebuild while a batch is still running draws different windows and new ids: build once
per rating page and keep that key.
"""
import argparse
import json
import math
import random
import re
import shutil
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import life_feel  # noqa: E402
import life_share  # noqa: E402
import trials  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / ".local/living/feel"
HOME = Path.home()
T = HOME / "dev"
# The coordinator's draw of 2026-11-11: single-thinker lives, then worlds where everyone thinks.
SOURCES = {
    "l6": [T / "slop-trials/.local/living/trials/l6"],
    "l7": [T / "slop-trials/.local/living/trials/l7"],
    "l8": [T / "slop-trials-cb/.local/living/trials/l8"],
    "l9": [T / "slop-trials-e6/.local/living/trials/l9"],
    "pf2": [T / "slop-runs-frame/.local/living/trials/pf2"],
    "s11": [T / "slop-trials/.local/living/trials/s11"],
    "s12": [T / "slop-trials-cb/.local/living/trials/s12", T / "slop-trials-cb/.local/living/trials/s12b"],
    "gr1a": [T / "slop-runs-greet/.local/living/trials/gr1a"],
    "gr1b": [T / "slop-runs-greet/.local/living/trials/gr1b"],
    # The greet-nearest and park-concurrent reruns (from 2026-11-11 18:00); add with --quota gr1c=N.
    "gr1c": [T / "slop-runs-greet/.local/living/trials/gr1c"],
}
QUOTA = {"l6": 2, "l7": 2, "l8": 2, "l9": 2, "pf2": 4, "s11": 2, "s12": 2, "gr1a": 3, "gr1b": 3, "gr1c": 0}
ALL_MINDS = {"s11", "s12", "gr1a", "gr1b", "gr1c"}
# Arms left out by default: in gr1a/gr1b these runs failed at publish (trial-server fd limit) and rerun as gr1c.
SKIP = {("gr1a", "greet-nearest"), ("gr1b", "park-concurrent")}
MAX_LINES = 12
QUOTE = 150
WINDOWS_PER_LIFE = 6
RESIDENTS_PER_RUN = 3
PSEUDONYMS = ["Tamsin", "Merrit", "Odile", "Brann", "Cadie", "Ferris", "Ysolde", "Garret", "Pell",
              "Sabra", "Tobiah", "Corwen", "Dasha", "Evander", "Jory", "Kestrel", "Lorne", "Maeve", "Niall", "Orla",
              "Perrin", "Quill", "Rhosyn", "Seren", "Teague", "Wynn"]
# goals_1d_other is left out: no goal can be held a game day inside a window shorter than a day.
POS_FEEL = ["plans_other", "acts_other", "self_started", "cells_h", "addressed", "people", "answered"]
NEG_FEEL = ["fail_repeats_h", "plan_repeats_h"]
# Words that would tell the owner where an excerpt came from, or that are out of the fiction.
LEAK = re.compile(r"verify-trial|\bbatch\b|\bvariant\b|player[- ]frame|\biter\d|\bl\d\b|\bs1\d\b|\bgr1|\bpf2\b|deepseek|glm|mistral|"
                  r"\bmodel\b|\bLLM\b|\bAI\b|\bNPC\b|\bplayers?\b|(?<!small )\bgame\b|\bsimulat\w*|#\d+|\(\s*-?\d+\s*,\s*-?\d+\s*\)|\bday \d+\b", re.I)

jl = life_share.jl
NOW = re.compile(r"Now day (\d+) (\d\d):(\d\d)")
STAMP = re.compile(r"^- \[day (\d+) (\d\d):(\d\d)\] (.*)$")  # "# Recent experiences" lines
STAMP2 = re.compile(r"^- \[\d+\] day (\d+) (\d\d):(\d\d) (.*)$")  # "# New experiences to integrate" lines
# Engine feedback about the thinking budget, not something that happens in the world.
ENGINE = re.compile(r"hardly lived with|not a habit to rework|habit to rework|see how it goes first")
ANNOT = re.compile(r"\s*\{[^{}]*=#\d+[^{}]*\}")
PAIR = re.compile(r"([^{},=]+)=#(\d+)")
SPEECH_PERCEPT = re.compile(r"\bsaid(?: to [^:“]+)?: “")
COORD = r"[\(\[]\s*-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?\s*[\)\]]"


# ----------------------------------------------------------------------------- evidence reading

def batch_variants(bd):
    p = bd / "batch.json"
    vs = json.loads(p.read_text()).get("variants", []) if p.exists() else []
    return sorted(vs, key=len, reverse=True)


def variant_of(run, variants):
    return next((v for v in variants if re.search(rf"-{re.escape(v)}-r\d+$", run)), "?")


def trial_of(run, variant):
    return re.sub(rf"-{re.escape(variant)}-r\d+$", "", run)


def journal_dir(d):
    live = d.parents[2] / "journal" / f"{trials.PREFIX}{d.parent.name}-{d.name}"
    return live if live.exists() else d / "journal"


def replies(rows):
    """(at_ms, reply dict, row) per journal row with a parsable reply."""
    out = []
    for r in rows:
        rep = life_share.reply(r)
        if rep:
            out.append((int(r.get("at_ms") or 0), rep, r))
    return out


def plan_of(rep):
    p = rep.get("plan")
    return p.strip() if isinstance(p, str) and p.strip() else None


def user_text(r):
    msgs = (r.get("request") or {}).get("messages") or []
    u = msgs[-1].get("content") if msgs else None
    return u if isinstance(u, str) else ""


class Life:
    """One character's run, normalised: percepts, body samples and plans on one ms clock."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def names_from(texts):
    m = {}
    for t in texts:
        for blob in re.findall(r"\{([^{}]*)\}", t):
            for name, i in PAIR.findall(blob):
                name = name.strip()
                if name and name.lower() not in ("someone", "you"):
                    m.setdefault(int(i), name)
    return m


def subject_life(d, label, variants):
    st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
    summ = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else None
    if summ:
        name, S = summ["subject"].split("#")
        S = int(S)
    else:
        S = st.get("subject")
        cast = json.loads((d / "cast.json").read_text())
        name = next(r["name"] for r in cast["roles"]["subject"] if r["id"] == S)
    jdir = journal_dir(d)
    jrows = jl(jdir / f"{name}.jsonl")
    reps = replies(jrows)
    if not any(plan_of(rep) or rep.get("acts") for _, rep, _ in reps):
        return None  # a scripted subject: follow residents instead
    exps = [e for e in jl(d / "experiences.jsonl") if e.get("observer", S) == S and e.get("at_ms")]
    samples = [x for x in jl(d / "samples.jsonl") if x.get("pos")]
    if not exps or len(samples) < 10:
        return None
    offs = sorted(int(e["at_ms"]) - e["t"] * 1000 for e in exps if e.get("t") is not None)
    t0 = offs[len(offs) // 2]
    percepts = [(int(e["at_ms"]), e.get("kind") or "", e.get("text") or "") for e in exps]
    body = [(t0 + x["t"] * 1000, (x.get("activity") or ["idle"])[0], x.get("hour"), x.get("hunger"), x.get("hp")) for x in samples]
    plans = [(at, plan_of(rep)) for at, rep, _ in reps if plan_of(rep)]
    variant = summ.get("variant") if summ else variant_of(d.name, variants)
    return Life(label=label, d=d, run=d.name, variant=variant, trial=trial_of(d.name, variant), name=name, id=S,
                kind="subject", t0=t0, end=body[-1][0], percepts=percepts, body=body, plans=plans,
                names=names_from(t for _, _, t in percepts), journal=jrows)


def census_clock(census):
    """ms for a game time in hours since day 1 00:00, fitted on the census (world hour, real ms)."""
    pts, day, last = [], 0, None
    for c in census:
        h = c.get("hour")
        if h is None or not c.get("now_ms"):
            continue
        if last is not None and h < last - 12:
            day += 1
        last = h
        pts.append((day * 24 + h, int(c["now_ms"])))
    if len(pts) < 2:
        return None
    mx, my = statistics.mean(p[0] for p in pts), statistics.mean(p[1] for p in pts)
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if not sxx:
        return None
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    return (lambda g: my + b * (g - mx)), b * 24  # ms at game hour g; ms per game day


def resident_lives(d, label, variants, rng):
    """The thinking residents of a run whose subject is scripted, each read through its journal."""
    st = json.loads((d / "state.json").read_text())
    jdir = journal_dir(d)
    files = sorted(jdir.glob("*.jsonl")) if jdir.exists() else []
    census = jl(d / "census.jsonl")
    if not files or not census:
        return []
    cc = census_clock(census)
    if not cc:
        return []
    to_ms, day_ms = cc
    t0 = st["t0"] * 1000
    people, stage = {}, {}
    for c in census:
        for p in c.get("people") or []:
            people[p["id"]] = p["name"]
            stage[p["id"]] = p.get("stage", 2)
    by_name = {v: k for k, v in people.items()}
    speech = jl(d / "speech.jsonl")
    hear = defaultdict(set)
    for a in jl(d / "audience.jsonl"):
        hear[(a.get("speaker"), int(a.get("at_ms") or 0))] |= {h[0] for h in a.get("hearers") or []}
    subj = st.get("subject")
    variant = variant_of(d.name, variants)
    cands = []
    for f in files:
        name = f.stem.replace("_", " ")
        R = by_name.get(name)
        if R is None or (subj is not None and R == subj):
            continue
        cands.append((f, name, R))
    lives = []
    for f, name, R in rng.sample(cands, min(RESIDENTS_PER_RUN, len(cands))):
        rows = jl(f)
        reps = replies(rows)
        if len(reps) < 5:
            continue
        seen, percepts, known = set(), [], {}  # known: id -> first ms the resident knew the name

        def learn(i, ms):
            if i not in known or ms < known[i]:
                known[i] = ms
        for r in rows:
            u = user_text(r)
            asked = int(r.get("at_ms") or 0) - int(r.get("latency_ms") or 0) - int(r.get("queue_wait_ms") or 0)
            if "# People you know" in u:
                for nm, i in re.findall(r"^- ([^\n(]+?) \(#(\d+)\)", u.split("# People you know", 1)[1].split("\n# ", 1)[0], re.M):
                    if not re.match(r"(a|an|the) ", nm.strip(), re.I):
                        learn(int(i), asked)
            for head, rx in (("# Recent experiences (oldest first)", STAMP), ("# New experiences to integrate", STAMP2)):
                if head not in u:
                    continue
                for line in u.split(head, 1)[1].split("\n# ")[0].splitlines():
                    m = rx.match(line.strip())
                    if not m:
                        continue
                    key = (m[1], m[2], m[3], m[4])
                    if key in seen:
                        continue
                    seen.add(key)
                    # Stamps are whole game minutes, rounded down: place each half a minute later.
                    ms = int(to_ms((int(m[1]) - 1) * 24 + int(m[2]) + (int(m[3]) + 0.5) / 60))
                    for blob in re.findall(r"\{([^{}]*)\}", m[4]):
                        for n, i in PAIR.findall(blob):
                            if n.strip().lower() not in ("someone", "you"):
                                learn(int(i), ms)
                    if SPEECH_PERCEPT.search(m[4]):
                        continue  # speech comes from speech.jsonl, at its exact time
                    percepts.append((ms, "", m[4]))

        def who(i, at, cap=False):
            if i == R:
                return "you"
            if i in people and i != subj and known.get(i, float("inf")) <= at:
                return people[i]
            s = {0: "a baby", 1: "a child", 3: "an old stranger"}.get(stage.get(i, 2), "a stranger")
            return s[0].upper() + s[1:] if cap else s

        for s in speech:
            words = re.search(r"“(.*)”", s.get("text") or "", re.S)
            words = words[1] if words else ""
            at, a, b = int(s["at_ms"]), s.get("a"), s.get("b")
            if a == R:
                percepts.append((at, "said", f"You said{' to ' + who(b, at) if b not in (0, None) else ''}: “{words}”"))
            elif R in hear.get((a, at), set()) or b == R:
                to = "you" if b == R else (who(b, at) if b not in (0, None) else None)
                percepts.append((at, "speech", f"{who(a, at, True)} said{' to ' + to if to else ''}: “{words}”"))
        percepts.sort(key=lambda p: p[0])
        body = []
        for c in census:
            p = next((p for p in c.get("people") or [] if p["id"] == R), None)
            if p and p.get("alive", True):
                body.append((int(c["now_ms"]), (p.get("activity") or ["idle"])[0], c.get("hour"), p.get("hunger"), p.get("hp")))
        names = {i: people[i] for i in known if i in people and i != subj}  # for ids in plans: names it ever knew
        lives.append(Life(label=label, d=d, run=d.name, variant=variant, trial=trial_of(d.name, variant), name=name, id=R,
                          kind="resident", t0=t0, end=max([b[0] for b in body] + [t0]), percepts=percepts, body=body,
                          plans=[(at, plan_of(rep)) for at, rep, _ in reps if plan_of(rep)], names=names, journal=rows,
                          census=census, speech=speech, day_ms=day_ms, stranger_name=people.get(subj)))
    return lives


def lives_of(label, dirs, rng):
    out = []
    for bd in dirs:
        variants = batch_variants(bd)
        for d in sorted(p for p in bd.iterdir() if p.is_dir() and ((p / "summary.json").exists() or (p / "state.json").exists())):
            if not (d / "samples.jsonl").exists() or (d / "samples.jsonl").stat().st_size == 0:
                continue
            life = subject_life(d, label, variants)
            out.extend([life] if life else resident_lives(d, label, variants, rng))
    return out


# ----------------------------------------------------------------------------- life_feel on a window

def write_jl(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def day_ms_of(life):
    if getattr(life, "day_ms", None):
        return int(life.day_ms)
    s = life.d / "summary.json"
    if s.exists() and json.loads(s.read_text()).get("day_ms"):
        return int(json.loads(s.read_text())["day_ms"])
    # From the first body samples: real ms per world hour, while the clock has not wrapped.
    pts = [(b[0], b[2]) for b in life.body if b[2] is not None][:200]
    if len(pts) > 2 and pts[-1][1] > pts[0][1]:
        return int((pts[-1][0] - pts[0][0]) / (pts[-1][1] - pts[0][1]) * 24)
    return 720000


def feel_dir(life, a_ms, b_ms, root):
    """A directory life_feel.run reads as this character's life between a_ms and b_ms. Every `t`
    is rebased to the window's start, as life_feel expects of a run's own files."""
    d = root / life.label / f"{life.run}-{life.id}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    base = (a_ms - life.t0) / 1000
    in_t = lambda t: t is not None and a_ms <= life.t0 + t * 1000 <= b_ms
    in_ms = lambda ms: ms is not None and a_ms <= int(ms) <= b_ms
    re_t = lambda r: dict(r, t=r["t"] - base)
    minutes = (min(b_ms, life.end) - a_ms) / 60000
    (d / "summary.json").write_text(json.dumps({"subject": f"{life.name}#{life.id}", "minutes_run": max(minutes, 0.5),
                                                "day_ms": day_ms_of(life), "variant": life.variant}))
    write_jl(d / "journal" / f"{life.name}.jsonl", [r for r in life.journal if in_ms(r.get("at_ms"))])
    # life_feel dates samples by the chronicle's (at_ms - t); an anchor row keeps that right in a quiet window.
    anchor = {"t": 0.0, "id": -1, "at_ms": int(a_ms), "kind": "window", "a": 0, "b": 0, "text": ""}
    if life.kind == "subject":
        src = life.d
        for f in ("samples", "experiences"):
            write_jl(d / f"{f}.jsonl", [re_t(r) for r in jl(src / f"{f}.jsonl") if in_t(r.get("t"))])
        gs = jl(src / "graphs.jsonl")
        held = [g for g in gs if g.get("source") == "mind" and g.get("t") is not None and life.t0 + g["t"] * 1000 < a_ms]
        # The plan held when the window opens, marked carried: life_feel reads it for the own-project measure only.
        write_jl(d / "graphs.jsonl", ([dict(held[-1], t=0.0, carried=True)] if held else []) + [re_t(r) for r in gs if in_t(r.get("t"))])
        write_jl(d / "chronicle.jsonl", [anchor] + [re_t(r) for r in jl(src / "chronicle.jsonl") if in_t(r.get("t"))])
        rows, last_persona = [], None
        for r in jl(src / "mind_rows.jsonl"):
            if r.get("table") == "persona":
                if r["t"] * 1000 + life.t0 < a_ms:
                    last_persona = dict(r, t=0.0)
                elif in_t(r["t"]):
                    rows.append(re_t(r))
            elif r.get("table") == "place" and r["t"] * 1000 + life.t0 <= b_ms:
                rows.append(dict(r, t=max(0.0, r["t"] - base)))
        write_jl(d / "mind_rows.jsonl", ([last_persona] if last_persona else []) + rows)
        return d
    # A resident: synthesise the files life_feel reads from its journal, the census and speech.
    R = life.id
    tt = lambda ms: (ms - a_ms) / 1000
    samples = []
    for c in life.census:
        p = next((p for p in c.get("people") or [] if p["id"] == R), None)
        if p and in_ms(c["now_ms"]):
            act = p.get("activity") or ["idle"]
            samples.append({"t": tt(c["now_ms"]), "hour": c.get("hour"), "pos": p.get("pos"), "hunger": p.get("hunger"),
                            "activity": [act[0], act[0]]})
    write_jl(d / "samples.jsonl", samples)
    write_jl(d / "chronicle.jsonl", [anchor] + [dict(s, t=tt(int(s["at_ms"]))) for s in life.speech if in_ms(s.get("at_ms"))])
    exps = []
    for ms, kind, text in life.percepts:
        if in_ms(ms) and kind not in ("said", "speech"):
            k = "silence" if text.startswith("No answer from") else ("act" if life_feel.FAIL.match(text) else "seen")
            exps.append({"t": tt(ms), "at_ms": ms, "observer": R, "kind": k, "text": text})
    write_jl(d / "experiences.jsonl", exps)
    before = [p for ms, p in life.plans if ms < a_ms]
    write_jl(d / "graphs.jsonl", ([{"t": 0.0, "plan": before[-1], "source": "mind", "carried": True}] if before else []) +
             [{"t": tt(ms), "plan": p, "source": "mind"} for ms, p in life.plans if in_ms(ms)])
    personas, last = [], None
    for r in life.journal:
        m = re.search(r"^Goals: (.*)$", user_text(r), re.M)
        if not m or not r.get("at_ms") or int(r["at_ms"]) > b_ms:
            continue
        goals = [g.strip() for g in m[1].split(";") if g.strip()]
        if goals != last:
            row = {"t": max(0.0, tt(int(r["at_ms"]))), "table": "persona", "rows": [{"id": R, "goals": goals}]}
            personas = [row] if int(r["at_ms"]) < a_ms else personas + [row]
            last = goals
    write_jl(d / "mind_rows.jsonl", personas)
    return d


def feel(d):
    r = life_feel.run(d, [])
    return {k: r.get(k) for k in life_feel.KEYS}


# ----------------------------------------------------------------------------- rendering

ARGS_FOR_SOMEONE = {"to", "with", "from", "for", "and", "or", "of", "at", "by", "on", "near", "toward", "towards", "ask", "tell", "give",
                    "teach", "find", "meet", "follow", "join", "see", "visit", "help", "greet", "watch", "let", "than", "as", "wave",
                    "nod", "face", "attack", "offer", "host", "heal", "demand", "threaten", "beside", "behind", "after", "when", "if"}


def clean(text, life, pseudo):
    t = ANNOT.sub("", text)
    t = re.sub(r"\bgoto → ", "go to ", t)
    t = re.sub(r"\b([a-z_0-9]+) → ", r"\1 ", t)
    known = lambda i: life.names.get(int(i))
    t = re.sub(r"\s*\(#(\d+)\)", lambda m: f" ({known(m[1])})" if known(m[1]) else "", t)
    t = re.sub(r"\bno #(\d+)", lambda m: f"no {known(m[1])}" if known(m[1]) else "no one", t)
    # "the hunter #45", "campfire #579": the id goes; "with #45": the name the character knows, else "someone".
    t = re.sub(r"\b([A-Za-z]+) #(\d+)\b", lambda m: f"{m[1]} {known(m[2])}" if known(m[2]) else
               (f"{m[1]} someone" if m[1].lower() in ARGS_FOR_SOMEONE else m[1]), t)
    t = re.sub(r"#(\d+)", lambda m: known(m[1]) or "someone", t)
    for n in sorted({life.name, life.name.split()[0]}, key=len, reverse=True) if life.kind == "subject" else []:
        t = re.sub(rf"\b{re.escape(n)}\b", pseudo, t)
    if getattr(life, "stranger_name", None):  # the scripted newcomer of a greeting trial
        t = re.sub(rf"\b{re.escape(life.stranger_name)}\b", "the stranger", t)
    t = re.sub(rf",? ?(?:around|at) {COORD}", "", t)
    t = re.sub(rf"\s*→\s*{COORD}", " somewhere", t)
    t = re.sub(rf"\b(near|to|toward|towards|by|from) {COORD}", r"\1 a spot", t)
    t = re.sub(COORD, "", t)
    t = re.sub(r"\(\{.*?\}\)", "", t)  # decided-act JSON in failure text
    t = re.sub(r"(\d+ tiles? \w+), [^.“]*\.$", r"\1.", t)  # what a sighted person was doing, as a skill name
    t = re.sub(r"(A new day begins for you): day \d+ \(([^)]*)\)", r"\1 (\2)", t)
    t = re.sub(r"\(written on day \d+\)", "(written earlier)", t)
    t = re.sub(r"\b(at|near|to) -?\d{1,4}(?:\.\d+)?, ?-?\d{1,4}(?:\.\d+)?\b", r"\1 a spot", t)
    parts = re.split(r"(“[^”]*”)", t)  # outside quotes, snake_case item and skill names read as words
    t = "".join(p if p.startswith("“") else re.sub(r"(?<=[a-z])_(?=[a-z])", " ", p) for p in parts)
    t = re.sub(r"\s{2,}", " ", t).strip()
    m = re.search(r"“([^”]*)”", t)
    if m and len(m[1]) > QUOTE:
        t = t.replace(m[1], m[1][: QUOTE - 1].rstrip() + "…")
    return t


FAILS = re.compile(r"^(What you had decided did not work out: |You could not act on what you decided:? ?|You failed to )")
SKIP_DONE = re.compile(r"^You did what you had decided: (goto|wander|wait|follow|face|flee|rework)\b")
GROUPS = [  # (pattern, group key, category): repeated percepts shown once, with a count
    (re.compile(r"^You come to a place new to you"), "new ground", "other"),
    (re.compile(r"^For the first time you see"), "first sight", "other"),
    (re.compile(r"^You see .* again after a long time"), "seen again", "other"),
    (re.compile(r"^You notice an? "), "notice", "other"),
    (re.compile(r"wolf is close|is close to you|stalks you|bares its teeth"), "danger", "struggle"),
    (re.compile(r"^You see an? (wolf|deer|rabbit|boar|fox|bear)\b"), "animal sighted", "other"),
    (re.compile(r"^You hear .*howl"), "howl", "other"),
    (re.compile(r"^You hear "), "sound", "other"),
    (re.compile(r"^No answer from"), "no answer", "struggle"),
    (re.compile(r"^You keep turning back and forth"), "dither", "struggle"),
    (re.compile(r"answers your greeting|greets you"), "greeting", "other"),
    (re.compile(r"^(A |An )?[\w .'-]*?(cooked|crafted|built|wrote|gathered|smoked|stored|planted) "), "others at work", "other"),
    (re.compile(r"took \d+ .* from .*storage"), "store taken", "other"),
    (re.compile(r"(decided to start a family)"), "animals", "skip"),
    (re.compile(r"^(A|An) (deer|wolf|rabbit|boar|fox|bear)\b"), "animals", "other"),
    (re.compile(r"^You are among a crowd"), "crowd", "other"),
    (re.compile(r"spoiled"), "spoiled", "other"),
]
EVENT = re.compile(r"taught you|^You taught|gave you|^You gave|you worked out|^While tinkering|^You read|terms|agree|takes you in|"
                   r"took you in|tended your|died|was killed|attack|threaten|^You built|^You learned", re.I)
STRUGGLE = re.compile(r"freezing|very hungry|starving|You are hungry|exhausted|hurt|bleeding|wound", re.I)
ORDER = ["event", "to_you", "said", "plan", "struggle", "other", "overheard"]
ACT_WORDS = {"sleep": "sleeping", "goto": "walking", "wander": "wandering", "wait": "waiting", "rest": "resting", "gather": "gathering",
             "keep": "tending a fire", "eat": "eating", "experiment": "tinkering", "store": "storing things", "write": "writing",
             "take": "taking from a store", "smoke": "smoking meat", "wave": "waving", "teach": "teaching", "build": "building",
             "follow": "following someone", "attack": "fighting", "give": "giving", "read": "reading", "rework": "deep in thought",
             "conceive": "courting", "craft": "crafting", "cook": "cooking", "nod": "nodding", "tend": "tending wounds",
             "flee": "fleeing", "drop": "putting things down", "offer_terms": "bargaining", "face": "turning to someone",
             "appraise": "sizing someone up", "offer": "offering", "demand": "demanding", "threaten": "threatening",
             "plant": "planting", "fish": "fishing", "idle": "standing about", "talk": "talking", "play": "playing",
             "host": "hosting", "heal": "healing", "signal": "signalling", "join": "joining someone", "seize": "seizing"}


def part_of_day(life, ms):
    hs = [(abs(b[0] - ms), b[2]) for b in life.body if b[2] is not None]
    if not hs:
        return None
    h = min(hs)[1] % 24
    return "night" if h < 5 or h >= 21 else "early morning" if h < 8 else "morning" if h < 12 else "afternoon" if h < 17 else "evening"


def hunger_word(v):
    return None if v is None else "fed" if v < 35 else "getting hungry" if v < 60 else "hungry" if v < 85 else "starving"


def spread(xs):
    """xs reordered so that taking a prefix samples the whole span: first, last, middle, quarters..."""
    if len(xs) <= 2:
        return list(xs)
    idx, out = [0, len(xs) - 1], []
    frac = [1 / 2, 1 / 4, 3 / 4, 1 / 8, 3 / 8, 5 / 8, 7 / 8]
    idx += [round(f * (len(xs) - 1)) for f in frac]
    idx += list(range(len(xs)))
    for i in idx:
        if xs[i] not in out:
            out.append(xs[i])
    return out


def render(life, a_ms, b_ms, pseudo):
    """The excerpt's lines: [{"t": "+m:ss", "kind", "text"}], and how many candidate lines were dropped."""
    items, groups = [], {}
    rel = lambda ms: f"+{int((ms - a_ms) // 60000)}:{int((ms - a_ms) % 60000 // 1000):02d}"

    def add(ms, kind, text, cat, key=None):
        if key is not None and key in groups:
            groups[key]["n"] += 1
            return
        it = {"ms": ms, "kind": kind, "text": text, "cat": cat, "n": 1, "near": False,
              "words": set(re.findall(r"[a-z']+", text.lower()))}
        if key is not None:
            groups[key] = it
        items.append(it)

    for ms, kind, raw in life.percepts:
        if not a_ms <= ms <= b_ms or SKIP_DONE.match(raw) or ENGINE.search(raw):
            continue
        text = clean(raw, life, pseudo)
        if not text:
            continue
        m = FAILS.match(text)
        if m:
            rest = re.sub(r"^[:\s]+", "", text[m.end():])
            if re.search(r"graph\.|unknown kind|could not parse|invalid|\{\"do\"|\bnode\b|\bschema\b", rest):
                rest = "what you decided could not be carried out"
            add(ms, "did", "Did not work: " + rest, "struggle", ("fail", re.sub(r"\d+", "#", rest).rstrip(" .")[:90]))
            continue
        if raw.startswith("You said almost the same thing"):
            add(ms, "saw", "You catch yourself saying almost the same thing again.", "struggle", ("group", "repeat"))
            continue
        if raw.startswith("You did what you had decided:"):
            add(ms, "did", "You did: " + text.split(":", 1)[1].strip(), "other", ("done", text[:80]))
            continue
        if kind == "said" or text.startswith("You said"):
            k, cat = "said", "said"
        elif kind == "speech" or SPEECH_PERCEPT.search(text):
            k, cat = "heard", ("to_you" if "said to you" in text else "overheard")
        else:
            g = next(((key, c) for rx, key, c in GROUPS if rx.search(text)), None)
            if g and g[1] == "skip":
                continue
            if g:  # unanswered calls are grouped per person, everything else per kind
                add(ms, "saw", text, g[1], ("group", g[0]) + ((text,) if g[0] == "no answer" else ()))
                continue
            cat = "event" if EVENT.search(text) else "struggle" if STRUGGLE.search(text) else "other"
            add(ms, "saw", text, cat, ("one", re.sub(r"\d+", "#", text)))
            continue
        # The same line again, or nearly (Jaccard of its words 0.6 or more), is one line with a count.
        ws = set(re.findall(r"[a-z']+", text.lower()))
        twin = next((it for it in items if it["kind"] == k and ws | it["words"] and
                     len(ws & it["words"]) / len(ws | it["words"]) >= 0.6), None)
        if twin:
            twin["n"] += 1
            twin["near"] = twin["near"] or twin["text"] != text
            continue
        add(ms, k, text, cat)
    plans = [(ms, p) for ms, p in life.plans if ms <= b_ms]
    start_plan = next((p for ms, p in reversed(plans) if ms < a_ms), None)
    last = start_plan
    changes = []
    for ms, p in plans:
        if a_ms <= ms <= b_ms and p != last:
            changes.append((ms, p))
            last = p
    if start_plan:
        add(a_ms, "plan", "Your plan: " + clean(start_plan, life, pseudo), "plan")
    for ms, p in changes:
        add(ms, "plan", "You decide: " + clean(p, life, pseudo), "plan")
    for it in items:
        if it["n"] > 1:
            it["text"] += f" (×{it['n']} in these minutes{', in much the same words' if it['near'] else ''})"
    # Conversation first: a line to the character and its reply (or its line and the answer) stay together.
    talk = sorted((it for it in items if it["cat"] in ("to_you", "said")), key=lambda it: it["ms"])
    units, used = [], set()
    for i, it in enumerate(talk):
        if id(it) in used:
            continue
        mate = next((o for o in talk[i + 1:] if id(o) not in used and o["cat"] != it["cat"] and o["ms"] - it["ms"] <= 45000), None)
        unit = [it] + ([mate] if mate else [])
        used |= {id(x) for x in unit}
        units.append(unit)
    exchanges = spread([u for u in units if len(u) == 2 or u[0]["cat"] == "to_you"])
    singles = spread([u for u in units if not (len(u) == 2 or u[0]["cat"] == "to_you")])
    queues = {c: spread(sorted((it for it in items if it["cat"] == c), key=lambda it: it["ms"])) for c in ORDER}
    plans_q = queues["plan"]
    start_item = next((it for it in plans_q if it["text"].startswith("Your plan: ")), None)
    changes_q = [it for it in plans_q if it is not start_item]
    chosen, budget = ([start_item] if start_item else []), MAX_LINES - 1

    def take(q, n):
        while q and n > 0 and len(chosen) < budget:
            chosen.append(q.pop(0))
            n -= 1

    take(queues["event"], 3)
    conv = 0
    for q in (exchanges, singles):
        while q and conv + len(q[0]) <= 6 and len(chosen) + len(q[0]) <= budget:
            u = q.pop(0)
            chosen.extend(u)
            conv += len(u)
    take(changes_q, 2)
    take(queues["struggle"], 2)
    take(queues["other"], 1)
    take(queues["overheard"], 1)
    # What is left of the budget: more talk, plans, struggles, events, other, overheard, in turn.
    rest = [exchanges, singles, changes_q, queues["struggle"], queues["event"], queues["other"], queues["overheard"]]
    while len(chosen) < budget and any(rest):
        for q in rest:
            if q and len(chosen) < budget:
                x = q.pop(0)
                if isinstance(x, list):
                    if len(chosen) + len(x) <= budget:
                        chosen.extend(x)
                else:
                    chosen.append(x)
    chosen.sort(key=lambda it: it["ms"])
    dropped = len(items) - len(chosen)
    lines = [{"t": rel(it["ms"]), "kind": it["kind"], "text": it["text"]} for it in chosen]
    # The body over the window.
    spans = Counter()
    pts = [b for b in life.body if a_ms <= b[0] <= b_ms]
    end = min(b_ms, life.end)
    for b, nxt in zip(pts, pts[1:] + [(end,)]):
        spans[b[1]] += max(0, nxt[0] - b[0])
    if sum(spans.values()) > 0:
        parts = [f"{ACT_WORDS.get(a, a.replace('_', ' '))} ~{round(v / 60000)} min" for a, v in spans.most_common(4) if round(v / 60000) >= 1]
        hs = [b[3] for b in pts if b[3] is not None]
        tail = []  # health is left out: the census of the greeting trials does not carry it
        if hs:
            w0, w1 = hunger_word(hs[0]), hunger_word(hs[-1])
            if w0 != w1:
                tail.append(f"you went from {w0} to {w1}")
            elif w0 == "starving":
                tail.append("you were starving throughout")
        if parts:
            text = f"Over these {round((end - a_ms) / 60000)} minutes your body was " + ", ".join(parts)
            lines.append({"t": "", "kind": "body", "text": text + ("; " + "; ".join(tail) if tail else "") + "."})
    return lines, dropped


# ----------------------------------------------------------------------------- the draw

def windows(life, w_ms, k):
    """Up to k non-overlapping window starts, from 2 minutes in (and not before the first decided plan,
    so every excerpt can open with the plan held) to the end. A life shorter than that gives none."""
    first_plan = min((ms for ms, _ in life.plans), default=None)
    if first_plan is None:
        return []
    start, end = max(life.t0 + 120000, first_plan + 1000), life.end - w_ms
    if end < start:
        return []
    n = max(1, min(k, int((end - start) // w_ms) + 1))
    return [int(start + i * (end - start) / (n - 1)) for i in range(n)] if n > 1 else [int(start)]


def pct_ranks(vals):
    xs = sorted(v for v in vals if v is not None)
    out = []
    for v in vals:
        if v is None or len(xs) < 2:
            out.append(0.5)
        else:
            lo = sum(1 for x in xs if x < v)
            eq = sum(1 for x in xs if x == v)
            out.append((lo + (eq - 1) / 2) / (len(xs) - 1))
    return out


def pick(pool, quota, rng, glob):
    """quota windows from one source: arms round-robin (each arm's shortfall passed on), and within an
    arm, slot j aims at trial j mod #trials, the early or late half of the run (j even/odd), then the
    feel0 at the 5th or 95th percentile of ALL candidates (one slot: the median; more: evenly spaced from the 5th to the 95th; within 0.05 counts as near
    enough), so narrow arms give their extremes, from runs (and, for residents, characters) not drawn
    yet, in that order of precedence."""
    by_var = defaultdict(list)
    for x in pool:
        by_var[x["life"].variant].append(x)
    vs = sorted(by_var)
    rng.shuffle(vs)
    slots = Counter()
    left = quota
    while left > 0 and any(len(by_var[v]) > slots[v] for v in vs):
        for v in vs:
            if left > 0 and len(by_var[v]) > slots[v]:
                slots[v] += 1
                left -= 1
    chosen, names_drawn = [], set()  # residents: one window per character across runs of the same world
    for v in vs:
        xs = sorted(by_var[v], key=lambda x: x["feel0"])
        trial_names = sorted({x["life"].trial for x in xs})
        n = slots[v]
        used = set()
        used_names = names_drawn if pool and pool[0]["life"].kind == "resident" else set()
        for j in range(n):
            q = 0.5 if n == 1 else (0.05, 0.95)[j] if n == 2 else 0.05 + 0.9 * j / (n - 1)
            target = glob[min(len(glob) - 1, int(q * len(glob)))] if glob else 0.5
            want_trial = trial_names[j % len(trial_names)]
            want_late = j % 2 == 1

            def cost(i):
                x = xs[i]
                life = x["life"]
                late = (x["start"] - life.t0) > (life.end - life.t0) / 2
                gap = abs(x["feel0"] - target)
                return (x["life"].run in used or x["life"].name in used_names, x["life"].trial != want_trial,
                        late != want_late, round(gap * 10), gap)
            order = sorted((i for i in range(len(xs)) if xs[i] not in chosen), key=cost)
            if order:
                x = xs[order[0]]
                chosen.append(x)
                used.add(x["life"].run)
                used_names.add(x["life"].name)
    return chosen


def build(a):
    sources = {k: list(v) for k, v in SOURCES.items()}
    for s in a.source or []:
        k, v = s.split("=", 1)
        sources[k] = [Path(p).expanduser() for p in v.split(",")]
    quota = dict(QUOTA)
    for q in a.quota or []:
        k, v = q.split("=", 1)
        quota[k] = int(v)
    labels = [k for k in sources if quota.get(k, 0) > 0]
    skip = set(SKIP) if not a.skip else {tuple(x.split(":", 1)) for x in a.skip if x != "none"}
    w_ms = int(a.window * 60000)
    cands = []
    tmp = Path(tempfile.mkdtemp(prefix="feel-"))
    root = tmp / "x" / "y"
    try:
        for label in labels:
            rng = random.Random(f"{a.seed}-{label}")
            dirs = [d for d in sources[label] if d.is_dir()]
            for d in sources[label]:
                if not d.is_dir():
                    print(f"{label}: {d} missing; skipped", file=sys.stderr)
            lives = [l for l in lives_of(label, dirs, rng) if (label, l.variant) not in skip]
            k = WINDOWS_PER_LIFE if all(l.kind == "subject" for l in lives) else 2
            n0 = len(cands)
            for life in lives:
                for start in windows(life, w_ms, k):
                    lines, _ = render(life, start, start + w_ms, "X")
                    if len([x for x in lines if x["kind"] != "body"]) < 5:
                        continue
                    f = feel(feel_dir(life, start, start + w_ms, root))
                    cands.append({"life": life, "start": start, "feel_window": f})
            print(f"{label}: {len(lives)} lives, {len(cands) - n0} candidate windows "
                  f"({', '.join(f'{v} {n}' for v, n in sorted(Counter(c['life'].variant for c in cands[n0:]).items()))})", file=sys.stderr)
        ranks = {c: pct_ranks([x["feel_window"].get(c) for x in cands]) for c in POS_FEEL + NEG_FEEL}
        for i, x in enumerate(cands):
            x["feel0"] = round(statistics.mean([ranks[c][i] for c in POS_FEEL] + [1 - ranks[c][i] for c in NEG_FEEL]), 3)
        chosen = []
        for label in labels:
            chosen += pick([x for x in cands if x["life"].label == label], quota[label], random.Random(f"{a.seed}-{label}-pick"),
                           sorted(x["feel0"] for x in cands))
        rng = random.Random(a.seed)
        rng.shuffle(chosen)
        run_feel = {}
        for x in chosen:
            life = x["life"]
            key = (life.label, life.run, life.id)
            if key not in run_feel:
                d = life.d if life.kind == "subject" else feel_dir(life, life.t0, life.end, root / "run")
                run_feel[key] = feel(d)
            x["feel_run"] = run_feel[key]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    pool = rng.sample(PSEUDONYMS, len(PSEUDONYMS))
    blind, key, used_ids = [], {}, set()
    for n, x in enumerate(chosen, 1):
        life = x["life"]
        # A subject (always the same newcomer name across trials) gets a pseudonym no one in its window
        # bears; a resident keeps its own name, which its neighbours use.
        if life.kind == "resident":
            pseudo = life.name.split()[0]
        else:
            raw = " ".join(t for ms, _, t in life.percepts if x["start"] <= ms <= x["start"] + w_ms)
            pseudo = next(p for p in pool if not re.search(rf"\b{p}\b", raw))
            pool.remove(pseudo)
        eid = None
        while eid is None or eid in used_ids:
            eid = "".join(rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(5))
        used_ids.add(eid)
        lines, dropped = render(life, x["start"], x["start"] + w_ms, pseudo)
        pod = part_of_day(life, x["start"])
        intro = f"It is {pod}." if pod else ""
        blind.append({"id": eid, "title": f"Excerpt {n}", "intro": intro, "lines": lines})
        text = " ".join([intro] + [l["text"] for l in lines])
        leaks = sorted({m.group(0) for m in LEAK.finditer(text)} |
                       ({life.name} if life.kind == "subject" and re.search(rf"\b{re.escape(life.name)}\b", text) else set()))
        key[eid] = {"n": n, "source": life.label, "kind": "all-minds" if life.label in ALL_MINDS else "single",
                    "follows": life.kind, "batch_dir": str(life.d.parent), "run": life.run, "trial": life.trial, "variant": life.variant,
                    "character": life.name, "character_id": life.id, "pseudonym": pseudo if life.kind == "subject" else None,
                    "window_min": [round((x["start"] - life.t0) / 60000, 1), round((min(x["start"] + w_ms, life.end) - life.t0) / 60000, 1)],
                    "window_ms": int(x["start"]), "run_min": round((life.end - life.t0) / 60000, 1), "running": not (life.d / "summary.json").exists(),
                    "lines": len(lines), "lines_dropped": dropped, "leak_terms": leaks,
                    "feel_window": x["feel_window"], "feel_run": x["feel_run"], "feel0": x["feel0"]}
    meta = {"version": 1, "window_min": a.window, "seed": a.seed, "max_lines": MAX_LINES}
    (out / "excerpts.json").write_text(json.dumps({**meta, "excerpts": blind}, indent=1, ensure_ascii=False))
    f0 = sorted(x["feel0"] for x in cands)
    (out / "excerpts_key.json").write_text(json.dumps({
        **meta, "PRIVATE": "never serve with the page", "columns": life_feel.KEYS,
        "feel0_columns": {"positive": POS_FEEL, "negative": NEG_FEEL}, "candidates": len(cands),
        "candidate_feel0": {"min": f0[0], "q25": f0[len(f0) // 4], "median": f0[len(f0) // 2], "q75": f0[3 * len(f0) // 4], "max": f0[-1]} if f0 else None,
        "sources": {k: [str(p) for p in v] for k, v in sources.items() if k in labels}, "quota": {k: quota[k] for k in labels},
        "skipped_arms": sorted(f"{l}:{v}" for l, v in skip),
        "excerpts": key}, indent=1, ensure_ascii=False))
    print(f"{len(blind)} excerpts from {len(cands)} candidate windows -> {out}/excerpts.json (blind), {out}/excerpts_key.json (private)")
    if f0:
        print(f"  candidate feel0: min {f0[0]:.2f}, median {f0[len(f0) // 2]:.2f}, max {f0[-1]:.2f}")
    for (s, v), n in sorted(Counter((k["source"], k["variant"]) for k in key.values()).items()):
        print(f"  {s} {v}: {n}  feel0 " + ", ".join(f"{k['feel0']:.2f}@{k['window_min'][0]:.0f}m" for k in key.values() if k["source"] == s and k["variant"] == v))
    for eid, v in key.items():
        if v["leak_terms"]:
            print(f"  LEAK CHECK {eid}: {v['leak_terms']}")


def find_life(label, batch_dir, run, character, cache):
    """The Life of one character in one run (every resident read, none sampled)."""
    global RESIDENTS_PER_RUN
    if batch_dir not in cache:
        keep, RESIDENTS_PER_RUN = RESIDENTS_PER_RUN, 10 ** 6
        try:
            cache[batch_dir] = lives_of(label, [Path(batch_dir)], random.Random(0))
        finally:
            RESIDENTS_PER_RUN = keep
    return next((l for l in cache[batch_dir] if l.run == run and l.name == character), None)


def rescore(a):
    """Recompute each key excerpt's life_feel columns on its own window with the current life_feel
    (new columns included), into a copy of the key; the blind excerpts and ids are untouched."""
    kp = Path(a.key).expanduser()
    key = json.loads(kp.read_text())
    cache, tmp = {}, Path(tempfile.mkdtemp(prefix="feel-"))
    try:
        for eid, k in key["excerpts"].items():
            life = find_life(k["source"], str(Path(k["batch_dir"])), k["run"], k["character"], cache)
            if life is None:
                print(f"{eid}: {k['run']} {k['character']} not found; columns left as they were", file=sys.stderr)
                continue
            start = k.get("window_ms") or int(life.t0 + k["window_min"][0] * 60000)
            k.setdefault("feel_window_built", k["feel_window"])
            k["feel_window"] = feel(feel_dir(life, start, start + int(key.get("window_min", 10) * 60000), tmp / "x" / "y"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    key["columns"] = life_feel.KEYS
    key["rescored"] = "feel_window recomputed with the current life_feel; the build's values are in feel_window_built"
    out = Path(a.out_key).expanduser() if a.out_key else kp.with_name(kp.stem + ".rescored.json")
    out.write_text(json.dumps(key, indent=1, ensure_ascii=False))
    print(f"{len(key['excerpts'])} excerpts rescored -> {out}")


def show(a):
    out = Path(a.out).expanduser()
    ex = json.loads((out / "excerpts.json").read_text())
    key = json.loads((out / "excerpts_key.json").read_text())["excerpts"] if a.key else {}
    for e in ex["excerpts"]:
        k = key.get(e["id"])
        src = f"  <{k['source']} {k['run']} {k['character']} {k['window_min']}>" if k else ""
        print(f"## {e['title']}  [{e['id']}]{src}\n{e['intro']}")
        for l in e["lines"]:
            print(f"  {l['t']:>6}  {l['text']}")
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", action="append", help="LABEL=DIR[,DIR...] batch directories (read-only); adds or replaces a default")
    b.add_argument("--quota", action="append", help="LABEL=N excerpts from that source (0 leaves it out)")
    b.add_argument("--skip", action="append", help="LABEL:VARIANT arm to leave out (replaces the default list; 'none' leaves out nothing)")
    b.add_argument("--window", type=float, default=10.0, help="real minutes per excerpt")
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--out", default=str(OUT))
    s = sub.add_parser("show")
    s.add_argument("--out", default=str(OUT))
    s.add_argument("--key", action="store_true", help="add each excerpt's source (for the coordinator, never the rater)")
    r = sub.add_parser("rescore", help="recompute the key's window columns with the current life_feel")
    r.add_argument("--key", default=str(OUT / "excerpts_key.json"))
    r.add_argument("--out-key", help="default: <key>.rescored.json beside it")
    a = ap.parse_args()
    {"build": build, "show": show, "rescore": rescore}[a.cmd](a)


if __name__ == "__main__":
    main()
