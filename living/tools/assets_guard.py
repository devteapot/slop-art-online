#!/usr/bin/env python3
"""Run a command that makes generated assets, and fail if it changed a tracked file.

    python3 living/tools/assets_guard.py -- COMMAND [ARGS...]

Generated assets are git-ignored (living/game/assets/lookdev, view, textures, envs/<name>/, the look
book); a run that makes them must leave every tracked file as it was. Rules data such as
living/rules/data/buildings.json is tracked because the authority and the client compile it in,
and changing it is a rules change, made on purpose and reviewed (`just living-rules-table`).

This takes `git status --porcelain --untracked-files=no` (tracked files only) before and after
the command, with each changed file's content hash, and exits 1 naming every tracked file the
run changed (or changed again, for one already modified before it). A failing command fails the
guard with its own exit status. `just living-game-assets` runs under it.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def tracked_state():
    """{path: (status, sha256 of the working file or None)} for every tracked file not as HEAD."""
    out = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=no"], cwd=REPO,
                         capture_output=True, check=True).stdout.decode()
    state = {}
    items = out.split("\0")
    i = 0
    while i < len(items):
        e = items[i]
        i += 1
        if not e:
            continue
        status, path = e[:2], e[3:]
        if status[0] in "RC":  # a rename names its source next
            i += 1
        p = REPO / path
        state[path] = (status, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    return state


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        sys.exit(__doc__)
    before = tracked_state()
    r = subprocess.run(argv, cwd=REPO)
    after = tracked_state()
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    if changed:
        print("assets_guard: the run changed tracked files (generated assets must not; rules data is "
              "changed on purpose, e.g. `just living-rules-table`):", file=sys.stderr)
        for p in changed:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)
    if r.returncode:
        sys.exit(r.returncode)
    print(f"assets_guard: no tracked file changed ({len(before)} already modified before the run, left as they were)"
          if before else "assets_guard: no tracked file changed")


if __name__ == "__main__":
    main()
