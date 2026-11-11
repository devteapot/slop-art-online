#!/usr/bin/env python3
"""One page about an owner's play session: what was on screen, and what happened.

  living/tools/play_report.py --db <database> --run <run> --journal <journal dir> \
      --logs <dir with client.log and mind.log> --out <dir> [--capture <dir>]

writes `<out>/index.html` and prints its path. It reads the world as its owner over SQL (it
works on a paused world and never calls a reducer), the mind journal, the client and mind
logs, the module's log (`spacetime logs`, read-only), and what the recorders left in
`--capture`. See docs/PLAY_REPORT.md.

Recording, for the launcher (docs/PLAY_REPORT.md "Recording"):

  play_report.py record-start --db <database> --capture <dir> [--no-screen]
  LIVING_GAME_RECORD=<dir>/client living-game ...      # the client's own stills and state
  play_report.py record-stop --capture <dir>

`record-start` starts one background process that keeps the authority's rows before they are
evicted (new experience and chronicle rows, and where everyone stood, once a second, by owner
SQL) and, when this app may record the screen, records the game's window with `screencapture`.
`record-stop` stops it by the PID it wrote. Standard library only.
"""
import argparse
import bisect
import glob
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journal_io import restore  # noqa: E402
from trials import PRICES, cost  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
CONTAINER = os.environ.get("LIVING_STDB_CONTAINER", "sao-living_spacetimedb_1")
# The authority's rules this report leans on (docs/LIVING_CORE.md, perceive.rs): speech
# carries to the hearing law's range; a line to no one is for the only listener within 6 m.
ADDRESS_M = 6.0
# Skills that move you rather than act on anyone; they do not break a silence.
MOVES = {"dodge", "jump", "guard", "block", "sprint"}
QUIET_S = 60.0          # a stretch with no word or act from the player worth showing
REPLY_WINDOW_S = 60.0   # how long after a line a resident's words to the player count as a reply
PLAYER_REDUCERS = {"join", "human_move", "human_act", "human_say", "use_skill", "release_skill", "human_face", "human_gesture"}
# Client warnings known to be harmless on this laptop (shown folded, not as errors).
VIA = {"think": "a deliberation (its think step)", "deliberate": "a deliberation", "talk": "a conversation turn", None: "an unknown source"}
BENIGN = [re.compile(p) for p in (r"Bindless textures are not yet supported on metal",)]


# ---------------------------------------------------------------------------------------
# Owner SQL (the in-container CLI identity is the world's admin; the token stays in memory)

def admin_token():
    r = subprocess.run(["docker", "exec", "-i", CONTAINER, "spacetime", "login", "show", "--token"], capture_output=True, text=True, timeout=30)
    for line in r.stdout.splitlines():
        if "auth token" in line and " is " in line:
            return line.rsplit(" is ", 1)[1].strip()
    raise SystemExit("play_report: could not read the owner's token from the SpacetimeDB container")


class Sql:
    def __init__(self, db):
        self.db, self.token = db, admin_token()

    def rows(self, query):
        """One SELECT. (2.14.1 refuses several statements in one request.) Each request opens
        and closes an HTTP connection, so the authority runs its connect and disconnect hooks."""
        req = urllib.request.Request(f"{URL}/v1/database/{self.db}/sql", data=query.encode(), method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode())[-1]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"sql {e.code}: {e.read().decode()[:300]}") from None
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, row)) for row in res["rows"]]


def flat(v):
    """SATS JSON: Option is {"some": x} / {"none": []}; identities are ["0x..."]."""
    if isinstance(v, dict) and len(v) == 1:
        k, x = next(iter(v.items()))
        return None if k == "none" else flat(x)
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], str) and v[0].startswith("0x"):
        return v[0]
    return v


def flat_row(r):
    return {k: flat(v) for k, v in r.items()}


# ---------------------------------------------------------------------------------------
# Time

def clock(ms, frac=True):
    if ms is None:
        return "–"
    ms = int(round(ms / 100) * 100) if frac else int(ms)
    t = time.localtime(ms // 1000)
    return time.strftime("%H:%M:%S", t) + (f".{(ms % 1000) // 100}" if frac else "")


def span(s):
    s = abs(s)
    if s < 60:
        return f"{s:.1f} s"
    m, s = divmod(int(round(s)), 60)
    return f"{m} min {s} s" if m < 60 else f"{m // 60} h {m % 60} min"


def iso_ms(stamp):
    """2026-11-11T12:54:10.549047Z or 2026-11-11T12:54:10Z (UTC) to unix ms."""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z", stamp)
    if not m:
        return None
    y, mo, d, h, mi, s, f = m.groups()
    import calendar
    sec = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s), 0, 0, 0))
    return sec * 1000 + (int((f or "0")[:3].ljust(3, "0")))


ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------------------
# Loading

class Session:
    def __init__(self, a):
        self.a = a
        self.notes = []          # what could not be read, shown on the page
        self.perceived = defaultdict(list)   # resident -> [(sent ms, distance to the player, doing)]
        self.sources = []        # what was read
        self.load_world()
        self.load_logs()
        self.load_capture()
        self.pick_player()
        self.load_journal()
        self.load_module_log()

    # -- the authority
    def load_world(self):
        a = self.a
        self.sql = Sql(a.db)
        q = self.sql.rows
        try:
            w = q("SELECT * FROM world")
        except (RuntimeError, urllib.error.URLError, OSError) as e:
            raise SystemExit(f"play_report: cannot read {a.db} as its owner ({e}); the report needs the world, paused or running") from None
        if not w:
            raise SystemExit(f"play_report: {a.db} has no world row")
        self.world = flat_row(w[0])
        self.chars = {r["id"]: r for r in map(flat_row, q("SELECT * FROM character"))}
        self.presence = [flat_row(r) for r in q("SELECT * FROM presence")]
        self.chronicle = sorted((flat_row(r) for r in q("SELECT * FROM chronicle")), key=lambda r: (r["at_ms"], r["id"]))
        exp = {r["id"]: r for r in map(flat_row, q("SELECT * FROM experience"))}
        self.exp_sql_ids = set(exp)
        self.bodies_now = {r["id"]: r for r in map(flat_row, q("SELECT * FROM body"))}
        self.exp = exp
        self.skill_use = {}
        try:
            self.skill_use = {r["id"]: r for r in map(flat_row, q("SELECT * FROM skill_use"))}
        except RuntimeError as e:
            self.notes.append(f"skill_use not read: {e}")
        # Earshot and the address rule from the world's installed laws, not the repository's.
        self.hearing_m, self.address_m = None, ADDRESS_M
        try:
            src = next((r["source"] for r in q("SELECT name, source FROM script") if r["name"] == "skills"), "")
            m = re.search(r"fn hearing_of_people\(\)\s*\{\s*([\d.]+)", src)
            self.hearing_m = float(m.group(1)) if m else None
            m = re.search(r"\baddress_m:\s*([\d.]+)", src)
            self.address_m = float(m.group(1)) if m else ADDRESS_M
        except (RuntimeError, KeyError):
            pass
        self.paused = bool(self.world.get("paused"))
        self.sources.append(f"owner SQL on {a.db}: world, character, presence, body, {len(self.chronicle)} chronicle rows, {len(exp)} experience rows still held")

    def name(self, cid):
        c = self.chars.get(cid)
        return c["name"] if c else f"#{cid}"

    def game_to_ms(self, day, hh, mm):
        """A prompt's `day D HH:MM` to unix ms. The world's clock starts at 07:00 of day 1."""
        day_ms = self.world.get("day_ms") or 720000
        minutes = (day - 1) * 1440 + hh * 60 + mm - 7 * 60
        return self.world["epoch_ms"] + minutes * day_ms / 1440

    # -- logs
    def load_logs(self):
        d = Path(self.a.logs) if self.a.logs else None
        self.client_log, self.mind_log = [], []
        if d and (d / "client.log").exists():
            for line in (d / "client.log").read_text(errors="replace").splitlines():
                line = ANSI.sub("", line)
                m = re.match(r"(\S+Z)\s+(\w+)\s+(\S+?):\s(.*)", line)
                if m:
                    self.client_log.append({"ms": iso_ms(m.group(1)), "level": m.group(2), "target": m.group(3), "msg": m.group(4)})
                elif line.strip():
                    self.client_log.append({"ms": None, "level": "", "target": "", "msg": line})
            self.sources.append(f"client log {d / 'client.log'} ({len(self.client_log)} lines)")
        else:
            self.notes.append("No client.log in --logs.")
        if d and (d / "mind.log").exists():
            for line in (d / "mind.log").read_text(errors="replace").splitlines():
                m = re.match(r"\[(\S+Z)\s+(\w+)\s+(\S+)\]\s(.*)", ANSI.sub("", line))
                if m:
                    self.mind_log.append({"ms": iso_ms(m.group(1)), "level": m.group(2), "target": m.group(3), "msg": m.group(4)})
            self.sources.append(f"mind log {d / 'mind.log'} ({len(self.mind_log)} lines; times to the second)")
        else:
            self.notes.append("No mind.log in --logs.")
        # The client's 2 s `island perf` line: frame times, and where my body was drawn.
        self.frames, self.my_track = [], []
        for l in self.client_log:
            m = re.match(r"island perf: mean ([\d.]+) ms \((\d+) fps\), worst ([\d.]+) ms.*? at \((-?[\d.]+), (-?[\d.]+)\)", l["msg"])
            if m and l["ms"]:
                self.frames.append((l["ms"], float(m.group(1)), float(m.group(3))))
                self.my_track.append((l["ms"], float(m.group(4)), float(m.group(5))))
        ids = [re.match(r"connected as ([0-9a-f]{64})", l["msg"]) for l in self.mind_log]
        ids = [m.group(1) for m in ids if m]
        self.mind_identity = ids[-1] if ids else None
        self.mind_connects = len(ids)

    # -- recorders
    def load_capture(self):
        self.cap = Path(self.a.capture) if self.a.capture else None
        self.stills, self.client_state, self.client_events, self.video, self.positions = [], [], [], None, defaultdict(list)
        self.rec_meta, self.skill_use_kept, self.captures = {}, {}, []
        if not self.cap or not self.cap.exists():
            self.notes.append("Nothing was recorded for this session (no --capture): no stills, no video, no client state, and no rows kept before eviction.")
            return
        cdir = self.cap / "client" if (self.cap / "client").exists() else self.cap
        for p in sorted(glob.glob(str(cdir / "stills" / "*"))):
            m = re.match(r"(\d{13})", Path(p).name)
            if m and p.lower().endswith((".png", ".jpg", ".jpeg")):
                self.stills.append((int(m.group(1)), Path(p)))
        f = cdir / "captures.csv"
        if f.exists():
            for line in f.read_text().splitlines():
                p = line.split(",")
                if len(p) == 4:
                    try:
                        self.captures.append((int(p[0]), int(p[1]), float(p[2]), int(p[3])))
                    except ValueError:
                        pass
        for name, into in (("state.jsonl", self.client_state), ("events.jsonl", self.client_events)):
            f = cdir / name
            if f.exists():
                for line in f.open(errors="replace"):
                    try:
                        into.append(json.loads(line))
                    except ValueError:
                        pass
        for v in ("screen.mov", "screen.mp4", "screen.mkv"):
            if (self.cap / v).exists() and (self.cap / v).stat().st_size > 0:
                self.video = self.cap / v
        meta = self.cap / "recorder.json"
        if meta.exists():
            try:
                self.rec_meta = json.loads(meta.read_text())
            except ValueError:
                pass
        kept = 0
        self.skill_use_kept = {}
        held_chronicle = {c["id"] for c in self.chronicle}
        recorded_chronicle = {}
        f = self.cap / "authority.jsonl"
        if f.exists():
            for line in f.open(errors="replace"):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("table") == "experience":
                    row = r["row"]
                    if row["id"] not in self.exp:
                        kept += 1
                        self.exp[row["id"]] = row
                elif r.get("table") == "skill_use":
                    self.skill_use_kept[r["row"]["id"]] = r["row"]
                elif r.get("table") == "chronicle":
                    # The authority updates a chronicle row in place (merged repeats), so the
                    # world's own row wins; recorded rows only fill in ones it no longer has.
                    if r["row"]["id"] not in held_chronicle:
                        recorded_chronicle[r["row"]["id"]] = r["row"]
                elif r.get("table") == "body":
                    for b in r["rows"]:
                        self.positions[b["id"]].append((r["t"], b["x"], b["y"]))
            self.chronicle = sorted(self.chronicle + list(recorded_chronicle.values()), key=lambda c: (c["at_ms"], c["id"]))
        for k, v in self.skill_use_kept.items():
            self.skill_use.setdefault(k, v)   # the newest recorded copy, where the world dropped it
        self.sources.append(f"capture {self.cap}: {len(self.stills)} stills, {len(self.client_state)} client state samples, {len(self.client_events)} client events, "
                            f"video {'yes' if self.video else 'no'}, {kept} experience rows kept that the world has since evicted, positions for {len(self.positions)} characters")
        if self.rec_meta.get("screen_note"):
            self.notes.append(f"Screen recording: {self.rec_meta['screen_note']}")

    # -- who played, and when
    def pick_player(self):
        pid = self.a.player
        if not pid:
            for l in reversed(self.client_log):
                m = re.search(r"playing character #(\d+)", l["msg"])
                if m:
                    pid = int(m.group(1))
                    break
        if not pid:
            pid = next((st["me"] for st in reversed(self.client_state) if st.get("me")), None)
        if not pid and self.presence:
            pid = max(self.presence, key=lambda p: p.get("changed_ms") or 0)["id"]
            self.notes.append(f"The played character was taken from the presence table (#{pid}); pass --player if that is wrong.")
        if not pid:
            raise SystemExit("play_report: cannot tell which character the owner played; pass --player")
        self.me = int(pid)
        self.me_name = self.name(self.me)
        pres = next((p for p in self.presence if p["id"] == self.me), None)
        self.pres = pres
        joined = next((l["ms"] for l in self.client_log if l["ms"] and "playing character" in l["msg"]), None)
        arrival = next((c["at_ms"] for c in self.chronicle if c["kind"] == "arrival" and c["a"] == self.me), None)
        self.start = joined or arrival or min((e["at_ms"] for e in self.exp.values() if e["observer"] == self.me), default=self.world["epoch_ms"])
        self.arrival = arrival
        end = None
        if pres and not pres.get("present") and pres.get("changed_ms", 0) > self.start:
            end = pres["changed_ms"]
        if end is None:
            last = [l["ms"] for l in self.client_log if l["ms"]]
            end = max(last) if last else max((e["at_ms"] for e in self.exp.values()), default=self.start)
        self.end = end
        self.takeover = pres.get("control_ms") if pres and pres.get("ai") and pres.get("control_ms", 0) >= end else None
        if self.me not in self.positions and self.my_track:
            self.positions[self.me] = list(self.my_track)

    # -- the mind journal
    def load_journal(self):
        self.journal = []
        d = Path(self.a.journal) if self.a.journal else None
        if not d or not d.exists():
            self.notes.append("No journal directory: no model calls, costs or hearers from prompts.")
            return
        for f in sorted(d.glob("*.jsonl")):
            for line in f.open(errors="replace"):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                restore(r, d)
                r["_file"] = f.name
                self.journal.append(r)
        self.journal.sort(key=lambda r: r.get("at_ms", 0))
        self.sources.append(f"journal {d} ({len(self.journal)} model calls)")
        by_name = {c["name"]: i for i, c in self.chars.items()}
        for r in self.journal:
            r["_who"] = by_name.get(r.get("actor"))
            if r["_who"] is None or r["_who"] == self.me:
                continue
            m = re.search(r"# What you perceive right now\n(\{.*?\})\s*(?:\n|$)", self.prompt(r))
            if not m:
                continue
            try:
                seen = json.loads(m.group(1))
            except ValueError:
                continue
            sent = r.get("at_ms", 0) - (r.get("latency_ms") or 0) - (r.get("queue_wait_ms") or 0)
            for c in seen.get("creatures") or []:
                if c.get("id") == self.me and c.get("dist") is not None:
                    self.perceived[r["_who"]].append((sent, float(c["dist"]), c.get("doing")))
        for v in self.perceived.values():
            v.sort()

    def load_module_log(self):
        self.module_log = []
        f = Path(self.a.logs) / "module.log.jsonl" if self.a.logs else None
        text = None
        if f and f.exists():
            text = f.read_text(errors="replace")
        else:
            try:
                r = subprocess.run(["docker", "exec", "-i", CONTAINER, "spacetime", "logs", "-s", "local", self.a.db, "--format", "json"], capture_output=True, text=True, timeout=60)
                if r.returncode == 0:
                    text = r.stdout
            except (OSError, subprocess.TimeoutExpired):
                text = None
        if text is None:
            self.notes.append("The module's log could not be read.")
            return
        for line in text.splitlines():
            if line.startswith("{"):
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                self.module_log.append({"ms": x.get("ts", 0) // 1000, "level": x.get("level", ""), "function": x.get("function", ""), "msg": x.get("message", ""), "file": x.get("filename", ""), "line": x.get("line_number")})
        self.sources.append(f"module log of {self.a.db} ({len(self.module_log)} lines)")

    # -- helpers over the journal
    def prompt(self, r):
        msgs = (r.get("request") or {}).get("messages") or []
        return "\n".join(m.get("content") or "" for m in msgs if m.get("role") != "system")

    def say_of(self, r):
        """What a reply said, and to whom: talk replies carry `say` as text, others {text,to}."""
        try:
            j = json.loads(r.get("reply") or "")
        except ValueError:
            return None, None
        if not isinstance(j, dict):
            return None, None
        s = j.get("say")
        if isinstance(s, str):
            return s, j.get("to")
        if isinstance(s, dict):
            return s.get("text"), s.get("to")
        return None, None


# ---------------------------------------------------------------------------------------
# Analysis

def at_pos(s, cid, ms):
    """Where a character stood at `ms`: the recorder's samples, else None."""
    p = s.positions.get(cid)
    if not p:
        return None
    i = bisect.bisect_left(p, (ms, -1e9, -1e9))
    best = min((p[j] for j in (i - 1, i) if 0 <= j < len(p)), key=lambda q: abs(q[0] - ms))
    return (best[1], best[2]) if abs(best[0] - ms) < 5000 else None


def perceived_dist(s, who, ms, within=20000):
    """The distance to the player in `who`'s prompt nearest `ms` (sent time), and how far off."""
    p = s.perceived.get(who)
    if not p:
        return None
    best = min(p, key=lambda q: abs(q[0] - ms))
    return (best[1], best[0] - ms) if abs(best[0] - ms) <= within else None


def quoted(text):
    m = re.search(r"“(.*)”", text or "")
    return m.group(1) if m else None


def analyse(s):
    me = s.me
    lo, hi = s.start - 2000, s.end + 1000
    ai = ("0x" + s.mind_identity) if s.mind_identity else None
    mine = [e for e in s.exp.values() if e["observer"] == me and lo <= e["at_ms"] <= hi and (not ai or str(e.get("controller") or "").lower() != ai)]
    mine.sort(key=lambda e: (e["at_ms"], e["id"]))
    out = {"lines": [], "events": [], "quiet": [], "refused": [], "fights": [], "errors": [], "approaches": []}

    # Model calls by game-time references: experience ids and texts shown in prompts.
    ref_id = defaultdict(set)      # experience id -> {(observer id, text)}
    ref_text = []                  # (observer id, ms, text line, journal entry)
    for r in s.journal:
        who = r.get("_who")
        if who is None:
            continue
        for m in re.finditer(r"^\s*-?\s*\[(?:(\d+)\]\s*day (\d+) (\d\d):(\d\d)|day (\d+) (\d\d):(\d\d)\])\s*(.*)$", s.prompt(r), re.M):
            if m.group(1):
                ref_id[int(m.group(1))].add((who, m.group(8)))
                ms = s.game_to_ms(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            else:
                ms = s.game_to_ms(int(m.group(5)), int(m.group(6)), int(m.group(7)))
            ref_text.append((who, ms, m.group(8), r))

    talk = [r for r in s.journal if r.get("purpose") == "talk"]

    def answering(r):
        p = s.prompt(r)
        m = re.search(r"# What you are answering\n(.*)", p)
        conv = re.search(r"# The conversation so far\n(.*?)(?:\n\n|\n# |\Z)", p, re.S)
        return (m.group(1) if m else ""), (conv.group(1).splitlines() if conv else [])

    # Speech the player heard, and lines addressed to the player.
    to_me = [e for e in mine if e["kind"] == "speech" and e["object"] == me and e["subject"] != me]
    heard = [e for e in mine if e["kind"] == "speech" and e["subject"] != me]

    def source_of(e):
        """The model call that produced a resident's line: same speaker, text in the reply."""
        q = quoted(e["text"]) or ""
        best = None
        for r in s.journal:
            if r.get("_who") != e["subject"] or abs(r.get("at_ms", 0) - e["at_ms"]) > 5000:
                continue
            t, _ = s.say_of(r)
            if t and (t.strip() == q.strip() or (q and q[:40] in t)):
                if best is None or abs(r["at_ms"] - e["at_ms"]) < abs(best["at_ms"] - e["at_ms"]):
                    best = r
        return best

    def trigger(r):
        p = s.prompt(r)
        m = re.search(r"# Why you are thinking now\n(.*?)(?:\n\n|\n# |\Z)", p, re.S)
        return " ".join(m.group(1).split())[:300] if m else ""

    said = [e for e in mine if e["kind"] == "said"]
    for i, e in enumerate(said):
        text = quoted(e["text"]) or e["text"]
        t = e["at_ms"]
        nxt = said[i + 1]["at_ms"] if i + 1 < len(said) else None
        line = {"id": e["id"], "ms": t, "text": text, "to": e["object"], "x": e["x"], "y": e["y"], "repeat": None}
        rep = next((x for x in mine if x["kind"] == "repeat" and x["at_ms"] == t), None)
        if rep:
            line["repeat"] = rep["text"]
        # Hearers: rows written in the same instant about this line (held, kept or shown in prompts).
        hearers = {}
        same = [x for x in s.exp.values() if x["at_ms"] == t and x["subject"] == me and x["observer"] != me and x["kind"] == "speech"]
        for x in same:
            hearers[x["observer"]] = {"id": x["id"], "salience": x.get("salience"), "how": "row"}
        ids = sorted(set(range(e["id"] + 1, e["id"] + 40)))
        # A prompt line about this line carries the speaker's tag ({someone=#26} or {Name=#26})
        # and no addressee of its own ("said:" or "said to you:").
        speaker = re.compile(r"^(?:An? [\w ]*?stranger|An? \w+|%s) said(?: to [^:“]+)?: “" % re.escape(s.me_name))
        def mine_line(txt):
            return quoted(txt) == text and re.search(r"=#%d\b" % me, txt) and speaker.match(txt)
        for k in ids:
            for who, txt in ref_id.get(k, ()):
                if mine_line(txt):
                    hearers.setdefault(who, {"id": k, "salience": None, "how": "prompt"})
        minute = (s.world.get("day_ms") or 720000) / 1440
        for who, ms, txt, r in ref_text:
            if abs(ms - t) <= minute * 1.2 and who not in hearers and mine_line(txt):
                hearers[who] = {"id": None, "salience": None, "how": "prompt (no id)"}
        # The line's rows have consecutive ids (said, repeat, then hearers nearest first). Ids in
        # that block that nothing explains were deleted (consolidation, death); hearers seen
        # only in id-less prompts fill such gaps.
        known = {h["id"] for h in hearers.values() if h["id"]}
        top = max(known | {e["id"] + (1 if rep else 0)})
        gaps = [k for k in range(e["id"] + 1, top) if k not in known and k not in s.exp and not ref_id.get(k)]
        idless = [w for w, h in hearers.items() if h["id"] is None]
        if len(idless) == len(gaps) == 1:
            hearers[idless[0]]["id"], hearers[idless[0]]["how"] = gaps[0], "prompt (id inferred from the gap)"
            gaps = []
        line["unknown_ids"] = gaps
        nxt_row = s.exp.get(top + 1)
        line["block_open"] = not (nxt_row and nxt_row["at_ms"] != t) and top + 1 not in s.exp
        line["block_next"] = top + 1
        # Distances: the recorder's positions, else what the hearer's own prompts perceived.
        for who, h in hearers.items():
            h["name"] = s.name(who)
            p0, p1 = at_pos(s, who, t), (e["x"], e["y"])
            if p0:
                h["dist"] = ((p0[0] - p1[0]) ** 2 + (p0[1] - p1[1]) ** 2) ** 0.5
            else:
                pd = perceived_dist(s, who, t)
                if pd:
                    h["dist"], h["dist_how"] = pd[0], f"perceived {abs(pd[1]) / 1000:.0f} s {'before' if pd[1] < 0 else 'after'}"
            h["why_no_turn"] = None
        near = []
        if s.positions:
            for cid in s.positions:
                if cid == me:
                    continue
                p0 = at_pos(s, cid, t)
                if p0:
                    d = ((p0[0] - e["x"]) ** 2 + (p0[1] - e["y"]) ** 2) ** 0.5
                    if d <= (s.hearing_m or 12.0) + 0.5:
                        near.append((d, cid))
        line["earshot"] = sorted(near)
        sal = [h["salience"] for h in hearers.values() if h.get("salience") is not None]
        line["addressed"] = bool(e["object"]) or any(v >= 0.8 for v in sal)
        line["hearers"] = hearers
        # Conversation turns: talk calls by anyone answering this line or carrying it.
        turns = []
        for r in talk:
            if r["at_ms"] < t or r["at_ms"] > t + REPLY_WINDOW_S * 1000:
                continue
            ans, conv = answering(r)
            hd = re.search(r"^# You and .*\(#(\d+)\)\s*$", s.prompt(r), re.M)
            if hd and int(hd.group(1)) != me:
                continue
            if quoted(ans) == text or any(quoted(c) == text for c in conv):
                turns.append({"who": r["_who"], "name": r.get("actor"), "ms": r["at_ms"], "latency": r.get("latency_ms"), "model": r.get("model"), "answering": quoted(ans) == text})
        line["turns"] = turns
        # Parked lines (the listener was deliberating) and released ones, from the mind log.
        line["parked"] = []
        for l in s.mind_log:
            if l["ms"] is None or l["ms"] < t - 1500 or l["ms"] > t + 2500:
                continue
            m = re.match(r"(.+?) is deliberating; the line from (.+?) waits", l["msg"])
            if m and m.group(2) == s.me_name:
                line["parked"].append(m.group(1))
        line["released"] = []
        for l in s.mind_log:
            if l["ms"] and t - 1500 <= l["ms"] <= t + REPLY_WINDOW_S * 1000:
                m = re.match(r"(.+?)'s deliberation ended: the line from (.+?) gets its turn", l["msg"])
                if m and m.group(2) == s.me_name and m.group(1) in line["parked"]:
                    line["released"].append((m.group(1), l["ms"]))
        line["settled"] = []
        for l in s.mind_log:
            if l["ms"] and t - 1500 <= l["ms"] <= t + 2500:
                m = re.match(r"(.+?) hears (.+?) but they settled", l["msg"])
                if m and m.group(2) == s.me_name:
                    line["settled"].append(m.group(1))
        took = {tn["name"] for tn in turns}
        for who, h in hearers.items():
            if h["name"] in took:
                h["why_no_turn"] = None
            elif h["name"] in line["parked"]:
                h["why_no_turn"] = "parked while deliberating"
            elif h["name"] in line["settled"]:
                h["why_no_turn"] = "settled exchange: no turn"
            elif (h.get("salience") or 0.45) < 0.8 and not e["object"]:
                h["why_no_turn"] = "no turn: unaddressed, and the mind service took none (its gate for overheard lines needs the listener to care; such a pass is not logged)"
            else:
                h["why_no_turn"] = "no turn (reason not logged)"
        line["next_ms"] = nxt
        out["lines"].append(line)

    # Replies: each resident line to the player, matched to the player's lines it answers.
    for e in to_me:
        src = source_of(e)
        kind = src.get("purpose") if src else None
        answered = []
        if src and kind == "talk":
            ans, conv = answering(src)
            texts = {quoted(c) for c in conv} | {quoted(ans)}
            answered = [l for l in out["lines"] if l["text"] in texts and l["ms"] <= e["at_ms"]]
        elif src:
            p = s.prompt(src)
            answered = [l for l in out["lines"] if l["ms"] <= e["at_ms"] and f"“{l['text']}”" in p]
        if not src:
            answered = [l for l in out["lines"] if 0 <= e["at_ms"] - l["ms"] <= REPLY_WINDOW_S * 1000]
        # A reply answers lines its speaker heard, said since it last spoke to the player.
        prev = max((x["at_ms"] for x in to_me if x["subject"] == e["subject"] and x["at_ms"] < e["at_ms"]), default=0)
        answered = [l for l in answered if l["ms"] > prev and (e["subject"] in l["hearers"] or not l["hearers"])]
        follow_up = bool(prev) and e["at_ms"] - prev < 90000
        rep = {"id": e["id"], "ms": e["at_ms"], "who": e["subject"], "name": s.name(e["subject"]), "text": quoted(e["text"]) or e["text"],
               "via": kind, "model": src.get("model") if src else None, "call_latency": src.get("latency_ms") if src else None,
               "trigger": trigger(src) if src and kind != "talk" else "", "answers": [l["id"] for l in answered]}
        for l in answered:
            l.setdefault("replies", []).append({**rep, "after": (e["at_ms"] - l["ms"]) / 1000})
        if not answered and follow_up:
            rep["follow_up"] = True
        elif not answered:
            out["approaches"].append(rep)
        elif kind != "talk":
            rep["half"] = True
            out["approaches"].append(rep)
    for l in out["lines"]:
        l.setdefault("replies", [])

    # Gestures to the player (nods, waves): the residents' own approaches.
    for e in mine:
        if e["kind"] == "gesture" and e["object"] == me and e["subject"] != me:
            out["approaches"].append({"id": e["id"], "ms": e["at_ms"], "who": e["subject"], "name": s.name(e["subject"]), "text": e["text"], "via": "gesture", "answers": []})
    out["approaches"].sort(key=lambda r: r["ms"])

    # Fights and deaths: the chronicle, the player's own rows, and blows seen in victims' prompts.
    blows = []
    for who, ms, txt, r in ref_text:
        m = re.search(r"(.+?) attacked you \((\d+) damage\)", txt)
        if m and ("#%d" % me in txt or s.me_name in m.group(1)):
            blows.append((round(ms / 500) * 500, who, int(m.group(2))))
    for e in s.exp.values():
        m = re.search(r"attacked you \((\d+) damage\)", e["text"] or "")
        if m and e["subject"] == me and lo <= e["at_ms"] <= hi:
            blows.append((e["at_ms"], e["observer"], int(m.group(1))))
    seen_b = set()
    out["blows"] = []
    for b in sorted(blows):
        key = (b[1], b[2], b[0] // 2000)
        if key not in seen_b:
            seen_b.add(key)
            out["blows"].append({"ms": b[0], "victim": b[1], "name": s.name(b[1]), "damage": b[2]})
    fight_kinds = {"attack", "yield", "killing", "death", "flee"}
    for c in s.chronicle:
        if c["kind"] in fight_kinds and lo <= c["at_ms"] <= hi and (me in (c["a"], c["b"]) or c["kind"] in ("killing", "death")):
            out["fights"].append(c)
    for e in mine:
        if e["kind"] in ("attacked", "yield", "death", "hurt", "wounded") and e["subject"] != me:
            out["fights"].append({"id": "e%d" % e["id"], "at_ms": e["at_ms"], "kind": "felt " + e["kind"], "a": e["subject"], "b": me, "text": e["text"]})
    out["fights"].sort(key=lambda c: c["at_ms"])
    first_strike = next((c for c in out["fights"] if c["kind"] == "attack" and c["a"] == me), None)
    if first_strike:
        victim = first_strike["b"]
        last_word = max((x for x in to_me if x["subject"] == victim and x["at_ms"] <= first_strike["at_ms"]), key=lambda x: x["at_ms"], default=None)
        out["first_strike"] = {"row": first_strike, "victim": victim, "after_greeting": (first_strike["at_ms"] - last_word["at_ms"]) / 1000 if last_word else None, "greeting": last_word}

    # Acts: refused and done.
    for e in mine:
        if e["kind"] == "act" and e["subject"] == me:
            refused = "did not work out" in e["text"] or "refused" in e["text"].lower() or "failed" in e["text"].lower()
            (out["refused"] if refused else out["events"]).append({"ms": e["at_ms"], "text": e["text"], "src": "authority"})
    for l in s.module_log:
        if l["level"].lower() in ("error", "panic") and lo <= l["ms"] <= hi and l["function"] in PLAYER_REDUCERS:
            out["refused"].append({"ms": l["ms"], "text": f"{l['function']}: {l['msg']}", "src": "module log"})
    out["skills"] = sorted((u for u in s.skill_use.values() if u["actor"] == me and lo <= u["at_ms"] <= hi and u.get("source") == "player"), key=lambda u: (u["at_ms"], u["id"]))
    for u in out["skills"]:
        if str(u.get("outcome") or "").startswith("refused"):
            tgt = f" on {s.name(u['target'])}" if u.get("target") else ""
            out["refused"].append({"ms": u["at_ms"], "text": f"{u['skill']}{tgt}: {u['outcome']}", "src": "authority (skill_use)"})
    for l in ([] if any(ev.get("kind") == "refused" for ev in s.client_events) else s.client_log):
        m = re.match(r"(\w+) (refused|failed): (.*)", l["msg"])
        if m and l["ms"] and lo <= l["ms"] <= hi and l["level"] == "WARN":
            out["refused"].append({"ms": l["ms"], "text": f"{m.group(1)}: {m.group(3)}", "src": "client log"})
    for ev in s.client_events:
        if ev.get("kind") == "refused" and lo <= ev.get("t", 0) <= hi:
            out["refused"].append({"ms": ev["t"], "text": f"{ev.get('reducer')}: {ev.get('reason')}", "src": "client"})
    out["refused"].sort(key=lambda r: r["ms"])
    # Repeats of one refusal close together are one row with a count.
    merged = []
    for r in out["refused"]:
        # The client and the module log report the same reducer refusal: one row, both sources.
        twin = next((m for m in merged[-6:] if m["src"] != r["src"] and abs(m["until"] - r["ms"]) < 2000
                     and m["text"].split(": ", 1)[-1] == r["text"].split(": ", 1)[-1]), None)
        if twin:
            if r["src"] not in twin["src"]:
                twin["src"] += " + " + r["src"]
            continue
        last = merged[-1] if merged else None
        if last and last["text"] == r["text"] and r["ms"] - last["until"] < 10000:
            last["n"] += 1
            last["until"] = r["ms"]
            continue
        merged.append({**r, "n": 1, "until": r["ms"]})
    out["refused"] = merged

    # Quiet stretches: no word and no act from the player.
    acts = sorted([l["ms"] for l in out["lines"]] + [r["ms"] for r in out["refused"]] + [r["until"] for r in out["refused"]] + [r["ms"] for r in out["events"]]
                  + [c["at_ms"] for c in out["fights"] if c.get("a") == me and c["kind"] in ("attack", "killing")]
                  + [u["at_ms"] for u in out["skills"] if u["skill"] not in MOVES]
                  + [ev["t"] for ev in s.client_events if lo <= ev.get("t", 0) <= hi and (ev.get("kind") == "say" or (ev.get("kind") == "call" and ev.get("reducer") not in ("move", "face", "join")))])
    # The silence clock starts when the first view is in (loading can take minutes).
    shown = next((l["ms"] for l in s.client_log if l["ms"] and l["msg"].startswith("loading: the first view is in")), None)
    begin = max(s.start, shown or s.start)
    marks = [begin] + [m for m in acts if m >= begin] + [s.end]
    for a_, b_ in zip(marks, marks[1:]):
        if (b_ - a_) / 1000 >= QUIET_S:
            near = [x for x in heard if a_ < x["at_ms"] < b_]
            moves = [u for u in out["skills"] if a_ < u["at_ms"] < b_]
            seen = {}
            for who, ser in s.perceived.items():
                ds = [d for t_, d, _ in ser if a_ <= t_ <= b_]
                if ds:
                    seen[who] = (min(ds), max(ds))
            out["quiet"].append({"from": a_, "to": b_, "heard": near, "moves": moves, "seen_by": seen})
    out["quiet"].sort(key=lambda q: q["from"])

    # Errors.
    for l in s.client_log:
        if l["level"] in ("WARN", "ERROR") and (l["ms"] is None or lo - 60000 <= l["ms"] <= hi + 60000):
            out["errors"].append({"ms": l["ms"], "src": "client", "level": l["level"], "msg": f"{l['target']}: {l['msg']}", "benign": any(p.search(l["msg"]) for p in BENIGN)})
    for l in s.mind_log:
        if l["level"] in ("WARN", "ERROR") and lo - 60000 <= l["ms"] <= hi + 60000:
            out["errors"].append({"ms": l["ms"], "src": "mind service", "level": l["level"], "msg": l["msg"], "benign": False})
    for l in s.module_log:
        if l["level"].lower() in ("error", "panic") and lo - 60000 <= l["ms"] <= hi + 60000:
            out["errors"].append({"ms": l["ms"], "src": "module", "level": l["level"].upper(), "msg": f"{l['function']}: {l['msg']}", "benign": False})
    for r in s.journal:
        if r.get("error") and lo <= r.get("at_ms", 0) <= hi:
            out["errors"].append({"ms": r["at_ms"], "src": "model call", "level": "ERROR", "msg": f"{r.get('actor')} {r.get('purpose')} on {r.get('model')}: {str(r['error'])[:300]}", "benign": False})
    out["errors"].sort(key=lambda r: r["ms"] or 0)
    out["mine"] = mine
    out["heard"] = heard
    out["to_me"] = to_me
    return out


def costs(s):
    """Model calls in the session (arrival to quit) and in the whole run, by purpose and model."""
    rows = {}
    for label, lo, hi in (("session", s.start, s.end), ("run", -1, 1 << 62)):
        by = defaultdict(lambda: {"calls": 0, "prompt": 0, "completion": 0, "cached": 0, "usd": 0.0, "unpriced": 0, "errors": 0, "lat": [], "queue": []})
        for r in s.journal:
            at = r.get("at_ms", 0)
            if not lo <= at <= hi:
                continue
            who = r.get("_who")
            kind = (s.chars.get(who) or {}).get("kind", "?") if who else "?"
            whom = "player's character" if who == s.me else ("people" if kind == "person" else "animals" if kind != "?" else "?")
            for key in ((r.get("purpose"), r.get("model")), ("all", "")):
                b = by[key]
                b["calls"] += 1
                p, c, k = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0
                b["prompt"] += p
                b["completion"] += c
                b["cached"] += k
                usd = cost(r.get("model"), p, c, k)
                if usd is None:
                    b["unpriced"] += 1
                else:
                    b["usd"] += usd
                b["errors"] += 1 if r.get("error") else 0
                b["lat"].append(r.get("latency_ms") or 0)
                b["queue"].append(r.get("queue_wait_ms") or 0)
            b = by[("by", whom)]
            b["calls"] += 1
            b["usd"] += cost(r.get("model"), r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0) or 0
        rows[label] = by
    return rows


# ---------------------------------------------------------------------------------------
# The page

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1c1a;--mut:#6b675f;--line:#e4e0d8;--card:#fff;--acc:#2f5d8a;--warn:#a2401b;--ok:#2e6b3a;--hl:#fff3c4;--chip:#efece6}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ecebe7;--mut:#9d998f;--line:#2e2d2a;--card:#1f1e1c;--acc:#8db7e0;--warn:#f08a62;--ok:#86c795;--hl:#3b3418;--chip:#2a2926}}
:root[data-theme=dark]{--bg:#161615;--fg:#ecebe7;--mut:#9d998f;--line:#2e2d2a;--card:#1f1e1c;--acc:#8db7e0;--warn:#f08a62;--ok:#86c795;--hl:#3b3418;--chip:#2a2926}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 80px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px;padding-top:10px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}.mut{color:var(--mut)}.warn{color:var(--warn)}.ok{color:var(--ok)}code{font:12.5px ui-monospace,Menlo,monospace;background:var(--chip);padding:1px 4px;border-radius:4px}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{font-weight:600;color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.t{font-variant-numeric:tabular-nums;white-space:nowrap}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.card b{display:block;font-size:20px}.card span{color:var(--mut);font-size:12.5px}
ul.find{padding-left:18px}ul.find li{margin:5px 0}.chip{display:inline-block;background:var(--chip);border-radius:10px;padding:0 7px;font-size:12px;margin:1px 2px 1px 0}
.tl{display:grid;grid-template-columns:96px 1fr;gap:0 10px}.tl>div{padding:6px 0;border-bottom:1px solid var(--line)}.tl .when{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px}
.k-say{border-left:3px solid var(--acc);padding-left:8px!important}.k-reply{border-left:3px solid var(--ok);padding-left:8px!important}.k-fight{border-left:3px solid var(--warn);padding-left:8px!important}.k-err{border-left:3px dashed var(--warn);padding-left:8px!important}.k-quiet{background:var(--hl);padding-left:8px!important}.k-other{padding-left:11px!important}
.thumb{width:150px;border-radius:6px;border:1px solid var(--line);cursor:zoom-in;display:block;margin-top:4px}.strip{display:flex;gap:6px;overflow-x:auto;padding:6px 0}.strip figure{margin:0;flex:0 0 auto}.strip img{height:96px;border-radius:5px;border:1px solid var(--line);cursor:zoom-in}.strip figcaption{font-size:11px;color:var(--mut);text-align:center}
video{width:100%;max-height:70vh;background:#000;border-radius:8px}#big{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:9}#big img{max-width:96vw;max-height:92vh}
.seek{cursor:pointer;color:var(--acc);text-decoration:underline dotted}details{margin:6px 0}summary{cursor:pointer;color:var(--mut)}
@media (max-width:640px){.tl{grid-template-columns:70px 1fr}.thumb{width:110px}}
"""

JS = """
function seek(s){var v=document.getElementById('vid');if(v){v.currentTime=Math.max(0,s);v.play();v.scrollIntoView({block:'center'})}}
function big(src){var b=document.getElementById('big');b.querySelector('img').src=src;b.style.display='flex'}
document.addEventListener('keydown',function(e){if(e.key==='Escape')document.getElementById('big').style.display='none'});
"""


def esc(x):
    return html.escape(str(x if x is not None else ""))


class Page:
    def __init__(self, s, an, out_dir):
        self.s, self.an, self.out = s, an, Path(out_dir)
        self.stills = []   # (ms, relative path)
        self.video_rel, self.video_start = None, None

    def copy_media(self):
        s = self.s
        if s.stills:
            d = self.out / "stills"
            d.mkdir(parents=True, exist_ok=True)
            for ms, p in s.stills:
                dst = d / p.name
                if not dst.exists():
                    shutil.copy2(p, dst)
                self.stills.append((ms, f"stills/{p.name}"))
        if s.video:
            dst = self.out / s.video.name
            if not dst.exists() or dst.stat().st_size != s.video.stat().st_size:
                try:
                    os.link(s.video, dst)
                except OSError:
                    shutil.copy2(s.video, dst)
            self.video_rel = s.video.name
            self.video_start = s.rec_meta.get("screen_start_ms")

    def still_near(self, ms, before=1500, after=4000):
        if not self.stills:
            return None
        keys = [m for m, _ in self.stills]
        i = bisect.bisect_left(keys, ms)
        cands = [self.stills[j] for j in (i - 1, i, i + 1) if 0 <= j < len(self.stills) and -before <= self.stills[j][0] - ms <= after]
        return min(cands, key=lambda c: abs(c[0] - ms - 500)) if cands else None

    def media(self, ms):
        bits = []
        if self.video_rel and self.video_start:
            off = (ms - self.video_start) / 1000
            if off >= 0:
                bits.append(f'<span class="seek" onclick="seek({off - 2:.1f})">▶ video {span(off)}</span>')
        st = self.still_near(ms)
        if st:
            bits.append(f'<img class="thumb" loading="lazy" src="{esc(st[1])}" onclick="big(this.src)" title="{clock(st[0])}">')
        return "".join(bits)

    def render(self):
        s, an = self.s, self.an
        self.copy_media()
        c = costs(s)
        P = []
        title = f"Play session: {s.me_name}, {time.strftime('%Y-%m-%d %H:%M', time.localtime(s.start / 1000))}"
        P.append(f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Play session report</title><style>{CSS}</style></head><body><main>")
        P.append(f"<h1>{esc(title)}</h1>")
        P.append(f"<p class=mut>World <code>{esc(s.a.db)}</code>, run <code>{esc(s.a.run)}</code>. {esc(s.me_name)} (#{s.me}) from {clock(s.start)} to {clock(s.end)} ({span((s.end - s.start) / 1000)}), local time. "
                 f"{'The world is paused.' if s.paused else 'The world was running when this was written.'} Written {time.strftime('%Y-%m-%d %H:%M:%S')} by <code>living/tools/play_report.py</code>.</p>")
        lines = an["lines"]
        unanswered = [l for l in lines if not l["turns"]]
        replies = [r for l in lines for r in l["replies"]]
        sess = c["session"]
        allc = sess.get(("all", ""), {"calls": 0, "usd": 0, "errors": 0})
        P.append("<div class=cards>")
        for v, k in ((len(lines), "lines said"), (f"{len(unanswered)}", "lines with no conversation turn"), (len(an["to_me"]), "lines said to you"),
                     (len(an["refused"]), "refused commands"), (len([f for f in an["fights"] if f["kind"] in ("attack", "killing") and f["a"] == s.me]), "your attacks and killings"),
                     (len([e for e in an["errors"] if not e["benign"]]), "errors and warnings"), (f"${allc['usd']:.3f}", f"model cost, {allc['calls']} calls")):
            P.append(f"<div class=card><b>{esc(v)}</b><span>{esc(k)}</span></div>")
        P.append("</div>")
        P.append("<h2>What stands out</h2><ul class=find>")
        for f in self.findings(c):
            P.append(f"<li>{f}</li>")
        P.append("</ul>")
        P.append(self.screen_section())
        P.append(self.lines_section())
        P.append(self.timeline_section())
        P.append(self.fights_section())
        P.append(self.refused_section())
        P.append(self.errors_section())
        P.append(self.cost_section(c))
        P.append(self.sources_section())
        P.append(f"</main><div id=big onclick=\"this.style.display='none'\"><img alt=''></div><script>{JS}</script></body></html>")
        out = self.out / "index.html"
        out.write_text("".join(P))
        (self.out / "report.json").write_text(json.dumps(self.facts(c), indent=1, default=str))
        return out

    # -- the summary
    def findings(self, c):
        s, an = self.s, self.an
        F = []
        for l in an["lines"]:
            hs = l["hearers"]
            names = ", ".join(esc(h["name"]) for h in sorted(hs.values(), key=lambda h: h["id"] or 1 << 40))
            crowd = len(hs) >= 2
            if not l["turns"]:
                first = min(l["replies"], key=lambda r: r["after"]) if l["replies"] else None
                tail = (f" {esc(first['name'])} spoke to you {first['after']:.1f} s later, from {esc(VIA.get(first['via'], 'a model call'))}"
                        + (f" whose trigger was: <i>{esc(first['trigger'][:140].rstrip('.'))}</i>" if first.get("trigger") else "") + ".") if first else " Nobody answered."
                F.append(f"<b>“{esc(l['text'])}”</b> at {clock(l['ms'])}: {'to ' + esc(s.name(l['to'])) if l['to'] else 'to no one'}{self.address_note(l)}; heard by {len(hs)}{' (a crowd)' if crowd else ''}: {names or 'nobody recorded'}"
                         f"{' (+%d deleted rows)' % len(l['unknown_ids']) if l['unknown_ids'] else ''}. <b>No conversation turn.</b>{tail}")
            else:
                parts = []
                for r in sorted(l["replies"], key=lambda r: r["ms"]):
                    parked = r["name"] in l["parked"]
                    parts.append(f"{esc(r['name'])} after <b>{r['after']:.1f} s</b>{' (parked: the listener was deliberating)' if parked else ''}")
                F.append(f"<b>“{esc(l['text'])}”</b> at {clock(l['ms'])}: {'to ' + esc(s.name(l['to'])) if l['to'] else 'to no one'}{self.address_note(l)}; heard by {len(hs)} ({names}); {len(l['turns'])} conversation turn(s); answers: {', '.join(parts) or 'none reached you'}.")
        fs = an.get("first_strike")
        if fs:
            g = fs["greeting"]
            F.append(f"<b>You struck {esc(s.name(fs['victim']))}</b> at {clock(fs['row']['at_ms'])}"
                     + (f", {fs['after_greeting']:.1f} s after {esc(s.name(fs['victim']))} spoke to you (“{esc((quoted(g['text']) or '')[:80])}”)" if g else "") + ".")
        for f in an["fights"]:
            if f["kind"] in ("killing",) and f["a"] == s.me:
                F.append(f"<b>{esc(f['text'])}</b> at {clock(f['at_ms'])}.")
            elif f["kind"] == "death" and f["a"] == s.me:
                F.append(f"<b>You died</b> at {clock(f['at_ms'])}: {esc(f['text'])}.")
        if an["blows"]:
            F.append("Blows the victims felt from you: " + ", ".join(f"{clock(b['ms'], False)} {esc(b['name'])} {b['damage']}" for b in an["blows"]) + ".")
        for q in sorted(an["quiet"], key=lambda q: q["from"] - q["to"])[:3]:
            sb = q["seen_by"]
            near = (f" Residents' prompts saw you at {min(v[0] for v in sb.values()):.0f}–{max(v[1] for v in sb.values()):.0f} m ({', '.join(esc(s.name(w)) for w in sorted(sb, key=lambda w: sb[w][0]))})." if sb else "")
            F.append(f"<b>Silent for {span((q['to'] - q['from']) / 1000)}</b> ({clock(q['from'])} → {clock(q['to'])}): you said nothing and acted on no one"
                     + (f" ({len(q['moves'])} dodge/jump)" if q["moves"] else "") + f"; you heard {len(q['heard'])} line(s)"
                     + (": " + "; ".join(f"{esc(s.name(h['subject']))} at {clock(h['at_ms'], False)}" for h in q["heard"][:4]) if q["heard"] else "") + "." + near)
        appr = [a for a in an["approaches"] if not a.get("half") and a["via"] != "gesture"]
        half = [a for a in an["approaches"] if a.get("half")]
        F.append(f"Unprompted approaches: {len(appr)} line(s) to you that answered nothing you said, {len([a for a in an['approaches'] if a['via'] == 'gesture'])} gesture(s) at you"
                 + (f"; {len(half)} reply(ies) came from a model call that only saw your line in passing" if half else "") + ".")
        if an["refused"]:
            cnt = Counter()
            for r in an["refused"]:
                cnt[r["text"]] += r["n"]
            F.append("Refused: " + "; ".join(f"{n}× <i>{esc(t)}</i>" for t, n in cnt.most_common(4)) + ".")
        errs = [e for e in an["errors"] if not e["benign"]]
        F.append(f"Errors: {len(errs)} ({', '.join(f'{n} {k}' for k, n in Counter(e['src'] for e in errs).items()) or 'none'}).")
        sess = c["session"]
        a = sess.get(("all", ""))
        if a:
            lat = sorted(a["queue"])
            F.append(f"Minds during the session: {a['calls']} model calls, {a['errors']} errors, queue wait p95 {lat[int(len(lat) * .95) - 1] if len(lat) > 1 else (lat or [0])[0]} ms, est. <b>${a['usd']:.3f}</b>.")
        if s.takeover:
            F.append(f"You quit at {clock(s.end)}; the minds took your character over at {clock(s.takeover)}. Later rows are theirs, not yours, and are left out.")
        lived = [l for l in s.mind_log if re.match(re.escape(s.me_name) + r" internalized \d+ lived experiences", l["msg"])]
        if lived:
            F.append(f"Your character's memory of the session: {esc(lived[-1]['msg'][:220])} ({clock(lived[-1]['ms'], False)}).")
        elif s.mind_log:
            F.append("Your character has not internalized what you lived: there is no <code>internalized … lived experiences</code> line in the mind log. It comes after the quit, unless the minds were stopped first.")
        if s.mind_connects > 1:
            F.append(f"<b class=warn>The mind service connected {s.mind_connects} times</b> (it exits when it loses the world; each restart is a gap in the minds).")
        return F

    def address_note(self, l):
        """What the hearers' rows say about addressing, and how close they stood."""
        hs = list(l["hearers"].values())
        sal = [h["salience"] for h in hs if h.get("salience") is not None]
        bits = []
        if sal:
            bits.append("addressed to some" if any(v >= 0.8 for v in sal) else f"unaddressed for the {len(sal)} hearer row(s) still held (salience {min(sal):.2f})")
        close = [h for h in hs if h.get("dist") is not None and h["dist"] <= self.s.address_m]
        if close:
            bits.append(f"{len(close)} within {self.s.address_m:.0f} m ({', '.join(esc(h['name']) + ' %.1f m' % h['dist'] for h in close)})")
        return (" — " + "; ".join(bits)) if bits else ""

    # -- sections
    def screen_section(self):
        s = self.s
        P = ["<h2>On screen</h2>"]
        if self.video_rel:
            P.append(f"<video id=vid controls preload=metadata src='{esc(self.video_rel)}'></video><p class=mut>The game's window, recorded by macOS <code>screencapture</code> from {clock(self.video_start)}. Times in the timeline below seek it.</p>")
        if self.stills:
            cap = s.captures
            cost = ""
            if cap:
                lag = sorted((c[1] - c[0]) / 1000 for c in cap)
                enc = sorted(c[2] for c in cap)
                mb = sum(c[3] for c in cap) / 1e6
                cost = f" Readback lag p50 {lag[len(lag) // 2]:.0f} ms; scaling and JPEG on the worker thread p50 {enc[len(enc) // 2]:.0f} ms; {mb:.1f} MB in all."
            us = sorted(st["rec_main_us"] for st in s.client_state if st.get("rec_main_us") is not None)
            if us:
                # Each state line covers 0.25 s; the recorder's own main-thread time per second.
                cost += f" The recorder's own main-thread time: p50 {us[len(us) // 2] * 4 / 1000:.2f} ms per second, p99 {us[int(len(us) * .99) - 1 if len(us) > 1 else 0] / 1000:.2f} ms in a quarter second."
            drop = max((st.get("dropped_stills") or 0 for st in s.client_state), default=0)
            P.append(f"<p class=mut>{len(self.stills)} stills from the client itself (<code>LIVING_GAME_RECORD</code>), on a clock and at each line, reducer call, bubble and note.{esc(cost)}{' %d dropped (writer behind).' % drop if drop else ''} Click to enlarge.</p><div class=strip>")
            step = max(1, len(self.stills) // 120)
            for ms, rel in self.stills[::step]:
                P.append(f"<figure><img loading=lazy src='{esc(rel)}' onclick='big(this.src)'><figcaption>{clock(ms, False)}</figcaption></figure>")
            P.append("</div>")
        if s.client_state:
            P.append(self.client_state_table())
        if not self.video_rel and not self.stills:
            P.append("<p class=warn>Nothing was recorded on screen in this session. The timeline below is from the authority's rows, the journal and the logs only.</p>")
        return "".join(P)

    def client_state_table(self):
        s = self.s
        rows = []
        last = None
        for st in s.client_state:
            key = (tuple(sorted((c.get("label"), c.get("id")) for c in st.get("drawn", []))), st.get("chat_open"), st.get("target"))
            if key == last:
                continue
            last = key
            rows.append(st)
        P = [f"<details><summary>What the client showed: {len(s.client_state)} samples, {len(rows)} changes</summary><table><tr><th>Time</th><th>You</th><th>Drawn near you</th><th>Pointed at</th><th>Chat</th></tr>"]
        for st in rows[:600]:
            me = st.get("me_pos") or []
            drawn = sorted(st.get("drawn", []), key=lambda c: c.get("d", 99))[:8]
            pos = ", ".join(f"{v:.0f}" for v in me[:2])
            near = "; ".join(f"{c.get('label')} #{c.get('id')} {c.get('d', 0):.0f} m" for c in drawn)
            P.append(f"<tr><td class=t>{clock(st['t'])}</td><td>{esc(pos)}</td><td>{esc(near)}</td>"
                     f"<td>{esc(st.get('target') or '')}</td><td>{esc(st.get('chat') or '')}</td></tr>")
        P.append("</table></details>")
        return "".join(P)

    def lines_section(self):
        s, an = self.s, self.an
        ear_m = f"{s.hearing_m:.0f} m" if s.hearing_m else "hearing range"
        P = [f"<h2>What you said, who heard it, who answered</h2><table><tr><th>Time</th><th>Line</th><th>Heard by (perceived)</th><th>In earshot ({ear_m})</th><th>Turns</th><th>Answers to you</th><th></th></tr>"]
        for l in an["lines"]:
            hs = sorted(l["hearers"].values(), key=lambda h: h["id"] or 1 << 40)
            heard = "".join(f"<span class=chip>{esc(h['name'])}{' ' + str(h['id']) if h['id'] else ''}{' %.1f m' % h['dist'] if h.get('dist') is not None else ''}{' · %.2f' % h['salience'] if h.get('salience') is not None else ''}</span>" for h in hs)
            if l["unknown_ids"]:
                heard += f"<div class=mut>ids {esc(', '.join(map(str, l['unknown_ids'])))} not identified (deleted rows)</div>"
            if l.get("block_open") and any(h["how"] != "row" for h in hs):
                heard += f"<div class=mut>rows from #{l['block_next']} on are not held: deleted rows may hide further hearers</div>"
            ear = "".join(f"<span class=chip>{esc(s.name(c))} {d:.1f} m</span>" for d, c in l["earshot"]) or "<span class=mut>positions not recorded</span>"
            turns = "".join(f"<span class=chip>{esc(t['name'])} {t['latency'] / 1000:.1f} s {esc((t['model'] or '').split('-')[0])}</span>" for t in l["turns"]) or "<b class=warn>none</b>"
            if l["parked"]:
                turns += f"<div class=mut>parked: {esc(', '.join(l['parked']))} deliberating" + "".join(f"; released {clock(ms)}" for _, ms in l["released"]) + "</div>"
            reps = "".join(f"<div><b>{esc(r['name'])}</b> +{r['after']:.1f} s <span class=mut>({esc(r['via'] or '?')}{', parked' if r['name'] in l['parked'] else ''})</span>: “{esc(r['text'][:160])}”</div>" for r in sorted(l["replies"], key=lambda r: r["ms"])) or "<span class=mut>none</span>"
            addr = f"to {esc(s.name(l['to']))}" if l["to"] else "to no one"
            P.append(f"<tr><td class=t>{clock(l['ms'])}</td><td><b>“{esc(l['text'])}”</b><div class=mut>{addr}{'' if l['addressed'] else ', unaddressed'} · at ({l['x']:.1f}, {l['y']:.1f}){'<br>' + esc(l['repeat']) if l['repeat'] else ''}</div></td>"
                     f"<td>{heard or '<span class=mut>no record</span>'}</td><td>{ear}</td><td>{turns}</td><td>{reps}</td><td>{self.media(l['ms'])}</td></tr>")
        P.append("</table>")
        if not an["lines"]:
            P.append("<p class=mut>You said nothing.</p>")
        return "".join(P)

    def timeline_section(self):
        s, an = self.s, self.an
        ev = []
        ev.append((s.start, "other", f"You join as {esc(s.me_name)} (#{s.me})" + (f"; arrival at {clock(s.arrival)}" if s.arrival else "")))
        for l in an["lines"]:
            ev.append((l["ms"], "say", f"<b>You say “{esc(l['text'])}”</b> {'to ' + esc(s.name(l['to'])) if l['to'] else 'to no one'}; heard by {len(l['hearers'])}; {len(l['turns'])} turn(s)"))
        for r in an["to_me"]:
            src = next((x for l in an["lines"] for x in l["replies"] if x["id"] == r["id"]), None)
            ev.append((r["at_ms"], "reply", f"<b>{esc(s.name(r['subject']))}</b> to you: “{esc(quoted(r['text']) or r['text'])}”" + (f" <span class=mut>({esc(src['via'])})</span>" if src and src.get("via") else "")))
        for h in an["heard"]:
            if h["object"] != s.me:
                to = f" to {esc(s.name(h['object']))}" if h["object"] else ""
                ev.append((h["at_ms"], "other", f"<span class=mut>you heard</span> {esc(s.name(h['subject']))}{to}: “{esc((quoted(h['text']) or h['text'])[:220])}”"))
        for e in an["mine"]:
            if e["kind"] in ("gesture",) and e["object"] == s.me:
                ev.append((e["at_ms"], "reply", esc(e["text"])))
        for f in an["fights"]:
            ev.append((f["at_ms"], "fight", esc(f["text"])))
        for b in an["blows"]:
            ev.append((b["ms"], "fight", f"{esc(b['name'])} felt your blow: {b['damage']} damage <span class=mut>(from their prompt; time ±0.5 s)</span>"))
        for r in an["refused"]:
            ev.append((r["ms"], "err", f"Refused ({esc(r['src'])}): {esc(r['text'])}"))
        for r in an["events"]:
            ev.append((r["ms"], "other", esc(r["text"])))
        for q in an["quiet"]:
            ev.append((q["from"] + 1, "quiet", f"<b>Silence for {span((q['to'] - q['from']) / 1000)}</b>, until {clock(q['to'])}; you heard {len(q['heard'])} line(s)"))
        for e in an["errors"]:
            if not e["benign"] and e["ms"]:
                ev.append((e["ms"], "err", f"{esc(e['src'])} {esc(e['level'])}: {esc(e['msg'][:240])}"))
        for e in self.s.client_events:
            k = e.get("kind")
            if k == "input":
                ev.append((e["t"], "other", f"<span class=mut>pressed: {esc(e.get('what'))}</span>"))
            elif k == "call" and e.get("reducer") not in ("move",):
                ev.append((e["t"], "other", f"<span class=mut>sent {esc(e.get('reducer'))}: <code>{esc(str(e.get('args'))[:160])}</code></span>"))
            elif k == "bubble":
                ev.append((e["t"], "other", f"<span class=mut>on screen: {esc(e.get('what'))}</span>"))
            elif k == "note":
                ev.append((e["t"], "other", f"<span class=mut>note shown: {esc(e.get('what'))}</span>"))
        ev.append((s.end, "other", "You quit (presence ends)" if s.pres and not s.pres.get("present") else "Last client log line"))
        ev.sort(key=lambda e: e[0])
        P = [f"<h2>Timeline</h2><p class=mut>{len(ev)} entries, {clock(s.start)}–{clock(s.end)}. Blue: you speak; green: to you; red: fights; dashed: refusals and errors; yellow: silence.</p><div class=tl>"]
        shown = set()
        for ms, k, text in ev:
            med = ""
            if k in ("say", "reply", "fight", "quiet", "err"):
                st = self.still_near(ms)
                if st and st[1] not in shown:
                    shown.add(st[1])
                    med = self.media(ms)
                elif self.video_rel:
                    med = self.media(ms)
            P.append(f"<div class=when>{clock(ms)}</div><div class='k-{k}'>{text}{med}</div>")
        P.append("</div>")
        return "".join(P)

    def fights_section(self):
        s, an = self.s, self.an
        if not an["fights"] and not an["blows"] and not an["skills"]:
            return "<h2>Fights and deaths</h2><p class=mut>None involving you.</p>"
        P = ["<h2>Fights and deaths</h2><table><tr><th>Time</th><th>What</th><th>Where</th><th></th></tr>"]
        for f in an["fights"]:
            P.append(f"<tr><td class=t>{clock(f['at_ms'])}</td><td>{esc(f['text'])} <span class=chip>{esc(f['kind'])}</span></td><td>{'(%.0f, %.0f)' % (f['x'], f['y']) if f.get('x') is not None else ''}</td><td>{self.media(f['at_ms'])}</td></tr>")
        P.append("</table>")
        if an["blows"]:
            P.append("<p>" + "; ".join(f"{clock(b['ms'], False)} {esc(b['name'])} −{b['damage']}" for b in an["blows"]) + " <span class=mut>(each victim's own record of a blow from you)</span></p>")
        if an["skills"]:
            P.append(f"<h3>Your skill presses the authority still holds ({len(an['skills'])}; it keeps the last 24 per character{', the recorder kept the rest' if s.cap else ''})</h3><table><tr><th>Time</th><th>Skill</th><th>On</th><th>Outcome</th></tr>")
            for u in an["skills"]:
                P.append(f"<tr><td class=t>{clock(u['at_ms'])}</td><td>{esc(u['skill'])}</td><td>{esc(s.name(u['target'])) if u.get('target') else ''}</td><td>{esc(u.get('outcome'))}</td></tr>")
            P.append("</table>")
        return "".join(P)

    def refused_section(self):
        an = self.an
        P = ["<h2>Refused commands</h2>"]
        if not an["refused"]:
            return P[0] + "<p class=mut>None.</p>"
        P.append("<table><tr><th>Time</th><th>The authority's reason</th><th>Source</th></tr>")
        for r in an["refused"]:
            when = clock(r["ms"]) + (f"–{clock(r['until'])}" if r["until"] != r["ms"] else "")
            P.append(f"<tr><td class=t>{when}</td><td>{esc(r['text'])}{' <b>×%d</b>' % r['n'] if r['n'] > 1 else ''}</td><td>{esc(r['src'])}</td></tr>")
        P.append("</table>")
        return "".join(P)

    def errors_section(self):
        an = self.an
        errs = [e for e in an["errors"] if not e["benign"]]
        ben = [e for e in an["errors"] if e["benign"]]
        P = [f"<h2>Errors</h2><p class=mut>Client, mind service, module (reducer errors) and model calls, from a minute before arrival to a minute after quitting.</p>"]
        if not errs:
            P.append("<p class=ok>None.</p>")
        else:
            P.append("<table><tr><th>Time</th><th>Where</th><th>Level</th><th>Message</th></tr>")
            for e in errs[:300]:
                P.append(f"<tr><td class=t>{clock(e['ms'])}</td><td>{esc(e['src'])}</td><td>{esc(e['level'])}</td><td>{esc(e['msg'][:400])}</td></tr>")
            P.append("</table>")
        if ben:
            P.append(f"<p class=mut>Folded as known and harmless: {len(ben)} ({esc(ben[0]['msg'][:120])}).</p>")
        return "".join(P)

    def cost_section(self, c):
        P = ["<h2>Cost</h2><p class=mut>Estimated from the journal's own token counts at the prices in <code>living/tools/trials.py</code> (USD per million tokens, input / output / cached): "
             + "; ".join(f"{esc(m)} {p[0]} / {p[1]} / {p[2]}" for m, p in PRICES.items() if any(m == k[1] for k in c['run'])) + ". An estimate, not an invoice.</p>"]
        for label, title in (("session", "During the session (arrival to quit)"), ("run", "The whole run (the minds' journal, start to stop)")):
            by = c[label]
            P.append(f"<h3>{title}</h3><table><tr><th>Purpose</th><th>Model</th><th class=n>Calls</th><th class=n>Prompt</th><th class=n>Completion</th><th class=n>Cached</th><th class=n>Latency p50</th><th class=n>Errors</th><th class=n>USD</th></tr>")
            for (p, m), b in sorted(((k, v) for k, v in by.items() if k[0] not in ("all", "by")), key=lambda kv: -kv[1]["usd"]):
                lat = sorted(b["lat"]) or [0]
                P.append(f"<tr><td>{esc(p)}</td><td>{esc(m)}</td><td class=n>{b['calls']}</td><td class=n>{b['prompt']:,}</td><td class=n>{b['completion']:,}</td><td class=n>{b['cached']:,}</td><td class=n>{lat[len(lat) // 2] / 1000:.1f} s</td><td class=n>{b['errors']}</td><td class=n>{b['usd']:.4f}{' +%d unpriced' % b['unpriced'] if b['unpriced'] else ''}</td></tr>")
            a = by.get(("all", ""))
            if a:
                P.append(f"<tr><th colspan=2>All</th><th class=n>{a['calls']}</th><th class=n>{a['prompt']:,}</th><th class=n>{a['completion']:,}</th><th class=n>{a['cached']:,}</th><th></th><th class=n>{a['errors']}</th><th class=n>{a['usd']:.4f}</th></tr>")
            P.append("</table><p class=mut>" + "; ".join(f"{esc(k[1])}: {v['calls']} calls, ${v['usd']:.4f}" for k, v in by.items() if k[0] == "by") + "</p>")
        return "".join(P)

    def sources_section(self):
        s = self.s
        P = ["<h2>Sources and limits</h2><ul>"]
        for x in s.sources:
            P.append(f"<li>{esc(x)}</li>")
        P.append("</ul><ul>")
        for n in s.notes:
            P.append(f"<li class=warn>{esc(n)}</li>")
        P.append("<li>Hearers come from the authority's experience rows written in the instant of the line; where a row was evicted, from the experience ids and lines shown in each resident's model requests (journal). A line shown in a prompt is perceived; a resident with no model call afterwards may have heard it and left no trace.</li>"
                 "<li>Turns are the mind service's conversation calls (purpose <code>talk</code>) carrying the line. A reply can also come from a deliberation that saw the line; that is marked by its purpose.</li>"
                 "<li>Mind log times are whole seconds; journal times are when the reply arrived.</li>"
                 "<li>Reported model thoughts are not proof of why a character acted.</li></ul>")
        return "".join(P)

    def facts(self, c):
        """The page's facts as JSON (for checks and comparisons)."""
        an = self.an
        return {
            "db": self.s.a.db, "player": self.s.me, "name": self.s.me_name, "start_ms": self.s.start, "end_ms": self.s.end,
            "lines": [{"ms": l["ms"], "text": l["text"], "to": l["to"], "addressed": l["addressed"], "hearers": {h["name"]: h["id"] for h in l["hearers"].values()},
                       "unknown_ids": l["unknown_ids"], "turns": [t["name"] for t in l["turns"]], "parked": l["parked"],
                       "replies": [{"name": r["name"], "after_s": round(r["after"], 1), "via": r["via"]} for r in l["replies"]]} for l in an["lines"]],
            "first_strike": {"ms": an["first_strike"]["row"]["at_ms"], "victim": self.s.name(an["first_strike"]["victim"]), "after_greeting_s": an["first_strike"]["after_greeting"]} if an.get("first_strike") else None,
            "fights": [{"ms": f["at_ms"], "kind": f["kind"], "text": f["text"]} for f in an["fights"]],
            "blows": an["blows"],
            "quiet": [{"from_ms": q["from"], "to_ms": q["to"], "s": (q["to"] - q["from"]) / 1000, "heard": len(q["heard"])} for q in an["quiet"]],
            "refused": [{"ms": r["ms"], "until_ms": r["until"], "n": r["n"], "text": r["text"], "src": r["src"]} for r in an["refused"]],
            "skills": [{"ms": u["at_ms"], "skill": u["skill"], "target": u.get("target"), "outcome": u.get("outcome")} for u in an["skills"]],
            "approaches": [{"ms": a["ms"], "name": a["name"], "via": a["via"], "half": bool(a.get("half"))} for a in an["approaches"]],
            "errors": [{"ms": e["ms"], "src": e["src"], "msg": e["msg"][:200]} for e in an["errors"] if not e["benign"]],
            "cost_session_usd": round(c["session"].get(("all", ""), {}).get("usd", 0), 4), "cost_run_usd": round(c["run"].get(("all", ""), {}).get("usd", 0), 4),
            "stills": len(self.stills), "video": self.video_rel,
        }


# ---------------------------------------------------------------------------------------
# Recording

def screen_allowed():
    try:
        import ctypes
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        return bool(cg.CGPreflightScreenCaptureAccess())
    except (OSError, AttributeError):
        return False


GAME_WINDOW_JS = ('ObjC.import("CoreGraphics");var a=ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly|$.kCGWindowListExcludeDesktopElements,$.kCGNullWindowID));'
                  'var o=[];for(var i=0;i<a.count;i++){var w=ObjC.deepUnwrap(a.objectAtIndex(i));if(w.kCGWindowLayer==0)o.push(w.kCGWindowNumber+"\\t"+w.kCGWindowOwnerName+"\\t"+w.kCGWindowOwnerPID)}o.join("\\n")')


def game_window(owner="living-game", pid=None):
    r = subprocess.run(["osascript", "-l", "JavaScript", "-e", GAME_WINDOW_JS], capture_output=True, text=True, timeout=20)
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and ((pid and parts[2] == str(pid)) or (not pid and parts[1] == owner)):
            return int(parts[0])
    return None


def disk_free_gb(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


U64_MAX = (1 << 64) - 1


def body_at(b, now):
    """Where a body row's segment puts it at `now`: straight-line motion from (x, y) at t_ms,
    held at the segment's end (`next_ms`). Turn arcs are not followed (common::pos does)."""
    end = b.get("next_ms")
    t = now if end in (None, U64_MAX) else min(now, end)
    dt = max(0.0, (t - b["t_ms"]) / 1000)
    return round(b["x"] + (b.get("vx") or 0) * dt, 2), round(b["y"] + (b.get("vy") or 0) * dt, 2)


def recorder(a):
    """The background loop record-start runs: rows before they are deleted, positions, and the
    game's window. Whatever goes wrong, the screen recording is stopped on the way out."""
    cap = Path(a.capture)
    meta_p = cap / "recorder.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("now", True))
    state = {"screen": None}

    def note(k, v):
        meta[k] = v
        meta_p.write_text(json.dumps(meta, indent=1))

    try:
        record_loop(a, cap, meta, note, stop, state)
    except Exception as e:  # noqa: BLE001 - the recorder must never leave the video running
        meta.setdefault("errors", []).append(f"{time.strftime('%H:%M:%S')} recorder stopped: {type(e).__name__}: {str(e)[:200]}")
    finally:
        screen = state["screen"]
        if screen is not None and screen.poll() is None:
            screen.send_signal(signal.SIGINT)
            try:
                screen.wait(timeout=20)
            except subprocess.TimeoutExpired:
                meta["screen_note"] = meta.get("screen_note", "") + "; screencapture did not stop within 20 s"
        meta["stopped_ms"] = int(time.time() * 1000)
        meta_p.write_text(json.dumps(meta, indent=1))


def record_loop(a, cap, meta, note, stop, state):
    sql = None
    for _ in range(30):
        if stop["now"]:
            return
        try:
            sql = Sql(a.db)
            sql.rows("SELECT id FROM world")
            break
        except Exception:  # noqa: BLE001
            sql = None
            time.sleep(2)
    out = (cap / "authority.jsonl").open("a")
    last = {"experience": 0, "chronicle": 0, "skill_use": 0}
    # Start from what is there now; everything newer is kept as it arrives.
    for t in last:
        try:
            r = sql.rows(f"SELECT * FROM {t}") if sql else []
            last[t] = max((x["id"] for x in r), default=0)
            for x in r:
                out.write(json.dumps({"t": int(time.time() * 1000), "table": t, "row": flat_row(x)}) + "\n")
        except Exception:  # noqa: BLE001
            pass
    want_screen = not a.no_screen
    if want_screen and not screen_allowed():
        note("screen_note", "not recorded: the app that launched the recorder may not record the screen (System Settings > Privacy & Security > Screen & System Audio Recording).")
        want_screen = False
    elif not want_screen:
        note("screen_note", "not recorded (--no-screen).")
    errors, lat_ms, tick = 0, [], 0
    t_start = time.time()
    while not stop["now"]:
        t0 = time.time()
        now = int(t0 * 1000)
        tick += 1
        if sql:
            try:
                # Skill presses each second: the authority keeps 24 per character and fills in
                # a press's outcome after it is inserted, so the last 40 ids are read again and
                # the newest copy wins. Positions each second. Experience rows (deleted when a
                # mind consolidates, at most every 90 s) every 2 s; the chronicle every 10 s.
                tables = ["skill_use"] + (["experience"] if tick % 2 == 0 else []) + (["chronicle"] if tick % 10 == 0 else [])
                for t in tables:
                    since = max(0, last[t] - 40) if t == "skill_use" else last[t]
                    t_q = time.time()
                    rows = sql.rows(f"SELECT * FROM {t} WHERE id > {since}")
                    lat_ms.append((time.time() - t_q) * 1000)
                    for x in rows:
                        out.write(json.dumps({"t": now, "table": t, "row": flat_row(x)}) + "\n")
                        last[t] = max(last[t], x["id"])
                t_q = time.time()
                bodies = sql.rows("SELECT id, x, y, t_ms, vx, vy, next_ms, heading FROM body")
                lat_ms.append((time.time() - t_q) * 1000)
                rows = []
                for b in map(flat_row, bodies):
                    x, y = body_at(b, now)
                    rows.append({"id": b["id"], "x": x, "y": y, "h": b.get("heading")})
                out.write(json.dumps({"t": now, "table": "body", "rows": rows}) + "\n")
                out.flush()
            except Exception as e:  # noqa: BLE001 - keep recording through a bad response
                errors += 1
                if errors in (1, 10, 100, 1000):
                    meta.setdefault("errors", []).append(f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {str(e)[:200]}")
                    note("errors", meta["errors"])
        try:
            # The game's window appears after the client starts; record it once it does.
            if want_screen and state["screen"] is None and time.time() - t_start < 600 and tick % 2 == 0:
                wid = game_window(pid=a.game_pid)
                if wid:
                    f = cap / "screen.mov"
                    # stdin stays open: screencapture is stopped by SIGINT, never by EOF.
                    state["screen"] = subprocess.Popen(["screencapture", "-x", "-v", "-o", "-l", str(wid), str(f)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    meta.update({"screen_pid": state["screen"].pid, "screen_start_ms": int(time.time() * 1000), "screen_window": wid, "screen_note": f"window {wid} recorded with screencapture"})
                    note("screen_pid", state["screen"].pid)
            sc = state["screen"]
            if sc is not None and sc.poll() is None and tick % 30 == 0 and disk_free_gb(cap) < 15:
                sc.send_signal(signal.SIGINT)
                note("screen_note", meta.get("screen_note", "") + f"; stopped at {time.strftime('%H:%M:%S')}: under 15 GB free")
        except Exception as e:  # noqa: BLE001
            meta.setdefault("errors", []).append(f"{time.strftime('%H:%M:%S')} screen: {type(e).__name__}: {str(e)[:200]}")
        time.sleep(max(0.05, a.every - (time.time() - t0)))
    if lat_ms:
        ls = sorted(lat_ms)
        meta["sql"] = {"requests": len(ls), "seconds": round(time.time() - t_start), "p50_ms": round(ls[len(ls) // 2], 1),
                       "p95_ms": round(ls[int(len(ls) * 0.95) - 1 if len(ls) > 1 else 0], 1), "max_ms": round(ls[-1], 1)}
    out.close()


def command_of(pid):
    r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip()


def is_recorder(pid, cap):
    cmd = command_of(pid)
    return " _record " in f" {cmd} " and str(cap) in cmd


def read_pid(pidf):
    try:
        return int(pidf.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def record_start(a):
    cap = Path(a.capture).resolve()
    cap.mkdir(parents=True, exist_ok=True)
    pidf = cap / "recorder.pid"
    pid = read_pid(pidf) if pidf.exists() else None
    if pid and is_recorder(pid, cap):
        raise SystemExit(f"play_report: a recorder is already running for {cap} (pid {pid})")
    (cap / "client").mkdir(exist_ok=True)
    (cap / "recorder.json").write_text(json.dumps({"db": a.db, "started_ms": int(time.time() * 1000), "every_s": a.every, "client_dir": str(cap / "client")}, indent=1))
    log = open(cap / "recorder.log", "a")
    args = [sys.executable, str(Path(__file__).resolve()), "_record", "--db", a.db, "--capture", str(cap), "--every", str(a.every)]
    if a.no_screen:
        args.append("--no-screen")
    if a.game_pid:
        args += ["--game-pid", str(a.game_pid)]
    p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    pidf.write_text(f"{p.pid} {int(time.time())}\n")
    print(f"recording {a.db} into {cap} (pid {p.pid}); the client records itself with LIVING_GAME_RECORD={cap / 'client'}")


def record_stop(a):
    cap = Path(a.capture).resolve()
    pidf = cap / "recorder.pid"
    pid = read_pid(pidf) if pidf.exists() else None
    if pid is None:
        print(f"play_report: no recorder for {cap}")
    elif is_recorder(pid, cap):
        # Only our own recorder: the PID file's process, still `_record --capture <this dir>`.
        os.kill(pid, signal.SIGINT)
        for _ in range(80):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.5)
        else:
            print(f"play_report: recorder pid {pid} did not stop within 40 s; left running", file=sys.stderr)
            return
        print(f"stopped recorder pid {pid}")
    else:
        print(f"play_report: pid {pid} is no longer the recorder; not signalled")
    # A recorder that died leaves its screencapture behind; stop that one too, by its pid.
    try:
        meta = json.loads((cap / "recorder.json").read_text())
    except (OSError, ValueError):
        meta = {}
    sp = meta.get("screen_pid")
    if sp and command_of(sp).startswith("screencapture") and str(cap) in command_of(sp):
        os.kill(sp, signal.SIGINT)
        print(f"stopped the screen recording (pid {sp}) its recorder left")
    pidf.unlink(missing_ok=True)


# ---------------------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    cmds = {"record-start", "record-stop", "_record", "report"}
    cmd = argv[0] if argv and argv[0] in cmds else "report"
    if argv and argv[0] in cmds:
        argv = argv[1:]
    ap = argparse.ArgumentParser(prog=f"play_report.py {cmd}", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if cmd == "report":
        ap.add_argument("--db", required=True, help="the world's database, e.g. verify-play2-20261111-135347")
        ap.add_argument("--run", required=True, help="the run's name (LIVING_RUN), e.g. play2-20261111-135347")
        ap.add_argument("--journal", help="the mind service's journal directory for the run")
        ap.add_argument("--logs", help="directory holding client.log and mind.log (and module.log.jsonl, optional)")
        ap.add_argument("--out", required=True, help="directory for index.html and its media")
        ap.add_argument("--capture", help="what record-start and the client recorded (stills, state, video, rows)")
        ap.add_argument("--player", type=int, help="the played character's id (default: from client.log)")
        a = ap.parse_args(argv)
        s = Session(a)
        an = analyse(s)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        print(Page(s, an, a.out).render())
    elif cmd in ("record-start", "_record"):
        ap.add_argument("--db", required=True)
        ap.add_argument("--capture", required=True, help="directory to record into")
        ap.add_argument("--every", type=float, default=1.0, help="seconds between the authority's samples")
        ap.add_argument("--no-screen", action="store_true", help="do not record the game's window")
        ap.add_argument("--game-pid", type=int, help="the client's pid, to find its window (default: by the name living-game)")
        a = ap.parse_args(argv)
        (recorder if cmd == "_record" else record_start)(a)
    else:
        ap.add_argument("--capture", required=True)
        record_stop(ap.parse_args(argv))


if __name__ == "__main__":
    main()
