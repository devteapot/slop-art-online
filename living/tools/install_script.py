#!/usr/bin/env python3
"""Install a rules script on a database as the world admin, over HTTP.

    python3 living/tools/install_script.py DB [SCRIPT] [--seed NAME]

SCRIPT defaults to living/scripts/skills.rhai; `-` reads it from stdin. `--seed NAME` composes that
seed's own laws (`laws`, or the file `laws_file` names under living/seeds) over the script first,
as the authority does when it creates the seed's world (`living_rules::floors::compose`):
installing the bare script on such a world drops its laws. `seed_script` and `compose_laws` are
the one Python copy of that composition (verify.py launch and trials.py use them). The source goes in the
request body: the shipped script passed 128 KiB on 2026-11-11, past Linux's limit on one
command-line argument (MAX_ARG_STRLEN), so `spacetime call ... install_script "<source>"` no
longer runs. The admin token is the in-container CLI identity's (living/tools/stdb), read into
memory only; LIVING_STDB_URL names the server (default the shared one, http://127.0.0.1:3300),
and LIVING_STDB_CONTAINER its container, as for living/tools/stdb. Standard library only.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
SEEDS = ROOT / "living/seeds"
SKILLS = ROOT / "living/scripts/skills.rhai"
# `living_rules::script::WORLD_LAW_MARK`: the authority appends a world's own law values (a seed's
# `rules`, `set_world_law`) after this line of every source it installs.
WORLD_LAW_MARK = "// ---- this world's own law values (written by the authority: a seed's `rules`, `set_world_law`) ----"
OVERLAY_MARK = "\n// ---- floor overlay ----\n"
DEF = re.compile(r"^(\s*)(private\s+)?fn\s+([A-Za-z0-9_]+)(\s*\()", re.M)


def compose_laws(base, overlay):
    """`living_rules::floors::compose` in Python: each function the overlay defines replaces the
    base's (`fn NAME(` at the start of a base line becomes `fn base_NAME(`), and the overlay is
    appended after the floor-overlay line."""
    names = {m.group(3) for m in DEF.finditer(overlay)}
    bad = sorted(n for n in names if n.startswith("base_"))
    if bad:
        raise ValueError(f"floor overlay defines `{bad[0]}`: `base_` names are the replaced base functions")
    renamed = DEF.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}fn base_{m.group(3)}{m.group(4)}" if m.group(3) in names else m.group(0), base)
    return renamed + ("" if renamed.endswith("\n") else "\n") + OVERLAY_MARK + overlay


def seed_json(seed):
    """A seed by the name LIVING_SEED takes (resolved under living/seeds, `.json` added, as
    living/authority/build.rs does; an absolute path also works), or None for `none` (a floor
    module, given its seed by `create_floor`) and a seed that does not exist."""
    if not seed or seed == "none":
        return None
    path = SEEDS / f"{seed}.json"
    return json.loads(path.read_text()) if path.exists() else None


def seed_laws(seed):
    """A seed's laws overlay (a parsed seed): `laws`, or the file `laws_file` names under living/seeds."""
    if str(seed.get("laws") or "").strip():
        return seed["laws"]
    if seed.get("laws_file"):
        return (SEEDS / seed["laws_file"]).read_text()
    return ""


def seed_script(seed, skills=None):
    """(source, overlay): the script a world created from `seed` (a name or a parsed seed) runs,
    the shipped `skills` text (default living/scripts/skills.rhai) with the seed's laws composed
    over it, and the overlay ("" for a seed without laws, or `none`)."""
    base = SKILLS.read_text() if skills is None else skills
    s = seed_json(seed) if isinstance(seed, (str, type(None))) else seed
    overlay = seed_laws(s) if s else ""
    return (compose_laws(base, overlay) if overlay.strip() else base), overlay


def without_world_laws(source):
    """`living_rules::script::without_world_laws`: an installed source without the world's own
    law values the authority appended, to compare with what was sent."""
    i = source.find(WORLD_LAW_MARK)
    return source if i < 0 else source[:i].rstrip("\n")


def installed(db, token=None, timeout=60):
    """The `skills` script the database runs (its `script` row's source), or None."""
    req = urllib.request.Request(f"{URL}/v1/database/{db}/sql", data=b"SELECT source FROM script WHERE name = 'skills'", method="POST")
    req.add_header("Authorization", f"Bearer {token or admin_token()}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rows = json.loads(r.read().decode())[-1]["rows"]
    except urllib.error.HTTPError:
        return None
    return rows[0][0] if rows else None


def same_script(made, sent):
    """Whether an installed source is the one sent, ignoring the world's own law values."""
    return made is not None and without_world_laws(made).rstrip("\n") == without_world_laws(sent).rstrip("\n")


def admin_token():
    out = subprocess.run([str(ROOT / "living/tools/stdb"), "login", "show", "--token"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if "auth token" in line and " is " in line:
            return line.rsplit(" is ", 1)[1].strip()
    sys.exit("could not read the admin token from `spacetime login show --token`")


def install(db, source, token=None, timeout=180):
    """POST the source to `install_script`; returns (status, body)."""
    req = urllib.request.Request(f"{URL}/v1/database/{db}/call/install_script", data=json.dumps([source]).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token or admin_token()}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    argv = sys.argv[1:]
    seed = None
    if "--seed" in argv:
        i = argv.index("--seed")
        if i + 1 >= len(argv):
            sys.exit(__doc__)
        seed = argv[i + 1]
        del argv[i:i + 2]
        if seed != "none" and seed_json(seed) is None:
            sys.exit(f"no seed {SEEDS / seed}.json")
    if len(argv) not in (1, 2):
        sys.exit(__doc__)
    db = argv[0]
    path = argv[1] if len(argv) == 2 else str(SKILLS)
    source = sys.stdin.read() if path == "-" else Path(path).read_text()
    source, overlay = seed_script(seed, source)
    code, body = install(db, source)
    if code != 200:
        sys.exit(f"install_script on {db}: {code} {body.strip()[-2000:]}")
    print(f"installed {len(source)} bytes of rules on {db}{f' with seed {seed} laws composed' if overlay else ''}")


if __name__ == "__main__":
    main()
