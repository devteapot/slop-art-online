#!/usr/bin/env python3
"""Resident inspector: one static page that answers "why did they do that?" for a run.

  inspector.py RUN_DIR [-o page.html] [--who NAMES] [--player NAME] [--since S] [--until S]
               [--journal DIR] [--mind-log FILE] [--rows PATH ...]

RUN_DIR is a trial instance (`.local/living/trials/<batch>/<instance>/`, finished or still
running) or a play session's evidence folder (for example `.local/living/playtest-2/`: a
`journal/` with the mind service's journal, a `mind.log`, and SQL exports of world tables as
the CLI's text tables `*.txt` or `verify.py sql --save` JSON lists). Everything found under it
is read; `--journal`, `--mind-log` and `--rows` add or override sources.

The page joins, for every resident and moment:
- what they perceived: experience rows, and the percept lines their model requests show;
- what they recalled: the recall sections of each request;
- what they decided and why: each model exchange (request sections, reply, timings);
- what graph they installed: deliberation replies and `brain` rows;
- what their body did: chronicle rows, census and sample activity, others' sightings,
  the player's reducer calls;
- the mind log's lines about them.
A "Lines" view lists every line said, who heard it, and for each hearer whether and why they
took a turn: a talk turn (with latency), an answer from a deliberation, a parked line, a
settled pair, or no turn with the gate's inputs as the evidence shows them (addressed,
cares, in another exchange; talk.rs `on_speech`).

Read-only; writes only the page. No model calls. Stdlib only. See docs/TRIALS.md,
"Resident inspector".
"""
import argparse
import base64
import bisect
import datetime as dt
import gzip
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# The speaker's `silence` row: the one a line was said to could not have heard it. Its words since
# `speech_truth` ("Bram is too far away: they could not have heard you.", "… is out of earshot: …",
# a planned line not said, and "Nobody was near enough to hear you." for a line to the room), speech-2's ("… is too far to hear you; …") and the first ("No answer from …").
UNHEARD = re.compile(r"^No answer from|could not have heard you|^Nobody was near enough to hear you|is too far to hear you")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal_io  # noqa: E402

# Conversation constants of the mind service (living/mind/src/mind/talk.rs).
QUIET_MS = 90_000        # an exchange quiet this long is over
ADDRESS_M = 6.0          # the authority's default `address_m` law
CLOSE = ["family", "partner", "friend", "parent", "mother", "father", "child", "son", "daughter", "sibling",
         "brother", "sister", "spouse", "wife", "husband", "lover"]
DEFAULT_DAY_MS = 720_000
WALK = 2.0               # m/s: how far a body can have moved between a seen distance and a line  # a game day is 12 real minutes in current worlds
RULE_NOTE = ("Gate as in talk.rs on_speech: a line gets a turn if it is addressed (said to the listener, "
             "or to no one with salience >= 0.8: the only hearer within address_m 6 m, or named), or the pair's "
             "exchange is active (a line within 90 s), or the listener cares (family or close label, |affinity| >= 40 "
             "or trust >= 60), is in no other exchange, was not drawn in within 60 s, the line is not claimed, and "
             "the sociability draw passes. Draws, stamina and 'lets the remark pass' are logged at debug level only.")

QUOTE = re.compile(r"“(.*)”")


def jl(p):
    out = []
    try:
        data = Path(p).read_bytes()
    except OSError:
        return out
    for n, line in enumerate(data.splitlines(), 1):
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict):
            v["_line"] = n
            out.append(v)
    return out


def quoted(text):
    m = QUOTE.search(text or "")
    return m.group(1) if m else ""


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def strip_reps(text):
    """Chronicle text 'A: “x” (×3)' -> ('A: “x”', 3)."""
    m = re.search(r" \(×(\d+)\)$", text or "")
    return (text[: m.start()], int(m.group(1))) if m else (text, 1)


# ---------------------------------------------------------------- SQL text tables

def _cell(v):
    v = v.strip()
    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
        try:
            return json.loads(v)
        except ValueError:
            return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def sql_text_table(path):
    """Rows of a `spacetime sql` ASCII table (header, a ----+---- rule, rows)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    rule = next((i for i, l in enumerate(lines[:6]) if re.match(r"^-+(\+-+)+-*\s*$", l)), None)
    if rule is None or rule == 0:
        return None
    cuts = [i for i, ch in enumerate(lines[rule]) if ch == "+"]

    def split(l):
        bounds = [0] + cuts + [None]
        return [l[bounds[k] + (1 if k else 0): bounds[k + 1]] for k in range(len(bounds) - 1)]
    head = [h.strip() for h in split(lines[rule - 1])]
    rows = []
    for n, l in enumerate(lines[rule + 1:], rule + 2):
        if not l.strip() or re.match(r"^\(\d+ rows?\)$", l.strip()):
            continue
        cells = split(l)
        if len(cells) != len(head):
            continue
        row = {h: _cell(c) for h, c in zip(head, cells)}
        row["_line"] = n   # the row's line in the file, for citations
        rows.append(row)
    return rows


def table_kind(cols):
    c = set(cols)
    if {"observer", "at_ms", "kind", "subject", "object", "text"} <= c:
        return "experience"
    if {"at_ms", "kind", "a", "b", "text"} <= c:
        return "chronicle"
    if {"actor", "at_ms", "kind", "summary"} <= c:
        return "thought"
    if {"actor", "other", "trust", "affinity"} <= c:
        return "relation"
    if {"speaker", "hearers"} <= c:
        return "audience"
    if {"id", "graph"} <= c and ("revision" in c or "installed_ms" in c):
        return "brain"
    if {"id", "present"} <= c or {"id", "control_ms"} <= c:
        return "presence"
    if {"id", "name"} <= c:
        return "character"
    return None


# ---------------------------------------------------------------- the run

class Run:
    def __init__(self, root, args):
        self.root = Path(root).resolve()
        self.args = args
        self.notes = []
        self.sources = []
        self.names = {}          # id -> name
        self.kinds = {}          # id -> kind
        self.players = set()
        self.died = {}           # id -> (ms, cause)
        self.takeover = {}       # id -> ms the AI took the character over
        self.t0_ms = None
        self.day_ms = None
        self.env = {}
        self.exps = defaultdict(dict)      # observer -> key -> row
        self.chron = {}                    # id -> row
        self.audience = []
        self.relations = defaultdict(list)  # (actor, other) -> [(ms, label, trust, affinity, src)]
        self.calls = []
        self.systems = {}
        self.body = defaultdict(list)      # id -> [ms, text, src]
        self.graphs = defaultdict(list)    # id -> [ms, text, src, graph]
        self.logs = []                     # [ms, text, ids, src, kind, pair]
        self.cands = []                    # speech candidates
        self.census_rows = []
        self.track = defaultdict(list)     # id -> [(ms, x, y, src)]
        self.human_calls = []

    # --- helpers
    def src(self, p, n=None):
        try:
            rel = Path(p).resolve().relative_to(self.root)
        except ValueError:
            rel = Path(p)
        return f"{rel}:{n}" if n else str(rel)

    def name(self, i):
        return self.names.get(i) or f"#{i}"

    def t_ms(self, t):
        return None if t is None or self.t0_ms is None else int(self.t0_ms + float(t) * 1000)

    def learn_name(self, i, name, kind=None):
        if not i or not name or name in ("a stranger", "someone", "a child"):
            return
        i = int(i)
        if i not in self.names:
            self.names[i] = name
        if kind and i not in self.kinds:
            self.kinds[i] = kind

    # --- discovery
    def find(self, *names):
        for n in names:
            p = self.root / n
            if p.exists():
                return p
        return None

    def load(self):
        a = self.args
        st = self.find("state.json")
        if st:
            s = json.loads(st.read_text())
            if s.get("t0"):
                self.t0_ms = int(s["t0"] * 1000)
            self.sources.append(self.src(st))
        summ = self.find("summary.json")
        if summ:
            s = json.loads(summ.read_text())
            self.day_ms = s.get("day_ms")
        envp = self.find("mind-env.json", "session/run/mind-env.json")
        if envp:
            self.env = json.loads(envp.read_text())
        cast = self.find("cast.json")
        if cast:
            c = json.loads(cast.read_text())
            for ms in c.get("roles", {}).values():
                for m in ms:
                    self.learn_name(m["id"], m["name"], m.get("kind"))
        self.load_trial_files()
        for p in [*(a.rows or [])]:
            self.load_rows_path(Path(p))
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and "journal" not in p.parts[len(self.root.parts):] and p.suffix in (".txt", ".json") \
                    and p.name not in ("state.json", "summary.json", "cast.json", "mind-env.json", "models.json", "batch.json", "final.json") \
                    and not p.name.startswith("._") and p.stat().st_size < 50_000_000:
                self.load_rows_path(p, quiet=True)
        fin = self.find("final.json")
        if fin:
            self.load_final(fin)
        jdir = Path(a.journal) if a.journal else self.find("journal", "session/journal")
        if not jdir and self.env.get("LIVING_ROOT") and self.env.get("LIVING_RUN"):
            live = Path(self.env["LIVING_ROOT"]) / ".local/living/journal" / self.env["LIVING_RUN"]
            if live.is_dir():
                jdir = live
                self.notes.append(f"journal read live from {live} (the run has not copied it yet)")
        if not jdir:
            js = [p.parent for p in self.root.rglob("*.jsonl") if p.parent.name == "journal"]
            jdir = js[0] if js else None
        if jdir:
            self.load_journal(jdir)
        else:
            self.notes.append("no journal found: no model exchanges")
        mlog = Path(a.mind_log) if a.mind_log else self.find("mind.log", "session/run/mind.log", "run/mind.log")
        if mlog:
            self.load_mind_log(mlog)
        if self.t0_ms is None:
            cr = self.find("session/run/created_utc", "run/created_utc", "created_utc")
            if cr:
                try:
                    self.t0_ms = int(dt.datetime.fromisoformat(cr.read_text().strip().replace("Z", "+00:00")).timestamp() * 1000)
                except ValueError:
                    pass

    def load_trial_files(self):
        r = self.root
        if self.t0_ms is None and (r / "chronicle.jsonl").exists():
            # Trial start from the chronicle: t (when the runner saw a row) is at or after at_ms.
            rows = [x for x in jl(r / "chronicle.jsonl") if x.get("t") is not None and x.get("at_ms")]
            if rows:
                self.t0_ms = int(max(x["at_ms"] - x["t"] * 1000 for x in rows))
        for x in jl(r / "census.jsonl"):
            self.census_rows.append(x)
            for p in x.get("people", []):
                self.learn_name(p["id"], p["name"], p.get("kind"))
                if not p.get("alive", True) and p.get("died_ms"):
                    self.died.setdefault(p["id"], (p["died_ms"], p.get("cause") or ""))
        if self.census_rows:
            self.sources.append(self.src(r / "census.jsonl"))
        for fn in ("chronicle.jsonl", "speech.jsonl"):
            rows = jl(r / fn)
            if rows:
                self.sources.append(self.src(r / fn))
            for x in rows:
                self.add_chronicle(x, self.src(r / fn, x["_line"]))
        rows = jl(r / "experiences.jsonl")
        if rows:
            self.sources.append(self.src(r / "experiences.jsonl"))
        for x in rows:
            self.add_exp(x, self.src(r / "experiences.jsonl", x["_line"]))
        rows = jl(r / "audience.jsonl")
        if rows:
            self.sources.append(self.src(r / "audience.jsonl"))
        for x in rows:
            x["_src"] = self.src(r / "audience.jsonl", x["_line"])
            self.audience.append(x)
        # The subject's samples and graphs.
        subj = None
        st = r / "state.json"
        if st.exists():
            subj = json.loads(st.read_text()).get("subject")
        if subj:
            prev = None
            for x in jl(r / "samples.jsonl"):
                ms = self.t_ms(x.get("t"))
                act = x.get("activity")
                label = act[1] if isinstance(act, list) and len(act) > 1 else (act[0] if act else "idle")
                key = (label, x.get("plan"))
                if ms and x.get("pos"):
                    self.track[subj].append((ms, x["pos"][0], x["pos"][1], self.src(r / "samples.jsonl", x["_line"])))
                if ms and key != prev:
                    pos = x.get("pos") or [None, None]
                    self.body[subj].append([ms, f"doing {label} (plan: {x.get('plan')}) at ({pos[0]}, {pos[1]}); hp {x.get('hp')}, hunger {x.get('hunger')}",
                                            self.src(r / "samples.jsonl", x["_line"])])
                    prev = key
            for x in jl(r / "graphs.jsonl"):
                ms = x.get("installed_ms") or self.t_ms(x.get("t"))
                self.graphs[x.get("id", subj)].append([ms, f"brain revision {x.get('revision')} from {x.get('source')}: {x.get('plan')}",
                                                       self.src(r / "graphs.jsonl", x["_line"]), x.get("graph")])
            for x in jl(r / "mind_rows.jsonl"):
                if x.get("table") == "relation":
                    ms = self.t_ms(x.get("t"))
                    for rr in x.get("rows", []):
                        self.relations[(rr["actor"], rr["other"])].append((rr.get("updated_ms") or ms, rr.get("label"), rr.get("trust"), rr.get("affinity"), self.src(r / "mind_rows.jsonl", x["_line"])))
        for x in jl(r / "thoughts.jsonl"):
            if x.get("kind") in ("error", "act", "instinct", "internalize"):
                self.graphs[x["actor"]].append([x["at_ms"], f"thought {x['kind']}: {x.get('summary')}", self.src(r / "thoughts.jsonl", x["_line"]), None])
        hum = jl(r / "human.jsonl")
        if hum and subj:
            self.players.add(subj)
            for x in hum:
                ms = self.t_ms(x.get("t"))
                if ms:
                    args = ", ".join(str(v) for v in x.get("args", []))
                    self.body[subj].append([ms, f"player calls {x['call']}({args[:200]}) → {x.get('status')} {x.get('error') or ''}".strip(),
                                            self.src(r / "human.jsonl", x["_line"])])
                    if x["call"] == "human_say":
                        self.human_calls.append((ms, x))
        for x in jl(r / "events.jsonl"):
            hl = x.get("human_line")
            if hl and subj:
                for d, i, nm in hl.get("near", []):
                    self.learn_name(i, nm)
                self.body[subj].append([hl.get("at_ms") or self.t_ms(x.get("t")),
                                        f"script line ({hl.get('kind')}): “{hl.get('text')}” to #{hl.get('to')}; near: " +
                                        ", ".join(f"{nm} {d} m" for d, i, nm in hl.get("near", [])[:6]),
                                        self.src(r / "events.jsonl", x["_line"])])
        # Census activity per person (every ~30 s).
        last = {}
        for x in self.census_rows:
            for p in x.get("people", []):
                act = p.get("activity")
                label = act[0] if act else "idle"
                if p.get("pos"):
                    self.track[p["id"]].append((x["now_ms"], p["pos"][0], p["pos"][1], self.src(r / "census.jsonl", x["_line"])))
                if last.get(p["id"]) != label:
                    last[p["id"]] = label
                    pos = p.get("pos") or [None, None]
                    self.body[p["id"]].append([x["now_ms"], f"census: {label} at ({pos[0]}, {pos[1]}), hunger {p.get('hunger')}", self.src(r / "census.jsonl", x["_line"])])

    def load_final(self, p):
        f = json.loads(p.read_text())
        for x in f.get("character", []) or []:
            if isinstance(x, dict):
                self.learn_name(x.get("id"), x.get("name"), x.get("kind"))
        for k, rows in f.items():
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                continue
            kind = table_kind(rows[0].keys())
            if kind in ("chronicle", "experience", "relation", "brain"):
                self.ingest(kind, rows, f"{self.src(p)}#{k}")

    def load_rows_path(self, p, quiet=False):
        if p.is_dir():
            for q in sorted(p.iterdir()):
                if q.suffix in (".txt", ".json"):
                    self.load_rows_path(q, quiet)
            return
        rows = None
        if p.suffix == ".txt":
            rows = sql_text_table(p)
        elif p.suffix == ".json":
            try:
                v = json.loads(p.read_text())
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rows = v
            except (ValueError, OSError, UnicodeDecodeError):
                rows = None
        if not rows:
            if not quiet:
                self.notes.append(f"{p}: no rows read")
            return
        kind = table_kind(rows[0].keys())
        if not kind:
            return
        self.ingest(kind, rows, self.src(p))
        self.sources.append(f"{self.src(p)} ({kind}, {len(rows)} rows)")

    def ingest(self, kind, rows, src):
        for n, x in enumerate(rows, 1):
            s = f"{src}:{x.get('_line', n)}" if "#" not in src else f"{src}[{n - 1}]"
            if kind == "chronicle":
                self.add_chronicle(x, s)
            elif kind == "experience":
                self.add_exp(x, s)
            elif kind == "character":
                self.learn_name(x.get("id"), x.get("name"), x.get("kind"))
                if x.get("alive") is False and x.get("died_ms"):
                    self.died.setdefault(x["id"], (x["died_ms"], x.get("cause") or ""))
            elif kind == "presence":
                self.players.add(x["id"])
                if x.get("control_ms") and x.get("ai"):
                    self.takeover[x["id"]] = x["control_ms"]
                if x.get("changed_ms"):
                    self.body[x["id"]].append([x["changed_ms"], f"presence: {'connected' if x.get('present') else 'left the game'}", s])
                if x.get("control_ms") and x.get("ai"):
                    self.body[x["id"]].append([x["control_ms"], "taken over by the AI (offline takeover): later rows are the mind's", s])
            elif kind == "relation":
                self.relations[(x["actor"], x["other"])].append((x.get("updated_ms") or 0, x.get("label"), x.get("trust"), x.get("affinity"), s))
            elif kind == "audience":
                x["_src"] = s
                self.audience.append(x)
            elif kind == "brain":
                self.graphs[x["id"]].append([x.get("installed_ms") or 0, f"brain revision {x.get('revision')} from {x.get('source')}: {x.get('plan')}", s, x.get("graph")])

    def add_chronicle(self, x, src):
        text, reps = strip_reps(x.get("text", ""))
        old = self.chron.get(x.get("id"))
        if old is not None:
            # The authority merges a repeat into the row: a later copy (final.json) has the
            # latest repeat's time and the count.
            _, old_reps = strip_reps(old.get("text", ""))
            if x.get("kind") == "speech" and reps > old_reps and x.get("at_ms") != old.get("at_ms"):
                m = re.match(r"^(.*?)(?: to (.*?))?: “(.*)”$", text, re.S)
                if m:
                    self.cands.append(dict(ms=x["at_ms"], exact=True, speaker=x.get("a", 0), to=x.get("b", 0), text=m.group(3), src=src, reps=reps, via="chronicle (latest repeat)"))
                self.chron[x["id"]] = x
            return
        self.chron[x["id"]] = x
        a, b, kind = x.get("a", 0), x.get("b", 0), x.get("kind")
        if kind == "arrival":
            m = re.match(r"^(.*) arrived$", text)
            if m:
                self.learn_name(a, m.group(1))
        m = re.match(r"^(\S+(?: \S+)?) and (\S+(?: \S+)?) are expecting", text)
        if m and a and b:
            self.learn_name(a, m.group(1))
            self.learn_name(b, m.group(2))
        if kind == "speech":
            m = re.match(r"^(.*?)(?: to (.*?))?: “(.*)”$", text, re.S)
            if m:
                self.learn_name(a, m.group(1))
                if b and m.group(2):
                    self.learn_name(b, m.group(2))
                # A merged repeat moved at_ms to the latest repeat: the first one is earlier.
                self.cands.append(dict(ms=x["at_ms"], exact=True, speaker=a, to=b, text=m.group(3), src=src, reps=reps, via="chronicle"))
                if x.get("x") is not None and reps == 1:
                    # A merged repeat keeps its first position but the latest time.
                    self.track[a].append((x["at_ms"], x["x"], x["y"], src))
            return
        if kind == "death" and a:
            m = re.search(r"died \((.*)\)$", text)
            self.died.setdefault(a, (x["at_ms"], m.group(1) if m else text))
        for i in {a, b} - {0}:
            self.body[i].append([x["at_ms"], f"chronicle {kind}: {x.get('text')}", src])
        if a and x.get("x") is not None and kind not in ("time", "family") and reps == 1:
            # Attack, killing and death rows hold the victim's position (act.rs).
            who = b if kind in ("attack", "killing", "threat") and b else a
            self.track[who].append((x["at_ms"], x["x"], x["y"], src))

    def add_exp(self, x, src):
        obs = x.get("observer")
        if obs is None:
            return
        key = ("id", x["id"]) if x.get("id") is not None else ("t", x.get("at_ms"), x.get("text"))
        if key in self.exps[obs]:
            return
        row = dict(ms=x.get("at_ms"), kind=x.get("kind"), subject=x.get("subject", 0), object=x.get("object", 0),
                   text=x.get("text", ""), sal=x.get("salience"), id=x.get("id"), src=src, exact=True)
        self.exps[obs][key] = row
        if row["kind"] == "speech" and row["subject"]:
            self.cands.append(dict(ms=row["ms"], exact=True, speaker=row["subject"], to=row["object"], text=quoted(row["text"]),
                                   src=src, hearer=obs, sal=row["sal"], via="experience", eid=row["id"]))
        if row["kind"] in ("said", "speech") and x.get("x") is not None and row["ms"]:
            self.track[obs if row["kind"] == "said" else row["subject"]].append((row["ms"], x["x"], x["y"], src))
        if row["kind"] == "said":
            self.cands.append(dict(ms=row["ms"], exact=True, speaker=obs, to=row["object"], text=quoted(row["text"]), src=src, via="said"))
        if row["subject"] and row["subject"] != obs and row["kind"] not in ("speech",):
            # Someone else saw this body do something.
            self.body[row["subject"]].append([row["ms"], f"seen by {{{obs}}}: {row['text']}", src])

    # --- journal
    def load_journal(self, jdir):
        jdir = Path(jdir)
        self.sources.append(f"{jdir} (journal)")
        files = sorted(p for p in jdir.glob("*.jsonl"))
        if self.args.who and not any(w.strip().lstrip("#").isdigit() for w in self.args.who.split(",")):
            # Only the chosen residents' exchanges are kept: skip the other files (by name).
            want = {re.sub(r"[^A-Za-z0-9]", "_", w.strip()) for w in self.args.who.split(",")}
            skipped = [p for p in files if p.stem not in want]
            files = [p for p in files if p.stem in want]
            self.notes.append(f"--who: read {len(files)} of {len(files) + len(skipped)} journal files; other hearers' fates use no model exchanges")
        size = sum(p.stat().st_size for p in files)
        if size > 150e6:
            print(f"note: {size / 1e6:.0f} MB of journal; narrow it with --who NAMES for a quicker, smaller page", file=sys.stderr)
        for p in files:
            for e in jl(p):
                journal_io.restore(e, jdir)
                self.add_call(e, p, jdir)
        for p in sorted(jdir.glob("system/*.txt")):
            self.systems.setdefault(f"system/{p.name}", p.read_text(encoding="utf-8", errors="replace"))

    def add_call(self, e, p, jdir):
        req = e.get("request") or {}
        msgs = req.get("messages") or []
        sys_ref, user_parts = None, []
        for m in msgs:
            if m.get("role") == "system":
                sys_ref = m.get("content_ref")
                if not sys_ref and m.get("content"):
                    sys_ref = f"inline:{hash(m['content']) & 0xffffffff:x}"
                    self.systems.setdefault(sys_ref, m["content"])
            else:
                user_parts.append((m.get("role"), m.get("content") or ""))
        user = "\n\n".join(c for r, c in user_parts if r == "user")
        first_user = next((c for r, c in user_parts if r == "user"), "")
        sections = split_sections(first_user)
        extra = [[f"({r} message {k + 1})", c] for k, (r, c) in enumerate(user_parts) if c is not first_user]
        reply_s = e.get("reply") or ""
        reply = parse_reply(reply_s)
        end = e.get("at_ms") or 0
        lat = e.get("latency_ms") or 0
        qw = e.get("queue_wait_ms") or 0
        actor = e.get("actor") or p.stem.replace("_", " ")
        c = dict(i=len(self.calls), actor_name=actor, purpose=e.get("purpose"), end=end, start=end - lat, queued=end - lat - qw,
                 lat=lat, qw=qw, model=e.get("model"), profile=e.get("profile"), lane=e.get("lane"), attention=e.get("attention"),
                 effort=e.get("effort"), tokens=e.get("tokens"), ptok=e.get("prompt_tokens"), ctok=e.get("completion_tokens"),
                 cached=e.get("cached_tokens"), error=e.get("error"), finish=e.get("finish_reason"), mode=e.get("mode"),
                 src=f"{self.src(p)}:{e['_line']}" if self.src(p) != str(p) else f"{p}:{e['_line']}",
                 sys=sys_ref, sections=sections + extra, reply=reply_s, reply_obj=reply)
        who = re.search(r"^# Who you are \((.+?)\)", first_user, re.M)
        c["who_name"] = who.group(1) if who else None
        sec = dict((h.split(" (")[0].strip(), b) for h, b in sections)
        c["why"] = re.split(r"\n\s*\n", (sec.get("Why you are thinking now") or "").strip())[0].strip()
        ans = re.search(r"^# What you are answering\n(.+?): “(.*)”\s*\Z", first_user, re.M | re.S)
        c["answering"] = [ans.group(1), ans.group(2)] if ans else None
        c["body_feel"] = (re.search(r"^How your body feels: (.*)$", first_user, re.M) or [None, None])[1]
        now = re.search(r"^(?:Now )?day (\d+) (\d\d):(\d\d)", first_user, re.M)
        c["game_now"] = [int(now.group(1)), int(now.group(2)), int(now.group(3))] if now else None
        # Temperament as the mind reads it for talk (persona traits and mood).
        c["temper"] = None
        tr = re.search(r"^Traits: (\{.*\})$", first_user, re.M)
        mood = re.search(r"^Mood: (.*)$", first_user, re.M)
        if tr:
            try:
                soc = float(json.loads(tr.group(1)).get("sociability", 50))
                c["temper"] = (max(0.0, min(100.0, soc)), mood.group(1) if mood else "")
            except (ValueError, AttributeError):
                pass
        tt = re.search(r"^sociability (\d+)/100 .*?; mood: (.*)$", first_user, re.M)
        if tt and not c["temper"]:
            c["temper"] = (float(tt.group(1)), tt.group(2))
        # Percepts, people and the scene, as the request shows them.
        c["percepts"] = parse_percepts(first_user)
        c["people"] = parse_people(first_user)
        c["scene"] = None
        scene = sec.get("What you perceive right now")
        if scene:
            try:
                c["scene"] = json.loads(scene.strip().splitlines()[0])
            except (ValueError, IndexError):
                pass
            you = (c["scene"] or {}).get("you")
            if isinstance(you, dict) and you.get("id") and you.get("name"):
                self.learn_name(you["id"], you["name"], you.get("kind"))
            for cr in (c["scene"] or {}).get("creatures", []):
                if cr.get("name"):
                    self.learn_name(cr.get("id"), cr["name"], cr.get("kind"))
        # What the reply says and installs.
        say = None
        if isinstance(reply, dict):
            s = reply.get("say")
            if isinstance(s, dict):
                say = [str(s.get("text") or ""), to_id(s.get("to"))]
            elif isinstance(s, str) and s:
                say = [s, to_id(reply.get("to"))]
        c["say"] = say
        self.calls.append(c)

    # --- mind.log
    def load_mind_log(self, p):
        self.sources.append(f"{self.src(p)} (mind log)")
        self._mind_log = []
        for n, line in enumerate(Path(p).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = re.match(r"^\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (\w+)\s+([\w:]+)\] (.*)$", line)
            if not m:
                continue
            ms = int(dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp() * 1000)
            nm = re.match(r"^(.+?) (?:the (\w+) )?\(#(\d+)\)", m.group(4))
            if nm:
                self.learn_name(int(nm.group(3)), nm.group(1), nm.group(2))
            self._mind_log.append((ms, m.group(2), m.group(3), m.group(4), f"{self.src(p)}:{n}"))

    # --- after loading: resolve names and build the joined views
    def resolve(self):
        a = self.args
        # Journal actors -> ids.
        # Names from "{Name=#id}" annotations and people lists.
        for c in self.calls:
            for p in c["people"]:
                if p["name"] and not p["name"].startswith("a "):
                    self.learn_name(p["id"], p["name"])
            for pc in c["percepts"]:
                for nm, i in pc["ann"]:
                    if nm not in ("someone",):
                        self.learn_name(i, nm)
        by_name = {}
        for i, nm in self.names.items():
            by_name.setdefault(nm, i)
        self.by_name = by_name
        for c in self.calls:
            nm = c["who_name"] or c["actor_name"]
            i = by_name.get(c["actor_name"]) or by_name.get(nm)
            if i is None:
                i = by_name.get(c["actor_name"].replace("_", " "))
            if i is None:
                fake = -(len(self.names) + 1000)
                self.names[fake] = c["actor_name"]
                by_name[c["actor_name"]] = fake
                i = fake
            c["actor"] = i
        if a.player:
            for nm in a.player.split(","):
                i = by_name.get(nm.strip()) or (int(nm.strip("#")) if nm.strip("#").isdigit() else None)
                if i:
                    self.players.add(i)
        self.fit_clock()
        # Percept lines from requests -> experience rows (approximate time: one game minute).
        # Lines with an experience id first; then id-less lines that no row already covers
        # (the same text within a game minute).
        mpm = self.clock["mpm"] if self.clock else 500
        seen = defaultdict(lambda: defaultdict(list))   # observer -> text -> [ms]
        for obs, rows in self.exps.items():
            for r in rows.values():
                if r["ms"] is not None:
                    seen[obs][r["text"]].append(r["ms"])
        for with_id in (True, False):
            for c in self.calls:
                obs = c["actor"]
                for pc in c["percepts"]:
                    if pc["gm"] is None or (pc["id"] is not None) != with_id:
                        continue
                    key = ("id", pc["id"]) if with_id else ("g", pc["gm"], pc["text"])
                    if key in self.exps[obs]:
                        continue
                    ms = self.game_to_ms(pc["gm"])
                    if ms is None or any(abs(m - ms) <= 1.5 * mpm for m in seen[obs].get(pc["text"], [])):
                        continue
                    seen[obs][pc["text"]].append(ms)
                    ann = pc["ann"]
                    row = dict(ms=ms, kind="(from request)", subject=ann[0][1] if ann else 0, object=ann[1][1] if len(ann) > 1 else 0,
                               text=pc["text"], sal=None, id=pc["id"], src=c["src"], exact=False, call=c["i"])
                    self.exps[obs][key] = row
                    sp = re.match(r"^(.*?) said(?: to (.*?))?: “(.*)”$", pc["text"], re.S)
                    if sp and not pc["text"].startswith("You said"):
                        label, tolabel, words = sp.groups()
                        # Annotations are [subject, object], without the observer (mind.rs exp_line).
                        speaker = self.by_name.get(label) or (ann[0][1] if ann else 0)
                        to = obs if tolabel == "you" else ((self.by_name.get(tolabel) or (ann[1][1] if len(ann) > 1 else 0)) if tolabel else 0)
                        if speaker and speaker != obs:
                            self.cands.append(dict(ms=ms, exact=False, speaker=speaker, to=to or 0, text=words, src=c["src"], hearer=obs,
                                                   sal=0.9 if tolabel == "you" else None, via="request", eid=pc["id"]))
        # mind.log lines -> events, speech candidates.
        names_re = "|".join(re.escape(n) for n in sorted(by_name, key=len, reverse=True) if n) or "$^"
        N = rf"((?:{names_re})|#\d+)(?: \(#\d+\))?"
        pats = [
            ("said", re.compile(rf"^{N} to {N}: “(.*)”(?: \((?:settled: (.*)|ends)\))?$", re.S)),
            ("silent", re.compile(rf"^{N} says nothing to {N}$")),
            ("settled", re.compile(rf"^{N} hears {N} but they settled(?: “(.*)”)? — no turn$")),
            ("reopen", re.compile(rf"^{N} and {N}: settled exchange reopens \((.*)\)$")),
            ("earshot", re.compile(rf"^{N} and {N}: out of earshot, conversation over$")),
            ("parked", re.compile(rf"^{N} is deliberating; the line from {N} (waits for it to end|gets its turn alongside)$")),
            ("unpark", re.compile(rf"^{N}'s deliberation ended: the line from {N} gets its turn$")),
            ("unpark", re.compile(rf"^{N}'s deliberation has decided, and not to speak to {N}: the line gets its turn now$")),
            ("answered", re.compile(rf"^{N} answered {N} in its deliberation$")),
            ("dropped", re.compile(rf"^{N} already answered {N} in conversation while deliberating: (.*)$")),
            ("dropped", re.compile(rf"^{N}'s deliberation spoke to {N} first: (.*)$")),
            ("drawn", re.compile(rf"^{N} is drawn in by {N}'s remark \((\w+)\)$")),
            ("faced", re.compile(rf"^{N} is faced by {N} and takes the remark as addressed$")),
            ("enough", re.compile(rf"^{N} has said enough to {N} for now$")),
            ("pass", re.compile(rf"^{N} lets {N}'s remark pass$")),
            ("turn", re.compile(rf"^{N} gets a reply turn for {N}$")),
        ]
        one = re.compile(rf"^{N}\b")
        for ms, level, target, text, src in getattr(self, "_mind_log", []):
            kind, pair = "log", None
            for k, rx in pats:
                m = rx.match(text)
                if m:
                    kind = k
                    pair = [self.id_of(m.group(1)), self.id_of(m.group(2))]
                    if k == "said" and pair[0] and pair[1] is not None:
                        self.cands.append(dict(ms=ms, exact=False, speaker=pair[0], to=pair[1] or 0, text=m.group(3), src=src, via="log", tol=2500))
                    break
            ids = set(x for x in (pair or []) if x)
            if not ids:
                m = one.match(text)
                if m and self.id_of(m.group(1)):
                    ids.add(self.id_of(m.group(1)))
                if "deliberation for " in text:
                    m = re.search(rf"deliberation for {N}", text)
                    if m and self.id_of(m.group(1)):
                        ids.add(self.id_of(m.group(1)))
            if level in ("WARN", "ERROR") or ids:
                self.logs.append([ms, f"{level} {text}", sorted(ids), src, kind, pair])
        # Where each mind's body stood, and how it was, when its request was built (the scene's
        # `you`).
        last, prev_scene = {}, {}
        for c in sorted(self.calls, key=lambda c: c["queued"]):
            # A deliberation's compile step reuses its think step's scene: date it there.
            c["scene_ms"] = c["queued"]
            if c["scene"]:
                p = prev_scene.get(c["actor"])
                if c["purpose"] == "deliberate" and p and p["scene"] == c["scene"]:
                    c["scene_ms"] = p["scene_ms"]
                prev_scene[c["actor"]] = c
            you = (c["scene"] or {}).get("you") if isinstance(c["scene"], dict) else None
            if not isinstance(you, dict) or not you.get("at"):
                continue
            x, y = you["at"][:2]
            if c["scene_ms"] != c["queued"]:
                continue
            self.track[c["actor"]].append((c["queued"], x, y, c["src"]))
            doing = you.get("doing") or ("decided, not yet done: " + ", ".join(you["decided, not yet done"]) if you.get("decided, not yet done") else "-")
            q = last.get(c["actor"])
            if q is None or (q[0] - x) ** 2 + (q[1] - y) ** 2 > 2.0 ** 2 or q[2] != doing or q[3] != you.get("health"):
                last[c["actor"]] = (x, y, doing, you.get("health"))
                self.body[c["actor"]].append([c["queued"], f"at ({x}, {y}), doing {doing}; health {you.get('health')}, hunger {you.get('hunger')}, energy {you.get('energy')} (the scene of its {c['purpose']}, taken at or before it was queued)", c["src"]])
        for k in self.track:
            self.track[k].sort()
        # Deliberation replies -> graphs.
        logs_sorted = sorted(self.logs, key=lambda x: x[0])
        log_ms = [x[0] for x in logs_sorted]
        for c in self.calls:
            r = c["reply_obj"]
            if c["purpose"] == "deliberate" and isinstance(r, dict):
                g = r.get("graph")
                intent = r.get("intent") if isinstance(r.get("intent"), dict) else None
                patch = r.get("patch") if isinstance(r.get("patch"), dict) else None
                parts = []
                if r.get("plan"):
                    parts.append(f"plan: {r['plan']}")
                if r.get("acts"):
                    parts.append("acts: " + "; ".join(act_text(x) for x in r["acts"]))
                if intent:
                    parts.append(f"intent weight {intent.get('weight')}")
                if g == "keep":
                    parts.append("graph: keep")
                elif patch:
                    parts.append(f"patch {patch.get('label')}")
                shown = intent.get("graph") if intent else (patch.get("graph") if patch else (g if isinstance(g, dict) else None))
                # What became of it, by the mind log's lines about this actor just after the reply.
                k = bisect.bisect_left(log_ms, c["end"] - 1000)
                outcome = "deliberation replied (no mind-log line about its outcome)"
                for x in logs_sorted[k:]:
                    if x[0] > c["end"] + 4000:
                        break
                    if c["actor"] not in x[2]:
                        continue
                    t = x[1]
                    if "failed" in t and x[1].startswith(("WARN", "ERROR")):
                        outcome = f"deliberation failed: {t[5:].split(': ', 1)[-1][:120]} ({x[3]})"
                        break
                    if "carries on" in t:
                        outcome = f"deliberation carries on: no new graph ({x[3]})"
                    elif "reworks routines" in t or "decided:" in t:
                        outcome = f"deliberation installs ({x[3]})"
                        break
                c["outcome"] = outcome.split(" (")[0].replace("deliberation ", "")
                self.graphs[c["actor"]].append([c["end"], outcome + " — " + "; ".join(parts), c["src"], json.dumps(shown) if shown else None, c["i"]])
            elif c["purpose"] == "deliberate" and c["reply"]:
                self.graphs[c["actor"]].append([c["end"], f"deliberation reply not readable as JSON here (finish: {c['finish']}); see the mind log for what was installed", c["src"], None, c["i"]])
        self.build_lines()

    def id_of(self, label):
        if label is None:
            return None
        if label.startswith("#") and label[1:].isdigit():
            return int(label[1:])
        return self.by_name.get(label)

    def label_to_id(self, label, ann):
        if not label:
            return 0
        if label in self.by_name:
            return self.by_name[label]
        for nm, i in ann:
            if nm == label or nm == "someone":
                return i
        return ann[0][1] if ann else 0

    # --- the game clock: total game minutes <-> epoch ms
    def fit_clock(self):
        pairs = []
        for c in self.calls:
            # A deliberation's compile step reuses its think step's context ("Now"), built
            # earlier, so only think and talk requests anchor the clock.
            if c["game_now"] and c["purpose"] in ("think", "talk"):
                d, h, mi = c["game_now"]
                gm = (d - 1) * 1440 + h * 60 + mi + 0.5
                pairs.append((c["queued"], gm))
        id_ms = {}
        for obs, rows in self.exps.items():
            for k, r in rows.items():
                if r.get("id") is not None and r.get("exact"):
                    id_ms[r["id"]] = r["ms"]
        for c in self.calls:
            for pc in c["percepts"]:
                if pc["id"] is not None and pc["id"] in id_ms and pc["gm"] is not None:
                    pairs.append((id_ms[pc["id"]], pc["gm"] + 0.5))
        day_ms = self.day_ms or DEFAULT_DAY_MS
        if self.census_rows:
            hs = [(x["now_ms"], x["hour"]) for x in self.census_rows if x.get("hour") is not None]
            if len(hs) >= 2 and hs[-1][0] > hs[0][0] and hs[-1][1] > hs[0][1]:
                day_ms = int((hs[-1][0] - hs[0][0]) / ((hs[-1][1] - hs[0][1]) / 24))
        mpm = day_ms / 1440
        if not pairs:
            self.clock = None
            self.notes.append("no game-clock anchors: percept lines from requests are not placed in time")
            return
        offs = [ms - gm * mpm for ms, gm in pairs]
        a0 = statistics.median(offs)
        resid = statistics.median([abs(o - a0) for o in offs])
        self.clock = dict(a=a0, mpm=mpm, n=len(pairs), resid_ms=round(resid), day_ms=day_ms)

    def game_to_ms(self, gm):
        if not self.clock:
            return None
        return int(self.clock["a"] + (gm + 0.5) * self.clock["mpm"])

    # --- lines and their fates
    def build_lines(self):
        cands = sorted((c for c in self.cands if c.get("ms") and c.get("speaker") and c.get("text") is not None), key=lambda c: c["ms"])
        clusters = defaultdict(list)    # (speaker, text) -> [cluster]
        for c in cands:
            k = (c["speaker"], norm(c["text"]))
            tol = c.get("tol") or (1500 if c["exact"] else 2500)
            hit = None
            for cl in clusters[k]:
                lim = 50 if (c["exact"] and cl["exact"]) else max(tol, cl.get("tol", 0))
                if abs(c["ms"] - cl["ms"]) <= lim:
                    hit = cl
                    break
            if hit is None:
                hit = dict(ms=c["ms"], exact=c["exact"], speaker=c["speaker"], to=c.get("to") or 0, text=c["text"], srcs=[], hearers={},
                           reps=1, tol=tol)
                clusters[k].append(hit)
            if c["exact"] and not hit["exact"]:
                hit["ms"], hit["exact"], hit["tol"] = c["ms"], True, 50
            if c.get("to") and not hit["to"]:
                hit["to"] = c["to"]
            if c.get("reps", 1) > 1:
                # The chronicle keeps one row for a line repeated within 2 minutes: (×n) counts
                # them all, and the row's time is the latest repeat's.
                hit["reps"] = max(hit["reps"], c["reps"])
            hit["srcs"].append(f"{c['via']}: {c['src']}")
            if c.get("eid") is not None:
                hit.setdefault("eids", set()).add(c["eid"])
            if c.get("hearer") and c["hearer"] != c["speaker"]:
                h = hit["hearers"].setdefault(c["hearer"], dict(id=c["hearer"], srcs=[], sal=None, d=None))
                h["srcs"].append(f"{c['via']}: {c['src']}")
                if c.get("sal") is not None and (c["via"] == "experience" or h["sal"] is None):
                    h["sal"] = c["sal"]
        lines = sorted((cl for cls in clusters.values() for cl in cls), key=lambda l: l["ms"])
        for i, l in enumerate(lines):
            l["i"] = i
        self.lines = lines
        self.calls_by_actor = defaultdict(list)
        for c in self.calls:
            self.calls_by_actor[c["actor"]].append(c)
        for v in self.calls_by_actor.values():
            v.sort(key=lambda c: c["queued"])
        self.logs.sort(key=lambda x: x[0])
        self.log_ms = [x[0] for x in self.logs]
        # Audience rows: exact time, hearers and distances.
        by_speaker = defaultdict(list)
        for l in lines:
            by_speaker[l["speaker"]].append(l)
        for a in self.audience:
            for l in by_speaker.get(a["speaker"], []):
                if abs(l["ms"] - a["at_ms"]) <= (50 if l["exact"] else 2500) and (not l["to"] or not a.get("to") or l["to"] == a.get("to")):
                    l["audience"] = True
                    l["ms"], l["exact"] = a["at_ms"], True
                    hs = a["hearers"]
                    if isinstance(hs, str):
                        try:
                            hs = json.loads(hs.replace("(", "[").replace(")", "]"))
                        except ValueError:
                            hs = []
                    for hh in hs:
                        hid, d, off = (list(hh) + [None, None, None])[:3] if isinstance(hh, (list, tuple)) else (hh.get("id"), hh.get("d"), hh.get("off"))
                        h = l["hearers"].setdefault(hid, dict(id=hid, srcs=[], sal=None, d=None))
                        h["d"], h["off"] = (round(d, 1) if d is not None else None), (round(off, 2) if off is not None else None)
                        h["d_dt"] = 0
                        h["srcs"].append(f"audience: {a['_src']}")
                    break
        # Who it was said to: heard, or shown not to have heard (audience, silence, earshot).
        for l in lines:
            to = l["to"]
            if not to or to in l["hearers"]:
                continue
            if l.get("audience"):
                l["unheard"] = "not among the hearers of the line's audience row: out of earshot"
                continue
            sil = self.silence_for(l)
            if sil:
                l["unheard"] = sil
                continue
            cov = self.consolidation_skips(l, to)
            if cov:
                l["unheard"] = cov
                continue
            l["hearers"][to] = dict(id=to, srcs=["(said to them; no row shows the hearing)"], sal=None, d=None, assumed=True)
        # Distances from requests' scenes when the audience did not give them: the hearer's
        # scene nearest in time that shows the speaker (a scene is taken at or before its
        # request is queued).
        for l in lines:
            for h in l["hearers"].values():
                if h["d"] is None:
                    sees = lambda c, sp=l["speaker"]: c["scene"] and any(cr.get("id") == sp for cr in c["scene"].get("creatures", []))
                    c = self.nearest_call(h["id"], l["ms"], sees, within=15_000)
                    if c:
                        cr = next(cr for cr in c["scene"]["creatures"] if cr.get("id") == l["speaker"])
                        h["d"] = cr.get("dist")
                        h["d_dt"] = c["scene_ms"] - l["ms"]
                        h["d_note"] = f"from the scene of their {c['purpose']} queued {fmt_dt(c['scene_ms'] - l['ms'])} from the line (the scene may be older) ({c['src']})"
        # Everyone whose position is known near the line, by distance from the speaker.
        for l in lines:
            sp = self.pos_at(l["speaker"], l["ms"], 3000)
            l["near"] = []
            if not sp:
                continue
            for i in self.track:
                if i == l["speaker"]:
                    continue
                q = self.pos_at(i, l["ms"], 15_000)
                if q:
                    d = ((q[1] - sp[1]) ** 2 + (q[2] - sp[2]) ** 2) ** 0.5
                    if d <= 15:
                        l["near"].append(dict(id=i, d=round(d, 1), dt=q[0] - l["ms"], src=q[3]))
            l["near"].sort(key=lambda x: x["d"])
            for x in l["near"]:
                h = l["hearers"].get(x["id"])
                if h and h["d"] is None:
                    h["d"], h["d_dt"] = x["d"], x["dt"]
                    h["d_note"] = f"estimated from positions: theirs {fmt_dt(x['dt'])} from the line ({x['src']}), the speaker's at the line"
        # Each talk call answers the latest line before it with the words it answers.
        self.turn_of = {}
        by_text = defaultdict(list)
        for l in lines:
            by_text[norm(l["text"])].append(l)
        for c in self.calls:
            if c["purpose"] == "talk" and c["answering"]:
                cand = [l for l in by_text.get(norm(c["answering"][1]), []) if l["ms"] <= c["queued"] + 1500 and c["queued"] - l["ms"] <= 180_000 and l["speaker"] != c["actor"]]
                if cand:
                    self.turn_of[(cand[-1]["i"], c["actor"])] = c
        for l in lines:
            self.fates(l)

    def consolidation_skips(self, l, who):
        """A later consolidation of `who` whose experience ids span the line's other hearers'
        rows but does not list the line: they did not hear it (the authority writes every
        hearer's row in the same reducer, so the ids are adjacent)."""
        eids = l.get("eids") or set()
        if not eids:
            return None
        lo, hi = min(eids), max(eids)
        words = norm(l["text"])
        for c in self.calls_by_actor.get(who, []):
            if c["purpose"] != "consolidate" or c["queued"] < l["ms"] or c["queued"] > l["ms"] + 600_000:
                continue
            ids = [pc["id"] for pc in c["percepts"] if pc["id"] is not None]
            if ids and min(ids) < lo and max(ids) > hi and not any(words in norm(pc["text"]) for pc in c["percepts"]):
                return f"their consolidation of experiences {min(ids)}–{max(ids)} ({c['src']}) does not list it, though the other hearers' rows for it are {lo}–{hi}"
        return None

    def silence_for(self, l):
        """Evidence that the one a line was said to did not hear it: the speaker's `silence`
        percept ("… could not have heard you", or before `speech_truth` "No answer from …"), or the mind's 'out of earshot' for the pair, at the line."""
        sp, to, ms = l["speaker"], l["to"], l["ms"]
        for r in self.exps.get(sp, {}).values():
            if r["ms"] is not None and UNHEARD.search(r["text"]) and abs(r["ms"] - ms) <= (1500 if r["exact"] else 2500) \
                    and (r.get("subject") == to or not r.get("subject")):
                return f"the speaker perceived “{r['text']}” ({r['src']})"
        i = bisect.bisect_left(self.log_ms, ms - 1000)
        for x in self.logs[i:]:
            if x[0] > ms + 3000:
                break
            if x[4] == "earshot" and x[5] and set(x[5]) == {sp, to}:
                return f"the mind ended their exchange at the line: out of earshot ({x[3]})"
        return None

    def pos_at(self, i, ms, within=20_000):
        tr = self.track.get(i) or []
        k = bisect.bisect_left(tr, (ms,))
        best = None
        for t in tr[max(0, k - 2): k + 2]:
            if abs(t[0] - ms) <= within and (best is None or abs(t[0] - ms) < abs(best[0] - ms)):
                best = t
        return best

    def nearest_call(self, actor, ms, pred, within=30_000):
        best = None
        for c in self.calls_by_actor.get(actor, []):
            if pred(c):
                d = abs(c.get("scene_ms", c["queued"]) - ms)
                if d <= within and (best is None or d < abs(best.get("scene_ms", best["queued"]) - ms)):
                    best = c
        return best

    def temper_at(self, i, ms):
        """(sociability, mood, src) from the nearest request that shows them."""
        best = None
        for c in self.calls_by_actor.get(i, []):
            if c.get("temper") and (best is None or abs(c["queued"] - ms) < abs(best["queued"] - ms)):
                best = c
        return (best["temper"][0], best["temper"][1], best["src"]) if best else None

    def spoken_after(self, who, to, after, words=None, within=180_000):
        """The first line `who` said to `to` (or with these words) after a time."""
        for x in self.lines:
            if x["speaker"] == who and after - 500 <= x["ms"] <= after + within and \
                    (x["to"] == to or (words and norm(x["text"])[:24] == norm(words)[:24])):
                return x
        return None

    def parked(self, l, hid, sp, ms, nxt, ev):
        """A line parked behind the hearer's running deliberation: what was running, each time it
        was released or parked again, and how it ended (up to the speaker's next line)."""
        run = [c for c in self.calls_by_actor.get(hid, []) if c["purpose"] in ("think", "deliberate") and c["queued"] <= ms + 500 and c["end"] >= ms]
        head = "parked behind a running deliberation"
        if run:
            c0 = min(run, key=lambda c: c["queued"])
            saw = any(norm(l["text"]) in norm(pc["text"]) for c in run for pc in c["percepts"])
            head += f" (its {c0['purpose']} prompt was built {fmt_dt(c0['queued'] - ms)} from the line{'' if saw else ' and does not show it'})"
            for c in run:
                ev.append(f"running: {c['purpose']} queued {fmt_dt(c['queued'] - ms)}, reply {fmt_dt(c['end'] - ms)}, model {c['lat'] / 1000:.1f} s ({c['src']})"
                          + (f"; says to {self.name(c['say'][1]) if c['say'][1] else 'no one'}: “{c['say'][0][:100]}”" if c["say"] and c["say"][0] else ""))
        i = bisect.bisect_left(self.log_ms, ms - 1000)
        chain = [x for x in self.logs[i:] if x[0] < min(nxt - 1000, ms + 180_000) and x[4] in ("parked", "unpark", "answered", "dropped")
                 and x[5] and x[5][0] == hid and x[5][1] == sp]
        bits, parks, out = [head], 0, None
        for k, x in enumerate(chain):
            if not any(x[3] in e for e in ev):
                ev.append(f"mind log {fmt_dt(x[0] - ms)}: {x[1][5:] if x[1].startswith('INFO') else x[1]} ({x[3]})")
            if x[4] == "parked" and "alongside" in x[1]:
                # LIVING_PARK=concurrent: the turn runs while the deliberation does.
                t = next((c for c in self.calls_by_actor.get(hid, []) if c["purpose"] == "talk" and x[0] - 1500 <= c["queued"] <= x[0] + 15_000), None)
                bits[0] = head.replace("parked behind", "heard during") + f"; its turn was taken alongside {fmt_dt(x[0] - ms)}"
                if t:
                    bits.append(f"that turn answered “{t['answering'][1][:60] if t['answering'] else '?'}” (reply {fmt_dt(t['end'] - ms)})")
                    out = dict(kind="parked", call=t["i"], latency=round((t["end"] - ms) / 1000, 1))
                    break
                continue
            if x[4] == "parked":
                parks += 1
                if parks > 1:
                    bits.append(f"parked again {fmt_dt(x[0] - ms)}" + (" (a new deliberation had started)" if k and chain[k - 1][4] == "unpark" and x[0] - chain[k - 1][0] <= 1000 else ""))
            elif x[4] == "answered":
                said = self.spoken_after(hid, sp, x[0] - 2000, within=5000)
                bits.append(f"answered in a deliberation {fmt_dt(x[0] - ms)}" + (f": “{said['text'][:70]}”" if said else ""))
                out = dict(kind="delib", latency=round(((said or {}).get("ms", x[0]) - ms) / 1000, 1))
                break
            elif x[4] == "dropped":
                bits.append(f"{x[1][5:]} {fmt_dt(x[0] - ms)}")
            elif x[4] == "unpark":
                bits.append(f"released {fmt_dt(x[0] - ms)}")
                t = next((c for c in self.calls_by_actor.get(hid, []) if c["purpose"] == "talk" and x[0] - 1500 <= c["queued"] <= x[0] + 15_000), None)
                nxt_park = chain[k + 1][0] if k + 1 < len(chain) and chain[k + 1][4] == "parked" else None
                if t and (nxt_park is None or t["queued"] <= nxt_park + 1000):
                    newer = t["answering"] and norm(t["answering"][1]) != norm(l["text"])
                    bits.append(f"the turn that followed answered {'the newer line ' if newer else ''}“{t['answering'][1][:60] if t['answering'] else '?'}” (reply {fmt_dt(t['end'] - ms)} from this line)")
                    out = dict(kind="parked", call=t["i"], latency=round((t["end"] - ms) / 1000, 1))
                    break
        if out is None:
            # The mind drops a parked line silently when the deliberation ends more than 90 s
            # after it (talk.rs: deliberation_ended).
            ends = [c["end"] for c in run if c["purpose"] == "deliberate"] or [c["end"] for c in run]
            if ends and max(ends) - ms > QUIET_MS and not any(x[4] == "unpark" for x in chain):
                bits.append(f"dropped without a log line: the deliberation ended {fmt_dt(max(ends) - ms)} after the line, past the 90 s a parked line is kept")
            elif nxt < ms + 180_000:
                bits.append(f"no turn followed before the speaker's next line to them ({fmt_dt(nxt - ms)})")
            else:
                last = chain[-1][0] - ms if chain else 0
                bits.append(f"no turn followed in the evidence (last word on it {fmt_dt(last)})")
            out = dict(kind="parked")
        out["short"] = "; ".join(bits)
        return out

    def relation_at(self, a, b, ms):
        """(label, trust, affinity, src, how) of a toward b at ms, from rows or requests."""
        rows = sorted(self.relations.get((a, b), []), key=lambda r: r[0])
        best = None
        for r in rows:
            if r[0] <= ms + 1000:
                best = r
        if best:
            return dict(label=best[1], trust=best[2], affinity=best[3], src=best[4], how="relation row")
        prior = [c for c in self.calls_by_actor.get(a, []) if c["queued"] <= ms + 500 and (c["people"] or c["purpose"] == "talk")]
        later = [c for c in self.calls_by_actor.get(a, []) if c["queued"] > ms + 500 and (c["people"] or c["purpose"] == "talk")]
        for c, how in ([(prior[-1], "last request before the line")] if prior else []) + ([(later[0], "first request after the line")] if later else []):
            for p in c["people"]:
                if p["id"] == b:
                    return dict(label=p["label"], trust=p["trust"], affinity=p["affinity"], src=c["src"], how=how, note=p.get("note"))
            if c["purpose"] != "talk" and c["people"]:
                full = len([p for p in c["people"] if p.get("from") == "people"]) >= 16
                return dict(label=None, trust=None, affinity=None, src=c["src"],
                            how=how + ": not among the people they know" + (" (the list is full at 16, so a weak relation could be cut)" if full else ""))
        return None

    def familiarity(self, hid, sp, ms, rel):
        """How the hearer stands toward the speaker for LIVING_GREET (talk.rs familiarity()):
        known (family, one community, a close or warm bond), hostile, barely (met), stranger
        (not met), or None when the evidence does not say."""
        if rel and rel.get("label") is not None:
            lab = (rel["label"] or "").lower()
            if any(w in lab for w in CLOSE) or (rel.get("affinity") or 0) >= 40 or (rel.get("trust") or 0) >= 60:
                return "known"
            if (rel.get("affinity") or 0) <= -40:
                return "hostile"
        c = self.nearest_call(hid, ms, lambda c: c["scene"] and any(cr.get("id") == sp for cr in c["scene"].get("creatures", [])), within=60_000)
        if c:
            cr = next(cr for cr in c["scene"]["creatures"] if cr.get("id") == sp)
            if cr.get("family") or cr.get("community") == "yours":
                return "known"
            if not cr.get("name"):
                return "stranger"
            return "barely"
        if rel and rel.get("label") is not None:
            return "barely"
        return None

    def heard(self, l, i):
        """Whether `i` (a party of the line) is shown to have heard it."""
        if l["speaker"] == i:
            return True
        h = l["hearers"].get(i)
        return bool(h) and not h.get("assumed")

    def fates(self, l):
        sp, ms = l["speaker"], l["ms"]
        greet = (self.env.get("LIVING_GREET") or "off").lower()
        park = (self.env.get("LIVING_PARK") or "wait").lower()
        only = {int(x) for x in re.findall(r"\d+", self.env.get("LIVING_ONLY") or "")}
        n_close = sum(1 for h in l["hearers"].values() if h.get("d") is not None and h["d"] <= ADDRESS_M and not h.get("assumed"))
        # Who on this line was drawn in or took a turn (a line to no one has one claimant).
        # A line to no one has one claimant among those drawn in by it (talk.rs `claimed`): a
        # hearer the mind logs as drawn in, or one who took an overheard turn on it.
        claim = {}
        faced_ids = set()
        if not l["to"]:
            for x in self.logs[bisect.bisect_left(self.log_ms, ms - 1000): bisect.bisect_left(self.log_ms, ms + 3000)]:
                if x[5] and x[5][1] == sp and x[5][0] in l["hearers"]:
                    if x[4] == "drawn":
                        claim.setdefault(x[5][0], "was drawn in")
                    elif x[4] == "faced":
                        faced_ids.add(x[5][0])
            for hid, h in l["hearers"].items():
                if (l["i"], hid) in self.turn_of and hid not in faced_ids and not ((h.get("sal") or 0) >= 0.8):
                    claim.setdefault(hid, "took an overheard turn on it")
        for hid, h in l["hearers"].items():
            ev, why = [], []
            fate = None
            hn, sn = self.name(hid), self.name(sp)
            if hid in self.players and (hid not in self.takeover or ms < self.takeover[hid]):
                h["fate"] = dict(kind="player", short="played by a person: the mind takes no turns for them")
                h["evidence"], h["why"] = [], []
                continue
            if (only and hid not in only) or (self.calls and not self.calls_by_actor.get(hid) and not self.args.who):
                h["fate"] = dict(kind="settled", short="not a mind in this run: " + ("not in LIVING_ONLY" if only and hid not in only else "no model exchange in the journal"))
                h["evidence"], h["why"] = [], []
                continue
            # The speaker's next line this hearer heard or was told: the window for its evidence.
            nxt = next((x["ms"] for x in self.lines[l["i"] + 1:] if x["speaker"] == sp and (hid in x["hearers"] or x["to"] == hid)), ms + 180_000)
            # 1. A talk turn on this line.
            c = self.turn_of.get((l["i"], hid))
            if c:
                said = c["say"][0] if c["say"] else ""
                spoken = self.spoken_after(hid, sp, c["end"], said, within=15_000) if said else None
                fate = dict(kind="turn", short=f"talk turn: reply {fmt_dt(c['end'] - ms)}" + (f", said {fmt_dt(spoken['ms'] - ms)}" if spoken else "")
                            + ("" if said else " (said nothing)"), call=c["i"], latency=round(((spoken or {}).get("ms", c["end"]) - ms) / 1000, 1))
                ev.append(f"talk call queued {fmt_dt(c['queued'] - ms)}, queue wait {c['qw'] / 1000:.1f} s, model {c['lat'] / 1000:.1f} s ({c['src']})")
                if said:
                    ev.append(f"reply: “{said}”")
            # 2. mind.log lines about this pair, from the line (logs have 1 s resolution) to the
            # speaker's next line to or heard by this hearer.
            lo = bisect.bisect_left(self.log_ms, ms - 1000)
            hi = bisect.bisect_left(self.log_ms, min(nxt - 1000, ms + 180_000))
            pair_logs = [x for x in self.logs[lo:max(lo, hi)] if x[5] and ((x[5][0] == hid and x[5][1] == sp) or (x[4] in ("earshot", "reopen") and set(x[5]) == {hid, sp}))]
            if l["to"] and l["to"] != hid:
                pair_logs = []   # a line said to someone else never passes this hearer's gate
            first_kind = None
            for x in pair_logs:
                if x[4] == "said":
                    continue
                ev.append(f"mind log {fmt_dt(x[0] - ms)}: {x[1][5:] if x[1].startswith('INFO') else x[1]} ({x[3]})")
                first_kind = first_kind or x[4]
            kinds = [x[4] for x in pair_logs]
            if fate and fate["kind"] == "turn" and "parked" in kinds:
                # The turn came, but only after the line waited behind deliberations.
                c_turn = self.turn_of.get((l["i"], hid))
                upto = c_turn["queued"] + 1000 if c_turn else ms + 180_000
                before = [x for x in self.logs[lo:bisect.bisect_right(self.log_ms, upto)]
                          if x[5] and x[5][0] == hid and x[5][1] == sp and x[4] in ("parked", "unpark")]
                parks = [x for x in before if x[4] == "parked" and "alongside" not in x[1]]
                rels = [x for x in before if x[4] == "unpark"]
                if parks:
                    fate["short"] += (f"; before it, the line was parked behind a running deliberation {len(parks)} time{'s' if len(parks) > 1 else ''}"
                                      + (f" (released {', '.join(fmt_dt(x[0] - ms) for x in rels)})" if rels else ""))
            if not fate:
                if first_kind == "settled":
                    fate = dict(kind="settled", short="no turn: they had settled the exchange")
                elif first_kind == "answered":
                    said = self.spoken_after(hid, sp, pair_logs[kinds.index("answered")][0] - 2000, within=5000)
                    fate = dict(kind="delib", short="answered in its running deliberation (no talk turn)" + (f": “{said['text'][:70]}”" if said else ""))
                elif "parked" in kinds:
                    fate = self.parked(l, hid, sp, ms, nxt, ev)
            # 3. A later deliberation that saw the line and spoke to the speaker.
            later = None
            for c in self.calls_by_actor.get(hid, []):
                if c["purpose"] in ("think", "deliberate") and c["say"] and c["say"][1] == sp and ms <= c["end"] <= min(nxt, ms + 120_000):
                    if any(norm(l["text"]) in norm(pc["text"]) for pc in c["percepts"]):
                        later = c
                        break
            if later:
                spoken = self.spoken_after(hid, sp, later["end"])
                when = f"said {fmt_dt(spoken['ms'] - ms)}" if spoken else f"its reply {fmt_dt(later['end'] - ms)}"
                ev.append(f"a later {later['purpose']}, built {fmt_dt(later['queued'] - ms)} (why: {later['why'][:160] or '-'}), shows the line and speaks to {sn} "
                          f"({when}): “{later['say'][0][:120]}” ({later['src']})")
                if fate and fate["kind"] in ("delib", "parked") and "call" not in fate:
                    fate["call"] = later["i"]
            # 4. The gate's inputs as the evidence shows them.
            asks = "?" in l["text"]
            addressed = None
            if l["to"] == hid:
                addressed = "said to them (to)"
            elif l["to"]:
                addressed = False
                why.append(f"said to {self.name(l['to'])}, not to them: only the one it was said to can be addressed, and only a line to no one can be overheard")
            elif "faced" in kinds:
                addressed = "faced by the speaker (LIVING_GREET=facing)"
            elif h.get("sal") is not None:
                addressed = "marked addressed (salience ≥ 0.8)" if h["sal"] >= 0.8 else False
                if addressed is False:
                    why.append(f"to no one, salience {h['sal']}: not marked addressed (only the one hearer within {ADDRESS_M:g} m, or one named, is)")
            elif l.get("audience"):
                if n_close >= 2:
                    addressed = False
                    why.append(f"to no one, with {n_close} hearers within {ADDRESS_M:g} m (audience row): addresses nobody")
                elif n_close == 1 and h.get("d") is not None and h["d"] <= ADDRESS_M:
                    addressed = f"the only hearer within {ADDRESS_M:g} m (audience row)"
                else:
                    addressed = False
                    why.append(f"to no one, and they were {h.get('d')} m off (only the one hearer within {ADDRESS_M:g} m is addressed)")
            else:
                dist = {x["id"]: (x["d"], x.get("d_dt", 0)) for x in l["hearers"].values() if x.get("d") is not None}
                for x in l.get("near", []):
                    dist.setdefault(x["id"], (x["d"], x["dt"]))
                # A distance seen dt from the line bounds where they stood at the line, at a walk
                # of up to WALK m/s.
                fresh = {i: v for i, v in dist.items() if abs(v[1]) <= 10_000}
                close = {i: v for i, v in fresh.items() if v[0] + WALK * abs(v[1]) / 1000 <= ADDRESS_M}
                show = lambda d: ", ".join(f"{self.name(i)} {v[0]} m ({fmt_dt(v[1])})" for i, v in sorted(d.items(), key=lambda kv: kv[1][0]))
                if len(close) >= 2:
                    addressed = False
                    why.append(f"to no one, and {len(close)} people stood within {ADDRESS_M:g} m of the speaker, so it addressed nobody ({show(close)}; each distance seen at the time given)")
                elif hid in fresh and fresh[hid][0] - WALK * abs(fresh[hid][1]) / 1000 > ADDRESS_M:
                    addressed = False
                    why.append(f"to no one, and they were {fresh[hid][0]} m away ({fmt_dt(fresh[hid][1])}), beyond {ADDRESS_M:g} m even at a walk: only the one hearer within {ADDRESS_M:g} m is addressed")
                elif hid in close:
                    why.append(f"to no one; they are the only one known within {ADDRESS_M:g} m ({show(close)}), so it may have been marked addressed; others nearby may be missing")
                elif hid in dist:
                    why.append(f"to no one; their distance {dist[hid][0]} m was seen {fmt_dt(dist[hid][1])} from the line, too far apart in time to apply the {ADDRESS_M:g} m rule; addressed is unknown")
                else:
                    why.append("to no one; no salience and no distance near the line, so whether it was marked addressed is unknown")
            if addressed:
                why.insert(0, f"addressed: {addressed}")
            rel = self.relation_at(hid, sp, ms)
            fam = self.familiarity(hid, sp, ms, rel)
            cares, known_rel = None, False
            if rel:
                if rel.get("label") is None and rel.get("trust") is None:
                    cares = False
                    why.append(f"cares: no — {sn} is not among the people they know ({rel['how']}, {rel['src']})")
                else:
                    known_rel = True
                    lab = (rel.get("label") or "").lower()
                    close_bond = any(w in lab for w in CLOSE) or (rel.get("trust") or 0) >= 60
                    strong = abs(rel.get("affinity") or 0) >= 40
                    cares = close_bond or strong
                    if greet != "off" and (rel.get("affinity") or 0) <= -40 and not close_bond:
                        cares = False   # with LIVING_GREET, hostility is not caring
                    why.append(f"cares: {'yes' if cares else 'no'} — {rel.get('label')}, trust {rel.get('trust')}, affinity {rel.get('affinity')} ({rel['how']}, {rel['src']})"
                               + (" (LIVING_GREET: hostility is not caring)" if greet != "off" and strong and not cares else ""))
            else:
                why.append("cares: unknown (no relation row or request near the line)")
            # Their exchange with the speaker: lines between them within 90 s that the other heard.
            prior = [x for x in self.lines[: l["i"]] if ms - x["ms"] <= QUIET_MS]
            # A pair's exchange exists in the mind once a line between them passed a gate: a talk
            # turn on it, by either side.
            with_sp = [x for x in prior if (x["i"], hid) in self.turn_of and x["speaker"] == sp] + \
                      [x for x in prior if (x["i"], sp) in self.turn_of and x["speaker"] == hid]
            with_sp.sort(key=lambda x: x["ms"])
            other = [x for x in prior if hid in (x["speaker"], x["to"]) and sp not in (x["speaker"], x["to"]) and x["to"] and self.heard(x, x["to"] if x["speaker"] == hid else hid)]
            j = bisect.bisect_left(self.log_ms, ms - QUIET_MS)
            ends = [(x[0], set(x[5])) for x in self.logs[j:bisect.bisect_left(self.log_ms, ms - 1000)] if x[4] == "earshot" and x[5]]
            other = [o for o in other if not any(t >= o["ms"] - 1000 and pr == {o["speaker"], o["to"]} for t, pr in ends)]
            closed = None
            # The mind logs "out of earshot" only for a pair it holds, so it proves an exchange
            # existed and ended, with or without a talk turn in the journal.
            for t, pr in ends:
                if pr == {hid, sp} and (not with_sp or t >= with_sp[-1]["ms"] - 1000):
                    closed = f"out of earshot {fmt_dt(t - ms)}"
            if with_sp:
                last_ms = with_sp[-1]["ms"]
                for c in self.calls_by_actor.get(hid, []) + self.calls_by_actor.get(sp, []):
                    r_ = c["reply_obj"]
                    if c["purpose"] == "talk" and isinstance(r_, dict) and {c["actor"], (c["say"] or [0, 0])[1]} == {hid, sp} and last_ms - 15_000 <= c["end"] <= ms:
                        st = r_.get("settled")
                        if r_.get("end") is True or (isinstance(st, str) and st.strip() and st.strip().lower() not in ("none", "no", "open", "null")) or not (c["say"] or [""])[0]:
                            closed = (f"settled by {self.name(c['actor'])}'s turn: “{st}”" if isinstance(st, str) and st.strip() else f"ended by {self.name(c['actor'])}'s turn") + f" ({c['src']})"
            active = bool(with_sp) and not closed
            if closed:
                why.append(f"exchange with {sn}: closed before this line ({closed}); it reopens only on a line that says something new")
            elif with_sp:
                why.append(f"exchange with {sn}: active (their last line {fmt_dt(with_sp[-1]['ms'] - ms)})"
                           + ("; that gives a turn only on a line to no one" if l["to"] and l["to"] != hid else ""))
            else:
                why.append(f"exchange with {sn}: none in the 90 s before")
            if other:
                o = other[-1]
                why.append(f"in another exchange: {self.name(o['speaker'])} → {self.name(o['to'])} {fmt_dt(o['ms'] - ms)} (this matters only for overhearing a line to no one)")
            why.append(f"a question: {'yes' if asks else 'no'}")
            # The mind's deterministic draws for this hearer and line (talk.rs draw()).
            tmp = self.temper_at(hid, ms)
            answers = remark = over = None
            if tmp and l["exact"]:
                answers = 0.3 + 0.65 * tmp[0] / 100
                remark = draw(hid, ms ^ 0x5EED)
                over = draw(hid, ms)
                why.append(f"draws (talk.rs draw(), recomputed from the line's time): answers remarks below {answers:.3f} (sociability {tmp[0]:.0f}, {tmp[2]}); "
                           f"remark draw {remark:.4f} → {'passes' if remark < answers else 'refuses'}; overheard draw {over:.4f} → {'passes' if over < answers else 'refuses'}")
            elif tmp:
                why.append("draws: the line's time is not exact (read from requests), so the deterministic draws cannot be recomputed")
            def turn_done(c):
                said = self.spoken_after(hid, None, c["end"], (c["say"] or [""])[0], within=10_000) if c["say"] and c["say"][0] else None
                return said["ms"] if said else c["end"]
            busy = next((c for c in self.calls_by_actor.get(hid, []) if c["purpose"] == "talk" and c["queued"] <= ms <= turn_done(c)
                         and self.turn_of.get((l["i"], hid)) is not c), None)
            others_claim = {k: v for k, v in claim.items() if k != hid}
            if not fate:
                if addressed or (active and not l["to"]):
                    base = "addressed" if addressed else "their exchange was active and the line was to no one"
                    # With LIVING_GREET, an addressed line from an unfamiliar speaker skips the remark draw.
                    stranger = greet != "off" and fam in ("stranger", "barely")
                    ended = closed and not closed.startswith("settled")
                    if ended:
                        reason = (f"{base}, but their exchange had ended ({closed}); a line reopens an ended exchange only when it says something new "
                                  "(half its words new to the exchange; not recomputed here)")
                    elif not asks and remark is not None and remark >= answers and not stranger:
                        reason = f"{base}, but the remark draw refused it: {remark:.4f} ≥ {answers:.3f} (the line asks nothing, and they let a remark pass by their sociability)"
                    elif busy:
                        reason = (f"{base}, but a talk turn of theirs was in flight (queued {fmt_dt(busy['queued'] - ms)}, on "
                                  f"“{(busy['answering'] or ['', '?'])[1][:50]}”, {busy['src']}): a line heard meanwhile waits, and afterwards only a speaker who still has the last word is answered")
                    else:
                        reason = (f"{base}, so a turn was due, but none is in the journal: " +
                                  ("the remark draw passed, so " if remark is not None and not asks and remark < answers else "") +
                                  "stamina, a turn already in flight or the off-stage hold took it; these are logged at debug level only")
                        if self.calls and not any(c["purpose"] == "talk" for c in self.calls_by_actor.get(hid, [])):
                            reason += f"; {hn} has no talk call at all in the journal"
                    fate = dict(kind="none", short="no turn: " + reason)
                elif l["to"]:
                    fate = dict(kind="none", short=f"no turn: said to {self.name(l['to'])}; nothing in the gate gives a turn to someone else")
                elif others_claim:
                    k, v = next(iter(others_claim.items()))
                    fate = dict(kind="none", short=f"no turn: {self.name(k)} {v} first; a line to no one draws one hearer")
                elif cares:
                    if over is not None and over >= answers:
                        fate = dict(kind="none", short=f"no turn: {hn} cares about {sn}, but the overheard draw refused it ({over:.4f} ≥ {answers:.3f})")
                    elif other:
                        fate = dict(kind="none", short=f"no turn: {hn} cares about {sn}, but was in another exchange, and an overheard line draws only a listener who is free")
                    elif not asks and remark is not None and remark >= answers:
                        fate = dict(kind="none", short=f"no turn: {hn} cares about {sn} and the overheard draw passed ({over:.4f}), but the remark draw then refused it ({remark:.4f} ≥ {answers:.3f})")
                    else:
                        fate = dict(kind="none", short=f"no turn: {hn} cares about {sn}" + (", and the overheard draw passed" if over is not None else "") +
                                    ", but the overheard path did not fire: " + ("they were in another exchange" if other else "drawn in within 60 s or another hearer claimed it (not logged)"))
                elif cares is False and addressed is False:
                    fate = dict(kind="none", short=f"no turn: not addressed, and {hn} does not care about {sn}"
                                + (" (not among the people they know)" if rel and rel.get("label") is None else "") + ": nothing in the gate gives a turn"
                                + (f"; LIVING_GREET={greet} did not draw them in" if greet != "off" else ""))
                elif cares is False:
                    if asks:
                        tail = "An addressed question always gets a turn, so it was not addressed."
                    elif remark is not None and remark >= answers and greet == "off":
                        tail = f"Had it been addressed, the remark draw would have refused it ({remark:.4f} ≥ {answers:.3f}): no turn either way"
                    elif remark is not None:
                        tail = f"Had it been addressed, the remark draw would have passed ({remark:.4f} < {answers:.3f}), so it was most likely not addressed."
                    else:
                        tail = "Had it been addressed, only the remark draw (not recomputable here) could refuse it."
                    fate = dict(kind="none", short=f"no turn: {hn} does not care about {sn}"
                                + (" (not among the people they know)" if rel and rel.get("label") is None else "")
                                + f", so only an addressed line could draw a turn. It was said to no one, which addresses a hearer only when they are "
                                f"the one person within {ADDRESS_M:g} m; the evidence does not show that. " + tail)
                else:
                    fate = dict(kind="none", short="no turn: " + ("not addressed" if addressed is False else "addressed status unknown") + "; whether they care is unknown")
                if later:
                    fate["short"] += f". Later, a deliberation that saw the line spoke to {sn} (why: {later['why'][:90] or '-'})"
                    fate["call"] = later["i"]
            h["fate"] = fate
            h["evidence"] = ev
            h["why"] = why
        if l.get("unheard"):
            l["unheard_to"] = dict(id=l["to"], why=l["unheard"])
        l["note"] = f"hearers from: {', '.join(sorted(set(s.split(':')[0] for h in l['hearers'].values() for s in h['srcs'])))}"
        if not l.get("audience"):
            l["note"] += " (no audience rows: hearers are those the evidence shows hearing it; others in earshot may be missing)"

    # --- the page data
    def page_data(self):
        a = self.args
        keep = None
        if a.who:
            keep = set()
            for w in a.who.split(","):
                w = w.strip()
                i = self.by_name.get(w) or (int(w.strip("#")) if w.strip("#").lstrip("-").isdigit() else None)
                if i is not None:
                    keep.add(i)
        all_ms = [c["queued"] for c in self.calls] + [l["ms"] for l in self.lines] + [x[0] for x in self.logs]
        start = self.t0_ms or (min(all_ms) if all_ms else 0)
        lo = start + int(a.since * 1000) if a.since is not None else None
        hi = start + int(a.until * 1000) if a.until is not None else None

        def inwin(ms):
            return ms is not None and (lo is None or ms >= lo) and (hi is None or ms <= hi)

        def kept(i):
            return keep is None or i in keep
        calls = [c for c in self.calls if kept(c["actor"]) and inwin(c["queued"])]
        call_idx = {c["i"]: k for k, c in enumerate(calls)}
        people = {}
        ids = set(self.names) | set(c["actor"] for c in self.calls) | set(self.body) | set(self.exps)
        for i in ids:
            if i is None or i == 0:
                continue
            people[i] = dict(name=self.name(i), kind=self.kinds.get(i), player=i in self.players,
                             died=self.died.get(i, (None, None))[0], cause=self.died.get(i, (None, None))[1],
                             takeover=self.takeover.get(i), calls=sum(1 for c in calls if c["actor"] == i))
        lines = []
        for l in self.lines:
            if not inwin(l["ms"]):
                continue
            if keep is not None and not ({l["speaker"], l["to"]} | set(l["hearers"])) & keep:
                continue
            hs = []
            for h in l["hearers"].values():
                f = dict(h.get("fate") or {})
                if "call" in f:
                    f["call"] = call_idx.get(f["call"])
                f["tag"] = fate_tag(f)
                hs.append(dict(id=h["id"], d=h.get("d"), d_note=h.get("d_note"), off=h.get("off"), sal=h.get("sal"), srcs=h["srcs"],
                               fate=f, why=h.get("why", []), ev=h.get("evidence", [])))
            hs.sort(key=lambda h: (h["id"] != l["to"], h["d"] if h["d"] is not None else 99, h["id"]))
            lines.append(dict(i=len(lines), ms=l["ms"], exact=l["exact"], speaker=l["speaker"], to=l["to"], text=l["text"], reps=l["reps"],
                              srcs=l["srcs"], hearers=hs, note=l.get("note"), near=l.get("near", []), unheard=l.get("unheard_to")))
        events = defaultdict(list)

        def ev(i, ms, lane, text, src, ref=None):
            if i and kept(i) and inwin(ms):
                events[i].append([ms, lane, text, src, ref])
        for obs, rows in self.exps.items():
            for r in rows.values():
                if r["ms"] is None:
                    continue
                if r["kind"] in ("speech", "said", "repeat", "silence") or re.search(r" said(?: to .*?)?: “", r["text"]):
                    lane = "talk"
                else:
                    lane = "perceive"
                if not r["exact"] and r["text"].startswith("You said") and any(
                        x["speaker"] == obs and norm(x["text"]) == norm(quoted(r["text"])) and abs(x["ms"] - r["ms"]) <= 3000 for x in self.lines):
                    continue   # the line itself is on the timeline already
                tag = "" if r["exact"] else " ≈"
                sal = f" [salience {r['sal']}]" if r.get("sal") is not None else ""
                ev(obs, r["ms"], lane, f"{r['text']}{sal}{tag}", r["src"], {"c": call_idx[r["call"]]} if r.get("call") in call_idx else None)
        for c in calls:
            k = call_idx[c["i"]]
            r = c["reply_obj"]
            if c["purpose"] == "talk":
                head = f"talk turn on {c['answering'][0]}: “{c['answering'][1][:120]}”" if c["answering"] else "talk turn"
                if isinstance(r, dict):
                    head += f" → {('“' + (c['say'][0] if c['say'] else '') + '”') if c['say'] and c['say'][0] else 'says nothing'}"
                    if r.get("settled"):
                        head += f" (settled: {r['settled']})"
            elif c["purpose"] in ("think", "deliberate"):
                th = r.get("thought") if isinstance(r, dict) else None
                head = f"{c['purpose']} — why: {c['why'][:140] or '-'}"
                if th:
                    head += f" | thought: {th[:200]}"
                if c["say"] and c["say"][0]:
                    head += f" | says to {self.name(c['say'][1]) if c['say'][1] else 'no one'}: “{c['say'][0][:140]}”"
                if c["purpose"] == "deliberate" and isinstance(r, dict) and r.get("plan"):
                    head += f" | plan: {r['plan'][:140]}"
                if c.get("outcome"):
                    head += f" → {c['outcome']}"
            else:
                summ = r.get("summary") if isinstance(r, dict) else None
                head = f"{c['purpose']}" + (f": {summ[:220]}" if summ else "")
            if c["error"]:
                head += f" | ERROR {c['error'][:160]}"
            ev(c["actor"], c["queued"], "decide", head, c["src"], {"c": k})
            rec = [b for h, b in c["sections"] if h.startswith("What comes to mind") or h.startswith("Memories this brings back")]
            if rec:
                lines_ = [x for x in "\n".join(rec).splitlines() if x.startswith("- ")]
                if lines_:
                    ev(c["actor"], c["queued"] + 1, "recall", f"{len(lines_)} recalled for this {c['purpose']}: " + " / ".join(x[2:120] for x in lines_[:3]), c["src"], {"c": k})
        for i, rows in self.graphs.items():
            for g in rows:
                ref = {"c": call_idx[g[4]]} if len(g) > 4 and g[4] in call_idx else ({"g": g[3]} if g[3] else None)
                ev(i, g[0], "graph", g[1], g[2], ref)
        for i, rows in self.body.items():
            for b in rows:
                text = re.sub(r"\{(-?\d+)\}", lambda m: self.name(int(m.group(1))), b[1])
                ev(i, b[0], "body", text, b[2])
        for x in self.logs:
            for i in x[2]:
                ev(i, x[0], "log", x[1], x[3])
        for l in lines:
            ev(l["speaker"], l["ms"], "talk", f"says{' to ' + self.name(l['to']) if l['to'] else ''}: “{l['text']}”" +
               (f" (×{l['reps']})" if l["reps"] > 1 else "") + f" — {len(l['hearers'])} hearers", l["srcs"][0], {"l": l["i"]})
        for i in events:
            events[i].sort(key=lambda e: e[0])
        off = dt.datetime.fromtimestamp((start or 0) / 1000).astimezone().utcoffset()
        out_calls = []
        for c in calls:
            d = {k: c[k] for k in ("actor", "purpose", "queued", "start", "end", "lat", "qw", "model", "profile", "lane", "attention", "effort",
                                   "tokens", "ptok", "ctok", "cached", "error", "finish", "mode", "src", "sys", "sections", "reply", "why", "answering", "say", "body_feel")}
            out_calls.append(d)
        used_sys = {c["sys"] for c in calls if c["sys"]}
        # Timing per purpose: queue wait (admission) against model time.
        def pct(v, q):
            v = sorted(v)
            return v[min(len(v) - 1, int(q * len(v)))] if v else None
        timing = []
        for purpose in sorted({c["purpose"] for c in calls}):
            cs = [c for c in calls if c["purpose"] == purpose]
            qw, lt = [c["qw"] for c in cs], [c["lat"] for c in cs]
            timing.append(dict(purpose=purpose, n=len(cs), q50=pct(qw, .5), q90=pct(qw, .9), qmax=max(qw), m50=pct(lt, .5), m90=pct(lt, .9), mmax=max(lt),
                               errors=sum(1 for c in cs if c["error"])))
        return dict(
            meta=dict(dir=str(self.root), generated=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                      start=start, tz_min=int(off.total_seconds() // 60) if off else 0, clock=self.clock, env=self.env,
                      sources=self.sources, notes=self.notes, rule=RULE_NOTE,
                      kind="trial" if (self.root / "state.json").exists() else "play session",
                      filters=dict(who=a.who, since=a.since, until=a.until), timing=timing),
            people=people, lines=lines, calls=out_calls, systems={k: v for k, v in self.systems.items() if k in used_sys},
            events=events)


# ---------------------------------------------------------------- request parsing

def split_sections(text):
    out, head, buf = [], "(preamble)", []
    for line in text.splitlines():
        m = re.match(r"^# (.+)$", line)
        if m:
            if buf and "\n".join(buf).strip():
                out.append([head, "\n".join(buf).strip("\n")])
            head, buf = m.group(1), []
        else:
            buf.append(line)
    if buf and "\n".join(buf).strip():
        out.append([head, "\n".join(buf).strip("\n")])
    return out


ANN = re.compile(r" \{([^{}]*=#-?\d+[^{}]*)\}$")
EXP_A = re.compile(r"^- \[day (\d+) (\d\d):(\d\d)\] (.*)$")           # think/deliberate "Recent experiences"
EXP_B = re.compile(r"^- \[(\d+)\] day (\d+) (\d\d):(\d\d) (.*)$")      # consolidate "New experiences to integrate"
EXP_C = re.compile(r"^- \[(\d+)\] (?:\[)?day (\d+) (\d\d):(\d\d)\]? (.*)$")


def parse_percepts(text):
    out = []
    sec = None
    for line in text.splitlines():
        m = re.match(r"^# (.+)$", line)
        if m:
            sec = m.group(1)
            continue
        if not sec or not (sec.startswith("Recent experiences") or sec.startswith("New experiences") or sec.startswith("Lately, involving")):
            continue
        eid, gm, body = None, None, None
        m = EXP_B.match(line) or EXP_C.match(line)
        if m:
            eid, d, h, mi, body = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
            gm = (d - 1) * 1440 + h * 60 + mi
        else:
            m = EXP_A.match(line)
            if m:
                d, h, mi, body = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                gm = (d - 1) * 1440 + h * 60 + mi
            elif line.startswith("- "):
                body = line[2:]
        if body is None:
            continue
        ann = []
        am = ANN.search(body)
        if am:
            for part in am.group(1).split(", "):
                if "=#" in part:
                    nm, _, i = part.rpartition("=#")
                    try:
                        ann.append((nm, int(i)))
                    except ValueError:
                        pass
            body = body[: am.start()]
        out.append(dict(id=eid, gm=gm, text=body.strip(), ann=ann, sec=sec.split(" (")[0]))
    return out


PEOPLE = re.compile(r"^- (.+?) \(#(\d+)\): (.*?),? ?trust (-?[\d.]+), affinity (-?[\d.]+)(?: — (.*))?$")
YOU_AND = re.compile(r"^# You and (.+?) \(#(\d+)\)\n(.*?)(?=\n# |\Z)", re.M | re.S)


def parse_people(text):
    out = []
    sec = None
    for line in text.splitlines():
        m = re.match(r"^# (.+)$", line)
        if m:
            sec = m.group(1)
            continue
        if sec == "People you know":
            m = PEOPLE.match(line)
            if m:
                out.append(dict(name=m.group(1), id=int(m.group(2)), label=m.group(3).rstrip(":, ") or None,
                                trust=float(m.group(4)), affinity=float(m.group(5)), note=m.group(6), **{"from": "people"}))
    for m in YOU_AND.finditer(text):
        body = m.group(3).strip()
        r = re.match(r"^(.*?):? ?trust (-?[\d.]+), affinity (-?[\d.]+)(?: — (.*))?", body)
        if r:
            out.append(dict(name=m.group(1), id=int(m.group(2)), label=r.group(1).rstrip(":, ") or None, trust=float(r.group(2)),
                            affinity=float(r.group(3)), note=r.group(4)))
        else:
            out.append(dict(name=m.group(1), id=int(m.group(2)), label="(none: " + body.splitlines()[0][:80] + ")", trust=0.0, affinity=0.0, note=None))
    return out


def parse_reply(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def act_text(a):
    if not isinstance(a, dict):
        return str(a)
    t = a.get("target")
    tt = ""
    if isinstance(t, dict):
        tt = " → " + ", ".join(f"{k} {v}" for k, v in t.items())
    item = f" {a.get('item')}" if a.get("item") else ""
    return f"{a.get('do')}{item}{tt}"


def fate_tag(f):
    """A few words for a hearer's fate, for the lines table."""
    k, s = f.get("kind"), f.get("short", "")
    tag = {"turn": "talk turn after parking" if "was parked" in s else "talk turn", "delib": "answered by a deliberation", "player": "a player", "later": "later deliberation"}.get(k)
    if k == "parked":
        tag = "parked → turn" if "turn that followed" in s else ("parked → answered" if "answered" in s else "parked → no turn")
    elif k == "settled":
        tag = "not a mind" if "not a mind" in s else "settled"
    elif k == "none" or tag is None:
        for pat, t in (("a turn was due, but none", "turn due, none ⚠"), ("no turn: said to ", "said to another"), ("first; a line to no one", "another took it"), ("draw refused", "draw refused"),
                       ("was in flight (queued", "busy with another turn"), ("had ended", "exchange ended"), ("nothing in the gate", "not addressed, no bond"),
                       ("no turn either way", "no bond; draw refused"), ("does not care", "no bond"), ("cares about", "cares, not drawn")):
            if pat in s:
                tag = t
                break
        else:
            tag = "no turn"
        if "Later, a deliberation" in s:
            tag += " (later spoke to them)"
    return tag


def draw(listener, at_ms):
    """The mind's deterministic draw in [0, 1) for one listener and line (talk.rs draw())."""
    m = (1 << 64) - 1
    h = (0x9E3779B97F4A7C15 ^ ((int(listener) & 0xFFFFFFFF) << 32) ^ int(at_ms)) & m
    h ^= h >> 33
    h = (h * 0xFF51AFD7ED558CCD) & m
    h ^= h >> 33
    return (h % 10_000) / 10_000


def to_id(v):
    """A reply's `to`: an id, {"id": n}, "#n" or a name-less value -> int (0 = no one)."""
    if isinstance(v, dict):
        v = v.get("id")
    if isinstance(v, str):
        v = v.lstrip("#")
        return int(v) if v.isdigit() else 0
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def fmt_dt(ms):
    s = ms / 1000
    return f"{'+' if s >= 0 else '−'}{abs(s):.1f} s"


# ---------------------------------------------------------------- page

def render(data, out):
    blob = base64.b64encode(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)).decode("ascii")
    tpl = (Path(__file__).resolve().parent / "inspector.html").read_text(encoding="utf-8")
    title = "Resident inspector: " + Path(data["meta"]["dir"]).name
    page = tpl.replace("__TITLE__", title.replace("<", "&lt;")).replace("__DATA__", blob)
    Path(out).write_text(page, encoding="utf-8")
    return len(page)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("-o", "--out", default=None, help="page path (default RUN_DIR/inspector.html is NOT used: default ./inspector-<name>.html)")
    ap.add_argument("--who", help="only these residents (names or ids, comma-separated) and the lines they said or heard")
    ap.add_argument("--player", help="mark these characters as players (names or ids)")
    ap.add_argument("--since", type=float, help="seconds from the run start")
    ap.add_argument("--until", type=float, help="seconds from the run start")
    ap.add_argument("--journal", help="journal directory (default: RUN_DIR/journal, the live journal of a running trial, or any */journal)")
    ap.add_argument("--mind-log", help="mind.log (default: RUN_DIR/mind.log or session/run/mind.log)")
    ap.add_argument("--rows", nargs="*", help="extra SQL exports: text tables (*.txt) or JSON row lists (*.json), files or folders")
    a = ap.parse_args()
    run = Run(a.run_dir, a)
    run.load()
    run.resolve()
    data = run.page_data()
    out = a.out or f"inspector-{Path(a.run_dir).resolve().name}.html"
    size = render(data, out)
    print(f"{out}: {size / 1e6:.2f} MB; {len(data['people'])} characters, {len(data['calls'])} model exchanges, "
          f"{len(data['lines'])} lines, {sum(len(v) for v in data['events'].values())} timeline events")
    for n in run.notes:
        print("note:", n)
    if size > 40e6:
        print("warning: a large page; narrow it with --who or --since/--until", file=sys.stderr)


if __name__ == "__main__":
    main()
