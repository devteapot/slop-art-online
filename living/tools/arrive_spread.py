#!/usr/bin/env python3
"""Arrival batches per replicate, with the guards beside them (docs/TRIALS.md, "Arrival batch ar2").

  arrive_spread.py BATCH_DIR [BATCH_DIR...] [--arrive-tools DIR] [--feel-model tune_result*.json]
                   [--json OUT] [--examples N]

Read-only, no model calls. A companion to `arrive_report.py` (branch `exp-arrive`; pass the
directory that holds it with --arrive-tools when this checkout has none). It runs
`arrive_report.run_report` on every instance and adds what that report does not give, one row per
replicate, then each arm's values side by side with control's and whether the arm's range is
disjoint from control's (with 4 replicates a side, disjoint ranges are the one-sided exact
Mann-Whitney p = 1/70 per direction; overlapping ranges are "within spread").

Arms are `trial:variant` (`arrive:arrive-notice`, `arrive-answer:arrive-all`, ...); each trial's
control is `<trial>:arrive-control`. Per run:

- **Contact**: `acted_share` (arrive_report: residents in range who made deliberate contact),
  `contact_join_s`: seconds from the newcomer's arrival (join) to the first deliberate contact
  (arrive_report's `first_contact_s` is from its first walk, 20 s after joining);
  `heard_join_s`: to the first line said to it that reached it: not out of earshot by the
  authority's own verdict (the speaker's "silence" experience at the line, "No answer from …; they
  don't seem to be within earshot" or, since `speech_truth`, "… could not have heard you.", in `experiences_all.jsonl`; without it, the speaker beyond
  EARSHOT_M, 12 m, Cullet's speech, of the newcomer's position interpolated from `positions.jsonl`).
  `lines_to`: lines said to the newcomer; `far`: those out of earshot, which never reached it;
  `heard_res`: residents who said at least one line to it that reached it.
- **First contact class** (arrive_report's classes per resident): `c_line` (greeting, question,
  offer, warning or other line), `c_watch` (watching), `c_pass` (approach, no line).
- **Follow-through** of contact (no answer comes in `arrive`; in `arrive-answer` one does):
  `intro`, residents who named themselves in a heard line to it ("I'm Sefa", their first name in
  their own words); `invite`, residents whose heard line to it offers or invites (arrive_report's
  OFFER words: food, a fire, a bed, work, company); `gave` and `threat`, chronicle rows from a
  resident to it (give, teach, host, trade; threaten, attack); `told`, residents who spoke of it to
  others (arrive_report's `about_them`); `reasks`, lines to it that ask its name or business again
  after the same resident had asked once (a silent newcomer is asked again and again; a cost).
- **Crowding** (arrive_report): `converge_60s`, `together_4m`.
- **Guards** (feel_tune.py's definitions over the residents' lives, split by addressee):
  `false_min`, false replies per minute (greet_report.py: turns that answered a resident's line
  meant for someone else); `rep_res`/`rep_new`: the share of residents' own lines to residents (or
  to no one) / to the newcomer that repeat an own line of the last 10 minutes; `led_res`: the
  share of residents' lines addressed to other residents that led to something within 180 s (a
  trade, lesson, gift, help, hosting or agreement it is part of, or a new plan of either naming
  the other), `plc_res` the same with every line 6 minutes earlier (placebo), `led_new` the share
  of lines to the newcomer followed by such an outcome (it makes no plans, so only outcomes count).
  `score`: the proxy-tuned window score (feel_tune.py score's window ridge, mean over the run's
  resident windows; PROXY ratings, circular: being answered mattered most) when --feel-model is
  given. Never read it without the guards.
- **Thinking and cost**: `delib_ph`, deliberations (`thoughts_all.jsonl` kind `deliberate`, one per
  think+compile pair) per thinking resident per hour of the run; `talk_ph`, talk turns
  (`talk.jsonl`) per resident-hour; `reused`, `reused_ev`, `carried_again` (arrive_report: reason
  lines reused across a resident's deliberations; 0 `carried_again` is the stale-reasons fix
  holding); `usd` per run and `usd_rh` per thinking resident-hour (journal at trials.py prices).

**Strangers** (docs/STRANGERS.md, decisions of 2026-11-12; `--strangers`), per run and per
resident thought for and in range (within 12 m of the newcomer during a stand):
- the resident's `duty` (the two lives: a stance on arrivals, or a sheet that sees the quay),
  curiosity, sociability and caution (the run's seed sheet, `LIVING_SEED` in mind-env.json), and
  `first`: whether a first-sight line named the newcomer (subject or object), or `-` when none did;
- `class`, exclusive, in this order: `asks` (a line to the newcomer, heard or not); `approaches`
  (came within 4 m, or waved, nodded, faced or aimed an act at them, with no line); `inward` (a
  thought after the join names them by id, or calls someone a stranger/newcomer while they are in
  that prompt, with no act toward them; in Cullet a scene's "a stranger" is also a neighbour past
  the naming distance); `unaware` (none of these);
- per run: `tells`, residents thought for (in range or not) who said a line to someone else with
  stranger words after the join, having perceived the newcomer before it (an experience naming it), and how many of them were beyond 12 m of the newcomer when it
  joined (`tells_out`); `first_heard` (seconds from the join and who); `fs_cover`, persons past
  infancy within 12 m of the newcomer at some sample after the join who got a first-sight line
  naming it, of all such persons (the crowd fix: everyone in sight is perceived); `routines`,
  compile replies whose graph uses `"relation": "stranger"`.

**Spoken ids** (every run): `id_lines`, lines said aloud (speech.jsonl, the quoted words) holding
`#<digits>`, and per speaker (`id_by`, in --json and the strangers section). An id is for acts and
memory ("a stranger #77" is a memory handle, fix-stranger-merge), never for speech: 0 expected.
"""
import argparse
import importlib.util
import json
import random
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import trials  # noqa: E402,F401  (prices, loaded once for every helper below)

# The speaker's `silence` row for a line its addressee could not have heard: its words since
# `speech_truth` (and its room line no one heard, subject 0), speech-2's, and the first ("No answer from …"). A planned line not said carries UNSAID.
UNHEARD = re.compile(r"^No answer from|could not have heard you|^Nobody was near enough to hear you|is too far to hear you|within earshot")
UNSAID = "You did not say your planned line"

EARSHOT_M = 12.0
GIVE_KINDS = {"give", "teach", "host", "trade", "lodge", "offer"}
HOSTILE_KINDS = {"threat", "threaten", "attack", "strike", "hit", "kill"}
ASK = re.compile(r"\b(your name|who are you|who might you be|what.{0,12}call you|what brings|your business|what do you want|where.{0,20}from)\b", re.I)


def load(name, d):
    """A tool module from another checkout, read-only: no bytecode is written beside it."""
    sys.dont_write_bytecode = True
    p = Path(d) / f"{name}.py"
    if not p.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"{name}_{abs(hash(str(p)))}", p)
    mod = importlib.util.module_from_spec(spec)
    path0 = list(sys.path)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = path0
    return mod


def jl(p):
    out = []
    if p.exists():
        for line in p.read_bytes().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def quoted(text):
    m = re.search(r"“(.*)”", text or "", re.S)
    return m[1] if m else (text or "")


def pos_at(track, ms):
    """The newcomer's position at ms, linearly between the samples around it."""
    if not track:
        return None
    prev = None
    for t, p in track:
        if t >= ms:
            if prev is None:
                return p
            t0, p0 = prev
            f = (ms - t0) / (t - t0) if t > t0 else 0
            return [p0[0] + f * (p[0] - p0[0]), p0[1] + f * (p[1] - p0[1])]
        prev = (t, p)
    return prev[1]


def extra(d, sid, names, minds):
    """What arrive_report does not give, for one instance."""
    st = json.loads((d / "state.json").read_text())
    summ = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    minutes = summ.get("minutes_run") or 0
    track = [(r["ms"], r["pos"][str(sid)]) for r in jl(d / "positions.jsonl") if str(sid) in r.get("pos", {})]
    speech = sorted(jl(d / "speech.jsonl"), key=lambda r: r["at_ms"])
    joined = next((e["newcomer_join"]["at_ms"] for e in jl(d / "events.jsonl") if "newcomer_join" in e), None)
    join_ms = joined or next((r["at_ms"] for r in jl(d / "chronicle.jsonl") if r.get("kind") == "arrival" and r.get("a") == sid), st["t0"] * 1000)
    to_new = [s for s in speech if s.get("b") == sid and s.get("a") != sid]
    # The authority's own verdict, when recorded: a "silence" experience of the speaker at the
    # line's time ("No answer from …; they don't seem to be within earshot" before `speech_truth`,
    # "… could not have heard you." since; `UNHEARD`). It counts every line said, where
    # speech.jsonl merges a line repeated word for word into its earlier row. A planned line the
    # authority did not say (`speech_truth`: its addressee out of reach as it came due) is no line.
    earshot = {(r["observer"], r["at_ms"]) for r in jl(d / "experiences_all.jsonl")
               if r.get("kind") == "silence" and r.get("subject") == sid and UNHEARD.search(r.get("text") or "")
               and UNSAID not in (r.get("text") or "")}
    heard, far = [], []
    for s in to_new:
        if (d / "experiences_all.jsonl").exists():
            out = (s["a"], s["at_ms"]) in earshot
        else:
            p = pos_at(track, s["at_ms"])
            out = not (p and s.get("x") is not None and ((p[0] - s["x"]) ** 2 + (p[1] - s["y"]) ** 2) ** 0.5 <= EARSHOT_M)
        (far if out else heard).append(s)
    n_far = len(earshot) if (d / "experiences_all.jsonl").exists() else len(far)
    intro, invite, asked, reasks = set(), set(), set(), 0
    for s in heard:
        a, w = s["a"], quoted(s["text"])
        first = names.get(a, "").split(" ")[0]
        if first and re.search(rf"\b{re.escape(first)}\b", w):
            intro.add(a)
        if AR.OFFER.search(w):
            invite.add(a)
    for s in to_new:
        if ASK.search(quoted(s["text"])):
            if s["a"] in asked:
                reasks += 1
            asked.add(s["a"])
    chron = jl(d / "chronicle.jsonl")
    gave = {r["a"] for r in chron if r.get("b") == sid and r.get("kind") in GIVE_KINDS}
    threat = {r["a"] for r in chron if r.get("b") == sid and r.get("kind") in HOSTILE_KINDS}
    # Spoken ids: lines whose words hold `#<digits>` (an id is for acts and memory, never speech).
    hashed = defaultdict(int)
    for s in speech:
        if re.search(r"#\d+", quoted(s.get("text", ""))):
            hashed[names.get(s["a"], f"#{s['a']}")] += 1
    delibs = sum(1 for r in jl(d / "thoughts_all.jsonl") if r.get("kind") == "deliberate" and r.get("actor") in minds)
    turns = sum(1 for r in jl(d / "talk.jsonl") if r.get("actor") in minds)
    res_h = len(minds) * minutes / 60 if minutes else None
    return {"minutes": minutes, "residents": len(minds),
            "contact_join_s": None, "heard_join_s": round((heard[0]["at_ms"] - join_ms) / 1000, 1) if heard else None,
            "first_heard_by": heard[0]["a"] if heard else None,
            "lines_to": len(heard) + n_far, "far": n_far, "heard": len(heard), "heard_res": len({s["a"] for s in heard}),
            "intro": len(intro), "invite": len(invite), "gave": len(gave), "threat": len(threat), "reasks": reasks,
            "delib_ph": round(delibs / res_h, 1) if res_h else None, "talk_ph": round(turns / res_h, 1) if res_h else None,
            "res_h": res_h, "join_ms": join_ms, "id_lines": sum(hashed.values()), "id_by": dict(hashed), "to_new_ms": {(s["a"], s["at_ms"]) for s in to_new}}


def guards(lives, to_new_ms, sid):
    """feel_tune.guards over the run's resident lives, split: lines to the newcomer, and the rest."""
    agg = defaultdict(int)
    for life in lives:
        by_name = {l.name: l for l in lives}
        said_new = [(ms, k, raw) for ms, k, raw in life.percepts if (k == "said" or raw.startswith("You said")) and (life.id, ms) in to_new_ms]
        said_other = [(ms, k, raw) for ms, k, raw in life.percepts if (k == "said" or raw.startswith("You said")) and (life.id, ms) not in to_new_ms]
        rest = [(ms, k, raw) for ms, k, raw in life.percepts if not (k == "said" or raw.startswith("You said"))]
        for tag, said in (("res", said_other), ("new", said_new)):
            sub = FE.Life(**{**life.__dict__, "percepts": sorted(rest + said)})
            g = FT.guards(sub, by_name)
            for k in ("lines", "repeated", "addressed", "led"):
                agg[f"{tag}_{k}"] += g[k]
            if tag == "res":
                agg["res_placebo"] += FT.guards(sub, by_name, shift_s=FT.PLACEBO_S)["led"]
    r = lambda a, b: round(agg[a] / agg[b], 2) if agg[b] else None
    return {"rep_res": r("res_repeated", "res_lines"), "rep_new": r("new_repeated", "new_lines"),
            "led_res": r("res_led", "res_addressed"), "plc_res": r("res_placebo", "res_addressed"),
            "led_new": r("new_led", "new_addressed"), "res_lines": agg["res_lines"], "res_addressed": agg["res_addressed"],
            "new_lines": agg["new_lines"]}


def proxy_score(lives, model):
    m = model["model"]["feel_window"]
    tmp = Path(__import__("tempfile").mkdtemp(prefix="arrive-spread-"))
    scores = []
    try:
        for life in lives:
            for start in FE.windows(life, 600000, 6):
                f = FE.feel(FE.feel_dir(life, start, start + 600000, tmp / "x" / "y"))
                sc = m["intercept"] + sum(t["beta"] * (((FT.num(f.get(t["column"])) if FT.num(f.get(t["column"])) is not None else t["median"]) - t["mean"]) / t["sd"]) for t in m["terms"])
                scores.append(min(5.0, max(1.0, sc)))
    finally:
        __import__("shutil").rmtree(tmp, ignore_errors=True)
    return round(statistics.mean(scores), 2) if scores else None


COLS = ["id_lines", "in_range", "acted_share", "heard_res", "contact_join_s", "heard_join_s", "lines_to", "far", "c_line", "c_watch", "c_pass",
        "intro", "invite", "gave", "threat", "told", "reasks", "converge_60s", "together_4m", "false_min", "rep_res", "rep_new",
        "led_res", "plc_res", "led_new", "score", "delib_ph", "talk_ph", "reused", "reused_ev", "carried_again", "usd", "usd_rh"]
# Which direction is a cost: +1 when more is worse (for the "worse" marks of the guards).
WORSE = {"false_min": 1, "rep_res": 1, "rep_new": 1, "led_res": -1, "converge_60s": 1, "together_4m": 1, "reasks": 1, "far": 1}


FAR_PERSON = "someone too far away to make out"
STRANGER_WORDS = re.compile(r"\b(stranger|strangers|newcomer|new arrival|traveller|traveler|visitor|outsider|new face|someone new|just arrived|wanderer|arrival)\b", re.I)
DUTY = re.compile(r"arrivals?_must|book of arrivals|ship-day book|the one who sees|sees everyone who walks|every back on", re.I)


def seed_people(d):
    """name -> (traits, duty) from the run's seed (mind-env.json LIVING_SEED, under living/seeds)."""
    env = json.loads((d / "mind-env.json").read_text()) if (d / "mind-env.json").exists() else {}
    rel = env.get("LIVING_SEED")
    if not rel:
        return {}
    p = HERE.parent / "seeds" / f"{rel}.json"
    if not p.exists():
        return {}
    out = {}

    def walk(x):
        if isinstance(x, dict):
            if "sheet" in x and "name" in x:
                sh = x["sheet"] or {}
                out[x["name"]] = (sh.get("traits") or {}, bool(DUTY.search(json.dumps(sh))))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(json.loads(p.read_text()))
    return out


def strangers(d, r, sid, names, minds, x):
    """The strangers measures for one run (module docstring, "Strangers")."""
    join = x["join_ms"]
    people = seed_people(d)
    prow = jl(d / "positions.jsonl")
    pos_join = min(prow, key=lambda q: abs(q["ms"] - join))["pos"] if prow else {}
    near_ever, cover = set(), set()
    stage = {}
    for c in jl(d / "census.jsonl"):
        for p in c.get("people", []):
            stage[p["id"]] = p.get("stage", 2)
    for q in prow:
        if q["ms"] < join or str(sid) not in q["pos"]:
            continue
        me = q["pos"][str(sid)]
        for k, v in q["pos"].items():
            if int(k) != sid and stage.get(int(k), 2) >= 1 and ((v[0] - me[0]) ** 2 + (v[1] - me[1]) ** 2) ** 0.5 <= 12.0:
                near_ever.add(int(k))
    perceived = {}
    for e in jl(d / "experiences_all.jsonl"):
        if sid in (e.get("subject"), e.get("object")):
            perceived.setdefault(e["observer"], e["at_ms"])
            if "first time you see" in (e.get("text") or ""):
                cover.add(e["observer"])
    # Thoughts after the join that name the newcomer or call someone a stranger.
    inward, routines = {}, 0
    for f in sorted((d / "journal").glob("*.jsonl")) if (d / "journal").exists() else []:
        for e in jl(f):
            if (e.get("at_ms") or 0) < join:
                continue
            rep_ = AR.reply_text(e)
            # Stranger words count only when the newcomer was in that prompt: in Cullet "a stranger"
            # in a scene is also a neighbour past the naming distance (docs/TRIALS.md, st1).
            if e.get("purpose") == "think" and (AR.names_id(rep_, sid) or (STRANGER_WORDS.search(rep_) and AR.names_id(AR.user_text(e), sid))):
                inward.setdefault(f.stem.replace("_", " "), (e["at_ms"], rep_[:240]))
            if e.get("purpose") == "deliberate" and re.search(r'"relation"\s*:\s*"stranger"', e.get("reply") or ""):
                routines += 1
    rows = []
    for z in r["residents"]:
        name = z["name"]
        tr, duty = people.get(name, ({}, False))
        if z["to_them"]:
            cls = "asks"
        elif z["approach"] or z["close"] or z["gesture"] or z["aimed"]:
            cls = "approaches"
        elif name in inward:
            cls = "inward"
        else:
            cls = "unaware"
        rows.append({"name": name, "duty": duty, "cur": tr.get("curiosity"), "soc": tr.get("sociability"), "cau": tr.get("caution"),
                     "first": "yes" if z["id"] in cover else "-", "class": cls,
                     "thought": inward.get(name, (None, ""))[1] if cls == "inward" else ""})
    speech = jl(d / "speech.jsonl")
    tellers = sorted({s["a"] for s in speech if s["at_ms"] >= join and s.get("a") in minds and s.get("b") != sid and s.get("a") != sid
                      and STRANGER_WORDS.search(quoted(s.get("text", ""))) and perceived.get(s["a"], 1 << 62) <= s["at_ms"]})
    me0 = pos_join.get(str(sid))
    out = [t for t in tellers if me0 and str(t) in pos_join and ((pos_join[str(t)][0] - me0[0]) ** 2 + (pos_join[str(t)][1] - me0[1]) ** 2) ** 0.5 > 12.0]
    heard_by = x.get("first_heard_by")
    # Someone too far away to make out (far-label): think prompts whose scene lists one, and the
    # replies that speak of a figure they cannot make out (examples kept).
    far_prompts = far_replies = 0
    far_examples = []
    for f in sorted((d / "journal").glob("*.jsonl")) if (d / "journal").exists() else []:
        for e in jl(f):
            if e.get("purpose") != "think":
                continue
            if FAR_PERSON in AR.user_text(e):
                far_prompts += 1
            rep_ = AR.reply_text(e)
            if re.search(r"too far (away )?to make out|can(no|')t make (them|him|her|out)|make out who", rep_, re.I):
                far_replies += 1
                if len(far_examples) < 3:
                    far_examples.append(f"{f.stem.replace('_', ' ')}: {rep_[:200]}")
    # The room line nobody heard (speech_truth: a line to no one with nobody in earshot).
    room = [e for e in jl(d / "experiences_all.jsonl") if e.get("kind") == "silence" and (e.get("text") or "").startswith("Nobody was near enough to hear you")]
    # First sights in crowds: lines, lines naming several people, the most named in one line.
    fs = [e for e in jl(d / "experiences_all.jsonl") if (e.get("text") or "").startswith("For the first time you see")]
    parts = [len((e.get("text") or "").split("; ")) for e in fs]
    return {"far_prompts": far_prompts, "far_replies": far_replies, "far_examples": far_examples,
            "room_unheard": len(room), "room_speakers": len({e["observer"] for e in room}),
            "first_sight_lines": len(fs), "first_sight_batched": sum(1 for n in parts if n > 1), "first_sight_people": sum(parts), "first_sight_most": max(parts, default=0),
            "residents": rows, "classes": {c: sum(1 for z in rows if z["class"] == c) for c in ("asks", "approaches", "inward", "unaware")},
            "tells": [names.get(t, f"#{t}") for t in tellers], "tells_out": len(out),
            "first_heard": f"{x['heard_join_s']} s, {names.get(heard_by, heard_by)}" if x.get("heard_join_s") is not None else None,
            "fs_cover": f"{len(near_ever & cover)} of {len(near_ever)}", "fs_missing": sorted(names.get(i, f"#{i}") for i in near_ever - cover),
            "routines": routines, "converge_60s": r["converge_60s"], "together_4m": r["together_4m"], "reasks": x["reasks"]}


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--arrive-tools", default=str(HERE), help="directory holding arrive_report.py (branch exp-arrive)")
    ap.add_argument("--feel-model", help="a feel_tune fit's tune_result*.json, for the proxy-tuned score")
    ap.add_argument("--json")
    ap.add_argument("--strangers", action="store_true", help="the strangers measures per run and resident (docs/STRANGERS.md)")
    ap.add_argument("--control", help="the control arm for every arm (`trial:variant`); default `<trial>:arrive-control`")
    a = ap.parse_args()
    global AR, FE, FT
    AR = load("arrive_report", a.arrive_tools)
    if AR is None:
        sys.exit(f"no arrive_report.py in {a.arrive_tools}: pass --arrive-tools (a checkout of exp-arrive)/living/tools")
    import feel_excerpts as FE  # noqa: E402
    import feel_tune as FT  # noqa: E402
    GR = load("greet_report", HERE)
    model = json.loads(Path(a.feel_model).read_text()) if a.feel_model else None
    if model:
        FE.RESIDENTS_PER_RUN = 12
    rows = []
    for b in a.batches:
        bd = Path(b).expanduser()
        lives_all = FE.lives_of(bd.name, [bd], random.Random(0))
        for d in sorted(p for p in bd.iterdir() if p.is_dir()):
            r = AR.run_report(d)
            if not r:
                continue
            sid = r["newcomer"]
            names, minds = {}, set()
            for c in jl(d / "census.jsonl"):
                for p in c.get("people", []):
                    names[p["id"]] = p["name"]
                    if p.get("kind", "person") == "person" and p.get("stage", 2) >= 1 and p.get("alive", True) and (c.get("thinkers") is None or p["id"] in c["thinkers"]):
                        minds.add(p["id"])
            minds.discard(sid)
            only = AR.thinkers_of(d)
            if only is not None:
                minds &= only
            x = extra(d, sid, names, minds)
            walk = next((e["human_walk"]["from_ms"] for e in jl(d / "events.jsonl") if "human_walk" in e), None)
            if r.get("first_contact_s") is not None and walk:
                x["contact_join_s"] = round(r["first_contact_s"] + (walk - x["join_ms"]) / 1000, 1)
            lives = [l for l in lives_all if l.run == d.name]
            g = guards(lives, x.pop("to_new_ms"), sid)
            fr = GR.run(d) if GR else None
            cl = r["classes"]
            row = {"batch": bd.name, "run": d.name, "arm": f"{r['trial']}:{r['variant']}", "trial": r["trial"],
                   "rep": int(re.search(r"-r(\d+)$", d.name)[1]),
                   "in_range": r["in_range"], "acted_share": r["acted_share"],
                   "c_line": sum(cl[k] for k in ("greeting", "question", "offer", "warning/hostility", "other line")),
                   "c_watch": cl["watching"], "c_pass": cl["approach, no line"],
                   "told": sum(1 for z in r["residents"] if z.get("about_them")),
                   "converge_60s": r["converge_60s"], "together_4m": r["together_4m"],
                   "false_min": round(fr["false_replies"] / fr["minutes"], 3) if fr and fr.get("minutes") else None,
                   "false": fr["false_replies"] if fr else None,
                   "score": proxy_score(lives, model) if model else None,
                   "reused": r.get("reused_share"), "reused_ev": r.get("reused_events"), "carried_again": r.get("carried_again"),
                   "usd": r.get("usd"), **x, **g}
            row["usd_rh"] = round(r["usd"] / x["res_h"], 3) if r.get("usd") is not None and x["res_h"] else None
            row["follow"] = r.get("follow")
            row.pop("first_heard_by", None)
            if a.strangers:
                row["strangers"] = strangers(d, r, sid, names, minds, {**x, "first_heard_by": x.get("first_heard_by")})
            rows.append(row)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1, default=list))
    arms = defaultdict(list)
    for r in rows:
        arms[(r["batch"], r["arm"])].append(r)
    print("## Per replicate\n")
    print("| arm | rep | " + " | ".join(COLS) + " |")
    print("|---|---|" + "---:|" * len(COLS))
    for (b, arm), rs in sorted(arms.items()):
        for r in sorted(rs, key=lambda r: r["rep"]):
            print(f"| {arm} | r{r['rep']} | " + " | ".join(fmt(r.get(c)) for c in COLS) + " |")
    print("\n## Per arm: replicate values r1/r2/r3/r4, and against the trial's control\n")
    print("`>`/`<`: every replicate above/below every control replicate (ranges disjoint); `~`: within spread.\n")
    print("| measure | " + " | ".join(arm for (_, arm) in sorted(arms)) + " |")
    print("|---|" + "---|" * len(arms))
    for c in COLS:
        cells = []
        for (b, arm), rs in sorted(arms.items()):
            vals = [r.get(c) for r in sorted(rs, key=lambda r: r["rep"])]
            ctl = [r.get(c) for r in arms.get((b, a.control or arm.split(":")[0] + ":arrive-control"), [])]
            mark = ""
            vv, cc = [v for v in vals if v is not None], [v for v in ctl if v is not None]
            if arm.endswith("arrive-control") or arm == a.control or not vv or not cc:
                mark = ""
            elif min(vv) > max(cc):
                mark = " >"
            elif max(vv) < min(cc):
                mark = " <"
            else:
                mark = " ~"
            cells.append("/".join(fmt(v) for v in vals) + mark)
        print(f"| {c} | " + " | ".join(cells) + " |")
    if a.strangers:
        print("\n## Strangers (docs/STRANGERS.md): per run, then each resident thought for and in range\n")
        for (b, arm), rs in sorted(arms.items()):
            for r in sorted(rs, key=lambda r: r["rep"]):
                st = r["strangers"]
                print(f"### {arm} r{r['rep']}\n")
                print(f"classes {st['classes']}; tells {st['tells']} ({st['tells_out']} beyond 12 m at the join); first heard line {st['first_heard']}; "
                      f"first-sight lines naming the newcomer {st['fs_cover']} persons within 12 m after the join (without one: {st['fs_missing']}); "
                      f"routines with relation stranger {st['routines']}; far label in think prompts {st['far_prompts']}, in replies {st['far_replies']}; "
                      f"room lines nobody heard {st['room_unheard']} (by {st['room_speakers']}); first-sight lines {st['first_sight_lines']} ({st['first_sight_batched']} naming several, "
                      f"{st['first_sight_people']} people, at most {st['first_sight_most']} in one); delib/res-h {r.get('delib_ph')}; spoken ids {r.get('id_lines')} {r.get('id_by') or ''}; converge_60s {st['converge_60s']}; together_4m {st['together_4m']}; re-asks {st['reasks']}\n")
                for ex in st.get("far_examples") or []:
                    print(f"- far label in a thought: {ex}")
                if st["residents"]:
                    print("| resident | duty | curiosity | sociability | caution | first sight | class | thought |")
                    print("|---|---|---:|---:|---:|---|---|---|")
                    for z in st["residents"]:
                        print(f"| {z['name']} | {'yes' if z['duty'] else ''} | {fmt(z['cur'])} | {fmt(z['soc'])} | {fmt(z['cau'])} | {z['first']} | {z['class']} | {z['thought'][:160].replace('|', '/')} |")
                print()
    pooled = defaultdict(lambda: defaultdict(float))
    for (b, arm), rs in arms.items():
        for r in rs:
            P = pooled[arm]
            P["false"] += r.get("false") or 0
            P["min"] += r.get("minutes") or 0
            P["usd"] += r.get("usd") or 0
            P["res_h"] += r.get("res_h") or 0
    print("\n## Pooled per arm\n")
    print("| arm | runs | false replies | per min | usd | usd per resident-hour |")
    print("|---|---:|---:|---:|---:|---:|")
    for arm, P in sorted(pooled.items()):
        n = sum(len(rs) for (_, a2), rs in arms.items() if a2 == arm)
        print(f"| {arm} | {n} | {int(P['false'])} | {P['false'] / P['min']:.3f} | {P['usd']:.2f} | {P['usd'] / P['res_h']:.3f} |")


if __name__ == "__main__":
    main()
