#!/usr/bin/env python3
"""The predicted disk charge (disk_charge.py, check.charge) against living-check's real plan.

    python3 living/tools/disk_charge_selftest.py

Unit cases of check.charge (no step to run, one step, every step, an unknown step, a doubt, a
warm target). Then, in a clone of this worktree (check_selftest's clone, a scratch stamp store
and target), the charge from `check.py --plan` itself:
- an empty stamp store (it cannot be read): the full charge;
- every step stamped at the clone's digests: nothing;
- a docs-only change: nothing; a tools-only change no step reads: nothing;
- a tools-only change the script bench reads: script-gate's cost alone;
- a change in living/authority: the authority's two steps (authority, authority-tests) alone;
- every stamp stale (a shared input, living/Cargo.toml, changed): the full charge;
- a step that cannot be keyed (a symlinked directory in its inputs): the full charge;
- the scene charge: none for docs or without --scenes, 1 GB for living/authority with --scenes;
- gate-merge's start-gb on branches merged onto a stamped base through a remote: the floor alone
  for a docs-only branch, the floor plus the authority's steps for an authority branch, the
  prediction checkout reused, and the full figure for a branch that does not merge cleanly.
Prints one line per case and exits 1 on any failure.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import check  # noqa: E402
import check_selftest  # noqa: E402
import disk_charge  # noqa: E402

GIB = check.GIB
fails = []


def expect(name, cond, detail=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  ({str(detail)[-400:]})"), flush=True)
    if not cond:
        fails.append(name)


def unit_cases(home):
    target = os.path.join(home, "none")
    full = 18 * GIB
    expect("charge: no step to run is nothing", check.charge([], target, full)[0] == 0)
    expect("charge: one step is its measured cost", check.charge(["script-gate"], target, full)[0] == check.STEP_COST_GB["script-gate"] * GIB)
    every = [s["name"] for s in check.STEPS]
    got = check.charge(every, target, full)
    expect("charge: every step is at most the full charge", got[0] == min(full, sum(check.STEP_COST_GB.values()) * GIB), got)
    expect("charge: an unknown step is the full charge", check.charge(["new-step"], target, full)[0] == full)
    expect("charge: a doubt is the full charge", check.charge([], target, full, unsure="a doubt")[0] == full)
    warm = os.path.join(home, "warm")
    os.makedirs(warm)
    with patch.object(check, "tree_size", return_value=17 * GIB):
        expect("charge: a warm target caps it (2 GiB at least)", check.charge(every, warm, full)[0] == 2 * GIB)
    got = check.disk_threshold(target, {}, ["script-gate"])
    expect("the check's own wait: the floor plus the steps it will run", got[0] == 45 * GIB + check.STEP_COST_GB["script-gate"] * GIB, got)
    expect("the check's own wait with no step list: the full charge, as before", check.disk_threshold(target, {})[0] == 63 * GIB)
    expect("every step of the check has a cost", set(check.STEP_COST_GB) == set(every), sorted(set(every) ^ set(check.STEP_COST_GB)))


def plan_charge(repo, home):
    env = check_selftest.check_env(home)
    return disk_charge.check_charge(repo, 18, target=os.path.join(home, "target"), env=env)


def stamp_all(repo, home):
    """Stamps at every step's digest for the clone as it is (the base tree has passed)."""
    out = os.path.join(home, "plan.json")
    subprocess.run([sys.executable, os.path.join(repo, "living/tools/check.py"), "--plan", "--json", out], cwd=repo,
                   env=check_selftest.check_env(home), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    for s in json.load(open(out))["plan"]:
        d = s["digest"]
        path = os.path.join(home, "store", "stamps", d[:2], d + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"step": s["name"], "at": "selftest", "worktree": repo, "commit": "0" * 40}, f)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def clone_cases(home):
    repo = check_selftest.clone_worktree(home)
    git(repo, "add", "-A", "living")
    git(repo, "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "commit", "-q", "--allow-empty", "-m", "the worktree's changes")
    c = plan_charge(repo, home)
    expect("an empty stamp store: the full charge", c["bytes"] == 18 * GIB and c["unsure"], c)
    stamp_all(repo, home)
    c = plan_charge(repo, home)
    expect("every step stamped: nothing", c["bytes"] == 0 and c["run"] == [], c)
    costs = check.STEP_COST_GB
    cases = [
        ("a docs-only change: nothing", "docs/TOOLING.md", "\ndisk_charge_selftest\n", [], 0),
        ("a tools-only change no step reads: nothing", "living/tools/merge.py", "\n# disk_charge_selftest\n", [], 0),
        ("a tools-only change the script bench reads: script-gate alone", "living/tools/script_bench/gate.py",
         "\n# disk_charge_selftest\n", ["script-gate"], costs["script-gate"]),
        ("a change in living/authority: the authority's steps alone", "living/authority/src/look.rs",
         "\n// disk_charge_selftest\n", ["authority", "authority-tests"], costs["authority"] + costs["authority-tests"]),
        ("every stamp stale (living/Cargo.toml changed): the full charge", "living/Cargo.toml",
         "\n# disk_charge_selftest\n", [s["name"] for s in check.STEPS], None),
    ]
    for name, rel, text, run, gb in cases:
        undo = check_selftest.edited(os.path.join(repo, rel), text)
        c = plan_charge(repo, home)
        undo()
        want = 18 * GIB if gb is None else min(18 * GIB, gb * GIB)
        expect(name, sorted(c["run"] or []) == sorted(run) and abs(c["bytes"] - want) < 1, c)
    link = os.path.join(repo, "living/rules/disk_charge_selftest_link")
    os.symlink(os.path.join(repo, "living/rules/src"), link)
    c = plan_charge(repo, home)
    os.remove(link)
    expect("a step that cannot be keyed: the full charge", c["bytes"] == 18 * GIB and c["unsure"] and "cannot be keyed" in c["unsure"], c)
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "sel-docs")
    with open(os.path.join(repo, "docs/TOOLING.md"), "a") as f:
        f.write("\ndisk_charge_selftest\n")
    git(repo, "-c", "user.name=s", "-c", "user.email=s@invalid", "commit", "-qam", "docs")
    git(repo, "checkout", "-q", "--detach", head)
    git(repo, "checkout", "-q", "-b", "sel-auth")
    with open(os.path.join(repo, "living/authority/src/look.rs"), "a") as f:
        f.write("\n// disk_charge_selftest\n")
    git(repo, "-c", "user.name=s", "-c", "user.email=s@invalid", "commit", "-qam", "authority")
    git(repo, "checkout", "-q", "--detach", head)
    git(repo, "checkout", "-q", "-b", "sel-clash")
    with open(os.path.join(repo, "docs/TOOLING.md"), "a") as f:
        f.write("\nanother line\n")
    git(repo, "-c", "user.name=s", "-c", "user.email=s@invalid", "commit", "-qam", "clash")
    git(repo, "checkout", "-q", "--detach", head)
    git(repo, "branch", "-q", "sel-base", head)
    sha_docs, sha_auth = git(repo, "rev-parse", "sel-docs"), git(repo, "rev-parse", "sel-auth")
    expect("scenes: none for a docs-only merge", disk_charge.scene_charge(repo, head, sha_docs, True)[0] == 0)
    expect("scenes: none without --scenes", disk_charge.scene_charge(repo, head, sha_auth, False)[0] == 0)
    expect("scenes: 1 GB for living/authority with --scenes", disk_charge.scene_charge(repo, head, sha_auth, True)[0] == disk_charge.SCENE_GB)
    # gate-merge's start-gb through a remote (the clone itself), on a stamped base
    git(repo, "remote", "add", "self", repo)
    env = check_selftest.check_env(home, SLOP_DISK_FLOOR_GB="40")
    state = os.path.join(home, "state")
    with patch.dict(os.environ, env, clear=True), patch.object(disk_charge, "STATE", state):
        gb, why = disk_charge.start_gb(["sel-docs", "--remote", "self", "--into", "sel-base"], root=repo)
        expect("start-gb: a docs-only branch waits for the floor alone", gb == 40, why)
        gb, why = disk_charge.start_gb(["sel-auth", "--remote", "self", "--into", "sel-base", "--scenes"], root=repo)
        want = 40 + int(-(-(costs["authority"] + costs["authority-tests"] + disk_charge.SCENE_GB) // 1))
        expect("start-gb: an authority branch, with scenes: the floor, its steps and the scenes", gb == want, (gb, want, why))
        made = [d for d in os.listdir(state) if d.startswith("disk-charge-") and not d.endswith(".lock")]
        expect("start-gb: one prediction checkout, reused", len(made) == 1, made)
        git(repo, "checkout", "-q", "--detach", "sel-docs")
        gb, why = disk_charge.start_gb(["sel-clash", "--remote", "self", "--into", "sel-docs"], root=repo)
        expect("start-gb: a branch that does not merge cleanly: the full figure", gb == 40 + 18 and "does not merge cleanly" in " ".join(why), (gb, why))


def main():
    with tempfile.TemporaryDirectory(prefix="disk-charge-selftest-") as home:
        unit_cases(home)
        clone_cases(home)
    print("disk_charge_selftest:", "all passed" if not fails else f"{len(fails)} failed: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
