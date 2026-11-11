#!/usr/bin/env python3
"""Does a life read like a player run by AI living their own life, or like an NPC surviving?
(docs/TRIALS.md, "Player-likeness measures")

  life_feel.py [--root DIR] [--examples N] BATCH [BATCH...]

BATCH is a batch name under DIR (default: this checkout's .local/living/trials) or a path to a
batch directory, so batches from several checkouts can be read in one call. Read-only: it opens
evidence files and writes nothing. A run still in progress (no summary.json yet) is read from
state.json and its files so far; its rates use the time it has run.

Every class below is a keyword or skill heuristic, not a judgment. They are pending calibration
against the owner's ratings of the same lives; read the printed examples before trusting a number.
"An act" is one entry of a model reply's `acts` (the decided acts, from the subject's journal),
timed by the journal row's `at_ms`. "Lines" are the chronicle's speech rows. An hour is a real
hour of the run; a game day is the summary's `day_ms` (720 s on current seeds).

1. Initiative.
   plans_other: share of the mind's installed plans (graphs.jsonl, source "mind") whose text
     matches neither life_share.FOOD nor life_share.WARM.
   acts_other: share of decided acts, moves left out, that life_share.act_class calls "other".
   self_started: share of decided acts (moves left out, exploring moves counted) that are
     directed, and were not prompted. Directed = social (say/wave/nod with a target; give, offer,
     offer_terms, accept, teach, demand, threaten, conceive, host, heal, follow, signal, play,
     join; not when the act's own words, its `text`, match FOOD or WARM, as an ask for a meal
     does), making (build other than campfire/shelter, craft other than cloak, experiment, write,
     read) or exploring (wander; a goto to an `at` point 32 m or more from every position sampled
     before the decision). Prompted = someone else said a line addressed to the subject in the 60 s
     before the decision (any addressed line, not only requests: the conservative reading).
   prompted: share of directed acts that were prompted.
2. Horizon. Goals are the subject's persona `goals` (mind_rows.jsonl, persona rows, in order).
   Goals are clustered by word overlap: content words (stopwords dropped, cut to 5 letters), a goal
   joins the cluster whose latest wording it shares the highest Jaccard index with, if 0.4 or
   more, at most one goal per cluster per persona version. A cluster is held from the first
   version that has it to the first later version that lacks it (or the end of the run).
   goals: clusters; goals_1d, goals_2d: held 1 and 2 game days or more; goals_1d_other: held 1
   day or more and matching neither FOOD nor WARM in any wording. goals_reached: clusters with an
   outcome in rows after the goal first appeared, by the goal's words: a structure kind named (or
   build/raise/house/home/holding → any build but a campfire) → the subject built it; a technique
   named (or a generic learning goal → any technique) → it learned it; write/tablet/sign/record → it
   wrote; trade/barter/deal/agree/bargain/exchange/sell/buy/pay → a give to or from it or an
   agreement record in its percepts; teach/pass on → it taught someone; a place it named
   (5+ letters, not home/camp) → it stood within 16 m of that place after the goal appeared and
   never before it (the town it arrives in does not count). Learning means a goal naming a
   technique, or a learn/master/study verb with craft/technique/art/knack. Family goals
   have no outcome class. The first class that matches gives the outcome; wordings drift within a
   cluster, so an outcome can answer an earlier or later wording of the goal.
3. Loops. A failure is an act/own percept saying "did not work out", "could not act" or "You
   failed"; its key is the text after that prefix, with ids and numbers replaced by #.
   fail_repeats_h: failures whose key was already seen in this run, per hour. fail_streak: the
   longest run of one key with no other act outcome (success or other failure) between.
   plan_repeats: installed plans whose text (lowercased, ids and numbers replaced) equals an
   earlier plan of the run; plan_repeats_h per hour.
4. Exploration. cells_h: distinct 16 m cells of the samples' positions per hour; late_cells_h:
   cells first entered after the first hour, per later hour; far_m: the farthest sample from the
   first sample's position.
5. Social reciprocity. lines: speech rows by the subject; addressed: those with an addressee;
   people: distinct addressees; answered: addressed lines followed within 60 s by a speech row
   from the addressee to the subject (each such row answers one line only); silence: 1 - answered / addressed; heard: lines addressed to
   the subject by anyone; no_earshot: "No answer from …; not within earshot" percepts. In
   single-mind trials residents do not think, so silence near 1 is the expected finding.
6. Distinctiveness, per batch x trial x variant: the mean (range) of 1 - cosine over pairs of
   runs, of three profiles. skill_diss: counts of decided acts by skill (the mind's choices);
   body_diss: the share of samples per activity (activity[0], "idle" when none; what the body
   did, graph routines included); goal_diss: counts of content words over the run's distinct goal
   wordings. Lives that look alike score near 0.
"""
import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import life_share  # noqa: E402  (jl, reply, act_class, FOOD, WARM)
import trials  # noqa: E402  (prices: trials.cost)

jl, reply, act_class, FOOD, WARM = life_share.jl, life_share.reply, life_share.act_class, life_share.FOOD, life_share.WARM

SOCIAL = {"give", "offer", "offer_terms", "accept", "teach", "demand", "threaten", "conceive", "host", "heal", "follow", "signal", "play", "join"}
GESTURE = {"say", "wave", "nod"}
MAKING = {"experiment", "write", "read"}
FAIL = re.compile(r"^(What you had decided did not work out: |You could not act on what you decided:? ?|You failed to )")
IDS = re.compile(r"#\d+|\d+(\.\d+)?")
STOP = set("""the a an and or of to in on at for my me i it its with by from before after that this is be so as one own
day days some someday any anyone someone who what all more then now here there get make find keep them their out up into about
every each not no but if when while until will can could would should just also still again first last today tomorrow
myself me mine our we us than is are was were been being let do done while ever never way ways""".split())
STRUCT_WORDS = re.compile(r"\b(campfire|shelter|storage|store|house|hut|trap|sign|wall|walls|smokehouse|rack|net|pen|well|bridge|forge|kiln|boat|raft|fence|gate|tower|workshop|granary|cellar)\b", re.I)
BUILD_GENERIC = re.compile(r"\b(build\w*|raise|house|home|holding|hut|homestead)\b", re.I)
LEARN_GENERIC = re.compile(r"\b(learn|master|study|work out)\w*\b.*\b(craft|technique|art|knack|know-how)", re.I)
WRITE = re.compile(r"\b(writ\w*|wrote|tablet\w*|sign|signs|record\w*)\b", re.I)
TRADE = re.compile(r"\b(trad\w*|barter\w*|deal\w*|agree\w*|bargain\w*|exchang\w*|sell\w*|buy\w*|pay\w*)\b", re.I)
TEACH = re.compile(r"\b(teach\w*|taught|pass on|pass down|hand down)\b", re.I)
TECHNIQUES = {"fire", "fire_bolt", "mending", "toolmaking", "archery", "torch", "fishing", "trapping", "shelter", "storage", "writing",
              "reading", "medicine", "masonry", "smoking", "cooking", "cloak", "weaving", "tanning", "carpentry", "farming", "pottery",
              "herbalism", "hunting", "healing"}


def words(text):
    return [w[:5] for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2]


def cosine(a, b):
    num = sum(a[k] * b.get(k, 0) for k in a)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def load(d):
    """The run's summary, or a partial one from state.json for a run still going."""
    if (d / "summary.json").exists():
        s = json.loads((d / "summary.json").read_text())
        name, S = s["subject"].split("#")
        return s, name, int(S), s["minutes_run"], s.get("day_ms") or 720000
    st = json.loads((d / "state.json").read_text())
    S = st["subject"]
    cast = json.loads((d / "cast.json").read_text())
    name = next(r["name"] for r in cast["roles"]["subject"] if r["id"] == S)
    samples = [x for x in jl(d / "samples.jsonl") if x.get("pos")]
    minutes = samples[-1]["t"] / 60 if samples else 0
    return {"variant": None, "partial": True, "stopped_by": st.get("status")}, name, S, minutes, 720000


def run(d, variants):
    s, name, S, minutes, day_ms = load(d)
    hours = max(minutes / 60, 1e-9)
    day_s = day_ms / 1000
    variant = s.get("variant") or next((v for v in variants if re.search(rf"-{re.escape(v)}-r\d+$", d.name)), "?")
    trial = re.sub(rf"-{re.escape(variant)}-r\d+$", "", d.name)
    samples = [x for x in jl(d / "samples.jsonl") if x.get("pos")]
    chron = jl(d / "chronicle.jsonl")
    exps = jl(d / "experiences.jsonl")
    graphs = [g for g in jl(d / "graphs.jsonl") if g.get("source") == "mind"]
    # As trials.py reads it: the mind's live journal while it exists, else the copy taken at the stop.
    live = d.parents[2] / "journal" / f"{trials.PREFIX}{d.parent.name}-{d.name}"
    journal = jl((live if live.exists() else d / "journal") / trials.journal_file(name))
    speech = [c for c in chron if c.get("kind") == "speech"]
    to_me = sorted(int(c["at_ms"]) for c in speech if c.get("b") == S and c.get("a") != S)
    ex = defaultdict(list)

    # 1. Initiative.
    plans = [g.get("plan") or "" for g in graphs]
    plan_other = [p for p in plans if not FOOD.search(p) and not WARM.search(p)]
    ex["plan_other"] = plan_other[:: max(1, len(plan_other) // 3)][:3]
    # Sample t is seconds since the run started; a chronicle row seen at t happened at or before it.
    t0_ms = max((int(c["at_ms"]) - c["t"] * 1000 for c in chron if c.get("at_ms") and c.get("t") is not None), default=0)
    seen_cells, si = [], 0
    acts = []
    for r in journal:
        at = int(r.get("at_ms") or 0)
        rep = reply(r)
        for a in rep.get("acts") or []:
            if isinstance(a, dict) and a.get("do"):
                acts.append((at, a, rep.get("plan") or rep.get("intent") or ""))
    acts.sort(key=lambda x: x[0])
    counted = directed = unprompted = prompted = 0
    classes = Counter()
    for at, a, why in acts:
        while si < len(samples) and t0_ms + samples[si]["t"] * 1000 <= at:
            seen_cells.append(samples[si]["pos"])
            si += 1
        do, cls = a["do"], act_class(a)
        classes[cls] += 1
        tgt = a.get("target")
        kind = None
        if do in SOCIAL or (do in GESTURE and isinstance(tgt, dict) and ("id" in tgt or "nearest" in tgt)):
            words_said = str(a.get("text") or "")
            kind = None if FOOD.search(words_said) or WARM.search(words_said) else "social"
        elif do in MAKING or (do == "build" and a.get("item") not in ("campfire", "shelter")) or (do == "craft" and a.get("item") != "cloak"):
            kind = "making"
        elif do == "wander" or (do == "goto" and isinstance(tgt, dict) and isinstance(tgt.get("at"), list) and len(tgt["at"]) == 2
                                and seen_cells and min(math.dist(tgt["at"], p) for p in seen_cells[::5]) >= 32):
            kind = "exploring"
        if cls != "move" or kind == "exploring":
            counted += 1
        if kind:
            directed += 1
            if any(at - 60000 <= t <= at for t in to_me):
                prompted += 1
            else:
                unprompted += 1
                if len(ex[kind]) < 2 and (kind != "social" or do != "wave"):
                    ex[kind].append(f"{json.dumps(a)[:110]} — {str(why)[:110]}")

    # 2. Horizon.
    personas = []
    for r in jl(d / "mind_rows.jsonl"):
        if r.get("table") == "persona":
            p = next((x for x in r.get("rows") or [] if x.get("id") == S), None)
            if p is not None:
                personas.append((r["t"], [str(g) for g in p.get("goals") or []]))
    clusters = []  # {texts, first, last_seen_version_index, dropped}
    for vi, (t, goals) in enumerate(personas):
        used = set()
        for g in goals:
            w = set(words(g))
            best, score = None, 0.0
            for ci, c in enumerate(clusters):
                if ci in used or c["dropped"] is not None:
                    continue
                lw = set(words(c["texts"][-1]))
                j = len(w & lw) / len(w | lw) if w | lw else 0
                if j > score:
                    best, score = ci, j
            if best is not None and score >= 0.4:
                c = clusters[best]
                if g != c["texts"][-1]:
                    c["texts"].append(g)
                c["last"] = vi
                used.add(best)
            else:
                clusters.append({"texts": [g], "first": t, "last": vi, "dropped": None})
                used.add(len(clusters) - 1)
        for ci, c in enumerate(clusters):
            if c["dropped"] is None and ci not in used:
                c["dropped"] = t
    end = minutes * 60
    places = {}
    for r in jl(d / "mind_rows.jsonl"):
        if r.get("table") == "place":
            for p in r.get("rows") or []:
                if p.get("actor") == S and p.get("name"):
                    places[p["name"].lower()] = (p["x"], p["y"])
    built = [(c["t"], c["text"]) for c in chron if c.get("kind") == "build" and c.get("a") == S]
    # A learn row's a is the teacher and b the learner; b is 0 when a worked it out alone.
    learned = [(c["t"], c["text"]) for c in chron if c.get("kind") == "learn" and ((c.get("a") == S and not c.get("b")) or c.get("b") == S)]
    wrote = [c["t"] for c in chron if c.get("kind") == "write" and c.get("a") == S]
    dealt = [c["t"] for c in chron if c.get("kind") == "give" and S in (c.get("a"), c.get("b"))] + \
            [e["t"] for e in exps if e.get("kind") == "record" and re.search(r"accepted your terms|agreed|kept on both sides", e.get("text", ""))]
    taught = [c["t"] for c in chron if c.get("kind") == "learn" and c.get("a") == S and c.get("b") not in (0, None, S)]

    def outcome(c):
        text = " ".join(c["texts"])
        after = lambda xs: [x for x in xs if (x[0] if isinstance(x, tuple) else x) >= c["first"]]
        kinds = {m.lower().rstrip("s") for m in STRUCT_WORDS.findall(text)} - {"store"}
        b = after(built)
        if kinds and any(k in t for _, t in b for k in kinds):
            return "built " + next(t for _, t in b if any(k in t for k in kinds)).split("built ", 1)[-1]
        if not kinds and BUILD_GENERIC.search(text) and any("campfire" not in t for _, t in b):
            return "built " + next(t for _, t in b if "campfire" not in t).split("built ", 1)[-1]
        named = {t for t in TECHNIQUES if re.search(rf"\b{t.replace('_', '[_ -]?')}\b", text, re.I)}
        lr = after(learned)
        if named and any(n.replace("_", " ") in t.replace("_", " ") for _, t in lr for n in named):
            return next(t for _, t in lr if any(n.replace("_", " ") in t.replace("_", " ") for n in named))
        if LEARN_GENERIC.search(text) and not named and lr:
            return lr[0][1]
        if WRITE.search(text) and after(wrote):
            return "wrote a tablet or sign"
        if TRADE.search(text) and after(dealt):
            return "a give or agreement"
        if TEACH.search(text) and after(taught):
            return "taught someone"
        for pname, xy in places.items():
            if len(pname) >= 5 and pname not in ("home", "camp") and pname in text.lower():
                near = [x["t"] >= c["first"] for x in samples if math.dist(x["pos"], xy) <= 16]
                if near and all(near):  # never there before the goal
                    return f"reached {pname}"
        return None

    held = []
    for c in clusters:
        span = (c["dropped"] if c["dropped"] is not None else end) - c["first"]
        held.append((span / day_s, c, outcome(c)))
    other_goal = lambda c: not any(FOOD.search(t) or WARM.search(t) for t in c["texts"])
    long = sorted((h for h in held if h[0] >= 2), key=lambda h: -h[0])
    ex["goal_2d"] = [f"{h[0]:.1f} d: “{h[1]['texts'][-1][:100]}” → {h[2] or 'no outcome in rows'}" for h in long[:3]]
    ex["goal_reached"] = [f"“{h[1]['texts'][0][:90]}” → {h[2][:70]}" for h in held if h[2]][:3]

    # 3. Loops.
    fails, streak, best, last = Counter(), 0, (0, ""), None
    for e in exps:
        if e.get("kind") not in ("act", "own") or e.get("observer", S) != S:
            continue
        m = FAIL.match(e.get("text", ""))
        key = IDS.sub("#", e["text"][m.end():])[:160] if m else None
        streak = streak + 1 if key and key == last else (1 if key else 0)
        last = key
        if key:
            fails[key] += 1
            if streak > best[0]:
                best = (streak, key)
    repeats = sum(n - 1 for n in fails.values())
    norm = [IDS.sub("#", p.lower()).strip() for p in plans if p]
    plan_rep = sum(1 for i, p in enumerate(norm) if p in set(norm[:i]))
    pc = Counter(norm)
    ex["loop"] = [f"{n}× {k[:120]}" for k, n in fails.most_common(2)] + ([f"longest streak {best[0]}× {best[1][:100]}"] if best[0] else [])
    ex["plan_repeat"] = [f"{n}× “{k[:110]}”" for k, n in pc.most_common(2) if n > 1]

    # 4. Exploration.
    cells = {}
    for x in samples:
        cells.setdefault((int(x["pos"][0] // 16), int(x["pos"][1] // 16)), x["t"])
    start = samples[0]["pos"] if samples else [0, 0]
    far = max(samples, key=lambda x: math.dist(x["pos"], start)) if samples else None
    late = sum(1 for t in cells.values() if t > 3600)
    if far:
        ex["far"] = [f"{math.dist(far['pos'], start):.0f} m from the start at minute {far['t'] / 60:.0f}, doing {(far.get('activity') or ['idle'])[1] if far.get('activity') else 'nothing'}; plan “{str(far.get('plan'))[:90]}”"]

    # 5. Social reciprocity.
    mine = [c for c in speech if c.get("a") == S]
    addressed = [c for c in mine if c.get("b") not in (0, None, S)]
    answered, used = [], set()
    for c in addressed:
        at = int(c["at_ms"])
        ans = next((r for r in speech if r.get("a") == c["b"] and r.get("b") == S and r["id"] not in used and at < int(r["at_ms"]) <= at + 60000), None)
        if ans:
            used.add(ans["id"])
            answered.append((c, ans))
    no_earshot = sum(1 for e in exps if e.get("kind") == "silence")
    ex["answered"] = [f"{c['text'][:90]} ⇒ {a['text'][:90]}" for c, a in answered[:2]]
    unanswered = [c["text"][:120] for c in addressed if all(c is not x for x, _ in answered)]
    ex["silence"] = unanswered[:: max(1, len(unanswered) // 2)][:2]

    # 6. Distinctiveness inputs.
    body = Counter((x.get("activity") or ["idle"])[0] for x in samples)
    decided = Counter(a["do"] for _, a, _ in acts)
    vocab = Counter(w for c in clusters for t in c["texts"] for w in words(t))

    if s.get("by_model"):
        cost = sum(trials.cost(m, b["prompt"], b["completion"], b["cached"]) or 0 for m, b in s["by_model"].items())
    else:  # a run still going: price the journal's calls
        cost = sum(trials.cost(r.get("model"), int(r.get("prompt_tokens") or 0), int(r.get("completion_tokens") or 0), int(r.get("cached_tokens") or 0)) or 0
                   for r in journal) if journal else None
    died = s.get("death") or next((c["text"] for c in chron if c.get("kind") == "death" and c.get("a") == S), None)
    share = lambda a, b: round(a / b, 2) if b else None
    return {
        "run": d.name, "batch": d.parent.name, "trial": trial, "variant": variant,
        "min": round(minutes), "partial": 1 if s.get("partial") else 0,
        "starved": 1 if died and "starv" in died else 0, "died": 1 if died else 0,
        "plans_other": share(len(plan_other), len(plans)),
        "acts_other": share(classes["other"], len(acts) - classes["move"]),
        "self_started": share(unprompted, counted), "prompted": share(prompted, directed),
        "goals": len(clusters), "goals_1d": sum(1 for h in held if h[0] >= 1), "goals_2d": len(long),
        "goals_1d_other": sum(1 for h in held if h[0] >= 1 and other_goal(h[1])),
        "goals_reached": sum(1 for h in held if h[2]),
        "fail_repeats_h": round(repeats / hours, 1), "fail_streak": best[0],
        "plan_repeats": plan_rep, "plan_repeats_h": round(plan_rep / hours, 1),
        "cells_h": round(len(cells) / hours, 1), "late_cells_h": round(late / (hours - 1), 1) if hours > 1 else None,
        "far_m": round(math.dist(far["pos"], start)) if far else None,
        "lines": len(mine), "addressed": len(addressed), "people": len({c["b"] for c in addressed}),
        "answered": len(answered), "silence": share(len(addressed) - len(answered), len(addressed)),
        "heard": len(to_me), "no_earshot": no_earshot,
        "cost_h": round(cost / hours, 2) if cost is not None else None,
        "_body": body, "_decided": decided, "_vocab": vocab, "_ex": ex,
    }


KEYS = ["min", "died", "starved", "plans_other", "acts_other", "self_started", "prompted", "goals", "goals_1d", "goals_2d",
        "goals_1d_other", "goals_reached", "fail_repeats_h", "fail_streak", "plan_repeats_h", "cells_h", "late_cells_h", "far_m",
        "lines", "addressed", "people", "answered", "silence", "heard", "cost_h"]


def spread(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if not xs:
        return "–"
    m = statistics.mean(xs)
    f = (lambda v: f"{v:.2f}") if any(isinstance(x, float) and x < 10 for x in xs) else (lambda v: f"{v:.0f}" if v >= 10 else f"{v:.1f}")
    return f"{f(m)} ({min(xs):g}–{max(xs):g})" if len(xs) > 1 else f"{f(m)}"


def pairwise(vs):
    vs = [v for v in vs if v]
    ds = [1 - cosine(a, b) for a, b in combinations(vs, 2)]
    return f"{statistics.mean(ds):.2f} ({min(ds):.2f}–{max(ds):.2f})" if ds else "–"


def batch_dir(b, root):
    p = Path(b).expanduser()
    return p if p.is_dir() else root / b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--root", type=Path, default=life_share.OUT, help="a .local/living/trials directory (read-only)")
    ap.add_argument("--examples", type=int, default=2, help="runs per group to print examples for")
    a = ap.parse_args()
    rows = []
    for b in a.batches:
        bd = batch_dir(b, a.root.expanduser())
        variants = json.loads((bd / "batch.json").read_text()).get("variants", []) if (bd / "batch.json").exists() else []
        for d in sorted(p for p in bd.iterdir() if p.is_dir() and ((p / "summary.json").exists() or (p / "state.json").exists())):
            rows.append(run(d, sorted(variants, key=len, reverse=True)))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["batch"], r["trial"], r["variant"])].append(r)

    print("## Per variant: mean (range)\n")
    print("| batch | trial | variant | n | " + " | ".join(KEYS) + " | skill_diss | body_diss | goal_diss |")
    print("| --- | --- | --- | ---: |" + " ---: |" * (len(KEYS) + 3))
    for (b, t, v), rs in groups.items():
        part = sum(r["partial"] for r in rs)
        print(f"| {b} | {t} | {v} | {len(rs)}{' (' + str(part) + ' running)' if part else ''} | "
              + " | ".join(spread([r[k] for r in rs]) for k in KEYS)
              + f" | {pairwise([r['_decided'] for r in rs])} | {pairwise([r['_body'] for r in rs])} | {pairwise([r['_vocab'] for r in rs])} |")

    print("\n## Per run\n")
    print("| run | " + " | ".join(KEYS) + " |")
    print("| --- |" + " ---: |" * len(KEYS))
    for r in rows:
        print(f"| {r['batch']}/{r['run']}{' (running)' if r['partial'] else ''} | " + " | ".join("–" if r[k] is None else str(r[k]) for k in KEYS) + " |")

    print("\n## Examples (verbatim)\n")
    labels = [("plan_other", "plans not about food or warmth"), ("social", "self-started social acts"), ("making", "self-started making acts"),
              ("exploring", "self-started exploring acts"), ("goal_2d", "goals held 2+ game days"), ("goal_reached", "goals with an outcome"),
              ("loop", "failure loops"), ("plan_repeat", "plans re-installed"), ("far", "farthest point"),
              ("answered", "addressed lines answered"), ("silence", "addressed lines unanswered")]
    for (b, t, v), rs in groups.items():
        print(f"### {b} {t} {v}\n")
        for r in rs[: a.examples]:
            print(f"- **{r['run']}**")
            for k, label in labels:
                for e in r["_ex"].get(k) or []:
                    print(f"  - {label}: {e}")
        print()


if __name__ == "__main__":
    main()
