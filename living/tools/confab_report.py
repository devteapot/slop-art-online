#!/usr/bin/env python3
"""Confabulation report: what minds say about their own deeds, against the record.

Read-only over trial evidence: no model calls, no database. For every line a
thinking character said (the chronicle's `speech` rows in `final.json`, one row
per line; a line repeated within 2 minutes is one row, marked "(×n)"), it finds
first-person claims about the speaker's own deeds, possessions or knowledge and
checks each against the authority's record of that speaker at that moment.

Usage:
    confab_report.py BATCH_DIR [BATCH_DIR ...] [--out DIR] [--examples N]

A BATCH_DIR holds run directories (`<trial>-<variant>-rN/`). The arm is the run
name without `-rN`. Writes `confab.json` (every claim with its verdict and
evidence) and `confab.md` (rates and examples) to --out (default: the current
directory).

## The record, per speaker

- **Snapshots** (`snap`): every think or deliberate request in the speaker's
  journal carries the authority's scene, built at the request (`at_ms`); its
  `you` object gives `pack` (inventory), `knows_how_to`, `hunger` and `at`.
  Talk requests add "You carry (as you last looked): ..." and "You know how to:
  ..." lines where the build has them.
- **Know-how over time** (`know`): snapshot `knows_how_to`, "You know how to:"
  prompt lines, `know_how` rows (`final.json` and `mind_rows.jsonl`, with
  `since_ms`), chronicle `learn` rows ("X taught Y T") and `learned` experiences.
- **Experiences** (`exp`): `experiences_all.jsonl` rows observed by the speaker
  where the batch keeps it (ar2, st1, st2, st2b); in every batch also the
  "Recent experiences" lines of the speaker's own prompts, timed by the prompt's
  game clock (fitted per run from the scenes' `time`), to within a game minute.
- **Deeds seen by others**: `experiences_all.jsonl` rows whose `subject` is the
  speaker (a witnessed craft, build, write, gift).
- **Chronicle** (`final.json`): `give`, `build`, `plant`, `learn`, `host` rows,
  complete for every character.
- **Positions**: snapshot `at`, `positions.jsonl` and `census.jsonl`.

## Claim classes

Each sentence of a line is matched separately, lower-cased, first person
singular ("I", "I've", "my"). A sentence is skipped for every class when it is a
question, or is hypothetical or future ("if I", "I'll", "I will", "I'd", "I
would", "I might", "I could", "I want to", "I'm going to", "I need to", "I
mean to", "let me"), except where a class says otherwise. Claims about the
distant past ("years", "ago", "once", "used to", "when I was", "long", "last
winter|year|season|spring|summer|autumn") are skipped: the authored past is not
in the record.

| class | matches | contradicted when |
|---|---|---|
| `know` | "I know (how to) T", "I know my letters", "I can read/write/cook/fish/...", and offers to teach: "I('ll\\| can\\| could) teach you (how to) T" (future allowed: an offer to teach claims the knowing) | T is not in the speaker's know-how at the line's moment: no source above shows it at or before the line |
| `know_not` | "I can't/cannot read", "I don't know (how to) T", "I never learned (my letters\\| to read\\| T)" | T is in the speaker's know-how at the line's moment |
| `read` | "I('ve\\| have)? (just\\| already)? read (the\\|your\\|that\\|this\\|both\\|it\\|...)" | the speaker did not know writing at the moment (strong), or, where `experiences_all` exists, no `read` experience of the speaker before the line |
| `gave` | "I('ve\\| have)? (just\\| already)? gave/given (you\\| him\\| her\\| them\\| NAME)" | no chronicle `give` row from the speaker before the line (to the addressee, when the claim says "you") |
| `have` | "I have / I've got / I carry / I got (N) ITEM" (ITEM any pack item; "fish" also counts cooked and smoked fish), not about a store, house or home | the item is absent from the speaker's pack in the snapshot before the line and in the one after, each within 180 s |
| `have_not` | "I have no ITEM", "I've no ITEM", "I don't have (any) ITEM", "not a single ITEM" | the item is in the pack in both bracketing snapshots |
| `made` | "I('ve\\| have)? (just\\| already)? built/made/crafted/cooked/baked/smoked/planted/wrote/lit X" | no record of that kind of deed by the speaker before the line: chronicle `build`/`plant` for built/planted (complete); for the rest only where `experiences_all` exists (the speaker's own "You finished: ..." lines and others' witnessed rows); elsewhere `unsupported` |
| `ate` | "I('ve\\| have)? (just\\| already)? ate/eaten/had my fill/had (a\\| my) meal" | no fall in the speaker's hunger of at least 3 between snapshots within the 20 minutes before the line, and hunger never below 15 in them (needs 2 snapshots) |
| `been` | "I('ve\\| have)? (just\\| already)? been to / come from / came from / walked from PLACE", with a recency word (just, today, this morning, earlier, already) | PLACE is one the minds named (any character's place rows) and the speaker was never within 40 m of it before the line, over at least 10 position samples |

Deed claims (`read` by one who knows writing, `gave`, `made`) are skipped in
clauses of time ("till", "until", "when", "after", "before", "once"). With no
record, they are `contradicted` only when the line dates them within the run (a
recency word: just, today, this morning, earlier, already); otherwise they are
`undated`, since a seeded person's authored past is not in the record. `gave`
needs a pack item among the six words after the verb, and `have` skips a
thing followed by a task or a figure ("I've wood to cut", "tablet work", "a net
of promises") or by a store word ("stored", "at home") (giving a name, an answer
or one's word is not a give). "read"/"write" count as writing only when what
follows is something written ("read the water" does not). "I can X" counts only
for read and write. The census's sampled activity (every 30 s) also counts as a
record of making.

Verdicts: `contradicted` (the record shows the claim false at that moment),
`supported` (the record shows it true), `unsupported` (the record cannot tell:
a missing snapshot, or a deed whose record this batch does not keep). Every
claim keeps its evidence in `confab.json`; `confab.md` shows it beside each
example. Rates are per 100 lines said by thinking characters (speakers with a
journal); the scripted player's lines are left out.

Limits: the patterns are English keyword heuristics, so they miss paraphrase
and can misread a sentence. A `contradicted` verdict says the record and the
words disagree, not that the speaker meant to deceive. A deliberate lie is not
told apart here; the thought before the line says whether it was one.
"""
import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter, defaultdict

TECH_WORDS = {
    "read": "writing", "write": "writing", "letters": "writing", "writing": "writing", "reading": "writing",
    "cook": "cooking", "cooking": "cooking", "fish": "fishing", "fishing": "fishing",
    "plant": "planting", "planting": "planting", "smoke": "smoking", "smoking": "smoking",
    "trap": "trapping", "trapping": "trapping", "tan": "tanning", "tanning": "tanning",
    "carpentry": "carpentry", "masonry": "masonry", "glassmaking": "glassmaking", "glass": "glassmaking",
    "basketry": "basketry", "archery": "archery", "toolmaking": "toolmaking", "medicine": "medicine",
    "torch": "torch", "torches": "torch", "cloak": "cloak", "cloaks": "cloak", "spear": "spear",
    "fire": "fire", "storage": "storage", "shelter": "shelter", "bridging": "bridging",
    "wound_tending": "wound_tending", "fire_bolt": "fire_bolt", "weaving": "basketry",
}
SKIP_ALL = re.compile(r"\b(if i|i'll|i will|i'd|i would|i might|i could|i want to|i'm going to|i am going to|i need to|i mean to|let me|i must|i should|i hope|i wish)\b")
DISTANT = re.compile(r"\b(years?|ago|once|used to|when i was|long|last (winter|year|season|spring|summer|autumn|fall))\b")
RECENT = re.compile(r"\b(just|today|this morning|earlier|already|this afternoon|a moment)\b")
STORE = re.compile(r"\b(store|stored|storage|stores|house|home|hall|shed|larder|basket at|at the)\b")
# "I've wood to cut", "I've crucibles to make", "tablet work", "a net of promises": a task or a figure, not a thing held.
NOT_HELD = re.compile(r"^\s*(?:to (?:make|finish|cut|do|build|craft|write|keep|mend|tend|see|fix|gather|fetch|split|haul|stack|chop|dig|fill|bake|cook)\b|work\b|of\b|-)")
NUM = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|some|a few|few|plenty of|enough|a handful of|a little|more|fresh|cooked|smoked|dried|good|spare)"


def jl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip().strip("\x00")
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def quoted(text):
    """The words of a chronicle speech row, and its addressee's name if any."""
    m = re.match(r"^(.*?)(?: to (.*?))?: “(.*)”(?: \(×\d+\))?$", text, re.S)
    if not m:
        return None, text
    return m.group(2), m.group(3)


class Run:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path.rstrip("/"))
        self.arm = re.sub(r"-r\d+$", "", self.name)
        self.final = json.load(open(os.path.join(path, "final.json"))) if os.path.exists(os.path.join(path, "final.json")) else {}
        self.chron = self.final.get("chronicle", [])
        self.names = {}
        self.ids = {}
        self.snaps = defaultdict(list)      # id -> [(ms, pack, know, hunger, at)]
        self.know_lines = defaultdict(list)  # id -> [(ms, set)]
        self.exp = defaultdict(list)        # id -> [(ms, kind, text)]
        self.seen_deeds = defaultdict(list)  # subject id -> [(ms, kind, text)]
        self.pos = defaultdict(list)        # id -> [(ms, x, y)]
        self.places = defaultdict(list)     # lower name -> [(x, y)]
        self.know_rows = defaultdict(list)  # id -> [(ms, technique)]
        self.minds = set()
        self.has_all = os.path.exists(os.path.join(path, "experiences_all.jsonl"))
        self.clock = []  # (game minutes, ms)
        self.items = set()
        self._load()

    def _load(self):
        p = self.path
        self.activity = defaultdict(list)
        for c in jl(os.path.join(p, "census.jsonl")):
            for pe in c.get("people", []):
                self.names[pe["id"]] = pe["name"]
                if pe.get("activity"):
                    self.activity[pe["id"]].append((c["now_ms"], pe["activity"][0]))
                if pe.get("pos"):
                    self.pos[pe["id"]].append((c["now_ms"], pe["pos"][0], pe["pos"][1]))
        for c in self.final.get("character", []):
            self.names.setdefault(c.get("id"), c.get("name"))
        for r in jl(os.path.join(p, "positions.jsonl")):
            for k, v in r.get("pos", {}).items():
                self.pos[int(k)].append((r["ms"], v[0], v[1]))
        jdir = os.path.join(p, "journal")
        rows_by_actor = {}
        if os.path.isdir(jdir):
            for fn in os.listdir(jdir):
                if fn.endswith(".jsonl"):
                    rows_by_actor[fn[:-6].replace("_", " ")] = jl(os.path.join(jdir, fn))
        # First pass: ids and the game clock from scenes.
        pending_exp = []
        for actor, rows in rows_by_actor.items():
            aid = None
            for r in rows:
                req = r.get("request") or {}
                for m in req.get("messages", []):
                    c = m.get("content") or ""
                    if '"you":' not in c:
                        continue
                    scene = self._scene(c)
                    if not scene:
                        continue
                    you = scene.get("you", {})
                    if "id" in you:
                        aid = you["id"]
                        self.names.setdefault(aid, you.get("name", actor))
                    t = scene.get("time") or {}
                    if "day" in t and "hour" in t:
                        self.clock.append(((t["day"] * 24 + t["hour"]) * 60, r["at_ms"]))
                    if aid is not None and "pack" in you:
                        pack = {k: v for k, v in (you.get("pack") or {}).items()}
                        self.items.update(pack.keys())
                        know = set(you.get("knows_how_to") or [])
                        self.snaps[aid].append((r["at_ms"], pack, know, you.get("hunger"), you.get("at")))
                        if you.get("at"):
                            self.pos[aid].append((r["at_ms"], you["at"][0], you["at"][1]))
                    break
            if aid is None:
                aid = next((i for i, n in self.names.items() if n == actor), None)
            if aid is None:
                continue
            self.ids[actor] = aid
            self.minds.add(aid)
            for r in rows:
                req = r.get("request") or {}
                for m in req.get("messages", []):
                    c = m.get("content") or ""
                    for mm in re.finditer(r"You know how to: ([^\n]*)", c):
                        self.know_lines[aid].append((r["at_ms"], {w.strip() for w in mm.group(1).split(",") if w.strip()}))
                    i = c.find("# Recent experiences")
                    if i >= 0:
                        for line in c[i:].split("\n")[1:]:
                            if line.startswith("#"):
                                break
                            em = re.match(r"- \[day (\d+) (\d+):(\d+)\] (.*)", line)
                            if em:
                                gm = (int(em.group(1)) * 24 + int(em.group(2))) * 60 + int(em.group(3))
                                pending_exp.append((aid, gm, r["at_ms"], em.group(4)))
        self.clock.sort()
        for aid, gm, req_ms, text in pending_exp:
            ms = min(self._game_ms(gm), req_ms)
            self.exp[aid].append((ms, "prompt", text))
        if self.has_all:
            for e in jl(os.path.join(p, "experiences_all.jsonl")):
                self.exp[e["observer"]].append((e["at_ms"], e["kind"], e["text"]))
                if e.get("subject") and e["subject"] != e["observer"]:
                    self.seen_deeds[e["subject"]].append((e["at_ms"], e["kind"], e["text"]))
        for tab in [self.final.get("know_how", [])] + [r["rows"] for r in jl(os.path.join(p, "mind_rows.jsonl")) if r.get("table") == "know_how"]:
            for k in tab:
                self.know_rows[k["actor"]].append((k.get("since_ms", 0), k["technique"]))
        for tab in [self.final.get("place", [])] + [r["rows"] for r in jl(os.path.join(p, "mind_rows.jsonl")) if r.get("table") == "place"]:
            for pl in tab:
                self.places[pl["name"].lower()].append((pl["x"], pl["y"]))
        for x in self.chron:
            if x["kind"] == "learn":
                m = re.match(r"(.*) taught (.*) (\S+)$", x["text"])
                if m and x.get("b"):
                    self.know_rows[x["b"]].append((x["at_ms"], m.group(3)))
        for d in (self.snaps, self.know_lines, self.exp, self.pos, self.seen_deeds):
            for k in d:
                d[k].sort(key=lambda r: r[0])

    @staticmethod
    def _scene(content):
        for m in re.finditer(r"\{\"creatures\"|\{\"[a-z_]+\":", content):
            pass
        # The scene is the JSON object that contains "you": find the outermost object around it.
        i = content.find('"you":')
        if i < 0:
            return None
        start = content.rfind("\n{", 0, i)
        start = 0 if start < 0 else start + 1
        depth, end = 0, None
        for j in range(start, len(content)):
            ch = content[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end is None:
            return None
        try:
            return json.loads(content[start:end])
        except json.JSONDecodeError:
            return None

    def _game_ms(self, gm):
        c = self.clock
        if not c:
            return 0
        keys = [g for g, _ in c]
        i = bisect.bisect_left(keys, gm)
        if i == 0:
            (g0, m0), (g1, m1) = c[0], c[min(1, len(c) - 1)]
        elif i >= len(c):
            (g0, m0), (g1, m1) = c[max(0, len(c) - 2)], c[-1]
        else:
            (g0, m0), (g1, m1) = c[i - 1], c[i]
        if g1 == g0:
            return m0
        return int(m0 + (gm - g0) * (m1 - m0) / (g1 - g0))

    # --- the record at a moment -------------------------------------------
    def known_at(self, aid, ms):
        """(techniques known at ms, whether any source covered this speaker before ms)."""
        k, covered = set(), False
        for t, s in self.know_lines.get(aid, []):
            if t <= ms + 5000:
                k |= s
                covered = True
        for t, pack, know, _, _ in self.snaps.get(aid, []):
            if t <= ms + 5000:
                k |= know
                covered = True
        for t, tech in self.know_rows.get(aid, []):
            if t <= ms + 5000:
                k.add(tech)
        for t, kind, text in self.exp.get(aid, []):
            if t <= ms + 5000:
                m = re.match(r".* taught you (\S+) \(", text) or re.search(r"worked out (?:how to )?(\S+)", text)
                if m:
                    k.add(m.group(1))
        return k, covered

    def bracket(self, aid, ms, within=180_000):
        s = self.snaps.get(aid, [])
        before = [x for x in s if ms - within <= x[0] <= ms]
        after = [x for x in s if ms < x[0] <= ms + within]
        return (before[-1] if before else None), (after[0] if after else None)

    def gives_by(self, aid, ms, to=None):
        out = []
        for x in self.chron:
            if x["kind"] == "give" and x.get("a") == aid and x["at_ms"] <= ms + 2000 and (to is None or x.get("b") == to):
                out.append(x)
        return out


CLAUSE_BEFORE = re.compile(r"\b(before|until|till|when|once|after|if|unless)\s*$")
DEED_SKIP = re.compile(r"\b(till|until|unless|when|after|before|once|whenever)\b")


def undated(low):
    """A deed with no record is contradicted only when the line dates it within the run."""
    return "contradicted" if RECENT.search(low) else "undated"


def reading_object(rest):
    """Whether "read"/"write" is about writing: what follows is something written, or nothing."""
    rest = rest.strip()
    return rest == "" or bool(re.match(r"^(?:and write|and read|letters|well|a little|now|too|them|it|the (?:signs?|tablets?|letters|marks|words|book)|(?:your|his|her|my|their|a|the) (?:\w+ )?(?:signs?|tablets?|letters|marks|words|name|writing))\b", rest))


def item_family(word, items):
    w = word.lower().rstrip(".,!;:")
    sing = w[:-3] + "y" if w.endswith("ies") else (w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    fam = set()
    for it in items:
        base = it.replace("_", " ")
        if w in (base, base + "s") or sing in (base,) or base.endswith(" " + sing) or base.endswith(" " + w):
            fam.add(it)
    return fam


def has_items(pack, fam):
    return sum(pack.get(i, 0) for i in fam)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?;—–])\s+|\s+[—–]\s+", text) if s.strip()]


def check_run(run, items):
    claims = []
    lines = 0
    for x in run.chron:
        if x["kind"] != "speech" or x.get("a") not in run.minds:
            continue
        lines += 1
        aid, ms = x["a"], x["at_ms"]
        to_name, words = quoted(x["text"])
        to_id = x.get("b") or None
        for s in sentences(words):
            low = s.lower().replace("’", "'")
            question = s.rstrip().endswith("?")
            hypo = bool(SKIP_ALL.search(low))
            distant = bool(DISTANT.search(low))
            def add(cls, verdict, claim, evidence):
                claims.append({"run": run.name, "arm": run.arm, "at_ms": ms, "speaker": run.names.get(aid, aid), "to": to_name,
                               "line": words, "sentence": s, "class": cls, "claim": claim, "verdict": verdict, "evidence": evidence})
            # know (offers to teach may be future)
            for m in re.finditer(r"\bi(?:'ll| will| can| could)? (?:teach|show) (?:you|him|her|them|\w+) (?:how to |to )?(\w+)\b(?!-)", low):
                t = TECH_WORDS.get(m.group(1))
                if t in ("writing",) and not reading_object(low[m.end():]):
                    t = None
                if t and not question and "if i" not in low:
                    known, cov = run.known_at(aid, ms)
                    add("know", "unsupported" if not cov else ("supported" if t in known else "contradicted"), f"can teach {t}",
                        {"known_at_line": sorted(known), "covered": cov})
            if not question and not hypo and not distant:
                for m in re.finditer(r"\bi (know how to|know|can) (?:my )?(\w+)\b(?!-)", low):
                    word = m.group(2)
                    if m.group(1) == "can" and word not in ("read", "write"):
                        continue  # "I can cook" is as often leave as skill
                    if m.group(1) == "know" and word in ("fish", "fishing", "fire", "storage", "spear", "torch", "glass", "shelter"):
                        continue  # "I know fishing spots", "I know fire": not a claim of the technique
                    if word in ("read", "write") and (not reading_object(low[m.end():]) or re.search(r"\bso (?:that )?i can\b", low[max(0, m.start() - 12):m.end()])):
                        continue
                    t = TECH_WORDS.get(word)
                    if t:
                        known, cov = run.known_at(aid, ms)
                        add("know", "unsupported" if not cov else ("supported" if t in known else "contradicted"), f"knows {t}",
                            {"known_at_line": sorted(known), "covered": cov})
                for m in re.finditer(r"\bi (?:can't|cannot|can not|don't know how to|never learned (?:to|how to)?|don't know|never learned) (?:my |any |the )?(\w+)", low):
                    t = TECH_WORDS.get(m.group(1))
                    if t:
                        known, cov = run.known_at(aid, ms)
                        add("know_not", "unsupported" if not cov else ("contradicted" if t in known else "supported"), f"does not know {t}",
                            {"known_at_line": sorted(known), "covered": cov})
                # read
                for m in ([] if DEED_SKIP.search(low) else re.finditer(r"\bi(?:'ve| have)? (?:just |already |now )?read (?:the |your |that |this |both |every |those |his |her |their |a |its |all )*(?:\w+ )?(?:signs?|tablets?|letters?|marks?|words?|writing|book|ledger|slate|list)\b", low)):
                    known, cov = run.known_at(aid, ms)
                    reads = [e for e in run.exp.get(aid, []) if e[0] <= ms + 2000 and (e[1] == "read" or e[2].startswith("You read"))]
                    if cov and "writing" not in known:
                        v = "contradicted"
                    elif reads:
                        v = "supported"
                    elif run.has_all:
                        v = "contradicted"
                    else:
                        v = "unsupported"
                    if v == "contradicted" and "writing" in known:
                        v = undated(low)
                    add("read", v, "read something", {"knows_writing": "writing" in known, "covered": cov, "read_experiences_before": [e[2][:120] for e in reads[-3:]], "experiences_all": run.has_all})
                # gave
                for m in re.finditer(r"\bi(?:'ve| have)? (?:just |already )?(?:gave|given) (you|him|her|them|[a-z]+)\b((?: \S+){0,6})", low):
                    if not any(item_family(w, items) for w in m.group(2).split()) or DEED_SKIP.search(low):
                        continue
                    target = to_id if m.group(1) == "you" else None
                    g = run.gives_by(aid, ms, target)
                    gall = run.gives_by(aid, ms)
                    add("gave", "supported" if g else undated(low), f"gave {m.group(1)}",
                        {"gives_to_target_before": [y["text"] for y in g[-3:]], "gives_any_before": [y["text"] for y in gall[-3:]], "target_id": target})
                # made
                for m in re.finditer(r"\bi(?:'ve| have)? (?:just |already )?(built|made|crafted|cooked|baked|smoked|planted|wrote|lit) (?:a |an |the |this |that |my |some |\d+ )?(\w+)", low):
                    verb = m.group(1)
                    if DEED_SKIP.search(low):
                        continue
                    if verb in ("built", "planted"):
                        kind = "build" if verb == "built" else "plant"
                        rec = [y["text"] for y in run.chron if y["kind"] == kind and y.get("a") == aid and y["at_ms"] <= ms + 2000]
                        v = "supported" if rec else undated(low)
                    else:
                        pat = {"made": r"(make|craft|cook|built|made|crafted|cooked|baked|smoked)", "crafted": r"(craft|crafted|made)",
                               "cooked": r"(cook|cooked|make)", "baked": r"(bake|baked|make)", "smoked": r"(smoke|smoked|make)",
                               "wrote": r"(write|wrote)", "lit": r"(lit|light|feed|fed)"}[verb]
                        own = [e[2] for e in run.exp.get(aid, []) if e[0] <= ms + 2000 and e[2].startswith(("You finished", "You did what")) and re.search(pat, e[2])]
                        seen = [e[2] for e in run.seen_deeds.get(aid, []) if e[0] <= ms + 2000 and re.search(pat, e[2])]
                        acts = {"made": ("make", "craft", "cook", "bake", "smoke"), "crafted": ("craft", "make"), "cooked": ("cook", "make"), "baked": ("make", "bake"),
                                "smoked": ("smoke", "make"), "wrote": ("write",), "lit": ("light", "feed")}[verb]
                        seen_doing = [f"census: {sk} at {round((ms - t) / 1000)} s before" for t, sk in run.activity.get(aid, []) if t <= ms + 2000 and sk in acts]
                        rec = own[-3:] + seen[-3:] + seen_doing[-2:]
                        v = "supported" if rec else (undated(low) if run.has_all or run.activity else "unsupported")
                    add("made", v, f"{verb} {m.group(2)}", {"records_before": rec[-4:], "experiences_all": run.has_all})
                # ate
                for m in ([] if DEED_SKIP.search(low) else re.finditer(r"\bi(?:'ve| have)? (?:just |already )?(?:ate|eaten|had my fill|had (?:a|my) (?:meal|supper|breakfast|dinner))\b", low)):
                    s20 = [z for z in run.snaps.get(aid, []) if ms - 1_200_000 <= z[0] <= ms + 60_000 and z[3] is not None]
                    if len(s20) < 2:
                        add("ate", "unsupported", "ate", {"snapshots": len(s20)})
                    else:
                        drops = [(a[3], b[3]) for a, b in zip(s20, s20[1:]) if b[3] <= a[3] - 3]
                        fed = min(z[3] for z in s20) < 15  # barely hungry: fed before the window
                        add("ate", "supported" if drops or fed else "contradicted", "ate", {"hunger_in_snapshots": [round(z[3]) for z in s20]})
                # been
                if RECENT.search(low):
                    for m in re.finditer(r"\bi(?:'ve| have)? (?:just |already )?(?:been (?:to|at|down to|up to|over to)|come (?:from|up from|down from)|came (?:from|up from|down from)|walked (?:from|to)) (?:the )?([a-z][\w' ]{2,30})", low):
                        place = None
                        tail = m.group(1)
                        for n in sorted(run.places, key=len, reverse=True):
                            if tail.startswith(n) and len(n) >= 4 and n not in ("home",):
                                place = n
                                break
                        if not place:
                            continue
                        (px, py) = run.places[place][0]
                        ps = [z for z in run.pos.get(aid, []) if z[0] <= ms]
                        if len(ps) < 10:
                            add("been", "unsupported", f"been at {place}", {"positions": len(ps)})
                            continue
                        dmin = min(((z[1] - px) ** 2 + (z[2] - py) ** 2) ** 0.5 for z in ps)
                        add("been", "supported" if dmin <= 40 else "contradicted", f"been at {place}", {"place_at": [px, py], "closest_m": round(dmin, 1), "positions": len(ps)})
            # have / have_not (present tense; not hypothetical)
            if question or hypo or distant:
                continue
            for m in re.finditer(r"\bi(?: have| have got|'ve got|'ve| carry| got| hold)\s+(?:" + NUM + r"\s+)?(?:" + NUM + r"\s+)?([a-z_]+)\b(?!-)", low):
                word = m.group(1)
                if word in ("no", "nothing", "not", "none", "never", "been", "had", "to", "seen", "heard", "a", "the"):
                    continue
                fam = item_family(word, items)
                if not fam or STORE.search(low[m.end():m.end() + 40]) or NOT_HELD.match(low[m.end():]) or CLAUSE_BEFORE.search(low[max(0, m.start() - 16):m.start()]):
                    continue
                b, a = run.bracket(aid, ms)
                if not b or not a:
                    add("have", "unsupported", f"has {word}", {"before": b and b[1], "after": a and a[1]})
                    continue
                nb, na = has_items(b[1], fam), has_items(a[1], fam)
                add("have", "contradicted" if nb == 0 and na == 0 else "supported", f"has {word}",
                    {"pack_before": b[1], "pack_after": a[1], "before_s": round((ms - b[0]) / 1000), "after_s": round((a[0] - ms) / 1000)})
            for m in re.finditer(r"\bi(?: have|'ve)? (?:no|not a single|not one|don't have any|don't have a|don't have|haven't any|haven't got any|haven't a) ([a-z_]+)", low):
                fam = item_family(m.group(1), items)
                if not fam or STORE.search(low[m.end():m.end() + 40]) or "left to spare" in low or "to spare" in low[m.end():m.end() + 20]:
                    continue
                b, a = run.bracket(aid, ms)
                if not b or not a:
                    add("have_not", "unsupported", f"has no {m.group(1)}", {"before": b and b[1], "after": a and a[1]})
                    continue
                nb, na = has_items(b[1], fam), has_items(a[1], fam)
                add("have_not", "contradicted" if nb > 0 and na > 0 else "supported", f"has no {m.group(1)}",
                    {"pack_before": b[1], "pack_after": a[1], "before_s": round((ms - b[0]) / 1000), "after_s": round((a[0] - ms) / 1000)})
    return lines, claims


BASE_ITEMS = {"berries", "fish", "cooked_fish", "smoked_fish", "meat", "cooked_meat", "wood", "stone", "fiber", "hide", "clay",
              "reeds", "spear", "bow", "arrow", "torch", "cloak", "tablet", "salve", "net", "basket", "leather", "armor", "peat",
              "kelp", "glass", "shard", "roots", "baked_roots", "greens", "bread", "mark", "ash", "sand"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--out", default=".")
    ap.add_argument("--examples", type=int, default=10)
    a = ap.parse_args()
    allc, table = [], []
    for bdir in a.batches:
        bname = os.path.basename(bdir.rstrip("/"))
        runs = sorted(d for d in os.listdir(bdir) if os.path.isdir(os.path.join(bdir, d)) and os.path.exists(os.path.join(bdir, d, "final.json")))
        per_arm = defaultdict(lambda: {"runs": 0, "lines": 0, "claims": Counter(), "verdicts": Counter()})
        for rn in runs:
            run = Run(os.path.join(bdir, rn))
            items = BASE_ITEMS | run.items
            lines, claims = check_run(run, items)
            for c in claims:
                c["batch"] = bname
            arm = per_arm[run.arm]
            arm["runs"] += 1
            arm["lines"] += lines
            for c in claims:
                arm["claims"][c["class"]] += 1
                arm["verdicts"][(c["class"], c["verdict"])] += 1
            allc += claims
            print(f"{bname}/{rn}: {lines} lines, {len(claims)} claims, {sum(1 for c in claims if c['verdict'] == 'contradicted')} contradicted", file=sys.stderr)
        for arm, v in sorted(per_arm.items()):
            table.append((bname, arm, v))
    os.makedirs(a.out, exist_ok=True)
    json.dump({"claims": allc}, open(os.path.join(a.out, "confab.json"), "w"), indent=1, ensure_ascii=False)
    classes = ["know", "know_not", "read", "gave", "have", "have_not", "made", "ate", "been"]
    out = ["# Confabulation report", "", "Per 100 lines said by thinking characters. Cells: contradicted / claims (u: unsupported, d: undated deeds with no record). Rate: contradicted per 100 lines.", "",
           "| batch | arm | runs | lines | contradicted per 100 lines | " + " | ".join(classes) + " |",
           "|---|---|---:|---:|---:|" + "---|" * len(classes)]
    for bname, arm, v in table:
        con = sum(n for (c, vd), n in v["verdicts"].items() if vd == "contradicted")
        rate = 100 * con / v["lines"] if v["lines"] else 0
        cells = []
        for c in classes:
            n = v["claims"][c]
            cells.append(f"{v['verdicts'][(c, 'contradicted')]}/{n} ({v['verdicts'][(c, 'unsupported')]}u, {v['verdicts'][(c, 'undated')]}d)" if n else "–")
        out.append(f"| {bname} | {arm} | {v['runs']} | {v['lines']} | {rate:.2f} | " + " | ".join(cells) + " |")
    for title, verdict in (("Every contradicted claim, with its evidence", "contradicted"), ("Undated deeds with no record (not counted in the rate)", "undated")):
        out += ["", "## " + title, ""]
        for c in [c for c in allc if c["verdict"] == verdict]:
            out.append(f"- **{c['batch']}/{c['run']}** {c['speaker']}{' to ' + c['to'] if c['to'] else ''} [{c['class']}: {c['claim']}]: “{c['line']}” — evidence: `{json.dumps(c['evidence'], ensure_ascii=False)[:400]}`")
    open(os.path.join(a.out, "confab.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:6 + len(table)]))


if __name__ == "__main__":
    main()
