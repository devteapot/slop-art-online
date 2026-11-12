#!/usr/bin/env python3
"""What residents do about a newcomer who says nothing (docs/TRIALS.md, "Arrivals"; docs/STRANGERS.md).

A newcomer who joins later (`newcomer` in the trial, cast role `newcomer`, event `newcomer_join`)
is read as the newcomer and its join as its arrival; a run whose minds think only for some
(`LIVING_ONLY` in `mind-env.json`) counts only those as residents. Unheard lines (the speaker's
silence row, in either wording: "No answer from …" before `speech_truth`, "… could not have heard
you." since) and re-asks are counted by arrive_spread.py, not here.

  arrive_report.py BATCH [BATCH...] [--root DIR] [--examples N] [--json OUT]
  arrive_report.py --journal DIR --subject ID --from-ms MS --to-ms MS [--examples N]

Read-only, no model calls. For each run of the `arrive` trial (trials.py evidence with
`record.speech`, `talk`, `experiences`, `gestures` and `positions`), the newcomer is the joined
player (`cast.json` subject) and its silent stands are the `human_stand` .. `human_stand_end`
events. The `greet` trial's runs read the same way, with its `human_listen` windows as the
stands (the player has spoken by then, so contact there is not unprompted).

Per resident (a person other than the newcomer, thought for by the minds at some census: in
`thinkers` under `minds.max`, else past infancy) who was **in range**, within RANGE_M (12 m,
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

Then, per batch x arm (an arm is the variant, or `trial:variant` for another trial such as
`arrive-answer`):

- **First contact by class**, per resident (those in range and any who spoke to the newcomer):
  the first line to them, or an earlier wave or nod, classed by `classify` (keywords, checked in
  this order): `warning/hostility` (leave, be off, careful, thieves …), `offer` (food, a bed,
  help, work, company: "you're welcome to share", "there's a bowl for you", "walk with us"),
  `question` (who are you, are you new, where from, what brings you), `greeting` (hello, good
  day, welcome), `other line`. Without a line: an offer or hostile act aimed at them (give,
  host, teach; threaten, attack), else `watching` (a face or appraise gesture; a gaze, standing
  still and turning at least 0.5 rad to face them within 0.35 rad from 4–25 m; a thought naming
  them), else `approach, no line`. Counts per arm and three verbatim examples per class.
- **Follow-through** (`human.answer`, the `arrive-answer` trial): who the newcomer answered and
  when that contact came, how many lines that resident said to them afterwards before 90 s of
  quiet, the seconds to each, and who else spoke to them in that time.
- **Crowding** (a cost: several converging at once reads as scripted): `converge_60s`, the most
  residents who spoke, gestured or aimed an activity at the newcomer within one 60 s window;
  `together_4m`, the most within 4 m at once who had done so in the minute before;
  `runs_3plus`, runs with `converge_60s` of 3 or more. `converge_any_60s` and
  `together_any_4m` also count approaches and arrivals from beyond 8 m, which residents'
  routines make in every arm (the baseline to read the others against).
- **Cost**: dollars per hour and per run, calls and tokens per minute; `reused_share`, the share
  of reason lines of residents' thoughts that an earlier thought of theirs already had, and
  `reused_events`, those of them that are one-time events (a feeling, a first sight) rather than
  plan states (read from the journals' prompts, so they work on any run); and, where the runs
  have `thoughts_all.jsonl` (`record.thoughts`) from a build with the stale-reasons fix, `carried`
  (reasons the residents' deliberations carried, `detail.reasons`) and `carried_again` (those an
  earlier deliberation had already carried: 0 when each reason is consumed once).

`--journal` reads a play-test record instead (a journal directory of `<Name>.jsonl`, no
positions): only `asked`, `thinks`, `in_prompt`, `mention` and `words`, per journal, for model
calls between `--from-ms` and `--to-ms` (Unix ms).
"""
import argparse
import json
import math
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
# First contact classes (`classify`), checked in this order: a line that warns and offers is a
# warning, one that offers and asks who they are is an offer. Keyword heuristics: read the examples.
HOSTILE = re.compile(r"\b(leave|go away|get out|be off|clear off|begone|not welcome|unwelcome|watch yourself|watch your step|careful|warn|warning|stay back|back off|keep away|keep your hands|no place for|thie(f|ves)|move along|on your way|trouble)\b", re.I)
OFFER = re.compile(r"(you'?re welcome to|you are welcome to|share (what|my|our|a)|have some|take (some|these|this|a)|i can (give|spare|show|help|find)|i'?ll (give|show|help|find|fetch|take you)|let me (help|show|get)|come (with|and eat|and sit|in)|walk with (us|me)|sit (by|with|down)|warm yourself|not go hungry|there'?s (bread|food|a bowl|fish|a bed|room|a corner|work for|a place)|a bowl for you|a bed for|a roof|lodg\w*|stay (with|the night|here)|are you hungry|you hungry|need (food|a bed|help|anything|somewhere to)|hand wanted|work for you|could use (a hand|help)|guest)", re.I)
QUESTION = re.compile(r"\b(who are you|who might you be|your name|what.{0,12}call you|are you new|new here|new to|where.{0,20}from|what brings|passing through|travell?ing|come from|lost)\b", re.I)
GREETING = re.compile(r"\b(hello|hi|hey|good (morning|day|evening|afternoon)|morning|evening|greetings|welcome|well met|hail|g'day)\b", re.I)
OFFER_ACTS = {"give", "host", "offer", "teach", "trade", "welcome"}
HOSTILE_ACTS = {"threaten", "attack", "strike", "shove", "seize", "throw", "kick", "lunge"}
CLASSES = ["greeting", "question", "offer", "warning/hostility", "other line", "watching", "approach, no line"]
# A gaze: standing (moved under GAZE_STILL_M), turned at least GAZE_TURN rad, and now facing
# the newcomer within GAZE_AT rad, from GAZE_NEAR to GAZE_FAR metres.
GAZE_STILL_M, GAZE_TURN, GAZE_AT, GAZE_NEAR, GAZE_FAR = 0.3, 0.5, 0.35, 4.0, 25.0
CONVERGE_S = 60
QUIET_S = 90


def classify(text):
    """A line's class for first contact (keyword heuristic)."""
    words = re.sub(r"^[^“]*“|”[^”]*$", "", text or "")
    if HOSTILE.search(words):
        return "warning/hostility"
    if OFFER.search(words):
        return "offer"
    if QUESTION.search(words) or ("?" in words and WORDS.search(words)):
        return "question"
    if GREETING.search(words):
        return "greeting"
    return "other line"


def angle(a, b):
    """The smaller angle between two headings (radians)."""
    d = (a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


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
        col = {"thinks": 0, "in_prompt": 0, "asked": 0, "mention": 0, "words": 0, "talk": 0, "examples": [], "reasons": []}
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
            m = names_id(rep, sid)
            col["mention"] += m
            if m and e["purpose"] == "think" and "first_mention_ms" not in col:
                col["first_mention_ms"] = at
            w = bool(WORDS.search(rep))
            col["words"] += w
            if (m or w) and len(col["examples"]) < 4:
                col["examples"].append(f"{e['purpose']} at {at}: {rep[:300]}")
        if col["thinks"] or col["talk"]:
            out[name] = col
    return out


def reused_reasons(jdir):
    """Deliberation reasons used again: per resident, a line of a thought's reason ("# Why you
    are thinking now") that an earlier thought of theirs already had, word for word. `feelings`
    counts those that are one-time events (a feeling, a first sight), not plan states."""
    plan = ("Nothing in my current plan works", "My actions keep failing", "I finished my plan", "A quiet moment to take stock")
    total = reused = feelings = 0
    for f in sorted(Path(jdir).glob("*.jsonl")):
        seen = set()
        for e in jl(f):
            if e.get("purpose") != "think":
                continue
            for line in section(user_text(e), "Why you are thinking now").splitlines():
                line = line.strip()
                if not line or line.startswith("(Note") or line.startswith("(You went"):
                    continue
                total += 1
                if line in seen:
                    reused += 1
                    feelings += not line.startswith(plan)
                seen.add(line)
    return {"reasons": total, "reused": reused, "reused_events": feelings}


def _detail(t):
    try:
        v = json.loads(t.get("detail") or "{}")
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def thinkers_of(d):
    """Who the run's mind service thought for, when it was limited (`LIVING_ONLY` in
    mind-env.json), else None (every person past infancy, or the census's `thinkers`)."""
    p = d / "mind-env.json"
    if not p.exists():
        return None
    only = json.loads(p.read_text()).get("LIVING_ONLY")
    return {int(x) for x in only.split(",") if x.strip()} if only else None


# Whether the newcomer's walks through the town (`human_route` .. `human_route_end`, the strangers
# trial's walk along the Strand) count as windows beside its stands: residents it passes are then
# in range too (st2b analysis, docs/TRIALS.md). `--stands-only` (arrive_spread) gives the old measure.
WALKS = True


def windows_of(events, end_ms=None, walks=None):
    """The silent stands (arrive) or listening windows (greet) as [(from_ms, to_ms)], and the
    newcomer's walks (`human_route`) unless `walks` is false. A stand the run's end cut short (no
    `_end` event) ends at `end_ms`, the run's last position sample, when given."""
    walks = WALKS if walks is None else walks
    out, opened = [], {}
    keys = (("human_stand", "human_stand_end"), ("human_listen", "human_listen_end")) + ((("human_route", "human_route_end"),) if walks else ())
    for e in events:
        for key, end in keys:
            if key in e:
                opened[(key, e[key].get("stand", e[key].get("cycle", e[key].get("name"))))] = e[key]["from_ms"]
            if end in e:
                k = (key, e[end].get("stand", e[end].get("cycle", e[end].get("name"))))
                if k in opened:
                    out.append((opened.pop(k), e[end]["to_ms"]))
    out += [(a, end_ms) for a in opened.values() if end_ms and end_ms > a]
    return sorted(out)


def run_report(d):
    cast = json.loads((d / "cast.json").read_text()) if (d / "cast.json").exists() else {}
    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    roles = cast.get("roles", {})
    sid = (roles.get("newcomer") or roles.get("subject") or [None])[0]
    if isinstance(sid, dict):
        sid = sid.get("id")
    if sid is None:
        m = re.search(r"#(\d+)", str(summary.get("subject", "")))
        sid = int(m.group(1)) if m else None
    events = jl(d / "events.jsonl")
    wins = windows_of(events, max((p.get("ms") or 0 for p in jl(d / "positions.jsonl")), default=None))
    if sid is None or not wins:
        return None
    t0 = wins[0][0]
    # The newcomer's arrival: its `join` call (human.jsonl), else the first stand.
    walk = next((e["human_walk"]["from_ms"] for e in events if "human_walk" in e), None)
    joined = next((e["newcomer_join"]["at_ms"] for e in events if "newcomer_join" in e), None)
    t_arrive = joined or walk or t0
    inwin = lambda ms: any(a <= ms <= b for a, b in wins)
    names, minds = {}, set()
    only = thinkers_of(d)
    for c in jl(d / "census.jsonl"):
        for p in c.get("people", []):
            names[p["id"]] = p["name"]
            # Thought for by the minds at some census: in `thinkers` (under `minds.max`), else any
            # person past infancy. Others live by their graphs and are left out of the residents.
            if p.get("kind", "person") == "person" and p.get("stage", 2) >= 1 and p.get("alive", True) and (c.get("thinkers") is None or p["id"] in c["thinkers"]) and (only is None or p["id"] in only):
                minds.add(p["id"])
    minds.discard(sid)
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
    # A speaker's `silence` rows, whoever they name: one about someone too far away to make out
    # names them by a far handle, not their id (fs1e's heard/unheard split).
    silences = defaultdict(list)
    for r in jl(d / "experiences_all.jsonl"):
        if r.get("subject") == sid or r.get("object") == sid:
            exps[r["observer"]].append(r)
        if r.get("kind") == "silence":
            silences[r["observer"]].append(r)
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

    # Gazes: a resident standing still turns to face the newcomer from a distance.
    gazes = defaultdict(list)
    series = defaultdict(list)
    for ms, ps in pos:
        if inwin(ms) and sid in ps:
            for i, p in ps.items():
                if i != sid and len(p) > 2:
                    series[i].append((ms, p, ps[sid]))
    for i, xs in series.items():
        for (_, a, _), (ms, b, n) in zip(xs, xs[1:]):
            dd = dist(b, n)
            if dist(a, b) < GAZE_STILL_M and angle(a[2], b[2]) >= GAZE_TURN and angle(b[2], math.atan2(n[1] - b[1], n[0] - b[0])) <= GAZE_AT and GAZE_NEAR <= dd <= GAZE_FAR:
                gazes[i].append(ms)
    acts_at = defaultdict(list)
    for r in prow:
        for k, (skill, target) in (r.get("act") or {}).items():
            if target == sid:
                acts_at[int(k)].append((r["ms"], skill))

    rows, contacts, passes = [], [], []
    converge = []  # (ms, resident, deliberate): an approach to within 4 m, a line, gesture or act at them
    # The deliberate part split by whether a line reached them (fs1e): (ms, resident, kind) with kind
    # "heard" (a line the authority did not mark unheard, a gesture, an act aimed at them) or
    # "unheard" (a line the speaker was told could not have been heard: its `silence` row).
    converge_split = []
    for i in sorted((set(in_range) | {s["a"] for s in speech if s.get("b") == sid}) & (minds or set(in_range) | {s["a"] for s in speech})):
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
                converge.append((ms, i, False))
            # Within 3 m having been farther during the stands: they came, not the newcomer.
            if dd <= CLOSE_M and far_since:
                if not close:
                    passes.append((ms, "close", i))
                close = 1
        to_them = sorted((s for s in speech if s.get("a") == i and s.get("b") == sid), key=lambda s: s["at_ms"])
        for s in to_them:
            contacts.append((s["at_ms"], "line", i))
            converge.append((s["at_ms"], i, True))
            unheard = any(0 <= e["at_ms"] - s["at_ms"] <= 1500 and ("could not have heard" in e.get("text", "") or "within earshot" in e.get("text", "")) for e in silences.get(i, []))
            converge_split.append((s["at_ms"], i, "unheard" if unheard else "heard"))
        about = [s for s in speech if s.get("a") == i and s.get("b") != sid and inwin(s["at_ms"]) and WORDS.search(s.get("text", "")) and (near_at(i, s["at_ms"]) or 99) <= RANGE_M]
        aim = aimed.get(i, [])
        if aim:
            contacts.append((aim[0][0], "aimed:" + aim[0][1], i))
        g = [x for x in gestures if x.get("actor") == i]
        converge += [(x["at_ms"], i, True) for x in g] + [(ms, i, True) for ms, _ in aim]
        converge_split += [(x["at_ms"], i, "heard") for x in g] + [(ms, i, "heard") for ms, _ in aim]
        for x in g:
            contacts.append((x["at_ms"], "gesture:" + x["skill"], i))
        name = names.get(i, f"#{i}")
        jc = jcols.get(name, {})
        ja = jall.get(name, {})
        # First contact and its class: the first line (or an earlier wave or nod, a greeting);
        # without a line an offer or a hostile act aimed at them; else watching (a face or
        # appraise gesture, a gaze, a thought naming them); else an approach with no line.
        ev = [(s["at_ms"], classify(s["text"]), s["text"]) for s in to_them]
        ev += [(x["at_ms"], "greeting", f"{name}: {x['skill']} at the newcomer") for x in g if x["skill"] in ("wave", "nod")]
        kind = None
        if ev:
            kind = min(ev)
        else:
            acts = [(ms, "offer" if sk in OFFER_ACTS else "warning/hostility", f"{name}: {sk} aimed at the newcomer") for ms, sk in acts_at.get(i, []) if sk in OFFER_ACTS | HOSTILE_ACTS]
            watch = [(x["at_ms"], "watching", f"{name}: {x['skill']} at the newcomer") for x in g if x["skill"] in ("face", "appraise")]
            watch += [(ms, "watching", f"{name}: turned to look at the newcomer from {next((dist(b, n) for t, b, n in series[i] if t == ms), 0):.0f} m") for ms in gazes.get(i, [])[:1]]
            if ja.get("first_mention_ms"):
                watch.append((ja["first_mention_ms"], "watching", f"{name} thought of them: " + next((e for e in ja.get("examples", []) if "think" in e), "")[:240]))
            if acts:
                kind = min(acts)
            elif watch:
                kind = min(watch)
            elif appr:
                kind = (next(ms for ms, k, who in passes if who == i and k == "approach"), "approach, no line", f"{name} came within {APPROACH_END_M:.0f} m and said nothing")
        rows.append({
            "id": i, "name": name, "seen": len(mine),
            "first_s": round((first["at_ms"] - t0) / 1000, 1) if first else None,
            "first_sal": first["salience"] if first else None, "crowd": first is None,
            "asked": ja.get("asked", 0), "thinks": jc.get("thinks", 0), "in_prompt": jc.get("in_prompt", 0),
            "mention": jc.get("mention", 0), "words": jc.get("words", 0),
            "approach": appr, "aimed": len(aim), "aimed_skills": sorted({x[1] for x in aim}), "close": close, "gesture": len(g), "to_them": len(to_them), "about_them": len(about),
            "gazes": len(gazes.get(i, [])), "contact": kind[1] if kind else None, "contact_s": round((kind[0] - t_arrive) / 1000, 1) if kind else None,
            "contact_text": kind[2] if kind else None,
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
    # Crowding: residents converging on the newcomer within CONVERGE_S of each other, and the
    # most at once within 4 m having come from beyond LEAVE_M in the minute before.
    converge.sort()

    def most_within(evs):
        return max((len({who for t, who, _ in evs[k:] if t - ms <= CONVERGE_S * 1000}) for k, (ms, _, _) in enumerate(evs)), default=0)
    most, most_any = most_within([c for c in converge if c[2]]), most_within(converge)
    converge_split.sort()
    most_heard = most_within([c for c in converge_split if c[2] == "heard"])
    most_unheard = most_within([c for c in converge_split if c[2] == "unheard"])
    # At once: within 4 m and, in the minute before, having spoken, gestured or aimed an
    # activity at them (deliberate) or come from beyond LEAVE_M (any).
    together = together_any = 0
    deliberate = defaultdict(list)
    for t, who, dl in converge:
        if dl:
            deliberate[who].append(t)
    for ms, ps in pos:
        if not inwin(ms) or sid not in ps:
            continue
        near = [i for i, p in ps.items() if i != sid and dist(p, ps[sid]) <= APPROACH_END_M]
        together = max(together, sum(1 for i in near if any(ms - CONVERGE_S * 1000 <= t <= ms for t in deliberate.get(i, []))))
        together_any = max(together_any, sum(1 for i in near if any(ms - CONVERGE_S * 1000 <= t < ms and dd > LEAVE_M for t, dd in track.get(i, []))))
    # Follow-through (`human.answer`): the newcomer's one answer, and the exchange after it.
    follow = None
    ans = next((e["human_answer"] for e in events if "human_answer" in e), None)
    if ans:
        who, t_ans = ans["to"], ans["at_ms"]
        later = sorted((s for s in speech if s.get("b") == sid and s["at_ms"] > t_ans), key=lambda s: s["at_ms"])
        theirs, last, gaps = [], t_ans, []
        for s in later:
            if s["at_ms"] - last > QUIET_S * 1000:
                break
            if s["a"] == who:
                gaps.append(round((s["at_ms"] - last) / 1000, 1))
                theirs.append(s)
            last = s["at_ms"]
        joined = sorted({s["a"] for s in later if s["a"] != who and s["at_ms"] - t_ans <= QUIET_S * 1000})
        follow = {"answered": names.get(who, f"#{who}"), "contact_s": round((ans["heard"]["at_ms"] - t_arrive) / 1000, 1), "heard": ans["heard"]["text"],
                  "replies": len(theirs), "reply_s": gaps, "others_joined": [names.get(x, f"#{x}") for x in joined],
                  "lines": [s["text"][:200] for s in theirs[:4]]}
    reasons = reused_reasons(d / "journal")
    # What each deliberation carried (`detail.reasons`, since fix-stale-reasons; `record.thoughts`):
    # a reason an earlier deliberation already carried (same words, same arrival) is re-used.
    carried = [r for t in jl(d / "thoughts_all.jsonl") for r in (_detail(t).get("reasons") or [])]
    reasons["carried"] = len(carried) if carried else None
    reasons["carried_again"] = sum(1 for r in carried if r.get("carried_before")) if carried else None
    return {
        "run": d.name, "variant": summary.get("variant", "?"), "fake": fake, "newcomer": sid, "stands": len(wins),
        "stand_min": round(minutes, 1), "in_range": len(rows), "acted": len(acted), "any": len(anyx),
        "acted_share": round(len(acted) / len(rows), 2) if rows else None,
        "first_stand_s": round((t0 - t_arrive) / 1000, 1),
        "first_contact_s": round((contacts[0][0] - t_arrive) / 1000, 1) if contacts else None,
        "first_contact": contacts[0][1] + " by " + names.get(contacts[0][2], "?") if contacts else None,
        "first_close_s": round((passes[0][0] - t_arrive) / 1000, 1) if passes else None,
        "first_sight": sum(1 for r in rows if not r["crowd"]), "asked": sum(1 for r in rows if r["asked"]),
        "in_prompt": sum(r["in_prompt"] for r in rows), "mention": sum(r["mention"] for r in rows),
        "thinks_per_res_min": round(thinks / max(1, len(rows)) / max(minutes, 1e-9), 2),
        "approaches": sum(r["approach"] for r in rows), "aimed": sum(1 for r in rows if r["aimed"]), "gestures": sum(r["gesture"] for r in rows),
        "lines_to": sum(r["to_them"] for r in rows), "lines_about": sum(r["about_them"] for r in rows),
        "calls_min": round((summary.get("calls") or 0) / run_min, 1) if run_min else None,
        "tok_min": round((summary.get("tokens") or 0) / run_min) if run_min else None,
        "usd_h": round(usd / run_min * 60, 2) if run_min else None,
        "usd": round(usd, 2),
        "converge_60s": most, "converge_60s_heard": most_heard, "converge_60s_unheard": most_unheard, "together_4m": together, "converge_any_60s": most_any, "together_any_4m": together_any,
        "reasons": reasons["reasons"], "reused": reasons["reused"], "reused_events": reasons["reused_events"],
        "reused_share": round(reasons["reused"] / reasons["reasons"], 2) if reasons["reasons"] else None,
        "carried": reasons["carried"], "carried_again": reasons["carried_again"],
        "follow": follow, "trial": summary.get("trial") or d.name.rsplit("-", 2)[0],
        "classes": {c: sum(1 for r in rows if r["contact"] == c) for c in CLASSES},
        "residents": rows,
    }


COLS = ["run", "variant", "stand_min", "in_range", "first_sight", "asked", "in_prompt", "mention", "thinks_per_res_min",
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
        r["arm"] = r["variant"] if r["trial"] == "arrive" else f"{r['trial']}:{r['variant']}"
        groups[(r["batch"], r["arm"])].append(r)
    print("\n## Mean (range) per batch x arm\n")
    agg = []
    for (b, v), rs in sorted(groups.items()):
        row = {"batch": b, "variant": v, "n": len(rs)}
        for c in ["in_range", "first_sight", "asked", "in_prompt", "mention", "approaches", "aimed", "gestures", "lines_to", "lines_about", "acted_share", "first_contact_s", "thinks_per_res_min", "usd_h"]:
            xs = [r[c] for r in rs if r.get(c) is not None]
            row[c] = f"{statistics.mean(xs):.2f} ({min(xs)}–{max(xs)})" if xs else None
        row["no_contact"] = sum(1 for r in rs if r["first_contact_s"] is None)
        agg.append(row)
    print(table(agg, ["batch", "variant", "n", "in_range", "first_sight", "asked", "in_prompt", "mention", "approaches", "aimed", "gestures", "lines_to", "lines_about", "acted_share", "first_contact_s", "no_contact", "thinks_per_res_min", "usd_h"]))

    # 1. First contact, by class.
    print("\n## First contact per resident, by class (residents in range, and any who spoke to the newcomer)\n")
    crows = []
    for (b, v), rs in sorted(groups.items()):
        row = {"batch": b, "arm": v, "n": len(rs), "residents": sum(len(r["residents"]) for r in rs)}
        for c in CLASSES:
            row[c] = sum(r["classes"][c] for r in rs)
        row["none"] = row["residents"] - sum(row[c] for c in CLASSES)
        crows.append(row)
    print(table(crows, ["batch", "arm", "n", "residents", *CLASSES, "none"]))
    for c in CLASSES:
        ex = [(r["arm"], x) for r in runs for x in r["residents"] if x["contact"] == c]
        if ex:
            print(f"\n{c} ({len(ex)}):")
            for arm, x in ex[:3]:
                print(f"- [{arm}, {x['name']}, {x['contact_s']} s after arrival] {x['contact_text'][:300]}")

    # 2. Follow-through after the newcomer's one answer (`arrive-answer`).
    fr = [r for r in runs if r.get("follow")]
    if fr or any(r["trial"] == "arrive-answer" for r in runs):
        print("\n## Follow-through after the newcomer's answer\n")
        rows = [{"run": r["run"], "arm": r["arm"], **{k: v for k, v in r["follow"].items() if k not in ("lines", "heard")}} for r in fr]
        print(table(rows, ["run", "arm", "answered", "contact_s", "replies", "reply_s", "others_joined"]) if rows else "no answer given (no resident addressed the newcomer)")
        for r in runs:
            if r["trial"] == "arrive-answer" and not r.get("follow"):
                print(f"- {r['run']}: nobody addressed the newcomer, so it never answered")
        for r in fr[:6]:
            f = r["follow"]
            print(f"- {r['run']}: heard “{f['heard'][:160]}” → answered; then: " + (" / ".join(f["lines"]) or "no reply"))

    # 3-4. Crowding and cost per arm.
    print("\n## Crowding and cost per arm\n")
    krows = []
    for (b, v), rs in sorted(groups.items()):
        row = {"batch": b, "arm": v, "n": len(rs)}
        for c in ["converge_60s", "together_4m", "converge_any_60s", "together_any_4m", "usd_h", "usd", "calls_min", "tok_min", "reused_share", "reused_events", "carried", "carried_again"]:
            xs = [r[c] for r in rs if r.get(c) is not None]
            row[c] = f"{statistics.mean(xs):.2f} ({min(xs)}–{max(xs)})" if xs else None
        row["runs_3plus"] = f"{sum(1 for r in rs if r['converge_60s'] >= 3)} of {len(rs)}"
        krows.append(row)
    print(table(krows, ["batch", "arm", "n", "converge_60s", "together_4m", "runs_3plus", "converge_any_60s", "together_any_4m", "usd_h", "usd", "calls_min", "tok_min", "reused_share", "reused_events", "carried", "carried_again"]))
    print("\n## Residents in range\n")
    for r in runs:
        print(f"### {r['batch']} {r['run']}\n")
        print(table(r["residents"], ["id", "name", "seen", "first_s", "first_sal", "crowd", "asked", "thinks", "in_prompt", "mention", "words", "approach", "aimed", "close", "gazes", "gesture", "to_them", "about_them", "contact", "contact_s"]))
        for x in r["residents"]:
            for e in x["examples"][:a.examples]:
                print(f"- {x['name']}: {e}")
        print()
    if a.json:
        Path(a.json).write_text(json.dumps(runs, indent=1))


if __name__ == "__main__":
    main()
