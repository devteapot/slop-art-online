#!/usr/bin/env python3
"""The disk a merge will take: one prediction for living-merge and gate-merge (docs/TOOLING.md, "Disk").

    python3 living/tools/disk_charge.py start-gb [living-merge's arguments]   # gate_merge.sh's start wait

The check's charge is living-check's own: `check.py --plan --json` on the merged tree keys every
step from its inputs exactly as the check will, against the stamp store, and charges only the
steps that would run (check.charge: their measured cold cost, never more than the full charge).
Any doubt (the plan fails, a step cannot be keyed, the store cannot be read, the merge does not
apply cleanly) charges the full allowance. The scene charge (scratch databases, SCENE_GB) applies
only with --scenes and only when the merge touches a path the scene gate runs scenes for
(scene_gate.behavioural and scene_gate.rendering): no scenes selected, no scene charge.

living-merge predicts on the merged tree in its own worktree, after each attempt's merge.
gate-merge waits before living-merge has merged: `start-gb` merges the branch onto the fetched
target branch as a commit object (`git merge-tree`, no ref written), checks it out in one
persistent prediction checkout (STATE/disk-charge-<repo>, reused, never edited), plans there with
the real Cargo target (so a warm target still counts), and prints the free space to wait for in
whole GB: the floor (SLOP_DISK_FLOOR_GB, default 45, as before) plus the charge. Reasons go to
stderr. A failure prints the full figure and says why.
"""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402

GIB = check.GIB
CHECK_GB = 18
SCENE_GB = 1
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local/state"), "slop-merge")


def full_check(target, cold_gb, why):
    cost, size = check.remaining_check_cost(target, cold_gb * GIB)
    return {"bytes": cost, "why": f"full charge ({why}): max of 2 GiB and {cold_gb:g} GiB minus {size / GIB:.2f} GiB already in the target",
            "run": None, "unsure": why}


def check_charge(root, cold_gb=CHECK_GB, target=None, env=None):
    """living-check's charge for the tree at `root` (a dict: bytes, why, run, unsure). `target`
    overrides the Cargo target the charge is credited against (CARGO_TARGET_DIR does not enter
    a step's digest)."""
    env = dict(os.environ if env is None else env)
    env["SLOP_CHECK_COST_GB"] = str(int(round(float(cold_gb))))  # check.py reads whole GiB
    env.pop("LIVING_CHECK_FULL", None)
    if target:
        env["CARGO_TARGET_DIR"] = target
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "plan.json"
        try:
            r = subprocess.run([sys.executable, str(Path(root) / "living/tools/check.py"), "--plan", "--json", str(out)],
                               cwd=root, env=env, capture_output=True, text=True, timeout=600)
            data = json.loads(out.read_text()) if r.returncode == 0 and out.exists() else None
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            data, r = None, None
            err = str(e)
        if not data or "charge" not in data:
            why = f"the check's plan failed: {(r.stderr or r.stdout).strip()[-300:] if r else err}" if not data else \
                "this tree's check.py predates the charge"
            try:
                t = target or check.target_dir(root)
            except (OSError, subprocess.SubprocessError, ValueError):
                t = os.path.join(root, "living/target")
            return full_check(t, cold_gb, why)
        c = data["charge"]
        return {"bytes": c["bytes"], "why": c["why"], "run": c["run"], "unsure": c["unsure"]}


def scene_charge(root, base, head, scenes):
    """(GB, why): SCENE_GB when --scenes and base..head touches what the scene gate runs scenes for."""
    if not scenes:
        return 0, "no --scenes"
    try:
        sys.path.insert(0, str(Path(root) / "living/tools"))
        import scene_gate
        paths = scene_gate.changed(base, head, cwd=root)
        hit = scene_gate.behavioural(paths) + scene_gate.rendering(paths)
    except Exception as e:  # any doubt: charge
        return SCENE_GB, f"scene selection could not be read ({e}): charged"
    if not hit:
        return 0, f"no scenes selected ({len(paths)} paths, none behavioural or drawing)"
    return SCENE_GB, f"scenes selected ({len(hit)} behavioural or drawing paths, e.g. {hit[0]})"


def git(*args, cwd=None, check_=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check_ and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def parse_merge_args(args):
    """(branch, remote, into, scenes) from living-merge's arguments."""
    branch, remote, into = None, "origin", "main"
    scenes = os.environ.get("LIVING_MERGE_SCENES") == "1"
    args = list(args)
    while args:
        a = args.pop(0)
        if a in ("-m", "--retries") and args:
            args.pop(0)
        elif a == "--remote" and args:
            remote = args.pop(0)
        elif a == "--into" and args:
            into = args.pop(0)
        elif a == "--scenes":
            scenes = True
        elif a.startswith("-"):
            continue
        elif branch is None:
            branch = a
    return branch, remote, into, scenes


def predicted_merge(root, branch, remote, into):
    """(base, merge commit) for branch merged onto remote/into, as a commit object only."""
    git("fetch", "-q", remote, f"+refs/heads/{into}:refs/remotes/{remote}/{into}", cwd=root)
    if branch.startswith(f"{remote}/"):
        branch = branch[len(remote) + 1:]
    if git("ls-remote", "--exit-code", remote, f"refs/heads/{branch}", cwd=root, check_=False).returncode == 0:
        git("fetch", "-q", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", cwd=root)
        ref = f"refs/remotes/{remote}/{branch}"
    else:
        ref = branch
    base = git("rev-parse", f"refs/remotes/{remote}/{into}", cwd=root).stdout.strip()
    tip = git("rev-parse", f"{ref}^{{commit}}", cwd=root).stdout.strip()
    r = git("merge-tree", "--write-tree", base, tip, cwd=root, check_=False)
    if r.returncode:
        raise RuntimeError(f"{branch} does not merge cleanly onto {remote}/{into} (living-merge will refuse it)")
    tree = r.stdout.split()[0]
    commit = git("commit-tree", tree, "-p", base, "-p", tip, "-m", f"disk_charge prediction: {branch} onto {into}", cwd=root).stdout.strip()
    return base, commit


def prediction_path(root):
    common = git("rev-parse", "--git-common-dir", cwd=root).stdout.strip()
    common = os.path.realpath(common if os.path.isabs(common) else os.path.join(root, common))
    return os.path.join(STATE, "disk-charge-" + hashlib.sha1(common.encode()).hexdigest()[:12])


def prediction_checkout(root, commit):
    """The persistent prediction checkout for this repository, at commit (detached). Call it with
    the checkout's lock held (start_gb)."""
    path = prediction_path(root)
    if not os.path.isdir(path):
        os.makedirs(STATE, exist_ok=True)
        git("worktree", "add", "-q", "--detach", path, commit, cwd=root)
    else:
        if git("status", "--porcelain", "--untracked-files=all", cwd=path).stdout.strip():
            raise RuntimeError(f"the prediction checkout {path} has changes; it must stay as git leaves it")
        git("checkout", "-q", "--detach", commit, cwd=path)
    return path


def start_gb(args, root=None):
    """(whole GB to wait for, lines of reasons) for gate-merge."""
    root = root or git("rev-parse", "--show-toplevel").stdout.strip()
    floor = float(os.environ.get("SLOP_DISK_FLOOR_GB") or 45)
    cold = float(os.environ.get("SLOP_GATE_COST_GB") or os.environ.get("SLOP_MERGE_CHECK_GB") or CHECK_GB)
    branch, remote, into, scenes = parse_merge_args(args)
    try:
        target = check.target_dir(root)
    except (OSError, subprocess.SubprocessError, ValueError):
        target = os.path.join(root, "living/target")
    try:
        if not branch:
            raise RuntimeError("no branch in the arguments")
        base, commit = predicted_merge(root, branch, remote, into)
        os.makedirs(STATE, exist_ok=True)
        with open(prediction_path(root) + ".lock", "a") as lock:  # one prediction at a time per repository
            fcntl.flock(lock, fcntl.LOCK_EX)
            where = prediction_checkout(root, commit)
            c = check_charge(where, cold, target=target)
            s_gb, s_why = scene_charge(where, base, commit, scenes)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        c = full_check(target, cold, str(e))
        s_gb, s_why = (SCENE_GB, "charged (no prediction)") if scenes else (0, "no --scenes")
    total = floor + c["bytes"] / GIB + s_gb
    whole = int(-(-total // 1))  # up to a whole GB, as gate_merge.sh compares
    return whole, [f"floor {floor:g} GB", f"check {c['bytes'] / GIB:.2f} GB: {c['why']}", f"scenes {s_gb:g} GB: {s_why}"]


def main(argv):
    if not argv or argv[0] != "start-gb":
        print(__doc__, file=sys.stderr)
        return 2
    gb, why = start_gb(argv[1:])
    for line in why:
        print(f"disk-charge: {line}", file=sys.stderr)
    print(gb)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
