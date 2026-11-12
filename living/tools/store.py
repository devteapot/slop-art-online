#!/usr/bin/env python3
"""The store: one place for the heavy outputs that sit on three disks (docs/STORE.md).

Subcommands:

  manifest [--md FILE] [--json FILE]     what this machine holds, by kind: path, size, file
                                         count, whether it can be regenerated, where it would go
  scrub --dry-run SRC [--report DIR]     what would be uploaded from SRC (a directory, file or
                                         tarball), per file, with every redaction (masked) and the
                                         categories the owner decides
  pack batch|session|motion SRC --out DIR   scrub SRC and write the unit as it would be published
  publish batch|session|motion SRC --backend local|hf [--yes-publish]
  fetch motion-library [--dest DIR]      the raw Kimodo takes into .local/kimodo/outputs/library
  fetch batch NAME [--dest DIR] [--unpack]   a packed trial batch, optionally back into the
                                         trials.py evidence layout
  layout [--manifest FILE]               the proposed repositories with size and file estimates

Hugging Face is the first backend, behind the `Backend` interface; no other script calls it.
Publishing to it needs BOTH `--yes-publish` and `publish_enabled: true` in the machine-local
config (~/.config/slop-store/config.json); the repository's config may not switch it on.

Runs with the Python 3.9+ standard library on Linux and macOS. The Hugging Face backend imports
`huggingface_hub` only once its gate has opened (or for a fetch).
Self-test: living/tools/store_selftest.py.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import getpass
import glob
import gzip
import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(TOOLS))
REPO_CONFIG = os.path.join(TOOLS, "store_config.json")
LOCAL_CONFIG = os.path.expanduser("~/.config/slop-store/config.json")
FORMAT = 1


class Refused(Exception):
    """An operation the store will not do (a gate, a never-touch path, an undecided category)."""


# --------------------------------------------------------------------------------------------
# Configuration and machine
# --------------------------------------------------------------------------------------------

def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(repo_config=None, local_config=None):
    repo_config = repo_config or REPO_CONFIG
    local_config = local_config or os.environ.get("STORE_CONFIG") or LOCAL_CONFIG
    with open(repo_config, encoding="utf-8") as f:
        cfg = json.load(f)
    if "publish_enabled" in cfg or "publish_sessions" in cfg:
        raise Refused(f"{repo_config} sets publish_enabled; that switch belongs in the machine-local "
                      f"config only ({LOCAL_CONFIG})")
    local = {}
    if os.path.exists(local_config):
        with open(local_config, encoding="utf-8") as f:
            local = json.load(f)
    cfg = _merge(cfg, local)
    cfg["publish_enabled"] = local.get("publish_enabled") is True
    cfg["publish_sessions"] = local.get("publish_sessions") is True
    cfg["_local_config"] = local_config
    return cfg


def machine_name(cfg):
    m = os.environ.get("STORE_MACHINE") or cfg.get("machine")
    if m:
        return m
    if platform.system() == "Darwin":
        return "laptop"
    if platform.machine() in ("aarch64", "arm64") and platform.system() == "Linux":
        return "spark"
    return "dev-box"


def expand(p):
    return os.path.realpath(os.path.expanduser(p))


def tilde(p):
    home = os.path.expanduser("~")
    p = os.path.abspath(p)
    if p == home:
        return "~"
    if p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p


def _under(path, roots):
    path = os.path.realpath(path)
    for r in roots:
        if path == r or path.startswith(r.rstrip(os.sep) + os.sep):
            return r
    return None


def never_touch(cfg, machine):
    return [expand(p) for p in (cfg.get("never_touch") or {}).get(machine, [])]


def is_never_touch(path, cfg, machine):
    hit = _under(path, never_touch(cfg, machine))
    if hit:
        return hit
    for name in cfg.get("never_touch_names") or []:
        if name in os.path.realpath(path).split(os.sep) or any(
                part.startswith(name) for part in os.path.realpath(path).split(os.sep)):
            return name
    return None


# --------------------------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------------------------

# kind: (what it is, can it be regenerated and how long, where it goes)
KINDS = {
    "trial-batch": ("One trials.py batch: per instance cast, samples, rows, the mind's journal "
                    "(real model requests and replies), mind log, summary; the batch report",
                    "no: real model calls (cost) and hours of run time; a --fake batch reruns in its run time",
                    "runs"),
    "trials-archive": ("Trial batches packed by hand into tarballs after their checkout was cleaned",
                       "no (as trial-batch)", "runs (unpacked per batch, deduplicated against live batches)"),
    "trial-ledger": ("trials.py's ledger of real tokens per batch, and other small batch-side files",
                     "no", "runs"),
    "journal-copy": ("Live mind journals of trial databases; trials.py copies each into its batch "
                     "(instance/journal) when the instance stops", "duplicate of trial-batch",
                     "not uploaded (duplicate)"),
    "mind-journal": ("Mind journals of verify/lab/play databases that are not part of a trial batch",
                     "no: model calls", "runs (verify)"),
    "verify-evidence": ("Verification evidence (.local/living/verify/<run>): logs, SQL dumps, journals "
                        "of verify-* scratch databases", "mostly yes with the same commit, minutes; "
                        "paid tiers no", "runs (verify, packed per checkout)"),
    "play-session": ("An owner play session: journals, client/mind logs, authority rows, the "
                     "report page, stills and video, the owner's feedback", "no", "runs (sessions)"),
    "play-report": ("play_report.py pages and the evidence they were built from", "the page yes "
                    "(seconds, from the session); the capture no", "runs (sessions)"),
    "motion-raw": ("Raw Kimodo SOMA-77 takes (.npz) of the motion library on the Spark "
                   "(~/kimodo-test/library, read-only)", "partly: same prompt and seed on the same "
                   "model and GPU stack, about 3-4 s a take; bit-identical not guaranteed",
                   "assets (motion/raw)"),
    "motion-library-copy": (".local/kimodo/outputs/library: every take kept for the library, the "
                            "input of gen_anim.sh/gen_person.sh", "as motion-raw", "assets (motion/raw)"),
    "cliplab": ("Clip lab runs: takes per clip, checks.json scores, contact sheets", "the scores yes "
                "(seconds); the takes as motion-raw", "assets (motion/cliplab: checks and sheets; "
                "adopted takes are in motion/raw)"),
    "clip-handoff": ("Clip handoff tarballs (cliplab.py --handoff) with sha256", "from the takes, seconds",
                     "assets (motion/handoffs)"),
    "clip-deliverable": ("Hand-made tarballs and review folders of Kimodo clips sent between machines",
                         "from the takes, seconds", "not uploaded (superseded by motion/raw + handoffs)"),
    "asset-board": ("Asset board media and pages (~/archive/asset-board; records are in git)",
                    "photographs yes with the same build (minutes, needs the game renderer); "
                    "decisions no (they are in git)", "assets (board)"),
    "game-assets": ("Generated game assets (living/game/assets/lookdev, git-ignored)",
                    "yes: just living-game-assets, minutes (needs Blender and the clip library)",
                    "not uploaded (regenerable); accepted versions go through the board"),
    "trial-build": ("Trial modules (wasm), derived seeds and build logs", "yes: trials.py build, minutes",
                    "not uploaded (build output)"),
    "build-output": ("Cargo target folders inside .local/living (target-*, verify/build-*)",
                     "yes: cargo, minutes", "not uploaded (build output)"),
    "secret": ("Files holding passwords or keys (neo4j.env, .env)", "n/a", "never uploaded"),
    "other": ("Anything else under .local/living (logs of checks and runs)", "mostly yes",
              "review case by case"),
    "never-touch": ("A folder this machine must not touch; not scanned", "n/a", "never uploaded"),
}


def measure(path):
    """(bytes, files) under path, without following links."""
    if os.path.islink(path):
        return 0, 0
    if os.path.isfile(path):
        return os.lstat(path).st_size, 1
    total = files = 0
    for root, dirs, names in os.walk(path, followlinks=False):
        for n in names:
            try:
                st = os.lstat(os.path.join(root, n))
            except OSError:
                continue
            total += st.st_size
            files += 1
    return total, files


def _checkouts(home):
    out = []
    for pat in ("dev/*", ".t3/worktrees/*/*"):
        for d in sorted(glob.glob(os.path.join(home, pat))):
            if os.path.isdir(d) and not d.endswith(".git"):
                out.append(d)
    return out


def _is_batch(d):
    if os.path.exists(os.path.join(d, "batch.json")):
        return True
    try:
        return any(os.path.exists(os.path.join(d, c, "summary.json")) or
                   os.path.exists(os.path.join(d, c, "cast.json")) for c in os.listdir(d))
    except OSError:
        return False


def scan(home=None, cfg=None, machine=None):
    """Every item this machine holds, as dicts. Never-touch folders are listed, not scanned."""
    home = home or os.path.expanduser("~")
    cfg = cfg or load_config()
    machine = machine or machine_name(cfg)
    items = []

    def add(kind, path, unit=None, note=None, measure_it=True):
        nt = is_never_touch(path, cfg, machine)
        if nt and kind != "never-touch":
            return
        b, n = measure(path) if measure_it else (None, None)
        what, regen, plan = KINDS[kind]
        items.append({"kind": kind, "machine": machine, "path": tilde(path), "unit": unit,
                      "bytes": b, "files": n, "regen": regen, "plan": plan, "note": note})

    for p in never_touch(cfg, machine):
        if os.path.exists(p):
            add("never-touch", p, measure_it=False)

    for co in _checkouts(home):
        if is_never_touch(co, cfg, machine):
            continue
        living = os.path.join(co, ".local", "living")
        if os.path.isdir(living):
            for name in sorted(os.listdir(living)):
                p = os.path.join(living, name)
                if name == "trials" and os.path.isdir(p):
                    batches = set()
                    for t in sorted(os.listdir(p)):
                        tp = os.path.join(p, t)
                        if os.path.isdir(tp) and t not in ("wasm", "seeds") and _is_batch(tp):
                            batches.add(t)
                    for t in sorted(os.listdir(p)):
                        tp = os.path.join(p, t)
                        if t in batches:
                            fake = None
                            try:
                                with open(os.path.join(tp, "batch.json")) as f:
                                    fake = json.load(f).get("fake")
                            except (OSError, ValueError):
                                pass
                            add("trial-batch", tp, unit=t,
                                note=("fake" if fake else "real" if fake is False else None))
                        elif t.endswith(".log") and re.sub(r"-(runner|resume\d*|clean)$", "", t[:-4]) in batches:
                            add("trial-batch", tp, unit=re.sub(r"-(runner|resume\d*|clean)$", "", t[:-4]),
                                note="runner log")
                        elif t in ("wasm", "seeds") or (t.startswith("build") and t.endswith(".log")):
                            add("trial-build", tp)
                        elif t.endswith(".env"):
                            add("secret", tp)
                        elif t.endswith(".log") or t == "ledger.json" or os.path.isdir(tp):
                            add("trial-ledger", tp, unit=t)
                        else:
                            add("other", tp)
                elif name == "journal" and os.path.isdir(p):
                    copies = []
                    for j in sorted(os.listdir(p)):
                        jp = os.path.join(p, j)
                        if j.startswith("verify-trial-"):
                            copies.append(jp)
                        else:
                            add("mind-journal", jp, unit=j)
                    if copies:
                        b = n = 0
                        for jp in copies:
                            bb, nn = measure(jp)
                            b += bb
                            n += nn
                        what, regen, plan = KINDS["journal-copy"]
                        items.append({"kind": "journal-copy", "machine": machine, "path": tilde(p) + "/verify-trial-*",
                                      "unit": f"{len(copies)} journals", "bytes": b, "files": n,
                                      "regen": regen, "plan": plan, "note": None})
                elif name == "verify" and os.path.isdir(p):
                    runs = []
                    for v in sorted(os.listdir(p)):
                        vp = os.path.join(p, v)
                        if v.startswith("build") or v.startswith("target"):
                            add("build-output", vp)
                        else:
                            runs.append(vp)
                    if runs:
                        b = n = 0
                        for vp in runs:
                            bb, nn = measure(vp)
                            b += bb
                            n += nn
                        what, regen, plan = KINDS["verify-evidence"]
                        items.append({"kind": "verify-evidence", "machine": machine, "path": tilde(p),
                                      "unit": f"{len(runs)} runs", "bytes": b, "files": n,
                                      "regen": regen, "plan": plan, "note": None})
                elif name.startswith("target"):
                    add("build-output", p)
                elif name.startswith("playtest") or name.startswith("play-"):
                    add("play-session", p, unit=name)
                elif name == "play-report":
                    add("play-report", p)
                else:
                    add("other", p)
        lib = os.path.join(co, ".local", "kimodo", "outputs", "library")
        if os.path.isdir(lib):
            add("motion-library-copy", lib)
        for pl in sorted(glob.glob(os.path.join(co, ".local", "play*"))):
            if os.path.isdir(pl):
                add("play-session", pl, unit=os.path.basename(pl))
        ga = os.path.join(co, "living", "game", "assets", "lookdev")
        if os.path.isdir(ga):
            add("game-assets", ga)

    def home_glob(kind, pattern, unit_from_name=False):
        for p in sorted(glob.glob(os.path.join(home, pattern))):
            add(kind, p, unit=os.path.basename(p) if unit_from_name else None)

    home_glob("play-session", "playtest-*", True)
    for p in sorted(glob.glob(os.path.join(home, "trials-archive", "*"))):
        add("trials-archive", p, unit=os.path.basename(p).split(".")[0])
    home_glob("motion-raw", "kimodo-test/library")
    home_glob("cliplab", "cliplab*", True)
    home_glob("clip-handoff", "clip-handoff")
    for pat in ("kimodo-clips-*", "kimodo-locomotion-*", "kimodo-library-*"):
        home_glob("clip-deliverable", pat, True)
    home_glob("asset-board", "archive/asset-board")
    return items


def fmt_bytes(n):
    if n is None:
        return "–"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def manifest_summary(items):
    by = {}
    for it in items:
        s = by.setdefault(it["kind"], {"items": 0, "bytes": 0, "files": 0, "units": set()})
        s["items"] += 1
        s["bytes"] += it["bytes"] or 0
        s["files"] += it["files"] or 0
        if it["unit"]:
            s["units"].add(it["unit"])
    return by


def manifest_markdown(items, machine, when):
    by = manifest_summary(items)
    lines = [f"<!-- generated by `python3 living/tools/store.py manifest --md` on {machine}, {when} -->",
             f"### {machine}: summary by kind", "",
             "| Kind | Items | Distinct units | Size | Files | Regenerable | Goes to |",
             "| --- | ---: | ---: | ---: | ---: | --- | --- |"]
    order = list(KINDS)
    real = [i for i in items if i["kind"] == "trial-batch" and i["note"] == "real"]
    fake = [i for i in items if i["kind"] == "trial-batch" and i["note"] == "fake"]
    for kind in sorted(by, key=order.index):
        s = by[kind]
        _, regen, plan = KINDS[kind]
        if kind == "trial-batch":
            regen = (f"{len(real)} real batches ({fmt_bytes(sum(i['bytes'] or 0 for i in real))}): {regen}; "
                     f"{len(fake)} fake ({fmt_bytes(sum(i['bytes'] or 0 for i in fake))}): yes, in their run time")
        lines.append(f"| `{kind}` | {s['items']} | {len(s['units']) or '–'} | {fmt_bytes(s['bytes'])} | "
                     f"{s['files']} | {regen} | {plan} |")
    tot_b = sum(s["bytes"] for s in by.values())
    tot_n = sum(s["files"] for s in by.values())
    lines += [f"| **total scanned** | {len(items)} | | {fmt_bytes(tot_b)} | {tot_n} | | |", "",
              f"### {machine}: items", "",
              "| Kind | Path | Unit | Size | Files | Note |", "| --- | --- | --- | ---: | ---: | --- |"]
    for it in sorted(items, key=lambda i: (order.index(i["kind"]), i["path"])):
        lines.append(f"| `{it['kind']}` | `{it['path']}` | {it['unit'] or ''} | {fmt_bytes(it['bytes'])} | "
                     f"{'' if it['files'] is None else it['files']} | {it['note'] or ''} |")
    lines.append("")
    lines.append("What each kind is:")
    lines.append("")
    for kind in sorted(by, key=order.index):
        lines.append(f"- `{kind}`: {KINDS[kind][0]}.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------
# Identity: what identifies the owner, read at run time and never written to the repository
# --------------------------------------------------------------------------------------------

SECRET_NAME = re.compile(r"(?i)(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|APIKEY|_KEY|_AUTH|_PASS|CREDENTIALS?)$")


def _git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10,
                             cwd=REPO).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _env_file_secrets(path):
    vals = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.replace("export ", "").strip()
                v = v.strip().strip("'\"")
                if SECRET_NAME.search(k) and len(v) >= 8:
                    vals.add(v)
                    if "/" in v and k.endswith("_AUTH"):   # NEO4J_AUTH=user/password
                        vals.add(v.split("/", 1)[1])
    except OSError:
        pass
    return vals


class Identity:
    """The owner's identifying strings and the machine's secrets. Built at run time from git
    config, the environment, ~/.ssh/config, the hostname and the .env files of checkouts;
    tests build it directly."""

    def __init__(self, names=(), emails=(), logins=(), hostnames=(), secrets=(), first_names=()):
        self.names = {n for n in names if n and len(n) >= 3}
        self.emails = {e.lower() for e in emails if e and "@" in e}
        self.logins = {l for l in logins if l and len(l) >= 3 and l not in ("root", "user", "runner")}
        self.hostnames = {h for h in hostnames if h and len(h) >= 4 and h not in ("localhost",)}
        self.secrets = {s for s in secrets if s and len(s) >= 8}
        first = set(first_names)
        self.surnames = set()
        for n in self.names:
            parts = n.split()
            if len(parts) >= 2:
                first.add(parts[0])
                self.surnames.update(p for p in parts[1:] if len(p) >= 3)
        self.first_names = {f for f in first if f and len(f) >= 3}

    @classmethod
    def from_runtime(cls, cfg=None, machine=None):
        cfg = cfg or load_config()
        machine = machine or machine_name(cfg)
        names, emails = set(), set()
        for args in (("config", "--get", "user.name"), ("config", "--global", "--get", "user.name")):
            v = _git(*args)
            if v:
                names.add(v)
        for args in (("config", "--get", "user.email"), ("config", "--global", "--get", "user.email")):
            v = _git(*args)
            if v:
                emails.add(v)
        for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            if os.environ.get(var):
                names.add(os.environ[var])
        for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            if os.environ.get(var):
                emails.add(os.environ[var])
        names.update(x.strip() for x in os.environ.get("STORE_OWNER_NAMES", "").split(",") if x.strip())
        emails.update(x.strip() for x in os.environ.get("STORE_OWNER_EMAILS", "").split(",") if x.strip())
        logins = {getpass.getuser(), os.environ.get("USER", ""), os.environ.get("LOGNAME", ""),
                  os.path.basename(os.path.expanduser("~"))}
        hosts = set()
        try:
            h = socket.gethostname()
            hosts.update({h, h.split(".")[0]})
        except OSError:
            pass
        hosts.update(x.strip() for x in os.environ.get("STORE_HOSTNAMES", "").split(",") if x.strip())
        ssh = os.path.expanduser("~/.ssh/config")
        if os.path.exists(ssh):
            with open(ssh, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.match(r"\s*(Host|HostName)\s+(.+)", line, re.I)
                    if not m:
                        continue
                    for h in m.group(2).split():
                        if "*" in h or "?" in h or re.fullmatch(r"[\d.]+", h):
                            continue
                        hosts.add(h)
        secrets = set()
        for var, val in os.environ.items():
            if SECRET_NAME.search(var) and len(val) >= 8:
                secrets.add(val)
        home = os.path.expanduser("~")
        env_files = [os.path.join(REPO, ".env")]
        for co in _checkouts(home):
            if is_never_touch(co, cfg, machine):
                continue
            env_files.append(os.path.join(co, ".env"))
            env_files += glob.glob(os.path.join(co, ".local", "living", "trials", "*.env"))
        for p in env_files:
            secrets |= _env_file_secrets(p)
        for p in (os.path.expanduser("~/.cache/huggingface/token"), os.path.expanduser("~/.config/slop-store/hf_token")):
            try:
                with open(p) as f:
                    t = f.read().strip()
                    if t:
                        secrets.add(t)
            except OSError:
                pass
        cli = os.path.expanduser("~/.config/spacetime/cli.toml")
        try:
            with open(cli) as f:
                for m in re.finditer(r"token\s*=\s*\"([^\"]+)\"", f.read()):
                    secrets.add(m.group(1))
        except OSError:
            pass
        return cls(names=names, emails=emails, logins=logins, hostnames=hosts, secrets=secrets)


# --------------------------------------------------------------------------------------------
# Scrubber
# --------------------------------------------------------------------------------------------

CODE_KEYS = {"do", "skill", "kind", "type", "purpose", "act", "rel", "lane", "mix", "profile", "effort", "stage",
             "folk", "activity", "verb", "hook", "law", "fn", "status", "role", "model", "finish_reason", "stream"}
ARTICLES = {"a", "an", "the"}
POSSESSIVES = {"my", "your", "his", "her", "its", "our", "their", "thy"}
DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our",
               "their", "some", "any", "no", "each", "every", "another", "one", "first", "last", "next"}
_SELF = r"(?:him|her|them)sel(?:f|ves)"
NAME_BEFORE = re.compile(
    r"(?i)(?:\bcalled|\bnamed|\bintroduced " + _SELF + r"(?: as)?|\bintroduced as|\bgoes by|\bgo by|"
    r"\bknown as|\bcall me|\bcalls " + _SELF + r"|\bcalling " + _SELF + r"|\bcalled " + _SELF + r"|"
    r"\bstyles? " + _SELF + r"(?: as)?|\bstyled " + _SELF + r"(?: as)?|\bstyling " + _SELF + r"(?: as)?|"
    r"\bself-styled|\bname is|\bname's|\bi'?m|\bi am|"
    # a name field, in plain or escaped JSON: "known_name": "X", \"known_name\": \"X, \\\"…
    r"\\*\"(?:known_name|known_as|introduced_as|nickname|name|given_name|told_name|self_name|calls_self)\\*\"\s*:)"
    r"\s*(?:\\*[\"'])?\s*(?:[«“\"'‘»”’`]|\\+u(?:00ab|00bb|201c|201d|2018|2019))*\s*$")
CODE_BEFORE = re.compile(r"\\*\"(?:" + "|".join(sorted(CODE_KEYS)) + r")\\*\"\s*:\s*\\*\"$")


def _self_name_kind(s, a, b, word, game_word=False):
    """name | ordinary | ambiguous, for a self-given name found at s[a:b]. game_word: the word
    occurs in the game's own text of this run (templates, system prompts, installed scripts)."""
    before, after = s[max(0, a - 60):a], s[b:b + 20]
    if NAME_BEFORE.search(before):
        return "name"                                       # called «X», known_name: "X"
    if re.match(r"\s*(?:=#\d+|\((?:#|person:)\d+\))", after):
        return "name"                                       # {X=#26}, X (#26)
    if CODE_BEFORE.search(before):
        return "ordinary"                                   # "do": "strike": a game code
    prev = re.search(r"([A-Za-z']+)\W*$", before)
    if (game_word and word.islower() and prev and prev.group(1).lower() in DETERMINERS
            and not re.search(r"[«“\"'‘]\s*$", before)):
        return "ordinary"                                   # "a strike", "the strike": the game's word
    if word.islower() and not re.search(r"[«“\"'‘]\s*$", before):
        words_before = re.findall(r"[A-Za-z'’]+", before)[-2:]
        last = words_before[-1].lower() if words_before else ""
        pair = [w.lower() for w in words_before]
        if (last in ARTICLES or last in POSSESSIVES or re.search(r"['’]s$", last)
                or (len(pair) == 2 and pair[1] == "own" and (pair[0] in POSSESSIVES or re.search(r"['’]s$", pair[0])))):
            return "kept-listed"                            # "Mercy's word", "my own word", "the word"
    stripped = before.rstrip(" \t")
    at_start = not stripped or stripped[-1] in "\n.!?:;([{«“\"'‘—-" or stripped.endswith("\\n")
    if at_start and re.match(r"\s*[,!]", after):
        return "name"                                       # "X, come here" addressed
    if word[:1].isupper() and not word.isupper() and not at_start:
        return "name"                                       # "I told X about the well"
    return "ambiguous"


NAME_FIELD_TEXT = re.compile(
    r"\\*\"(known_name|known_as|introduced_as|nickname|name|given_name|told_name|self_name|calls_self)\\*\"\s*:\s*"
    r"\\*\"([^\"\\\n]{1,40})")
NAME_KEYS = {"known_name", "known_as", "introduced_as", "nickname", "calls_self", "self_name", "name",
             "given_name", "told_name"}
NOT_NAMES = {"new", "here", "fine", "good", "ok", "okay", "lost", "sorry", "back", "home", "hungry", "tired",
             "ready", "done", "friend", "stranger", "traveller", "traveler", "newcomer", "someone", "nobody",
             "player", "person", "happy", "sad", "well", "alive", "dead", "busy", "free", "glad", "late", "early",
             "cold", "hot", "afraid", "scared", "sure", "safe", "alone", "armed", "unarmed", "wounded", "hurt",
             "looking", "trying", "going", "leaving", "staying", "waiting", "coming", "just", "only", "still",
             "not", "no", "yes", "null", "none", "unknown", "you", "me", "him", "her", "them", "child", "adult",
             "later", "soon", "tomorrow", "again", "sometime", "anytime", "anything", "whatever", "maybe",
             "please", "sir", "madam", "maam", "mate", "buddy", "pal", "boss", "anyone", "everyone", "nothing"}
# Quotes around a typed name may be stray, doubled or mixed: ""X"", «X», 'X", “X”.
NAME_Q = r"[\"'«»“”‘’`]*"
SELF_NAME_RULES = (
    re.compile(r"(?i)\b(?:i'?m called|i am called|im called|i'?m named|i am named|(?:they|people|folks|everyone) "
               r"calls? me|call me|my name(?:'s| is)|the name'?s|name'?s|named|i go by)\s*" + NAME_Q +
               r"\s*([A-Za-z][A-Za-z-]{1,30})"),
    re.compile(r"(?i)^\W*(?:(?:hi|hello|hey|greetings|evening|morning)\W+)?(?:i'?m|i am|im|it'?s|this is)\s+" +
               NAME_Q + r"\s*([A-Za-z][A-Za-z-]{1,30})\s*" + NAME_Q + r"\W*$"),
)
ISO_STAMP = re.compile(r"\b\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")


def _iso_ms(t):
    try:
        return int(_dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


IDENTITY_CATS = {"owner-first-name", "owner-name", "owner-identity", "login", "owner-line", "owner-echo",
                 "hostname", "dropped-entry", "dropped-row", "dropped-line", "kept-row", "self-name",
                 "self-name-kept"}
SECRET_CATS = {"known-secret", "hf-token", "github-token", "api-key", "aws-key", "jwt", "bearer",
               "secret-assignment", "secret-field", "url-credentials", "slack-token", "google-key"}
DECISIONS = {
    "model_exchanges": "Journals: the actual model requests (prompts built from the world) and replies "
                       "from Mistral-hosted models. Thoughts, experiences and chronicle rows also carry "
                       "the models' words (plans, spoken lines); they are world rows and stay unless "
                       "you say otherwise.",
    "owner_lines": "The owner's own typed lines from play sessions, wherever they recur (prompts of "
                   "everyone who heard them, experiences, consolidations). exclude = each is replaced "
                   "by [owner line].",
    "owner_first_name": "The owner's first name, used as the player character's name. redact = "
                        "replaced by `Player` (file names too).",
    "owner_notes": "The owner's own written feedback (FEEDBACK.md and similar).",
    "session_media": "Play-session stills, screenshots and video: they show the HUD, the chat and the "
                     "owner's typed lines as drawn, which text redaction cannot reach.",
}
OWNER_NOTE_NAMES = ("FEEDBACK.md", "feedback.md", "NOTES.md")
MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mkv")
BINARY_OK_EXT = MEDIA_EXT + (".npz", ".npy", ".glb", ".gltf", ".bin", ".ktx2", ".exr", ".hdr", ".blend")
ARCHIVE_EXT = (".tar.gz", ".tgz", ".tar")
SECRET_FILE_PATTERNS = (".env", "*.env", ".env.*", "cli.toml", "credentials*", "*.pem", "*.key", "id_rsa*",
                        "id_ed25519*", "id_ecdsa*", ".netrc", ".git-credentials", "*.p12", "*.pfx")
BUILD_DIRS = ("target", "node_modules", "__pycache__", ".git", "wasm")
BUILD_DIR_PREFIXES = ("target-", "build-")
BUILD_EXT = (".wasm", ".pyc", ".o", ".rlib", ".rmeta", ".so", ".dylib")
EMAIL_ALLOW = {"noreply@anthropic.com"}
# A browser profile (cookies, logins, history, extension state) is refused whole.
BROWSER_PROFILE_MARKERS = ("prefs.js", "cookies.sqlite", "key4.db", "logins.json", "places.sqlite",
                           "Cookies", "Login Data", "Local State")


def _octets_ok(s):
    return all(0 <= int(x) <= 255 for x in s.split("."))


def mask(value, cat):
    n = len(value)
    if cat in SECRET_CATS:
        for pre in ("github_pat_", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "hf_", "sk-ant-", "sk-", "eyJ",
                    "AKIA", "xox", "AIza"):
            if value.startswith(pre):
                return f"{pre}…[{n} chars]"
        return f"…[{n} chars]"
    if cat in ("email", "owner-email"):
        return f"…@…[{n} chars]"
    if cat == "private-ip":
        return ".".join(value.split(".")[:2]) + ".x.x"
    if cat == "home-path":
        return re.sub(r"(/(?:home|Users)/|\\Users\\)([^/\\]+)", lambda m: m.group(1) + "…", value)
    if cat in IDENTITY_CATS:
        return f"[{n} chars]"   # no letters: a first and last letter can be enough to recognise
    if n <= 2:
        return value[:1] + "…"
    return f"{value[:1]}…{value[-1:]}[{n}]"


class Findings:
    def __init__(self):
        self.counts = {}
        self.examples = {}

    def add(self, cat, value, k=1):
        self.counts[cat] = self.counts.get(cat, 0) + k
        ex = self.examples.setdefault(cat, [])
        m = mask(value, cat)
        if m not in ex and len(ex) < 3:
            ex.append(m)

    def merge(self, other):
        for c, n in other.counts.items():
            self.counts[c] = self.counts.get(c, 0) + n
            ex = self.examples.setdefault(c, [])
            for e in other.examples.get(c, []):
                if e not in ex and len(ex) < 3:
                    ex.append(e)

    def total(self):
        return sum(self.counts.values())

    def as_dict(self):
        return {c: {"count": self.counts[c], "examples": self.examples.get(c, [])} for c in sorted(self.counts)}


# A word may follow a JSON \\uXXXX escape ("\\u00abName\\u00bb" in ASCII-escaped JSON): that is a boundary.
U_ESC = r"(?<=\\u[0-9a-fA-F]{4})"


def _lb(joiners):
    """A left word boundary: not after a joining character, or right after a \\uXXXX escape."""
    return rf"(?:{U_ESC}|(?<![{joiners}]))"


def _alternation(words, flags=0, boundary=True, hyphen_joins=True):
    words = sorted({w for w in words if w}, key=len, reverse=True)
    if not words:
        return None
    body = "|".join(re.escape(w) for w in words)
    if not boundary:
        return re.compile(f"(?:{body})", flags)
    # "_" separates ("experience_name.txt"). For host names "-" joins ("spark-2b4e"); for names
    # and logins it separates ("login-sessions", "experience-name").
    j = "A-Za-z0-9-" if hyphen_joins else "A-Za-z0-9"
    return re.compile(rf"{_lb(j)}(?:{body})(?![{j}])", flags)


PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
PRIVATE_IP = re.compile(r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
                        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
                        r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})(?![\d.]*\d)")
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
HOME_PATH = re.compile(r"(?<![\w.])(?:/home|/Users)/(?!\[)([A-Za-z0-9._-]+)|[A-Za-z]:\\\\?Users\\\\?([A-Za-z0-9._-]+)")
TOKEN_RULES = [
    ("hf-token", re.compile(r"(?<![\w-])hf_[A-Za-z0-9]{30,}(?![\w-])")),
    ("github-token", re.compile(r"(?<![\w-])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})(?![\w-])")),
    ("api-key", re.compile(r"(?<![\w-])sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}(?![\w-])")),
    ("aws-key", re.compile(r"(?<![\w-])AKIA[0-9A-Z]{16}(?![\w-])")),
    ("slack-token", re.compile(r"(?<![\w-])xox[abposr]-[A-Za-z0-9-]{10,}(?![\w-])")),
    ("google-key", re.compile(r"(?<![\w-])AIza[0-9A-Za-z_-]{35}(?![\w-])")),
    ("jwt", re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
]
# (category, regex, group holding the secret)
CONTEXT_RULES = [
    ("bearer", re.compile(r"(?i)\bbearer\s+((?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{12,}|[A-Za-z0-9._~+/=-]{24,})"), 1),
    ("secret-assignment", re.compile(r"(?i)(?:authorization|proxy-authorization)\s*\"?\s*[:=]\s*[\"']?basic\s+([A-Za-z0-9+/=]{8,})"), 1),
    ("secret-assignment", re.compile(r"(?i)\bx-api-key\"?\s*[:=]\s*[\"']?([^\s\"',;]{8,})"), 1),
    ("secret-assignment", re.compile(
        r"\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|_KEY|_AUTH|_PASS)\"?\s*[=:]\s*[\"']?"
        r"((?=[^\s\"',;]*[A-Za-z])[^\s\"',;$]{6,})"), 1),
    ("secret-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|client[_-]?secret|secret|password|passwd|token)"
        r"\"?\s*[=:]\s*[\"']?((?=[^\s\"',;]*[A-Za-z])(?=[^\s\"',;]*\d)[^\s\"',;$]{8,})"), 1),
    ("url-credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:@\"']+:[^/\s@\"']+)@"), 1),
]
SECRET_KEY = re.compile(r"(?i)(?:token|secret|password|passwd|api_?key|apikey|authorization|auth|credentials?|private_?key|_key)$")
NOT_SECRET_KEY = re.compile(r"(?i)(?:cache_key|sort_key|prompt_cache_key|^key|tokens)$")
MDNS = re.compile(r"(?<![\w./-])[A-Za-z0-9][A-Za-z0-9-]*\.(?:local|lan|ts\.net|tailnet)(?![\w/-])")
TS_NAME = re.compile(r"(?<![\w.-])[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net(?![\w-])")
# A Mac's default name ("Someones-MacBook-Pro"): short hyphenated words around the model name,
# bounded on both sides by a non-word character, so base64 runs in pages do not match.
MAC_HOST = re.compile(r"(?<![\w+/=-])(?:[A-Za-z0-9]{1,30}-){0,4}(?:MacBook(?:-(?:Pro|Air))?|iMac|Mac-mini|Mac-Studio)"
                      r"(?:-[A-Za-z0-9]{1,12}){0,3}(?![\w+/=-])")
PLAYER_LOG = re.compile(r"playing character #(\d+)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


# Owner-line echoes: a model quoting, varying or repeating an owner's typed line.
# ("say" is left out: it is the JSON key in front of every spoken line, "say": "Hi! …")
SPEECH_VERBS = {"said", "says", "saying", "typed", "types", "babbled", "babbles", "babbling", "muttered",
                "mutters", "called", "calls", "shouted", "shouts", "whispered", "greeted", "greets", "answered",
                "replied", "repeated", "repeats", "told", "asked", "asks", "uttered"}
COMMON_SHORT = {"hi", "hey", "helo", "yes", "no", "ok", "okay", "yeah", "thanks", "bye", "sup", "yo", "what",
                "why", "huh", "oh", "ah", "wow", "please", "sory", "god", "nice", "cool", "here", "there"}
WORD = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")
# Words too common to make a fuzzy echo on their own ("can see it" is not anyone's line).
STOPWORDS = set("""a an the and or but if then so of to in on at by for from with without into onto over under
up down out off about as is are was were be been being am do does did done have has had having i me my mine
we us our you your yours he him his she her hers it its they them their this that these those there here
what which who whom whose when where why how not no yes can could will would shall should may might must
just very too also only even still yet now then than all any some each every both few more most much many
one two get got go goes going went come came see saw seen look looked know knew think thought say said tell
told want wanted like make made let take took give gave well oh ah ok okay hi hey hello sure right good""".split())
QUOTE_CHARS = "\"'“”‘’«»`"
LINE_OPEN = r"(“|‘|«|\"|'|`|\\\"|&quot;|&#34;|&ldquo;|&#8220;|&lsquo;|&#8216;|&#39;|&apos;)"
LINE_CLOSE = r"(”|’|»|\"|'|`|\\\"|&quot;|&#34;|&rdquo;|&#8221;|&rsquo;|&#8217;|&#39;|&apos;)"


def _line_core(line):
    """A line without its leading or trailing whitespace and punctuation ("where am i ?" -> "where am i")."""
    return re.sub(r"^[\s.!?,…;:¿¡\-]+|[\s.!?,…;:\-]+$", "", line or "")


def _core_pattern(core):
    """Its regex: internal whitespace of any width."""
    return r"\s+".join(re.escape(w) for w in core.split())


def _collapse(w):
    """Lower case, runs of one letter folded ("ssssssssshi" and "sssshi" are both "shi")."""
    return re.sub(r"(.)\1+", r"\1", w.lower().replace("'", ""))


def _norm_line(s):
    return " ".join(_collapse(w) for w in WORD.findall(s))


class EchoMatcher:
    """Finds where a text quotes or closely repeats one of the owner's lines, beyond exact quotes.

    Tuned on play-tests 2 and 3 (docs/STORE.md, "Owner-line echoes"):
    - one- or two-word lines: a word equal after folding letter runs, or within edit ratio 0.8 for
      words of four letters or more ("sssshi" for "ssssssssshi"). A common word ("hi") counts
      only quoted alone or within two words after a speech verb ("said hi, then …"), so a
      resident's own "Hi! Are you new here?" stays;
    - longer lines: a window of the same length sharing at least 60% of its words (Jaccard, at
      least three) or reading 80% alike (difflib)."""

    def __init__(self, lines):
        import difflib
        self._difflib = difflib
        self.short, self.long = [], []
        for line in lines:
            toks = [_collapse(w) for w in WORD.findall(line)]
            toks = [t for t in toks if t]
            if not toks:
                continue
            if len(toks) <= 2:
                self.short.append((line, toks))
            elif len(self._distinctive(toks)) >= 2:
                # a longer line echoes fuzzily only through its distinctive words; one made of
                # common words ("I can see it") is caught only when repeated exactly
                self.long.append((line, toks))

    @staticmethod
    def _distinctive(toks):
        return {t for t in toks if t not in STOPWORDS and _collapse(t) not in STOPWORDS and len(t) >= 3}

    def __bool__(self):
        return bool(self.short or self.long)

    def _close(self, w, t):
        if w == t:
            return True
        return len(t) >= 4 and len(w) >= 3 and self._difflib.SequenceMatcher(None, w, t).ratio() >= 0.8

    def find(self, text, context=True):
        """[(start, end, line)] of every echo in text. context=False drops the quote-or-verb
        requirement for common words (for file names)."""
        words = [(m.start(), m.end(), _collapse(m.group(0))) for m in WORD.finditer(text)]
        out = []
        for line, toks in self.short:
            n = len(toks)
            common = all(t in COMMON_SHORT or len(t) <= 3 for t in toks)
            for i in range(len(words) - n + 1):
                if not all(self._close(words[i + k][2], toks[k]) for k in range(n)):
                    continue
                a, b = words[i][0], words[i + n - 1][1]
                if common and context:
                    before = text[max(0, a - 2):a]
                    after = re.match(r"[.!?,…]*\s?(.)?", text[b:b + 4])
                    quoted = any(c in QUOTE_CHARS for c in before[-1:]) and after and after.group(1) and \
                        after.group(1) in QUOTE_CHARS
                    verb = any(words[j][2] in SPEECH_VERBS for j in range(max(0, i - 2), i))
                    if not (quoted or verb):
                        continue
                out.append((a, b, line))
        for line, toks in self.long:
            n = len(toks)
            want = set(toks)
            rare = self._distinctive(toks)
            joined = " ".join(toks)
            for i in range(0, max(0, len(words) - n + 1)):
                win = [w[2] for w in words[i:i + n]]
                ws = set(win)
                shared_rare = rare & ws
                if len(shared_rare) < 2 or sum(len(t) for t in shared_rare) < 8:
                    continue
                inter = len(want & ws)
                if (inter >= 3 and inter / len(want | ws) >= 0.6) or \
                        self._difflib.SequenceMatcher(None, " ".join(win), joined).ratio() >= 0.8:
                    out.append((words[i][0], words[i + n - 1][1], line))
        out.sort()
        merged = []
        for a, b, l in out:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]), merged[-1][2])
            else:
                merged.append((a, b, l))
        return merged


# Play sessions publish an allow-list: the record of the run, not analysis of the person who played.
SESSION_ALLOW = (
    ("journal/*.jsonl", "the minds' journals"),
    ("journal/system/*.txt", "the journals' system prompts"),
    ("journal/batches/*.json", "the journals' provider batch records"),
    ("run/*.log", "the run's logs"),
    ("run/*.jsonl", "the run's recorded rows"),
    ("run/*.txt", "the run's installed script"),
    ("run/*.rhai", "the run's installed rules"),
    ("run/created_utc", "the run's creation time"),
    ("skills.rhai", "the scene's rules"),
    ("README.md", "the scene's description (only if it does not describe the owner)"),
)
OWNER_WORDS = re.compile(r"(?i)\b(owner|owner's|you|your|you're|yourself|feedback|play-?test(?:er)?s?|intends?|"
                         r"intention|wants? to|wishes|liked|disliked|felt)\b")


# Files we wrote, not the owner: an owner line can reach them only by substitution, in quotes.
TEMPLATE_PATTERNS = ("journal/system/*.txt", "*/journal/system/*.txt", "*.rhai", "*/run/installed_script.txt",
                     "run/installed_script.txt", "*/installed_source*", "installed_source*")
# A session's review files: scrubbed for review in the same pass, never published without approval.
SESSION_REVIEW_NAMES = ("report.json", "commands.jsonl")
COMMAND_FILES = ("commands.jsonl", "events.jsonl")
SAY_WORDS = {"say", "said", "speak", "human_say", "human_speak", "line", "sent", "chat"}


# Credential files: refused by name before anything is read, and listed as held.
SECRET_NAME_PATTERNS = (".env", ".env.*", "*.env", "*.token", "*.tokens", "*.key", "*.pem", "*.p12", "*.pfx",
                        "*.jks", "*.keystore", "*.kdbx", "*.secret", "*.secrets", "secrets.*", "id_rsa*",
                        "id_dsa*", "id_ecdsa*", "id_ed25519*", "credentials*", ".netrc", ".git-credentials",
                        ".pgpass", ".npmrc", ".pypirc", "cli.toml", "hf_token", "token", "*.credentials")
SECRET_DIRS = {"tokens", "token", "secrets", "secret", ".ssh", ".gnupg", "credentials", ".aws", "slop-store"}


def is_secret_path(relpath):
    """Whether a path names a credential: its file name or any folder of it."""
    parts = relpath.replace("\\", "/").replace("!", "/").split("/")
    name = parts[-1]
    if any(fnmatch.fnmatch(name, pat) for pat in SECRET_NAME_PATTERNS):
        return True
    return any(p in SECRET_DIRS for p in parts[:-1])


def _never_read():
    raise Refused("a secret path must not be read")


def is_template(relpath):
    p = relpath.replace("\\", "/").split("!")[-1]
    return any(fnmatch.fnmatchcase(p, pat) for pat in TEMPLATE_PATTERNS)


def is_command_row(relpath, obj):
    """A row of a command history (the client's commands or events): kept when it says a line."""
    if os.path.basename(relpath.split("!")[-1]) in COMMAND_FILES:
        return True
    if isinstance(obj, dict):
        for k in ("cmd", "command", "reducer", "kind", "type", "ev", "event"):
            if str(obj.get(k, "")).lower() in SAY_WORDS:
                return True
    return False


def session_rel(relpath):
    """The path inside the session folder ("session/journal/x.jsonl" -> "journal/x.jsonl"), or None."""
    parts = relpath.replace("\\", "/").split("/")
    if "session" not in parts[:-1]:
        return None
    return "/".join(parts[parts.index("session") + 1:])


def session_allowed(relpath):
    """(allowed?, reason) under the play-session allow-list."""
    inner = session_rel(relpath)
    if inner is None:
        return False, "held: outside session/ (feedback, reports, agents' analysis of the owner's play)"
    for pat, what in SESSION_ALLOW:
        if fnmatch.fnmatchcase(inner, pat) and inner.count("/") == pat.count("/"):
            return True, what
    return False, f"held: not on the session allow-list (session/{inner})"


class Scrubber:
    """Redacts what must not be public from text, refuses whole files that cannot be made safe,
    and holds back files in categories the owner has not decided."""

    def __init__(self, identity, decisions=None, cfg=None, machine=None, player_ids=(), kind=None,
                 player_names=()):
        self.id = identity
        self.extra_names = {n.strip() for n in player_names if n and n.strip()}   # --player-name
        self.self_names = set()      # names the player gave themself, learned from the run
        self.name_candidates = {}    # names residents hold for the player: lower -> forms, holders, where
        self.name_table = []         # the backstop: every candidate and what was done with it
        self._holder = ""            # who holds what is being read (a journal's actor, a file)
        self.name_uses = {}          # candidate lower -> {holder: uses in speech, journals and logs}
        self._name_keys = []         # name_table's candidate keys, in order (never written out)
        self._cand_re = None
        self.session_span = None     # (first, last) unix ms of the client log: the played span
        self.decisions = dict((cfg or {}).get("decisions") or {})
        self.decisions.update(decisions or {})
        self.decisions = {k: v for k, v in self.decisions.items() if not k.startswith("_")}
        for k in DECISIONS:
            self.decisions.setdefault(k, "undecided")
        self.decisions.setdefault("owner_lines", "exclude")
        self.cfg = cfg or {"never_touch": {}, "never_touch_names": []}
        self.machine = machine or "test"
        self.player_ids = {int(p) for p in player_ids}
        self.player_labels = set()
        self.owner_lines = set()
        self.kind = kind
        self.logins_seen = set()
        self.profile_dirs = set()
        self.dropped = []       # what the session echo pass dropped: {file, where, why}
        self.review_data = {}   # scrubbed copies of review-only files (report.json, commands.jsonl)
        self._template = False  # inside a prompt template or installed script: exact quoted lines only
        self.ambiguous = []     # self-given names replaced where it could not be told name from word
        self.template_words = set()   # words of the game's own text in this run (templates, scripts)
        self._cur_file, self._cur_loc = "", ""
        self.echo = None
        self._build()

    def _build(self):
        idn = self.id
        self.known_secret = _alternation(idn.secrets, boundary=False)
        self.owner_email = _alternation(idn.emails, re.I, boundary=False)
        self.owner_name = _alternation(idn.names, re.I, hyphen_joins=False)
        self.surname = _alternation(idn.surnames, re.I, hyphen_joins=False)
        # names: any case, and "_" counts as a separator ("experience_diego.txt")
        self._names()
        self.hostnames = _alternation(idn.hostnames, re.I)
        # binary scans: literals without word boundaries (strings in binaries run into bytes)
        self.bin_literals = _alternation(idn.emails | idn.hostnames | idn.names | idn.surnames, re.I,
                                         boundary=False)
        self._logins()
        self._lines()

    def _names(self):
        """The player's names, replaced by "Player".
        - The owner's first name: everywhere, any case; "_" and "-" separate.
        - Names the player gave themself in a typed line, and --player-name: only where the word
          names the player, never in templates (_self_name_sub), because such a name can also be
          an ordinary game word."""
        first = set(self.id.first_names)
        own = (self.extra_names | self.self_names) - first
        self.player_names = first | own
        self.self_name_set = {n.lower() for n in own}
        self.first_name = (re.compile(_lb("A-Za-z0-9") + r"(?:" + "|".join(re.escape(n) for n in
                                      sorted(first, key=len, reverse=True)) + r")(?![A-Za-z0-9])", re.I)
                           if first else None)
        alt = "|".join(re.escape(n) for n in sorted(own, key=len, reverse=True))
        # in text "_" joins: on_strike is an identifier, not a name; in file names "_" separates
        self.self_name_re = re.compile(rf"{_lb('A-Za-z0-9_')}(?:{alt})(?![A-Za-z0-9_])", re.I) if own else None
        self.self_name_path = re.compile(rf"{_lb('A-Za-z0-9')}(?:{alt})(?![A-Za-z0-9])", re.I) if own else None

    @staticmethod
    def _clean_name(name):
        n = (name or "").strip().strip("«»“”\"'‘’`.,!?;:()[]\\ ")
        if not n or " " in n or len(n) < 2 or len(n) > 30 or not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", n):
            return None
        return n

    def learn_self_name(self, name):
        """A name the player gave themself. Single words only; not a common word or a state."""
        n = self._clean_name(name)
        if not n or n.lower() in STOPWORDS or n.lower() in NOT_NAMES:
            return
        self.self_names.add(n)

    def _candidate(self, name, where):
        """A name a resident holds for the player's character. Not yet the player's name: it is
        kept only if the player typed the same word (finish_learning)."""
        if self._holder is None:        # the player's own record (player memory) is not a resident's
            return
        n = self._clean_name(name)
        if not n:
            return
        c = self.name_candidates.setdefault(n.lower(), {"forms": set(), "holders": set(), "where": set()})
        c["forms"].add(n)
        c["holders"].add(self._holder or "?")
        c["where"].add(where)

    def _logins(self):
        self.login = _alternation(self.id.logins | self.logins_seen, hyphen_joins=False)

    def _lines(self):
        lines = sorted(self.owner_lines, key=len, reverse=True)
        cores = sorted({_line_core(l) for l in lines if _line_core(l)}, key=len, reverse=True)
        if cores:
            body = "|".join(_core_pattern(c) for c in cores)
            # any quote, typographic, single, escaped or as an HTML entity; any case; the line's
            # whitespace and leading or trailing punctuation are not required ("where am i ?")
            self.line_re = re.compile(LINE_OPEN + rf"[\s.!?,…¿¡]*({body})([\s.!?,…]*)" + LINE_CLOSE, re.I)
        else:
            self.line_re = None
        self.line_norms = {_norm_line(l) for l in lines}
        self.echo = EchoMatcher(lines) if lines else None
        # Lines of 6+ characters are also caught unquoted (a model repeating them in a reply);
        # shorter ones ("hi") only in quotes, or every "hi" in the world would go.
        longer = [c for c in cores if len(c) >= 6]
        self.line_bare = (re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(_core_pattern(c) for c in longer) +
                                     r")(?![A-Za-z0-9])", re.I) if longer else None)

    # -- pass 1: learn the session's player and the owner's lines --------------------------------
    def learn_player(self, text):
        clean = ANSI.sub("", text)
        for m in PLAYER_LOG.finditer(clean):
            self.player_ids.add(int(m.group(1)))
        stamps = [_iso_ms(m.group(0)) for m in ISO_STAMP.finditer(clean)]
        stamps = [x for x in stamps if x]
        if stamps and PLAYER_LOG.search(clean):
            lo, hi = min(stamps), max(stamps)
            if self.session_span:
                lo, hi = min(lo, self.session_span[0]), max(hi, self.session_span[1])
            self.session_span = (lo, hi)

    def in_span(self, at_ms):
        """Whether a row's time lies in the played span (unknown span or time: yes). A "You said"
        row after the client quit is the character's AI mind speaking, not the owner."""
        if not self.session_span or not isinstance(at_ms, int):
            return True
        return self.session_span[0] - 1000 <= at_ms <= self.session_span[1] + 5000

    def learn_logins(self, text):
        before = len(self.logins_seen)
        for m in HOME_PATH.finditer(text):
            name = m.group(1) or m.group(2)
            if name and name not in ("Shared", "runner", "root", "user", "Public", "x"):
                self.logins_seen.add(name)
        if len(self.logins_seen) != before:
            self._logins()

    def learn_lines(self, s):
        if not self.player_ids:
            return
        pids = self.player_ids
        # Names residents hold for the player's character, as candidates: tags ({X=#26}), labels
        # ("X (#26)", "X (person:26)"), and name fields in a graph (also as escaped JSON text) near
        # the player's id. A candidate becomes the player's name only if the player typed it.
        for m in re.finditer(r"([^=,{}\n]{1,40})=#(\d+)", s):
            if int(m.group(2)) in pids:
                self._candidate(m.group(1), "tag {X=#id}")
        for m in re.finditer(r"(?<![\w'-])([A-Z][A-Za-z'-]{1,30}) \((?:#|person:)(\d+)\)", s):
            if int(m.group(2)) in pids:
                self._candidate(m.group(1), "label X (#id)")
        for m in NAME_FIELD_TEXT.finditer(s):
            window = s[max(0, m.start() - 400):m.start()]
            if any(re.search(rf"person:{p}\b|\\*\"(?:id|key|person|who|about|target)\\*\"\s*:\s*\\*\"?{p}\b", window)
                   for p in pids):
                self._candidate(m.group(2), f"graph field {m.group(1)} (in text)")
        if "“" not in s:
            return
        # The player's own percepts (player memory, "played by a person"; their own rows):
        # "You said[ to …]: “…”" is the owner speaking.
        own = "(played by a person" in s or any(f"# Who you are ({n})" in s
                                                for n in self.player_labels | self.id.first_names)
        if own:
            for m in re.finditer(r"You said(?: to [^:“\n]{1,80})?: “([^”\n]{1,800})”", s):
                self.owner_lines.add(m.group(1))
        for m in re.finditer(r"(?m)^\s*\d+\s*\|\s*(\d+)\s*\|.*?You said(?: to [^:“\n]{1,80})?: “([^”\n]{1,800})”", s):
            if int(m.group(1)) in pids:
                cols = [c.strip() for c in m.group(0).split("|")]
                at = int(cols[3]) if len(cols) > 3 and cols[3].isdigit() and len(cols[3]) >= 12 else None
                if self.in_span(at):
                    self.owner_lines.add(m.group(2))
        # "<speaker> said[ to <x>]: “…” {<speaker>=#n, …}": the tags follow the order of mention,
        # so the first is the speaker, except in "You said to …", where the tags start after "You".
        for m in re.finditer(r"(?:^|\n|\] |\d\d:\d\d )([^:“\n\]]{1,80}?) [a-z]+(?: to [^:“\n]{1,80})?: "
                             r"“([^”\n]{1,800})” \{([^}]*)\}", s):
            if m.group(1).strip().lower() in ("you", "- you"):
                continue
            first = re.search(r"=#(\d+)", m.group(3))
            if first and int(first.group(1)) in pids:
                self.owner_lines.add(m.group(2))
        for m in re.finditer(r"\(#(\d+)\)\s*(?:said)?:\s*“([^”\n]{1,800})”", s):
            if int(m.group(1)) in pids:
                self.owner_lines.add(m.group(2))
        for h in re.finditer(r"# You and (.+?) \(#(\d+)\)", s):
            if int(h.group(2)) not in pids:
                continue
            label = h.group(1)
            self.player_labels.add(label)
            for m in re.finditer(rf"(?m)^\s*(?:- )?{re.escape(label)}: “([^”\n]{{1,800}})”", s):
                self.owner_lines.add(m.group(1))

    def learn_json(self, obj, name):
        if not self.player_ids:
            return
        if isinstance(obj, dict) and obj.get("role") == "system" and isinstance(obj.get("content"), str):
            self.template_words.update(w.lower() for w in WORD.findall(obj["content"]))
        if isinstance(obj, dict):
            who = None
            for k in ("speaker", "by", "from", "said_by"):
                v = obj.get(k)
                if isinstance(v, int) and v in self.player_ids:
                    who = v
            said = any(str(obj.get(k, "")).lower() in ("say", "said", "line", "sent", "speech", "human_say")
                       for k in ("kind", "type", "ev", "event", "reducer"))
            for k in ("text", "words", "line", "said"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip() and (who is not None or
                                                         (said and os.path.basename(name) == "events.jsonl")):
                    self.owner_lines.add(v)
            if self._about_player(obj):
                self._learn_graph_names(obj)
            subj = obj.get("subject")
            if isinstance(subj, int) and subj in self.player_ids and self.in_span(obj.get("at_ms")):
                for v in obj.values():
                    if isinstance(v, str):
                        m = re.match(r"\s*You said(?: to [^:“\n]{1,80})?: “([^”\n]{1,800})”", v)
                        if m:
                            self.owner_lines.add(m.group(1))
            for v in obj.values():
                self.learn_json(v, name)
        elif isinstance(obj, list):
            for v in obj:
                self.learn_json(v, name)
        elif isinstance(obj, str):
            self.learn_lines(obj)
            t = obj.strip()
            if t[:1] in "{[" and t[-1:] in "}]" and len(t) < 2_000_000:
                try:
                    self.learn_json(json.loads(t), name)   # a model reply is JSON text
                except ValueError:
                    pass

    def _about_player(self, d):
        """A dict about the player: an id key holding the player's id, or "person:<id>"/"#<id>"."""
        for k, v in d.items():
            if k in ("id", "person", "who", "about", "target", "of", "key", "node", "character") and (
                    (isinstance(v, int) and v in self.player_ids) or
                    (isinstance(v, str) and any(v in (f"person:{p}", f"#{p}", str(p)) for p in self.player_ids))):
                return True
        return False

    def _learn_graph_names(self, d):
        """known_name and the like, in a memory graph node or relation about the player: candidates."""
        for k, v in d.items():
            if isinstance(v, str) and k in NAME_KEYS:
                self._candidate(v, f"graph field {k}")
            elif isinstance(v, dict):
                self._learn_graph_names(v)

    def finish_learning(self):
        self.owner_lines = {l for l in self.owner_lines if l.strip()}
        # 1. names residents hold for the player, kept if the player typed the same word
        typed = {w.lower().strip("'") for l in self.owner_lines for w in WORD.findall(l)}
        first = {n.lower() for n in self.id.first_names}
        for low, c in sorted(self.name_candidates.items()):
            form = sorted(c["forms"])[0]
            entry = {"name": mask(form, "owner-first-name"), "held_by": sorted(c["holders"]),
                     "where": sorted(c["where"]), "typed_by_player": low in typed}
            self._name_keys.append(low)
            if low in first:
                entry["action"] = "replaced everywhere: the owner's first name"
            elif low not in typed:
                entry["action"] = "kept: the player never typed it (a resident's word)"
            elif low in STOPWORDS or low in NOT_NAMES:
                entry["action"] = "kept: a common word or a state, not a name"
            else:
                self.learn_self_name(form)
                entry["action"] = "replaced where it names the player (self-given name)"
            self.name_table.append(entry)
        # 2. an extra source: a self-introduction in a typed line ("I'm X", "call me X", ...)
        held = set(self.name_candidates)
        for line in self.owner_lines:
            for rx in SELF_NAME_RULES:
                m = rx.search(line)
                if m:
                    n = self._clean_name(m.group(1))
                    if n and n.lower() not in held and n.lower() not in first:
                        before = set(self.self_names)
                        self.learn_self_name(n)
                        if self.self_names != before:
                            self._name_keys.append(n.lower())
                            self.name_table.append({"name": mask(n, "owner-first-name"), "held_by": [],
                                                    "where": ["the player's typed self-introduction"],
                                                    "typed_by_player": True,
                                                    "action": "replaced where it names the player (typed only)"})
        keys = sorted(set(self._name_keys), key=len, reverse=True)
        self._cand_re = (re.compile(_lb("A-Za-z0-9_") + "(?:" + "|".join(re.escape(k) for k in keys) +
                                    r")(?![A-Za-z0-9_])", re.I) if keys else None)
        self._names()
        self._lines()

    def _count_uses(self, text, holder):
        """Uses of each resident-held name in speech, journals and logs, by holder (not templates)."""
        if self._cand_re is None or not text:
            return
        for m in self._cand_re.finditer(text):
            d = self.name_uses.setdefault(m.group(0).lower(), {})
            d[holder] = d.get(holder, 0) + 1

    def uses_column(self):
        """For names.md: per table row, "holder N, …", most uses first."""
        out = []
        for k in self._name_keys:
            d = self.name_uses.get(k, {})
            out.append(", ".join(f"{h} {n}" for h, n in sorted(d.items(), key=lambda x: (-x[1], x[0]))) or "–")
        return out

    # -- pass 2: redact -------------------------------------------------------------------------
    def _sub(self, regex, text, cat, acc, repl, group=0):
        if regex is None:
            return text

        def f(m):
            acc.add(cat, m.group(group))
            if group == 0:
                return repl
            s, e = m.span(group)
            base = m.start(0)
            whole = m.group(0)
            return whole[:s - base] + repl + whole[e - base:]
        return regex.sub(f, text)

    def scrub_text(self, s, acc, binary=False, self_names="narrow"):
        s = self._sub(self.known_secret, s, "known-secret", acc, "[redacted:secret]")
        for cat, rx in TOKEN_RULES:
            s = self._sub(rx, s, cat, acc, f"[redacted:{cat}]")
        if binary:
            # Only literal and high-specificity patterns: generic ones (any email, any private
            # address, assignments) match noise in compressed or numeric bytes.
            s = self._sub(self.bin_literals, s, "owner-identity", acc, "[owner]")
            s = self._sub(re.compile(r"(?<![\w.])(?:/home|/Users)/[A-Za-z0-9._-]{3,}/"), s, "home-path", acc, "~/")
            return s
        for cat, rx, g in CONTEXT_RULES:
            s = self._sub(rx, s, cat, acc, "[redacted:secret]", g)
        if not binary and self.line_re is not None and self.decisions.get("owner_lines") != "include":
            def lf(m):
                acc.add("owner-line", m.group(2))
                return m.group(1) + "[owner line]" + m.group(4)
            s = self.line_re.sub(lf, s)
            if not self._template:
                s = self._sub(self.line_bare, s, "owner-line", acc, "[owner line]")
        s = self._sub(self.owner_email, s, "owner-email", acc, "[owner-email]")

        def ef(m):
            v = m.group(0)
            if v.lower() in EMAIL_ALLOW or v.startswith("[") or v.lower().endswith((".png", ".jpg", ".glb")):
                return v
            acc.add("email", v)
            return "[email]"
        s = EMAIL.sub(ef, s)

        def hf(m):
            acc.add("home-path", m.group(0))
            return "~"
        s = HOME_PATH.sub(hf, s)

        def ipf(m):
            v = m.group(0)
            if not _octets_ok(v):
                return v
            acc.add("private-ip", v)
            return "[private-ip]"
        s = PRIVATE_IP.sub(ipf, s)
        s = self._sub(self.hostnames, s, "hostname", acc, "[host]")
        for rx in (TS_NAME, MDNS, MAC_HOST):
            s = self._sub(rx, s, "hostname", acc, "[host]")
        s = self._sub(self.owner_name, s, "owner-name", acc, "[owner]")
        s = self._sub(self.surname, s, "owner-name", acc, "[owner]")
        s = self._sub(self.login, s, "login", acc, "[user]")
        if not binary and self.decisions.get("owner_first_name", "redact") != "include":
            def fn(m):
                acc.add("owner-first-name", m.group(0))
                v = m.group(0)
                return "player" if v.islower() else "PLAYER" if v.isupper() and len(v) > 1 else "Player"
            if self.first_name is not None:
                s = self.first_name.sub(fn, s)
            if self.self_name_re is not None and self_names != "off" and not self._template:
                s = self._self_name_sub(s, acc, self_names)
        return s

    # -- names the player gave themself --------------------------------------------------------
    def _self_name_sub(self, s, acc, mode):
        """Replace a self-given name where it names the player; keep it where it is plainly the
        ordinary word; replace and list it where that cannot be told (self.ambiguous).
        mode "all" (review output) replaces every occurrence."""
        out, last = [], 0
        for m in self.self_name_re.finditer(s):
            a, b, word = m.start(), m.end(), m.group(0)
            kind = "name" if mode == "all" else _self_name_kind(s, a, b, word,
                                                                 word.lower() in self.template_words)
            out.append(s[last:a])
            if kind == "ordinary":
                acc.add("self-name-kept", word)
                out.append(word)
            elif kind == "kept-listed":
                acc.add("self-name-kept", word)
                out.append(word)
                self._list_ambiguous(s, a, b, word, "kept: lowercase right after a possessive or an article "
                                                    "(the ordinary word)")
            else:
                acc.add("self-name", word)
                rep = "player" if word.islower() else "PLAYER" if word.isupper() and len(word) > 1 else "Player"
                out.append(rep)
                if kind == "ambiguous":
                    self._list_ambiguous(s, a, b, rep, f"replaced by {rep}")
            last = b
        out.append(s[last:])
        return "".join(out)

    def _list_ambiguous(self, s, a, b, rep, action):
        ctx = s[max(0, a - 70):a] + "\x00" + s[b:b + 70]
        ctx = self.self_name_path.sub(lambda m: f"[{len(m.group(0))} chars]", ctx)
        ctx = self.scrub_text(ctx, Findings(), self_names="off").replace("\n", " ")
        ctx = ctx.replace("\x00", f"[{b - a} chars]")
        line = s.count("\n", 0, a) + 1
        where = self._cur_loc + (f", line {line}" if "\n" in s else "")
        self.ambiguous.append({"file": self._cur_file, "where": where, "context": ctx,
                               "replacement": rep if action.startswith("replaced") else None, "action": action})
    def scrub_obj(self, obj, acc):
        if isinstance(obj, dict) and obj.get("role") == "system" and not self._template:
            # a system prompt is our template: an owner line can reach it only by substitution
            self._template = True
            try:
                return self.scrub_obj(obj, acc)
            finally:
                self._template = False
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                k2 = self.scrub_text(k, acc, self_names="off") if isinstance(k, str) else k
                if (isinstance(v, str) and isinstance(k, str) and SECRET_KEY.search(k)
                        and not NOT_SECRET_KEY.search(k) and len(v) >= 6 and not v.startswith("[redacted")
                        and " " not in v):
                    acc.add("secret-field", v)
                    out[k2] = "[redacted:secret]"
                elif (isinstance(v, str) and k in NAME_KEYS and self.self_name_re is not None
                      and v.strip().strip("«»“”\"'‘’").lower() in self.self_name_set):
                    acc.add("self-name", v)
                    out[k2] = "Player"                       # the name on the person
                elif isinstance(v, str) and k in CODE_KEYS:
                    out[k2] = self.scrub_text(v, acc, self_names="off")   # a game code, not a name
                else:
                    loc = self._cur_loc
                    self._cur_loc = f"{loc}.{k}" if loc else str(k)
                    try:
                        out[k2] = self.scrub_obj(v, acc)
                    finally:
                        self._cur_loc = loc
            return out
        if isinstance(obj, list):
            return [self.scrub_obj(v, acc) for v in obj]
        if isinstance(obj, str):
            if (self.line_re is not None and self.decisions.get("owner_lines") != "include"
                    and _norm_line(obj) in self.line_norms and obj.strip()):
                acc.add("owner-line", obj)
                return "[owner line]"
            return self.scrub_text(obj, acc)
        return obj

    def publish_path(self, rel, acc=None):
        """The path a file is published under: scrubbed like text, and in a play session any
        word of it that echoes an owner line, even a common one ("reply_hi"), is replaced."""
        acc = acc if acc is not None else Findings()
        pub = self.scrub_text(rel, acc, self_names="off").replace("[owner line]", "owner-line")
        if self.self_name_path is not None:
            pub = self.self_name_path.sub(lambda m: "player" if m.group(0).islower() else "Player", pub)
        if self._echo_on():
            for a, b, line in reversed(self.echo.find(pub, context=False)):
                acc.add("owner-echo", pub[a:b])
                pub = pub[:a] + "owner-line" + pub[b:]
        return pub

    def _replace_lines(self, obj, acc):
        """Every string that holds or echoes an owner line becomes "[owner line]"; numbers (the
        row's time) and other strings stay."""
        if isinstance(obj, dict):
            return {k: self._replace_lines(v, acc) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._replace_lines(v, acc) for v in obj]
        if isinstance(obj, str) and ("[owner line]" in obj or self.echo.find(obj)):
            acc.add("owner-line", obj)
            return "[owner line]"
        return obj

    def safe_text(self, text):
        """What review output may say: the published redaction, plus echoes of owner lines."""
        out = self.scrub_text(str(text), Findings(), self_names="all")
        if self.echo is not None and bool(self.echo) and self.decisions.get("owner_lines") != "include":
            for a, b, line in reversed(self.echo.find(out)):
                out = out[:a] + "[owner line]" + out[b:]
        return out

    def safe(self, obj, path_keys=("path", "published_as", "file", "files")):
        """A report object made safe for review files: paths as published, every string redacted."""
        if isinstance(obj, dict):
            return {self.safe_text(k): (self._safe_path(v) if k in path_keys else self.safe(v, path_keys))
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.safe(v, path_keys) for v in obj]
        if isinstance(obj, str):
            return self.safe_text(obj)
        return obj

    def _safe_path(self, v):
        if isinstance(v, list):
            return [self._safe_path(x) for x in v]
        if isinstance(v, str):
            return self.safe_text(self.publish_path(v))
        return v

    # -- session echo pass: drop what quotes or repeats an owner line ------------------------------
    def _echo_on(self):
        return (self._session() and self.decisions.get("owner_lines") != "include"
                and self.echo is not None and bool(self.echo))

    def _echoes(self, text):
        hits = []
        if "[owner line]" in text:
            hits.append("quotes an owner line")
        for a, b, line in self.echo.find(text):
            hits.append(f"echo of {mask(line, 'owner-line')}: {mask(text[a:b], 'owner-line')}")
        return hits

    def _redact_echo(self, obj, acc):
        if isinstance(obj, dict):
            if obj.get("role") == "system":
                return obj      # templates: exact quoted lines only, already redacted
            return {k: self._redact_echo(v, acc) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._redact_echo(v, acc) for v in obj]
        if isinstance(obj, str):
            spans = self.echo.find(obj)
            for a, b, line in reversed(spans):
                acc.add("owner-echo", obj[a:b])
                obj = obj[:a] + "[owner line]" + obj[b:]
            return obj
        return obj

    def _echo_pass(self, relpath, name, new, acc):
        """In a play session: drop journal entries whose reply, and world rows or text lines that,
        quote or echo an owner line; redact echoes inside prompts and JSON files. Command-history
        rows (a say) are kept, with their text replaced. Templates are left to the exact pass."""
        if is_template(relpath):
            return new
        if name.endswith(".jsonl"):
            out = []
            for i, line in enumerate(new.splitlines()):
                try:
                    obj = json.loads(line) if line.strip() else None
                except ValueError:
                    obj = None
                if isinstance(obj, dict) and "request" in obj and "reply" in obj:
                    hits = self._echoes(str(obj.get("reply")))
                    if hits:
                        self.dropped.append({"file": relpath, "where": f"entry {i} ({obj.get('purpose')}, "
                                             f"{obj.get('actor')})", "why": "; ".join(hits)})
                        acc.add("dropped-entry", str(i))
                        continue
                    out.append(json.dumps(self._redact_echo(obj, acc), ensure_ascii=False, separators=(",", ":")))
                    continue
                hits = self._echoes(line) if line.strip() else []
                if hits and isinstance(obj, (dict, list)) and is_command_row(relpath, obj):
                    # a command history keeps its row and timestamp; only the words go
                    obj = self._replace_lines(obj, acc)
                    self.dropped.append({"file": relpath, "where": f"row {i}", "why": "; ".join(hits),
                                         "action": "kept, text replaced by [owner line]"})
                    acc.add("kept-row", str(i))
                    out.append(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
                    continue
                if hits:
                    self.dropped.append({"file": relpath, "where": f"row {i}", "why": "; ".join(hits),
                                         "action": "dropped"})
                    acc.add("dropped-row", str(i))
                    continue
                out.append(line)
            return "\n".join(out) + ("\n" if out else "")
        if name.endswith(".json"):
            try:
                return json.dumps(self._redact_echo(json.loads(new), acc), ensure_ascii=False, indent=1) + "\n"
            except ValueError:
                pass
        out = []
        for i, line in enumerate(new.splitlines()):
            hits = self._echoes(line)
            if hits:
                self.dropped.append({"file": relpath, "where": f"line {i + 1}", "why": "; ".join(hits)})
                acc.add("dropped-line", str(i + 1))
                out.append("[line dropped: it quotes or repeats an owner line]")
            else:
                out.append(line)
        return "\n".join(out) + ("\n" if new.endswith("\n") else "")

    # -- files ----------------------------------------------------------------------------------
    def classify(self, relpath, abspath=None):
        """(status, reason) before reading: refused | held | skipped | ok."""
        name = os.path.basename(relpath)
        parts = relpath.replace("\\", "/").split("/")
        if abspath:
            nt = is_never_touch(abspath, self.cfg, self.machine)
            if nt:
                return "refused", f"never-touch folder ({tilde(nt)})"
        if name.startswith("._") or name == ".DS_Store":
            return "refused", "macOS metadata (AppleDouble/.DS_Store)"
        norm = relpath.replace("\\", "/")
        for d in self.profile_dirs:
            if d == "." or norm.startswith(d + "/"):
                return "refused", f"browser profile ({d}/: cookies, logins, history)"
        if is_secret_path(relpath) or any(fnmatch.fnmatch(name, p) for p in SECRET_FILE_PATTERNS):
            return "refused", "secret path, not read"
        for p in parts[:-1]:
            if p in BUILD_DIRS or p.startswith(BUILD_DIR_PREFIXES):
                return "skipped", f"build output or cache ({p}/)"
        if name.endswith(BUILD_EXT):
            return "skipped", "build output"
        if self._session():
            if name in SESSION_REVIEW_NAMES:
                return "review", ("held: scrubbed for review only (review/); not published without the "
                                  "general coordinator's approval")
            allowed, why = session_allowed(relpath)
            if not allowed:
                return "excluded", why
        if name.endswith(MEDIA_EXT) and self._session():
            return self._decision("session_media")
        if name.endswith((".html", ".htm")) and self._session():
            return "excluded", "report page: play_report.py regenerates it from the session's evidence"
        if name in OWNER_NOTE_NAMES:
            return self._decision("owner_notes")
        if "journal" in parts[:-1] and name.endswith((".jsonl", ".txt")):
            return self._decision("model_exchanges")
        return "ok", None

    def _session(self):
        return self.kind == "play-session"

    def _decision(self, cat):
        d = self.decisions.get(cat, "undecided")
        if d == "include":
            return "ok", None
        if d == "undecided":
            return "held", f"owner decision pending: {cat}"
        if d == "hold":
            return "excluded", f"held by the owner: {cat}"
        return "excluded", f"owner decision: {cat} = {d}"

    def scrub_bytes(self, relpath, data):
        """(status, reason, scrubbed bytes or None, Findings). Status ok means publishable."""
        if is_template(relpath) and not self._template:
            self._template = True
            try:
                return self.scrub_bytes(relpath, data)
            finally:
                self._template = False
        acc = Findings()
        name = os.path.basename(relpath)
        if name.endswith(".gz") and not name.endswith(ARCHIVE_EXT):
            try:
                inner = gzip.decompress(data)
            except (OSError, EOFError):
                return "refused", "unreadable gzip", None, acc
            st, why, out, acc = self.scrub_bytes(relpath[:-3], inner)
            return st, why, (gzip.compress(out, mtime=0) if out is not None else None), acc
        text = _as_text(data)
        if text is None:
            if not name.lower().endswith(BINARY_OK_EXT):
                return "refused", "binary of unknown kind (not scanned)", None, acc
            probe = data.decode("latin-1")
            if PRIVATE_KEY.search(probe):
                return "refused", "contains a private key", None, acc
            self.scrub_text(probe, acc, binary=True)
            if acc.total():
                return "refused", "binary holding identifying or secret text (cannot redact in place)", None, acc
            return "ok", "binary (scanned for secrets and identity)", data, acc
        if PRIVATE_KEY.search(text):
            return "refused", "contains a private key", None, acc
        if self._session() and session_rel(relpath) == "README.md":
            hit = OWNER_WORDS.search(text)
            idn = None if hit else (self.first_name.search(text) if self.first_name else None) or \
                (self.owner_name.search(text) if self.owner_name else None) or \
                (self.login.search(text) if self.login else None)
            if hit or idn:
                return "excluded", ("held: the README describes the owner or their intentions "
                                    f"({'mentions “' + hit.group(0) + '”' if hit else 'names the owner'})"), None, acc
        self._cur_file, self._cur_loc = relpath, ""
        base = os.path.basename(relpath.split("!")[-1])
        counting = self._cand_re is not None and not self._template and not is_template(relpath)
        if counting and not name.endswith(".jsonl"):
            self._count_uses(text, base)
        if name.endswith(".jsonl"):
            out = []
            for i, line in enumerate(text.splitlines()):
                self._cur_loc = f"row {i}"
                if not line.strip():
                    out.append(line)
                    continue
                if counting:
                    try:
                        h = self._holder_of(json.loads(line), base)
                    except ValueError:
                        h = base
                    self._count_uses(line, h if h is not None else "the player's own record")
                try:
                    obj = json.loads(line)
                except ValueError:
                    out.append(self.scrub_text(line, acc))
                    continue
                out.append(json.dumps(self.scrub_obj(obj, acc), ensure_ascii=False, separators=(",", ":")))
            new = "\n".join(out) + ("\n" if text.endswith("\n") else "")
        elif name.endswith(".json"):
            try:
                obj = json.loads(text)
                new = json.dumps(self.scrub_obj(obj, acc), ensure_ascii=False, indent=1) + "\n"
            except ValueError:
                new = self.scrub_text(text, acc)
        else:
            new = self.scrub_text(text, acc)
        if self._echo_on():
            new = self._echo_pass(relpath, name, new, acc)
        return "ok", None, new.encode("utf-8"), acc

    def learn_bytes(self, relpath, data):
        name = os.path.basename(relpath)
        if name.endswith(".gz") and not name.endswith(ARCHIVE_EXT):
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError):
                return
            name = name[:-3]
        text = _as_text(data)
        if text is None:
            return
        self.learn_logins(text)
        if is_template(relpath):
            self.template_words.update(w.lower() for w in WORD.findall(text))
        base = os.path.basename(relpath.split("!")[-1])
        self._holder = base
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                try:
                    obj = json.loads(line)
                except ValueError:
                    self._holder = base
                    self.learn_lines(line)
                    continue
                self._holder = self._holder_of(obj, base)
                self.learn_json(obj, relpath)
        elif name.endswith(".json"):
            try:
                self.learn_json(json.loads(text), relpath)
            except ValueError:
                self.learn_lines(text)
        else:
            self.learn_lines(text)
        self._holder = ""

    def _holder_of(self, obj, base):
        """Who holds a journal entry's words: its actor; None for the player's own record."""
        if not isinstance(obj, dict):
            return base
        req = json.dumps(obj.get("request") or "", ensure_ascii=False)
        actor = str(obj.get("actor") or "")
        if "(played by a person" in req or actor.lower() in {n.lower() for n in self.id.first_names}:
            return None
        return actor or base


def _as_text(data):
    head = data[:8192]
    if b"\x00" in head:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --------------------------------------------------------------------------------------------
# Walking a source (directory, file, tarball members)
# --------------------------------------------------------------------------------------------

def iter_source(src):
    """Yield (relpath, abspath or None, loader) for every regular file under src, recursing into
    tarballs (members appear as `archive.tgz!member`)."""
    src = os.path.abspath(src)
    if os.path.isfile(src):
        base = os.path.dirname(src)
        yield from _iter_file(os.path.basename(src), src)
        return
    for root, dirs, names in os.walk(src, followlinks=False):
        dirs.sort()
        for n in sorted(names):
            p = os.path.join(root, n)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            yield from _iter_file(os.path.relpath(p, src), p)


def _iter_file(rel, path):
    if is_secret_path(rel):
        yield rel, path, _never_read                              # listed, never opened
        return
    if path.endswith(ARCHIVE_EXT) and tarfile.is_tarfile(path):
        yield rel, path, None  # the archive itself (listed, not uploaded as-is)
        try:
            with tarfile.open(path) as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    if is_secret_path(m.name):
                        yield f"{rel}!{m.name}", None, _never_read   # listed, never extracted
                        continue
                    data = tf.extractfile(m).read()
                    yield f"{rel}!{m.name}", None, (lambda d=data: d)
        except (tarfile.TarError, OSError, EOFError):
            return
    else:
        yield rel, path, (lambda p=path: _read(p))


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def detect_kind(src):
    s = os.path.abspath(src)
    if os.path.isdir(s) and _is_batch(s):
        return "trial-batch"
    base = os.path.basename(s.rstrip("/"))
    if "playtest" in s or "play-report" in s or base.startswith("play"):
        return "play-session"
    if "kimodo" in s or "cliplab" in s or "clip-handoff" in s:
        return "motion"
    return "generic"


def scrub_source(src, scrubber, keep_data=False):
    """Two passes over src: learn (player, owner lines, logins), then classify and redact.
    Returns (rows, totals Findings, data map relpath -> bytes when keep_data)."""
    entries = list(iter_source(src))
    for rel, path, load in entries:
        norm = rel.replace("!", "/").replace("\\", "/")
        if os.path.basename(norm) in BROWSER_PROFILE_MARKERS:
            scrubber.profile_dirs.add(os.path.dirname(rel.split("!")[-1].replace("\\", "/")) or ".")
    for rel, path, load in entries:
        if load is None:
            continue
        if os.path.basename(rel.split("!")[-1]) == "client.log" or rel.endswith("report.json"):
            try:
                scrubber.learn_player(load().decode("utf-8", "replace"))
            except OSError:
                pass
    for rel, path, load in entries:
        if load is None:
            continue
        st, _ = scrubber.classify(rel.split("!")[-1] if "!" in rel else rel, path)
        if st in ("refused", "skipped"):
            continue
        try:
            scrubber.learn_bytes(rel, load())
        except OSError:
            pass
    scrubber.finish_learning()
    rows, totals, data = [], Findings(), {}
    for rel, path, load in entries:
        inner = rel.split("!")[-1] if "!" in rel else rel
        size = os.path.getsize(path) if path else None
        if load is None:
            rows.append({"path": rel, "bytes": size, "status": "archive",
                         "reason": "tarball: members listed below; published unpacked", "findings": {}})
            continue
        st, why = scrubber.classify(inner, path)
        raw = None
        if st not in ("refused", "skipped"):
            raw = load()
        if raw is not None:
            st2, why2, out, acc = scrubber.scrub_bytes(inner, raw)
            if st2 in ("refused", "excluded") and st not in ("excluded", "review"):
                st, why = st2, why2
            if st == "review" and st2 == "ok":
                scrubber.review_data[rel] = out
            elif st == "ok":
                why = why or why2
            totals.merge(acc)
            if keep_data and st == "ok":
                data[rel] = out
            # renames: the published path is scrubbed too
            pub = scrubber.publish_path(rel, acc_paths := Findings())
            rows.append({"path": rel, "published_as": pub if pub != rel else None,
                         "bytes": size if size is not None else len(raw), "status": st, "reason": why,
                         "findings": acc.as_dict()})
            totals.merge(acc_paths)
        else:
            rows.append({"path": rel, "bytes": size, "status": st, "reason": why, "findings": {}})
    return rows, totals, data


def decision_report(src, scrubber, rows, totals):
    """The categories the owner decides, with counts and masked examples."""
    out = {}
    journal_rows = [r for r in rows if r["reason"] and "model_exchanges" in r["reason"]]
    calls, models, purposes = 0, {}, {}
    examples = []
    for rel, path, load in iter_source(src):
        if load is None or not any(r["path"] == rel for r in journal_rows) or not rel.endswith(".jsonl"):
            continue
        for line in load().decode("utf-8", "replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or "request" not in e:
                continue
            calls += 1
            models[e.get("model")] = models.get(e.get("model"), 0) + 1
            purposes[e.get("purpose")] = purposes.get(e.get("purpose"), 0) + 1
            if len(examples) < 3 and e.get("reply"):
                r = scrubber.scrub_text(str(e["reply"]), Findings())
                examples.append(f"{e.get('purpose')} / {e.get('model')}: {r[:70]}…")
    out["model_exchanges"] = {"decision": scrubber.decisions.get("model_exchanges"),
                              "files": len(journal_rows), "bytes": sum(r["bytes"] or 0 for r in journal_rows),
                              "calls": calls, "by_model": models, "by_purpose": purposes,
                              "examples": examples, "about": DECISIONS["model_exchanges"]}
    out["owner_lines"] = {"decision": scrubber.decisions.get("owner_lines"),
                          "player_ids": sorted(scrubber.player_ids),
                          "player_labels": sorted(scrubber.player_labels),
                          "distinct_lines": len(scrubber.owner_lines),
                          "occurrences": totals.counts.get("owner-line", 0),
                          "examples": [mask(l, "owner-line") for l in sorted(scrubber.owner_lines)[:5]],
                          "about": DECISIONS["owner_lines"]}
    out["owner_first_name"] = {"decision": scrubber.decisions.get("owner_first_name"),
                               "self_given_names": [mask(n, "owner-first-name") for n in sorted(scrubber.self_names)],
                               "extra_names": len(scrubber.extra_names),
                               "occurrences": totals.counts.get("owner-first-name", 0),
                               "examples": totals.examples.get("owner-first-name", []),
                               "about": DECISIONS["owner_first_name"]}
    notes = [r for r in rows if r["reason"] and "owner_notes" in r["reason"]]
    out["owner_notes"] = {"decision": scrubber.decisions.get("owner_notes"),
                          "files": [r["path"] for r in notes], "about": DECISIONS["owner_notes"]}
    media = [r for r in rows if r["reason"] and "session_media" in r["reason"]]
    out["session_media"] = {"decision": scrubber.decisions.get("session_media"), "files": len(media),
                            "bytes": sum(r["bytes"] or 0 for r in media), "about": DECISIONS["session_media"]}
    return out


def dry_run_markdown(src, kind, rows, totals, decisions, scrubber):
    by = {}
    for r in rows:
        s = by.setdefault(r["status"], [0, 0])
        s[0] += 1
        s[1] += r["bytes"] or 0
    lines = [f"# Store dry run: `{src}`", "",
             f"Kind: {kind}. Nothing was uploaded; nothing was written outside this report.", "",
             "## Files by status", "", "| Status | Files | Bytes |", "| --- | ---: | ---: |"]
    for st in ("ok", "review", "held", "excluded", "refused", "skipped", "archive"):
        if st in by:
            lines.append(f"| {st} | {by[st][0]} | {fmt_bytes(by[st][1])} |")
    lines += ["", "## Redactions (all files read, masked)", "", "| Category | Count | Examples (masked) |",
              "| --- | ---: | --- |"]
    tot = totals if isinstance(totals, dict) else totals.as_dict()
    for c, v in tot.items():
        lines.append(f"| {c} | {v['count']} | {', '.join('`' + e + '`' for e in v['examples'])} |")
    if not tot:
        lines.append("| (none) | 0 | |")
    lines += ["", "## For the owner to decide", ""]
    for cat, d in decisions.items():
        lines.append(f"### `{cat}` (now: **{d['decision']}**)")
        lines.append("")
        lines.append(d["about"])
        lines.append("")
        for k, v in d.items():
            if k in ("about", "decision"):
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            lines.append(f"- {k}: {v}")
        lines.append("")
    lines += ["## Per file", "", "| Path | Bytes | Status | Reason | Redactions |", "| --- | ---: | --- | --- | --- |"]
    for r in rows:
        red = ", ".join(f"{c} {n}" for c, n in (r.get("redactions") or {}).items())
        lines.append(f"| `{r['path']}` | {r['bytes'] if r['bytes'] is not None else ''} | {r['status']} | "
                     f"{r['reason'] or ''} | {red} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------
# Packing units
# --------------------------------------------------------------------------------------------

def _jsonl_gz(path, rows):
    """Deterministic gzip (no name, mtime 0): the same rows give the same bytes."""
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0,
                                                compresslevel=9) as gz:
        for r in rows:
            gz.write((json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))


def _tar_add(tf, name, data):
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mtime = 0
    ti.mode = 0o644
    tf.addfile(ti, io.BytesIO(data))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def pack_batch(src, out_dir, scrubber, name=None, machine=None):
    """A trial batch as the runs dataset holds it (docs/STORE.md, "Layout"):
    instances.jsonl.gz, calls.jsonl.gz, rows.jsonl.gz, prompts.jsonl.gz, files.tar.gz, MANIFEST.json."""
    name = name or os.path.basename(os.path.abspath(src).rstrip("/"))
    rows, totals, data = scrub_source(src, scrubber, keep_data=True)
    problems = installed_sha_problems(rows, data)
    if problems:
        raise Refused("installed script check failed: " + "; ".join(scrubber.safe_text(p) for p in problems))
    os.makedirs(out_dir, exist_ok=True)
    instances, calls, streams, prompts = {}, [], [], []
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for rel in sorted(data):
            body = data[rel]
            pub = scrubber.publish_path(rel)
            parts = pub.split("/")
            inst = parts[0] if len(parts) > 1 else None
            base = parts[-1]
            if inst and len(parts) == 2 and base in ("summary.json", "cast.json", "state.json", "models.json",
                                                      "mind-env.json"):
                instances.setdefault(inst, {"batch": name, "instance": inst})[base[:-5].replace("-", "_")] = \
                    body.decode("utf-8")
                continue
            if inst and len(parts) >= 3 and parts[1] == "journal":
                if len(parts) == 4 and parts[2] == "system":
                    prompts.append({"batch": name, "instance": inst, "ref": "/".join(parts[2:]),
                                    "text": body.decode("utf-8")})
                    continue
                if len(parts) == 3 and base.endswith(".jsonl"):
                    for seq, line in enumerate(body.decode("utf-8").splitlines()):
                        if not line.strip():
                            continue
                        try:
                            e = json.loads(line)
                        except ValueError:
                            e = {}
                        calls.append({"batch": name, "instance": inst, "file": base, "seq": seq,
                                      "actor": str(e.get("actor")), "at_ms": e.get("at_ms"),
                                      "purpose": e.get("purpose"), "model": e.get("model"),
                                      "tokens": e.get("tokens"), "latency_ms": e.get("latency_ms"),
                                      "error": None if e.get("error") is None else str(e.get("error")),
                                      "entry": line})
                    continue
            if inst and len(parts) == 2 and base.endswith(".jsonl"):
                for seq, line in enumerate(body.decode("utf-8").splitlines()):
                    if not line.strip():
                        continue
                    try:
                        at = json.loads(line).get("at_ms")
                    except (ValueError, AttributeError):
                        at = None
                    streams.append({"batch": name, "instance": inst, "stream": base[:-6], "seq": seq,
                                    "at_ms": at if isinstance(at, int) else None, "row": line})
                continue
            _tar_add(tf, pub, body)
    for inst in instances.values():
        for k in ("summary", "cast", "state", "models", "mind_env"):
            inst.setdefault(k, None)
    _jsonl_gz(os.path.join(out_dir, "instances.jsonl.gz"), sorted(instances.values(), key=lambda r: r["instance"]))
    _jsonl_gz(os.path.join(out_dir, "calls.jsonl.gz"), calls)
    _jsonl_gz(os.path.join(out_dir, "rows.jsonl.gz"), streams)
    _jsonl_gz(os.path.join(out_dir, "prompts.jsonl.gz"), prompts)
    with open(os.path.join(out_dir, "files.tar.gz"), "wb") as f:
        f.write(gzip.compress(tar_buf.getvalue(), compresslevel=9, mtime=0))
    man = {"format": FORMAT, "unit": "batch", "name": name, "machine": machine,
           "source": scrubber.scrub_text(tilde(src), Findings()),
           "packed": _dt.datetime.now().isoformat(timespec="seconds"), "tool_commit": _git("rev-parse", "--short", "HEAD"),
           "decisions": scrubber.decisions,
           # counts only: even masked examples ("/home/g…") are not for publication
           "redactions": {c: v["count"] for c, v in totals.as_dict().items()},
           "files": [{k: r[k] for k in ("path", "bytes", "status", "reason")} |
                     {"path": scrubber.publish_path(r["path"]),
                      "redactions": {c: v["count"] for c, v in r["findings"].items()}} for r in rows],
           "models": _model_counts(calls),
           "held": [{"path": scrubber.publish_path(r["path"]), "reason": r["reason"]}
                    for r in rows if r["status"] in ("excluded", "held", "review", "refused")],
           "self_name_ambiguous": len([d for d in scrubber.ambiguous
                                       if d["file"] in {r["path"].split("!")[-1] for r in rows if r["status"] == "ok"}]),
           "dropped": [{"file": scrubber.publish_path(d["file"]), "where": d["where"],
                        "why": "quotes an owner line" if d["why"].startswith("quotes") else "repeats an owner line",
                        "action": d.get("action", "dropped")}
                       for d in scrubber.dropped
                       if d["file"] in {r["path"].split("!")[-1] for r in rows if r["status"] == "ok"}],
           "counts": {"instances": len(instances), "calls": len(calls), "rows": len(streams),
                      "prompts": len(prompts)}}
    with open(os.path.join(out_dir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    return man


def unpack_batch(packed_dir, dest):
    """The reverse of pack_batch: the trials.py evidence layout (scrubbed) under dest."""
    os.makedirs(dest, exist_ok=True)

    def rd(name):
        p = os.path.join(packed_dir, name)
        if not os.path.exists(p):
            return []
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    for inst in rd("instances.jsonl.gz"):
        d = _safe_join(dest, inst["instance"])
        os.makedirs(d, exist_ok=True)
        for k, fname in (("summary", "summary.json"), ("cast", "cast.json"), ("state", "state.json"),
                         ("models", "models.json"), ("mind_env", "mind-env.json")):
            if inst.get(k) is not None:
                with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
                    f.write(inst[k])
    files = {}
    for c in rd("calls.jsonl.gz"):
        files.setdefault(os.path.join(c["instance"], "journal", c["file"]), []).append((c["seq"], c["entry"]))
    for r in rd("rows.jsonl.gz"):
        files.setdefault(os.path.join(r["instance"], r["stream"] + ".jsonl"), []).append((r["seq"], r["row"]))
    for rel, lines in files.items():
        p = _safe_join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for _, line in sorted(lines):
                f.write(line + "\n")
    for pr in rd("prompts.jsonl.gz"):
        p = _safe_join(dest, os.path.join(pr["instance"], "journal", pr["ref"]))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(pr["text"])
    tp = os.path.join(packed_dir, "files.tar.gz")
    if os.path.exists(tp):
        with tarfile.open(tp) as tf:
            for m in tf:
                if not m.isfile():
                    continue
                p = _safe_join(dest, m.name)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(tf.extractfile(m).read())
    return dest


def _safe_join(root, rel):
    p = os.path.realpath(os.path.join(root, rel))
    if not (p == os.path.realpath(root) or p.startswith(os.path.realpath(root) + os.sep)):
        raise Refused(f"path escapes the destination: {rel}")
    return p


def pack_session(src, out_dir, scrubber, name=None, machine=None):
    """A play session: the same shape as a batch with one 'instance' per top-level folder."""
    man = pack_batch(src, out_dir, scrubber, name=name, machine=machine)
    man["unit"] = "session"
    with open(os.path.join(out_dir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    return man


def pack_motion(src, out_dir, scrubber, machine=None):
    """Raw takes as files (fetchable one by one) plus a MANIFEST with sha256 per take.
    Asset packs name no machine and no host, in fields or paths (`machine` is accepted for the
    common signature and ignored)."""
    rows, totals, data = scrub_source(src, scrubber, keep_data=True)
    raw = os.path.join(out_dir, "motion", "raw")
    os.makedirs(raw, exist_ok=True)
    files = []
    for rel in sorted(data):
        if "!" in rel:
            continue
        base = os.path.basename(rel)
        with open(os.path.join(raw, base), "wb") as f:
            f.write(data[rel])
        files.append({"path": f"motion/raw/{base}", "sha256": _sha(data[rel]), "bytes": len(data[rel])})
    man = {"format": FORMAT, "unit": "motion-library", "files": files,
           "refused": [r["path"] for r in rows if r["status"] == "refused"],
           "redactions": {c: v["count"] for c, v in totals.as_dict().items()}, "packed": _dt.datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(out_dir, "motion", "MANIFEST.json"), "w") as f:
        json.dump(man, f, indent=1)
    return man


# --------------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------------

class Backend:
    """Where units are published and fetched. `repo` is a logical name (runs, assets)."""
    name = "abstract"

    def publish(self, repo, local_dir, path_in_repo, message):
        raise NotImplementedError

    def fetch(self, repo, path_in_repo, dest):
        raise NotImplementedError

    def list(self, repo, prefix=""):
        raise NotImplementedError


class LocalBackend(Backend):
    """A directory per repository: <root>/<repo>/<path>. For tests and for a machine-local mirror."""
    name = "local"

    def publish_units(self, repo, units, message):
        """Several (path_in_repo, local_dir) units in one commit."""
        for path_in_repo, local_dir in units:
            self.publish(repo, local_dir, path_in_repo, message)
        return os.path.join(self.root, repo)

    def __init__(self, root):
        self.root = expand(root)

    def _repo(self, repo):
        return os.path.join(self.root, repo)

    def publish(self, repo, local_dir, path_in_repo, message):
        dest = _safe_join(self._repo(repo), path_in_repo)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(local_dir, dest)
        log = os.path.join(self._repo(repo), ".commits.jsonl")
        with open(log, "a") as f:
            f.write(json.dumps({"at": _dt.datetime.now().isoformat(timespec="seconds"),
                                "path": path_in_repo, "message": message}) + "\n")
        return dest

    def fetch(self, repo, path_in_repo, dest):
        srcp = _safe_join(self._repo(repo), path_in_repo)
        if not os.path.exists(srcp):
            raise Refused(f"{repo}:{path_in_repo} not found in {self.root}")
        os.makedirs(dest, exist_ok=True)
        got = []
        for root, _, names in os.walk(srcp):
            for n in names:
                s = os.path.join(root, n)
                rel = os.path.relpath(s, srcp)
                d = _safe_join(dest, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                got.append(d)
        return got

    def list(self, repo, prefix=""):
        base = self._repo(repo)
        out = []
        for root, _, names in os.walk(base):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), base)
                if rel.startswith(prefix) and not rel.startswith("."):
                    out.append(rel)
        return sorted(out)


def token_path():
    """The store's Hugging Face token: this file and nowhere else (not HF_TOKEN, not the hf CLI's
    cache, not the machine's other tokens)."""
    return os.path.expanduser("~/.config/slop-store/hf_token")


def read_token():
    p = token_path()
    try:
        st = os.stat(p)
    except OSError:
        raise Refused(f"no store token at {tilde(p)}")
    if st.st_mode & 0o077:
        raise Refused(f"{tilde(p)} must be readable by its owner only (chmod 600)")
    with open(p, encoding="utf-8") as f:
        tok = f.read().strip()
    if not tok:
        raise Refused(f"{tilde(p)} is empty")
    return tok


def _hide(text, secret):
    return text.replace(secret, "[redacted:token]") if secret else text


def _isolate_hub_env():
    """Keep huggingface_hub from finding any other token: no environment token, no implicit one."""
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_API_TOKEN"):
        os.environ.pop(var, None)
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_TOKEN_PATH"] = os.path.join(tempfile.gettempdir(), "slop-store-no-token")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class HFBackend(Backend):
    """Hugging Face datasets. Publishing needs the --yes-publish flag AND publish_enabled in the
    machine-local config; the check runs before huggingface_hub is imported. Every call passes the
    token read from token_path() explicitly; errors are re-raised with the token removed."""
    name = "hf"

    COMMIT_FILES = 100   # the Hub's advice: about 50-100 files a commit (docs/STORE.md)

    def __init__(self, cfg, yes_publish=False, api=None, op=None):
        self.cfg = cfg
        self._op = op
        hf = (cfg.get("backends") or {}).get("hf") or {}
        self.namespace = hf.get("namespace")
        self.private = bool(hf.get("private"))
        self.repo_type = hf.get("repo_type", "dataset")
        self.yes_publish = yes_publish
        self._api = api
        self._token = None

    def gate(self):
        if not self.yes_publish:
            raise Refused("publishing to Hugging Face needs --yes-publish")
        if not self.cfg.get("publish_enabled"):
            raise Refused(f"publishing is switched off: set \"publish_enabled\": true in "
                          f"{self.cfg.get('_local_config', LOCAL_CONFIG)} once the owner has agreed")
        if not self.namespace:
            raise Refused("backends.hf.namespace is not set in the machine-local config")

    def repo_id(self, repo):
        name = (self.cfg.get("repos") or {}).get(repo, repo)
        return name if "/" in name else f"{self.namespace}/{name}"

    def token(self):
        if self._token is None:
            self._token = read_token()
        return self._token

    def api(self):
        if self._api is None:
            _isolate_hub_env()
            from huggingface_hub import HfApi  # imported only past the gate or for a fetch
            self._api = HfApi(token=self.token())
        return self._api

    def _call(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except Refused:
            raise
        except Exception as e:  # noqa: BLE001 - re-raised without the token
            raise Refused(_hide(f"{type(e).__name__}: {e}", self._token)) from None

    def publish(self, repo, local_dir, path_in_repo, message):
        self.gate()
        api = self.api()
        rid = self.repo_id(repo)
        self._call(api.create_repo, rid, repo_type=self.repo_type, private=self.private, exist_ok=True)
        files = []
        for root, _, names in os.walk(local_dir):
            for n in sorted(names):
                files.append(os.path.relpath(os.path.join(root, n), local_dir))
        files.sort()
        if len(files) <= self.COMMIT_FILES:
            return self._call(api.upload_folder, repo_id=rid, repo_type=self.repo_type, folder_path=local_dir,
                              path_in_repo=path_in_repo, commit_message=message)
        op = self._op
        if op is None:
            from huggingface_hub import CommitOperationAdd as op
        out = None
        chunks = [files[i:i + self.COMMIT_FILES] for i in range(0, len(files), self.COMMIT_FILES)]
        for k, chunk in enumerate(chunks, 1):
            ops = [op(path_in_repo=f"{path_in_repo.rstrip('/')}/{f}", path_or_fileobj=os.path.join(local_dir, f))
                   for f in chunk]
            out = self._call(api.create_commit, repo_id=rid, repo_type=self.repo_type, operations=ops,
                             commit_message=f"{message} ({k}/{len(chunks)})")
        return out

    def publish_units(self, repo, units, message):
        """Several (path_in_repo, local_dir) units in one commit."""
        self.gate()
        api = self.api()
        rid = self.repo_id(repo)
        self._call(api.create_repo, rid, repo_type=self.repo_type, private=self.private, exist_ok=True)
        op = self._op
        if op is None:
            from huggingface_hub import CommitOperationAdd as op
        ops = []
        for path_in_repo, local_dir in units:
            for root, _, names in os.walk(local_dir):
                for n in sorted(names):
                    f = os.path.join(root, n)
                    ops.append(op(path_in_repo=f"{path_in_repo.rstrip('/')}/{os.path.relpath(f, local_dir)}",
                                  path_or_fileobj=f))
        return self._call(api.create_commit, repo_id=rid, repo_type=self.repo_type, operations=ops,
                          commit_message=message)

    def put_file(self, repo, local_file, path_in_repo, message):
        self.gate()
        api = self.api()
        rid = self.repo_id(repo)
        self._call(api.create_repo, rid, repo_type=self.repo_type, private=self.private, exist_ok=True)
        return self._call(api.upload_file, path_or_fileobj=local_file, path_in_repo=path_in_repo, repo_id=rid,
                          repo_type=self.repo_type, commit_message=message)

    def fetch(self, repo, path_in_repo, dest):
        if not self.namespace:
            raise Refused("backends.hf.namespace is not set")
        _isolate_hub_env()
        from huggingface_hub import snapshot_download
        stage = dest.rstrip("/") + ".hf"
        self._call(snapshot_download, repo_id=self.repo_id(repo), repo_type=self.repo_type, local_dir=stage,
                   allow_patterns=[path_in_repo.rstrip("/") + "/*"], token=self.token())
        srcp = os.path.join(stage, path_in_repo)
        os.makedirs(dest, exist_ok=True)
        got = []
        for root, _, names in os.walk(srcp):
            for n in names:
                s_ = os.path.join(root, n)
                d = _safe_join(dest, os.path.relpath(s_, srcp))
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.move(s_, d)
                got.append(d)
        shutil.rmtree(stage, ignore_errors=True)
        return got

    def list(self, repo, prefix=""):
        if not self.namespace:
            raise Refused("backends.hf.namespace is not set")
        files = self._call(self.api().list_repo_files, self.repo_id(repo), repo_type=self.repo_type)
        return sorted(f for f in files if f.startswith(prefix))


def make_backend(name, cfg, yes_publish=False, root=None):
    if name == "local":
        return LocalBackend(root or ((cfg.get("backends") or {}).get("local") or {}).get("root", "~/store-local"))
    if name == "hf":
        return HFBackend(cfg, yes_publish=yes_publish)
    raise Refused(f"unknown backend {name}")


def _model_counts(calls):
    out = {}
    for c in calls:
        m = c.get("model")
        if m:
            out[m] = out.get(m, 0) + 1
    return out


def model_status(model, cfg):
    """(verified?, note) for a model name, from store_config.json's models section."""
    models = cfg.get("models") or {}
    for pat, note in (models.get("verified") or {}).items():
        if fnmatch.fnmatch(model, pat):
            return True, note
    for pat, note in (models.get("unverified") or {}).items():
        if fnmatch.fnmatch(model, pat):
            return False, note
    return False, "not listed in store_config.json models"


def check_models(man, cfg):
    """Hold a unit with any call from a model whose terms were not read."""
    bad = {m: model_status(m, cfg)[1] for m in man.get("models") or {} if not model_status(m, cfg)[0]}
    if bad:
        raise Refused("held: calls from unverified model(s): " + "; ".join(f"{m} ({n})" for m, n in sorted(bad.items())))


def installed_sha_problems(rows, data):
    """The published installed rules script must hash to the sha installed_script.txt records,
    so the record stays verifiable. One message per problem; empty when every pair matches."""
    status = {r["path"]: r for r in rows}
    out = []
    for rel, body in data.items():
        if os.path.basename(rel.split("!")[-1]) != "installed_script.txt":
            continue
        m = re.search(r"installed sha256 ([0-9a-f]{64})", body.decode("utf-8", "replace"))
        if not m:
            continue
        src = rel[:-len("installed_script.txt")] + "installed_source.rhai"
        if src not in data:
            # older records name the installed file instead: "file sha256 <sha> (<path>/skills.rhai)"
            named = re.search(r"file\s+sha256 [0-9a-f]{64} \(([^)\n]+)\)", body.decode("utf-8", "replace"))
            if named:
                base = os.path.basename(named.group(1).strip())
                root = rel.split("!")[0] + "!" if "!" in rel else ""
                session = rel[:rel.rfind("run/")] if "run/" in rel else os.path.dirname(rel) + "/"
                cands = sorted((k for k in data if os.path.basename(k) == base and k.startswith(root)),
                               key=lambda k: (not k.startswith(session), len(k)))
                if cands:
                    src = cands[0]
        if src not in data:
            st = status.get(src)
            out.append(f"{src}: not published ({st['status'] + ', ' + (st['reason'] or '') if st else 'missing'}), "
                       f"so the installed sha {m.group(1)[:12]}… in {rel} cannot be checked")
            continue
        got = _sha(data[src])
        if got != m.group(1):
            why = ", ".join(f"{c} {v['count']}" for c, v in (status.get(src, {}).get("findings") or {}).items()) \
                or "no redaction recorded"
            out.append(f"{src}: sha256 {got[:12]}… after scrubbing, but {rel} records {m.group(1)[:12]}… "
                       f"(redactions in the script: {why})")
    return out


def check_batch_complete(src):
    """A batch is complete when batch.json exists and every instance has its summary.json."""
    if not os.path.exists(os.path.join(src, "batch.json")):
        raise Refused(f"{tilde(src)}: no batch.json")
    insts = [d for d in sorted(os.listdir(src)) if os.path.isdir(os.path.join(src, d))
             and os.path.exists(os.path.join(src, d, "cast.json"))]
    if not insts:
        raise Refused(f"{tilde(src)}: no instances")
    missing = [d for d in insts if not os.path.exists(os.path.join(src, d, "summary.json"))]
    if missing:
        raise Refused(f"{tilde(src)}: incomplete, no summary.json in {', '.join(missing[:3])}")
    return insts


def check_publishable(man, scrubber):
    """Refuse a unit that still has files waiting on an owner decision."""
    held = [f["path"] for f in man.get("files", []) if f.get("status") == "held"]
    if held:
        raise Refused(f"{len(held)} file(s) wait on an owner decision "
                      f"({', '.join(sorted({d for d, v in scrubber.decisions.items() if v == 'undecided'}))}); "
                      f"first: {held[0]}")


def unit_path(kind, name, machine):
    if kind == "batch":
        return f"batches/{machine}/{name}"
    if kind == "session":
        return f"sessions/{machine}/{name}"
    if kind == "motion":
        return "motion"
    raise Refused(kind)


def fetch_batch(backend, name, dest, machine=None, unpack=False, top="batches"):
    prefix = top + "/"
    hits = [p for p in backend.list("runs", prefix) if p.split("/")[2:3] == [name]]
    machines = sorted({p.split("/")[1] for p in hits})
    if machine:
        machines = [m for m in machines if m == machine]
    if not machines:
        raise Refused(f"no {top[:-2] if top.endswith('es') else top[:-1]} {name} in the runs repository")
    if len(machines) > 1:
        raise Refused(f"{name} exists on several machines ({', '.join(machines)}); pass --machine")
    path = f"{top}/{machines[0]}/{name}"
    packed = os.path.join(dest, "packed") if unpack else dest
    backend.fetch("runs", path, packed)
    if unpack:
        unpack_batch(packed, os.path.join(dest, name))
    return path


def fetch_motion(backend, dest, force=False):
    tmp = tempfile.mkdtemp(prefix="store-motion-")
    try:
        backend.fetch("assets", "motion", tmp)
        with open(os.path.join(tmp, "MANIFEST.json")) as f:
            man = json.load(f)
        os.makedirs(dest, exist_ok=True)
        wrote = kept = 0
        for e in man["files"]:
            s = os.path.join(tmp, e["path"][len("motion/"):])
            with open(s, "rb") as f:
                data = f.read()
            if _sha(data) != e["sha256"]:
                raise Refused(f"{e['path']}: sha256 differs from the manifest")
            d = _safe_join(dest, os.path.basename(e["path"]))
            if os.path.exists(d):
                with open(d, "rb") as f:
                    same = _sha(f.read()) == e["sha256"]
                if same:
                    kept += 1
                    continue
                if not force:
                    raise Refused(f"{tilde(d)} exists with other content; --force replaces it")
            with open(d, "wb") as f:
                f.write(data)
            wrote += 1
        return wrote, kept
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------------------------
# Layout estimate
# --------------------------------------------------------------------------------------------

def layout(items, ratio=0.2):
    """Estimated size and file count per repository from manifest items. `ratio` is the packed
    size of a batch against its raw size (measured on l9 by `pack`; JSON Lines compress well)."""
    runs_batches = {}
    for it in items:
        if it["kind"] == "trial-batch" and it["note"] != "runner log":
            key = it["unit"]
            if key not in runs_batches or (runs_batches[key]["bytes"] or 0) < (it["bytes"] or 0):
                runs_batches[key] = it
    arch = [it for it in items if it["kind"] == "trials-archive" and it["unit"] not in runs_batches
            and it["path"].endswith((".tar.gz", ".tgz"))]
    sessions = [it for it in items if it["kind"] in ("play-session", "play-report")]
    verify = [it for it in items if it["kind"] in ("verify-evidence", "mind-journal")]
    motion = [it for it in items if it["kind"] in ("motion-raw", "motion-library-copy")]
    lab = [it for it in items if it["kind"] in ("cliplab", "clip-handoff", "asset-board")]
    b = sum(i["bytes"] or 0 for i in runs_batches.values())
    est = {
        "runs": {
            "batches": {"units": len(runs_batches), "raw_bytes": b, "est_bytes": int(b * ratio),
                        "files": 6 * len(runs_batches)},
            "archived batches": {"units": len(arch), "raw_bytes": sum(i["bytes"] or 0 for i in arch),
                                 "est_bytes": int(sum(i["bytes"] or 0 for i in arch)), "files": 6 * len(arch)},
            "sessions": {"units": len(sessions), "raw_bytes": sum(i["bytes"] or 0 for i in sessions),
                         "est_bytes": int(sum(i["bytes"] or 0 for i in sessions) * 0.5),
                         "files": 6 * len(sessions)},
            "verify": {"units": len(verify), "raw_bytes": sum(i["bytes"] or 0 for i in verify),
                       "est_bytes": int(sum(i["bytes"] or 0 for i in verify) * ratio),
                       "files": len({i["path"].split("/.local/")[0] for i in verify})},
        },
        "assets": {
            "motion/raw": {"units": len(motion), "raw_bytes": max([i["bytes"] or 0 for i in motion] or [0]),
                           "est_bytes": max([i["bytes"] or 0 for i in motion] or [0]),
                           "files": max([i["files"] or 0 for i in motion] or [0]) + 1},
            "cliplab, handoffs, board": {"units": len(lab), "raw_bytes": sum(i["bytes"] or 0 for i in lab),
                                         "est_bytes": int(sum(i["bytes"] or 0 for i in lab) * 0.5),
                                         "files": sum(min(i["files"] or 0, 400) for i in lab)},
        },
    }
    return est


def layout_markdown(est):
    lines = ["| Repository | Part | Units | Raw | Estimated | Files |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for repo, parts in est.items():
        tb = tf = 0
        for part, v in parts.items():
            lines.append(f"| {repo} | {part} | {v['units']} | {fmt_bytes(v['raw_bytes'])} | "
                         f"{fmt_bytes(v['est_bytes'])} | {v['files']} |")
            tb += v["est_bytes"]
            tf += v["files"]
        lines.append(f"| **{repo}** | total | | | **{fmt_bytes(tb)}** | **{tf}** |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def _dryrun_dir():
    return os.path.expanduser(f"~/store-dryrun-{_dt.date.today().isoformat()}")


def _scrubber_for(src, cfg, machine, kind=None, player=None, decide=(), player_names=()):
    kind = kind or detect_kind(src)
    decisions = {}
    for d in decide or ():
        k, _, v = d.partition("=")
        if k not in DECISIONS or v not in ("include", "exclude", "redact", "hold", "undecided"):
            raise Refused(f"--decide {d}: expected one of {', '.join(DECISIONS)} = include|exclude|redact|undecided")
        decisions[k] = v
    return Scrubber(Identity.from_runtime(cfg, machine), decisions=decisions, cfg=cfg, machine=machine,
                    player_ids=[player] if player else (), kind=kind, player_names=player_names or ()), kind


def cmd_manifest(a, cfg, machine):
    items = scan(cfg=cfg, machine=machine)
    when = _dt.datetime.now().isoformat(timespec="minutes")
    md = manifest_markdown(items, machine, when)
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"machine": machine, "when": when, "items": items}, f, indent=1)
    if a.md:
        with open(a.md, "w") as f:
            f.write(md)
        print(a.md)
    else:
        sys.stdout.write(md)


def write_scrubbed(src, scrubber, out, review_out=None):
    """The scrubbed tree as it would be published, for review, under its published paths; and
    the session's review-only files (report.json, commands.jsonl), scrubbed, under review_out."""
    rows, totals, data = scrub_source(src, scrubber, keep_data=True)
    for target, files in ((out, data), (review_out, scrubber.review_data)):
        if target is None:
            continue
        for rel, body in files.items():
            pub = scrubber.publish_path(rel.replace("!", "/"))
            p = _safe_join(target, pub)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(body)
    return rows, totals, data


def source_label(src, scrubber):
    """How a report names its source: home-relative, or the last two parts of a path outside
    home; redacted like everything else."""
    t = tilde(src)
    if not t.startswith("~"):
        t = "…/" + "/".join(os.path.abspath(src).rstrip("/").split("/")[-2:])
    return scrubber.safe_text(t)


def names_markdown(table, player_ids, uses=None):
    lines = ["# Names residents hold for the player", "",
             "Every name residents hold for the player's character (by its id), whether the player typed it, "
             "and what was done. Names appear only as their length.", ""]
    if not player_ids:
        lines += ["**The player's character id was not found** (no `playing character #N` in a client log, and no "
                  "`--player`): no resident-held names could be tied to the player.", ""]
    lines += ["| Name | Held by (records: graphs, tags, labels) | Where | Uses by holder (speech, journals, logs) | "
              "Typed by the player | Done |", "| --- | --- | --- | --- | --- | --- |"]
    uses = uses or ["–"] * len(table)
    for e, u in zip(table, uses):
        lines.append(f"| {e['name']} | {', '.join(e['held_by']) or '–'} | {'; '.join(e['where'])} | {u} | "
                     f"{'yes' if e['typed_by_player'] else 'no'} | {e['action']} |")
    if not table:
        lines.append("| (none) | | | | | |")
    return "\n".join(lines) + "\n"


def ambiguous_markdown(amb):
    rep = sum(1 for d in amb if d.get("action", "replaced").startswith("replaced"))
    lines = ["# Self-given name: places it could not be told from the ordinary word", "",
             f"{len(amb)} place(s): {rep} replaced, {len(amb) - rep} kept as the ordinary word (lowercase right "
             "after a possessive or an article). The name appears only as its length. A wrong call here costs "
             "one word; templates, prompts and scripts are never touched.", "",
             "| File | Where | Context | Done |", "| --- | --- | --- | --- |"]
    for d in amb:
        ctx = d["context"].replace("|", "\\|")
        lines.append(f"| `{d['file']}` | {d['where']} | {ctx} | {d.get('action') or 'replaced by ' + str(d['replacement'])} |")
    return "\n".join(lines) + "\n"


def dropped_markdown(dropped):
    lines = ["# Dropped by the owner-line echo pass", "",
             f"{len(dropped)} item(s). Owner lines and echoes appear only as their length.", "",
             "| File | Where | Action | Why |", "| --- | --- | --- | --- |"]
    for d in dropped:
        lines.append(f"| `{d['file']}` | {d['where']} | {d.get('action', 'dropped')} | {d['why']} |")
    return "\n".join(lines) + "\n"


def cmd_scrub(a, cfg, machine):
    if not a.dry_run and not a.write:
        raise Refused("scrub runs as --dry-run, or with --write DIR to write the scrubbed tree for review")
    src = os.path.abspath(os.path.expanduser(a.src))
    nt = is_never_touch(src, cfg, machine)
    if nt:
        raise Refused(f"{tilde(src)} is in a never-touch folder ({tilde(nt)})")
    sc, kind = _scrubber_for(src, cfg, machine, a.kind, a.player, a.decide, a.player_name)
    if a.write:
        if os.path.exists(a.write) and os.listdir(a.write):
            raise Refused(f"{a.write} is not empty")
        rows, totals, data = write_scrubbed(src, sc, os.path.join(a.write, "tree"), os.path.join(a.write, "review"))
    else:
        rows, totals, data = scrub_source(src, sc, keep_data=True)
    problems = installed_sha_problems(rows, data)
    keep = {r["path"].split("!")[-1] for r in rows if r["status"] in ("ok", "review")}
    dropped = [d for d in sc.dropped if d["file"] in keep]
    dec = decision_report(src, sc, rows, totals)
    label = source_label(src, sc)
    # Everything a review file says goes through the published redaction: paths as published,
    # every other string redacted (owner names, logins, lines and their echoes).
    rows_s = sc.safe([{k: r.get(k) for k in ("path", "bytes", "status", "reason")} |
                      {"redactions": {c: v["count"] for c, v in r["findings"].items()}} for r in rows])
    dec_s, dropped_s, totals_s = sc.safe(dec), sc.safe(dropped), sc.safe(totals.as_dict())
    md = sc.safe_text(dry_run_markdown(label, kind, rows_s, totals_s, dec_s, sc))
    out = a.write or a.report or os.path.join(_dryrun_dir(), re.sub(r"[^\w.-]+", "_", label.strip("~/…")))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write(md)
    with open(os.path.join(out, "dropped.md"), "w") as f:
        f.write(sc.safe_text(dropped_markdown(dropped_s)))
    amb = [dict(d, file=sc.safe_text(sc.publish_path(d["file"]))) for d in sc.ambiguous if d["file"] in keep]
    with open(os.path.join(out, "names.md"), "w") as f:
        f.write(sc.safe_text(names_markdown(sc.name_table, sc.player_ids, sc.uses_column())))
    with open(os.path.join(out, "ambiguous.md"), "w") as f:
        f.write(sc.safe_text(ambiguous_markdown(amb)))
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump({"src": label, "kind": kind, "rows": rows_s, "redactions": totals_s,
                   "decisions": dec_s, "dropped": dropped_s, "ambiguous": sc.safe(amb),
                   "names": sc.safe([dict(e, uses=u) for e, u in zip(sc.name_table, sc.uses_column())]),
                   "installed_check": problems or "ok",
                   "review": sorted(sc.safe_text(sc.publish_path(r.replace("!", "/"))) for r in sc.review_data)},
                  f, ensure_ascii=False, indent=1)
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    say = lambda t: print(sc.safe_text(t))  # noqa: E731
    say(f"dry run of {label} ({kind}): " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    say(f"  dropped or replaced by the echo pass: {len(dropped)}")
    for c, v in totals_s.items():
        say(f"  {c}: {v['count']}  e.g. {', '.join(v['examples'])}")
    for c, d in dec_s.items():
        say(f"  decide {c} (now {d['decision']})")
    if sc.review_data:
        say(f"  review only (held from publishing): {len(sc.review_data)} file(s) in {tilde(os.path.join(out, 'review'))}")
    say(f"  names residents hold for the player: {len(sc.name_table)} (names.md); "
        f"self-given names learned: {len(sc.self_names)}" +
        ("" if sc.player_ids else "  WARNING: the player's character id was not found"))
    say(f"  self-given name where name and word could not be told apart: {len(amb)} place(s), "
        f"{sum(1 for d in amb if (d.get('action') or '').startswith('kept'))} kept (ambiguous.md)")
    say("  installed script: " + ("sha matches the record" if not problems else "MISMATCH"))
    print(tilde(os.path.join(out, "report.md")))
    if problems:
        raise Refused("installed script check failed: " + "; ".join(sc.safe_text(p) for p in problems))


def _pack(kind, src, out, sc, machine):
    if kind == "batch":
        return pack_batch(src, out, sc, machine=machine)
    if kind == "session":
        return pack_session(src, out, sc, machine=machine)
    if kind == "motion":
        return pack_motion(src, out, sc, machine=machine)
    raise Refused(kind)


def cmd_pack(a, cfg, machine):
    src = os.path.abspath(os.path.expanduser(a.src))
    if is_never_touch(src, cfg, machine):
        raise Refused(f"{tilde(src)} is in a never-touch folder")
    sc, _ = _scrubber_for(src, cfg, machine, {"session": "play-session"}.get(a.kind, a.kind), a.player, a.decide,
                          a.player_name)
    man = _pack(a.kind, src, a.out, sc, machine)
    print(json.dumps({k: man.get(k) for k in ("unit", "name", "counts")}, indent=1))
    print(a.out)


def cmd_publish(a, cfg, machine):
    backend = make_backend(a.backend, cfg, yes_publish=a.yes_publish, root=a.root)
    if isinstance(backend, HFBackend):
        backend.gate()  # before any reading or packing
    src = os.path.abspath(os.path.expanduser(a.src))
    if is_never_touch(src, cfg, machine):
        raise Refused(f"{tilde(src)} is in a never-touch folder")
    if a.kind == "session" and not cfg.get("publish_sessions"):
        raise Refused("play sessions are held: publish_sessions is not set in the machine-local config")
    if a.kind == "batch":
        check_batch_complete(src)
    if getattr(a, "packed", None):
        # an existing pack, uploaded unchanged (so a fetch can be compared with it byte for byte)
        if a.kind != "batch":
            raise Refused("--packed is for batches")
        name = a.name or os.path.basename(src.rstrip("/"))
        man = verify_pack(a.packed, src, cfg, machine)
        print(backend.publish("runs", a.packed, unit_path("batch", name, machine), f"batch {name} from {machine}"))
        return
    sc, _ = _scrubber_for(src, cfg, machine, {"session": "play-session"}.get(a.kind, a.kind), a.player,
                          player_names=a.player_name)
    stage = tempfile.mkdtemp(prefix="store-stage-")
    try:
        name = a.name or os.path.basename(src.rstrip("/"))
        man = _pack(a.kind, src, stage, sc, machine)
        check_publishable(man, sc)
        if a.kind in ("batch", "session"):
            check_models(man, cfg)
        local = stage if a.kind != "motion" else os.path.join(stage, "motion")
        # asset units name no machine, not even in the commit message
        msg = "motion library" if a.kind == "motion" else f"{a.kind} {name} from {machine}"
        where = backend.publish("runs" if a.kind != "motion" else "assets", local,
                                unit_path(a.kind, name, machine), msg)
        print(where)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


PACK_FILES = ("instances.jsonl.gz", "calls.jsonl.gz", "rows.jsonl.gz", "prompts.jsonl.gz", "files.tar.gz",
              "MANIFEST.json")


def verify_pack(packed, src, cfg, machine):
    """The checks publish runs on a fresh pack, run on an existing one."""
    names = sorted(os.listdir(packed))
    if names != sorted(PACK_FILES):
        raise Refused(f"{packed}: expected exactly {', '.join(PACK_FILES)}, found {', '.join(names)}")
    with open(os.path.join(packed, "MANIFEST.json"), encoding="utf-8") as f:
        man = json.load(f)
    if man.get("unit") != "batch" or man.get("name") != os.path.basename(src.rstrip("/")):
        raise Refused(f"{packed}: MANIFEST names {man.get('unit')} {man.get('name')}, not this batch")
    if man.get("machine") != machine:
        raise Refused(f"{packed}: packed on {man.get('machine')}, this is {machine}")
    held = [f["path"] for f in man.get("files", []) if f.get("status") == "held"]
    if held:
        raise Refused(f"{packed}: {len(held)} held file(s)")
    check_models(man, cfg)
    return man


def cmd_publish_batches(a, cfg, machine):
    """Pack many batches, then upload them in a few commits of whole batches."""
    backend = make_backend(a.backend, cfg, yes_publish=a.yes_publish, root=a.root)
    if isinstance(backend, HFBackend):
        backend.gate()
    with open(os.path.expanduser(a.list), encoding="utf-8") as f:
        srcs = [os.path.abspath(os.path.expanduser(l.strip())) for l in f if l.strip() and not l.startswith("#")]
    stage = os.path.abspath(os.path.expanduser(a.stage))
    os.makedirs(stage, exist_ok=True)
    ready, held = [], []
    for src in srcs:
        name = os.path.basename(src.rstrip("/"))
        out = os.path.join(stage, name)
        try:
            if is_never_touch(src, cfg, machine):
                raise Refused("never-touch folder")
            check_batch_complete(src)
            if not (os.path.isdir(out) and sorted(os.listdir(out)) == sorted(PACK_FILES)):
                shutil.rmtree(out, ignore_errors=True)
                sc, _ = _scrubber_for(src, cfg, machine, "trial-batch")
                man = pack_batch(src, out, sc, machine=machine)
                check_publishable(man, sc)
            man = verify_pack(out, src, cfg, machine)
            ready.append((name, out, man))
            print(f"packed {name}: {man['counts']['calls']} calls, {man['counts']['rows']} rows", flush=True)
        except Refused as e:
            held.append((name, str(e)))
            shutil.rmtree(out, ignore_errors=True)
            print(f"held {name}: {e}", flush=True)
    groups = [ready[i:i + a.per_commit] for i in range(0, len(ready), a.per_commit)]
    for k, group in enumerate(groups, 1):
        msg = f"{len(group)} batches from {machine} ({k}/{len(groups)}): {', '.join(n for n, _, _ in group)}"
        where = backend.publish_units("runs", [(unit_path("batch", n, machine), out) for n, out, _ in group], msg)
        print(f"commit {k}/{len(groups)}: {where}", flush=True)
    print(json.dumps({"published": [n for n, _, _ in ready], "held": held}, indent=1))


def cmd_fetch(a, cfg, machine):
    backend = make_backend(a.backend, cfg, root=a.root)
    if a.what == "motion-library":
        dest = a.dest or os.path.join(REPO, ".local", "kimodo", "outputs", "library")
        if _under(expand(dest), [expand(p) for p in cfg.get("read_only") or []]):
            raise Refused(f"{dest} is read-only on this machine")
        wrote, kept = fetch_motion(backend, dest, force=a.force)
        print(f"{wrote} take(s) written, {kept} already there: {tilde(dest)}")
    elif a.what in ("batch", "session"):
        if not a.name:
            raise Refused(f"fetch {a.what} NAME")
        top = a.what + ("es" if a.what == "batch" else "s")
        dest = a.dest or os.path.join(REPO, ".local", "living", "store", top, a.name)
        path = fetch_batch(backend, a.name, dest, machine=a.machine, unpack=a.unpack, top=top)
        print(f"{path} → {tilde(dest)}")


def cmd_card(a, cfg, machine):
    """Publish a dataset card (store_cards/<repo>.md) as the repository's README.md."""
    card = os.path.join(TOOLS, "store_cards", f"{a.repo}.md")
    with open(card, encoding="utf-8") as f:
        text = f.read()
    if "DRAFT" in text:
        raise Refused(f"{card} is still marked DRAFT")
    backend = make_backend(a.backend, cfg, yes_publish=a.yes_publish, root=a.root)
    if isinstance(backend, HFBackend):
        print(backend.put_file(a.repo, card, "README.md", f"card: {a.repo}"))
    else:
        d = tempfile.mkdtemp(prefix="store-card-")
        try:
            shutil.copy(card, os.path.join(d, "README.md"))
            print(backend.publish(a.repo, d, ".card", f"card: {a.repo}"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


def cmd_layout(a, cfg, machine):
    if a.manifest:
        with open(a.manifest) as f:
            items = json.load(f)["items"]
    else:
        items = scan(cfg=cfg, machine=machine)
    sys.stdout.write(layout_markdown(layout(items, ratio=a.ratio)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--md")
    m.add_argument("--json")
    s = sub.add_parser("scrub")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("src")
    s.add_argument("--report")
    s.add_argument("--kind", choices=["trial-batch", "play-session", "motion", "generic"])
    s.add_argument("--player", type=int)
    s.add_argument("--decide", action="append", help="what-if: CATEGORY=include|exclude|redact (not saved)")
    s.add_argument("--player-name", action="append", default=[],
                   help="an extra name of the player for this run (repeatable); names the player gave "
                        "themself are found automatically")
    s.add_argument("--write", help="write the scrubbed tree (DIR/tree) and the reports into DIR, for review")
    c = sub.add_parser("card")
    c.add_argument("repo", choices=["runs", "assets"])
    c.add_argument("--backend", choices=["local", "hf"], required=True)
    c.add_argument("--root")
    c.add_argument("--yes-publish", action="store_true")
    for name in ("pack", "publish"):
        q = sub.add_parser(name)
        q.add_argument("kind", choices=["batch", "session", "motion"])
        q.add_argument("src")
        q.add_argument("--player", type=int)
        q.add_argument("--player-name", action="append", default=[], help="an extra name of the player (repeatable)")
        q.add_argument("--name")
        if name == "pack":
            q.add_argument("--out", required=True)
            q.add_argument("--decide", action="append", help="what-if: CATEGORY=include|exclude|redact")
        else:
            q.add_argument("--backend", choices=["local", "hf"], required=True)
            q.add_argument("--root", help="local backend root")
            q.add_argument("--yes-publish", action="store_true")
            q.add_argument("--packed", help="upload this existing pack of SRC unchanged (batches)")
    pb = sub.add_parser("publish-batches")
    pb.add_argument("--list", required=True, help="file with one batch folder per line")
    pb.add_argument("--stage", required=True, help="where the packs are written (kept; reused when complete)")
    pb.add_argument("--per-commit", type=int, default=15)
    pb.add_argument("--backend", choices=["local", "hf"], required=True)
    pb.add_argument("--root")
    pb.add_argument("--yes-publish", action="store_true")
    f = sub.add_parser("fetch")
    f.add_argument("what", choices=["motion-library", "batch", "session"])
    f.add_argument("name", nargs="?")
    f.add_argument("--backend", choices=["local", "hf"], default="local")
    f.add_argument("--root")
    f.add_argument("--dest")
    f.add_argument("--machine")
    f.add_argument("--unpack", action="store_true")
    f.add_argument("--force", action="store_true")
    l = sub.add_parser("layout")
    l.add_argument("--manifest")
    l.add_argument("--ratio", type=float, default=0.2)
    a = p.parse_args(argv)
    try:
        cfg = load_config()
        machine = machine_name(cfg)
        {"manifest": cmd_manifest, "scrub": cmd_scrub, "pack": cmd_pack, "publish": cmd_publish,
         "fetch": cmd_fetch, "layout": cmd_layout, "card": cmd_card,
         "publish-batches": cmd_publish_batches}[a.cmd](a, cfg, machine)
    except Refused as e:
        print(f"store: refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
