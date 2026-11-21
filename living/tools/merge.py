#!/usr/bin/env python3
"""Merge a branch into main the coordinators' way, end to end (docs/TOOLING.md).

In the current worktree, which must be clean and have no commits that main lacks:
  1. fetch; move HEAD to origin/main (git reset --keep);
  2. git merge --no-ff the branch, pinned to the commit it had when this started;
  2a. seed freshness (`living/tools/scene_gate.py seeds`: every compiled seed against its
     `living/seeds/worlds/<world>/` sources, files only, a fraction of a second); stop without
     pushing when a seed is stale and not on the red-on-main list;
  3. run the check (`living/tools/check.py`: `just living-check` with step stamps), and
     stop without pushing if it fails or leaves the worktree dirty;
  3a. when the merge touches the module's shape (authority, rules, bindings, the workspace
     manifests): `just living-generate` on the checked tree (the check's own wasm; cargo
     rebuilds nothing when it is current), and stop without pushing when living/bindings
     changes ("bindings not regenerated: <files>") or the generator fails ("bindings check
     could not run"). Docs, client and tool merges skip it;
  3b. with --scenes (or LIVING_MERGE_SCENES=1): the scene gate (living/tools/scene_gate.py),
     real scenes on scratch verify-gate-* databases when the merge touches behaviour; it
     stops without pushing when a case fails twice on the branch and passes on main;
  4. git push origin HEAD:main; when that is refused because main moved, fetch, merge the
     same branch commit onto the new main and check again (unchanged steps are skipped by
     their stamps), up to --retries times. The scene gate runs again only when the new main
     commits touch behaviour themselves.
Every git command it runs is printed, and a summary at the end says what happened.

Usage: merge.py <branch> [-m MESSAGE] [--retries N] [--no-push] [--scenes] [--remote NAME] [--into BRANCH]
  <branch>     a branch on the remote (preferred) or a local branch or commit
  -m MESSAGE   the merge commit's message (default "Merge <branch>")
  --retries N  merge again at most N times after main moved (default 5)
  --no-push    stop after a passing check (the merge commit stays in this worktree)
  --scenes     run the scene gate after the check (also LIVING_MERGE_SCENES=1); its own
               settings (server, red-on-main list) come from LIVING_GATE_* (scene_gate.py)
Environment: LIVING_MERGE_CHECK replaces the check command (a shell command; for tests);
LIVING_MERGE_SCENES_CMD replaces the scene gate command (for tests); LIVING_MERGE_BINDINGS_CMD
replaces `just living-generate` in the bindings check (for tests). The generator itself is
LIVING_GENERATE_CMD (generate_bindings.sh); when unset and a container named
LIVING_GENERATE_CONTAINER (default slop-trials-stdb, the Spark's) is running, the bindings check
generates inside it (living/tools/generate_in_container.sh), else the Justfile's compose run.
LIVING_MERGE_BINDINGS=always runs the bindings check whatever the merge touches (=off skips it).
LIVING_MERGE_SEEDS_CMD replaces the seed freshness command (for tests); LIVING_MERGE_SEEDS=off
skips it, saying so.
Exit codes: 0 merged and pushed (or nothing to merge), 2 usage, 3 refused (worktree), 4 merge
conflict, 5 check failed, 6 check left the worktree dirty, 7 main kept moving, 8 push failed,
9 another git command failed, 10 the scene gate failed (or could not run), 11 the bindings
were not regenerated (or the bindings check could not run), 12 refused (disk), 13 a compiled seed is stale (or the freshness check could not run),
14 the scene gate's server is unreachable (gate_server.py check: a dead container fails the gate before the check, not after it).

Disk: SLOP_MERGE_FLOOR_GB overrides the installed disk cleaner's floor (45 GB without
an installed floor). SLOP_MERGE_CHECK_GB overrides the cold check allowance (18 GB).
Each attempt subtracts allocated Cargo target space, with a 2 GB minimum allowance.
SLOP_MERGE_DISK_CHECK=0 disables the pre-check and prints a warning.

The push is a compare-and-swap (--force-with-lease on the main it merged onto): it lands only
when main is still exactly the commit that was merged and checked, never over a main that
moved or was rewound meanwhile.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess
import sys
import time
from xml.parsers.expat import ExpatError

from check import remaining_check_cost, target_dir
from disk_clean import GB

HOME = os.path.expanduser("~")
# Checkouts this command never merges in: the owner's own.
PROTECTED = [os.path.join(HOME, "dev/slop-art-online")]
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state"), "slop-merge")
DISK_REFUSED = 12
GATE_UNREACHABLE = 14
DEFAULT_FLOOR_GB = 45
CHECK_GB = 18
SCENE_GB = 1
done = []  # what happened, for the summary


def say(msg):
    print(f"living-merge: {msg}", flush=True)


def git(*args, check=True, quiet=False, capture=True):
    if not quiet:
        say("$ git " + " ".join(shlex.quote(a) for a in args))
    r = subprocess.run(["git", *args], stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None, text=True)
    if check and r.returncode != 0:
        if capture and r.stdout:
            print(r.stdout.rstrip(), flush=True)
        raise GitError(f"git {' '.join(args[:2])} failed (exit {r.returncode})")
    return r


class GitError(Exception):
    pass


def remote_tip(remote, ref):
    """The remote's commit for exactly `ref`, or None when it cannot be told."""
    r = subprocess.run(["git", "ls-remote", remote, ref], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None


def out(*args):
    return git(*args, quiet=True).stdout.strip()


def ok(*args):
    return git(*args, check=False, quiet=True).returncode == 0


def refuse(code, msg):
    say(msg)
    summary(f"refused: {msg}")
    sys.exit(code)


def summary(result):
    say("summary:")
    for line in done:
        print(f"  - {line}", flush=True)
    print(f"  = {result}", flush=True)


def installed_floor():
    """Read the argument written by disk_clean_install.sh on Linux or macOS."""
    if sys.platform == "darwin":
        plist = Path(HOME) / "Library/LaunchAgents/dev.slop.disk-clean.plist"
        if not plist.is_file():
            return DEFAULT_FLOOR_GB
        args = plistlib.loads(plist.read_bytes()).get("ProgramArguments", [])
    else:
        systemd = Path(os.environ.get("XDG_CONFIG_HOME") or Path(HOME) / ".config") / "systemd/user"
        unit = systemd / "slop-disk-clean.service"
        if not unit.is_file():
            return DEFAULT_FLOOR_GB
        command = next((line.removeprefix("ExecStart=") for line in unit.read_text().splitlines()
                        if line.startswith("ExecStart=")), "")
        args = shlex.split(command)
    if "--floor-gb" in args:
        return args[args.index("--floor-gb") + 1]
    return DEFAULT_FLOOR_GB


def disk_budget():
    if os.environ.get("SLOP_MERGE_DISK_CHECK") == "0":
        say("WARNING: free-space pre-check disabled (SLOP_MERGE_DISK_CHECK=0)")
        return None
    try:
        floor_override = os.environ.get("SLOP_MERGE_FLOOR_GB")
        floor = float(installed_floor() if floor_override is None else floor_override)
        cost = float(os.environ.get("SLOP_MERGE_CHECK_GB", CHECK_GB))
        if floor < 0 or cost < 0 or not math.isfinite((floor + cost) * GB):
            raise ValueError("floor and check cost must be finite, non-negative GB values")
    except (OSError, ValueError, IndexError, ExpatError) as e:
        refuse(DISK_REFUSED, f"disk: invalid floor or check cost: {e}")
    return floor, cost


def disk_free(*cmd, timeout=None):
    df = subprocess.run(cmd, env={**os.environ, "LC_ALL": "C"}, capture_output=True, text=True,
                        check=True, timeout=timeout)
    row = df.stdout.strip().splitlines()[-1]
    fields = re.fullmatch(r"(.+?)\s+(\d+)\s+\d+\s+(-?\d+)\s+\d+%\s+(.+)", row)
    if not fields:
        raise ValueError(f"unexpected df output for {cmd[-1]}: {row}")
    device, blocks, available, mount = fields.groups()
    return (device, blocks), int(available) * 1024, mount


def scene_filesystem(scenes):
    if not scenes or os.environ.get("LIVING_MERGE_SCENES_CMD"):
        return None
    container = os.environ.get("LIVING_GATE_STDB_CONTAINER", "slop-trials-stdb")
    try:
        filesystem, _, _ = disk_free("docker", "exec", "-e", "LC_ALL=C", container, "df", "-Pk",
                                     "/home/spacetime", timeout=5)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        # The scene gate owns errors from reaching its server.
        return None
    return filesystem


def gate_server_alive(scenes):
    """With --scenes, refuse at once (14) when the gate's server does not answer (gate_server.py)."""
    if not scenes or os.environ.get("LIVING_MERGE_SCENES_CMD"):
        return
    import gate_server
    container = os.environ.get("LIVING_GATE_STDB_CONTAINER", "slop-trials-stdb")
    url = os.environ.get("LIVING_GATE_STDB_URL", "http://127.0.0.1:3320")
    why = gate_server.probe(container, url)
    if why:
        refuse(GATE_UNREACHABLE, f"the scene gate's server is unreachable: {why} (start it: living/tools/gate_server.py start)")


def check_disk(root, budget, scenes):
    floor, cold_cost = budget
    try:
        # Use the same Cargo resolution as living-check, including Cargo configuration.
        if os.path.isfile("living/Cargo.toml") or os.environ.get("CARGO_TARGET_DIR") or os.environ.get("CARGO_BUILD_TARGET_DIR"):
            target = target_dir(root)
        else:
            target = os.path.join(root, "living/target")
        cost_bytes, target_bytes = remaining_check_cost(target, cold_cost * GB)
        cost = cost_bytes / GB
        scene_fs = scene_filesystem(scenes)
        paths = {"worktree": root, "Cargo target": target}
        checked = set()
        for label, path in paths.items():
            probe = Path(path).resolve()
            while not probe.exists():
                probe = probe.parent
            if probe in checked:
                continue
            checked.add(probe)
            fs, free, mount = disk_free("df", "-Pk", str(probe))
            scene_cost = SCENE_GB if fs == scene_fs else 0
            need = floor + cost + scene_cost
            if free < need * GB:
                scene_note = f" + {scene_cost:g} GB scenes" if scene_cost else ""
                return (f"disk: {label} at {path} ({fs[0]} on {mount}) has {free / GB:.2f} GB free; "
                        f"need {need:g} GB ({floor:g} GB floor + {cost:g} GB check{scene_note}); "
                        f"check cost is max of 2 GB and {cold_cost:g} GB minus "
                        f"{target_bytes / GB:.2f} GB already in Cargo target {target}")
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError, RuntimeError) as e:
        return f"disk: could not determine free space for the worktree and Cargo target: {e}"
    return None


def run_check(cmd, log_path, what="check"):
    """Run the check, streaming its output to the terminal and a log; return (code, seconds)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    say(f"{what}: {cmd}  (log {log_path})")
    t0 = time.time()
    with open(log_path, "a") as log:
        p = subprocess.Popen(["bash", "-o", "pipefail", "-c", cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
        code = p.wait()
    return code, time.time() - t0


def reset_to(sha, why):
    """git reset --keep, reporting (not hiding) a reset that git refuses."""
    r = git("reset", "--keep", sha, check=False)
    if r.returncode != 0:
        print(r.stdout.rstrip(), flush=True)
        done.append(f"could not move HEAD back to {sha[:10]} ({why}); HEAD is {out('rev-parse', 'HEAD')[:10]}")
        return False
    return True


# What makes the module's shape (its tables, reducers and views, and the types they carry): a
# merge touching none of these cannot change the generated bindings.
MODULE_SHAPE = ("living/authority/", "living/rules/", "living/bindings/", "living/Cargo.toml", "living/Cargo.lock")
BINDINGS = "living/bindings"


def bindings_check(merge_sha, base, log_path, start_head, attempt):
    """Regenerate the bindings from the checked merge's module; None when they are unchanged
    (or the merge cannot change them), else the exit code after restoring the worktree and HEAD."""
    touched = [p for p in out("diff", "--name-only", base, merge_sha).splitlines() if p.startswith(MODULE_SHAPE)]
    if os.environ.get("LIVING_MERGE_BINDINGS") == "always":
        touched = touched or ["(LIVING_MERGE_BINDINGS=always)"]
    elif os.environ.get("LIVING_MERGE_BINDINGS") == "off":
        touched = []
    if not touched:
        done.append(f"attempt {attempt}: bindings check skipped (the merge touches no module shape)")
        return None
    cmd = os.environ.get("LIVING_MERGE_BINDINGS_CMD") or "just living-generate"
    env_note = ""
    if not os.environ.get("LIVING_MERGE_BINDINGS_CMD") and not os.environ.get("LIVING_GENERATE_CMD"):
        c = os.environ.get("LIVING_GENERATE_CONTAINER", "slop-trials-stdb")
        r = subprocess.run(["docker", "inspect", c, "--format", "{{.State.Running}}"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip() == "true":
            os.environ["LIVING_GENERATE_CMD"] = f"sh living/tools/generate_in_container.sh {shlex.quote(c)}"
            env_note = f" (generated in {c})"
    code, secs = run_check(cmd, log_path, "bindings")
    changed = git("status", "--porcelain", "--untracked-files=all", "--", BINDINGS, quiet=True).stdout.splitlines()
    files = [l[3:] for l in changed if l.strip()]
    if code == 0 and not files:
        done.append(f"attempt {attempt}: bindings regenerated from the merge{env_note}: no change ({secs:.0f} s)")
        return None
    # put the tree back as the merge left it before moving HEAD
    git("checkout", "--", BINDINGS, check=False, quiet=True)
    git("clean", "-fdq", "--", BINDINGS, check=False, quiet=True)
    restored = reset_to(start_head, "after the bindings check")
    tail = "" if restored else " (HEAD NOT restored, see above)"
    if code != 0:
        done.append(f"attempt {attempt}: merge {merge_sha[:10]}; bindings check could not run: `{cmd}` exited {code}{env_note} (log {log_path})")
        summary(f"bindings check could not run; nothing pushed{tail}")
        return 11
    done.append(f"attempt {attempt}: merge {merge_sha[:10]}; bindings not regenerated: {', '.join(files)}")
    summary(f"bindings not regenerated: {', '.join(files)}; nothing pushed{tail}. Run `just living-generate` on the branch and commit living/bindings")
    return 11


def seeds_check(merge_sha, log_path, start_head, attempt):
    """Seed freshness on the merged tree, before the check; None when fresh (or skipped)."""
    cmd = os.environ.get("LIVING_MERGE_SEEDS_CMD")
    if os.environ.get("LIVING_MERGE_SEEDS") == "off":
        done.append(f"attempt {attempt}: seed freshness skipped (LIVING_MERGE_SEEDS=off)")
        return None
    if not cmd and not os.path.isfile("living/tools/seed_fresh.py"):
        done.append(f"attempt {attempt}: no seed freshness check in this tree; skipped")
        return None
    cmd = cmd or f"{shlex.quote(sys.executable)} living/tools/scene_gate.py seeds"
    code, secs = run_check(cmd, log_path, "seeds")
    if code == 0:
        done.append(f"attempt {attempt}: compiled seeds fresh (or listed red on main) in {secs:.1f} s")
        return None
    done.append(f"attempt {attempt}: merge {merge_sha[:10]}; compiled seeds STALE (exit {code}); the lines above name each seed, block and recompile command")
    restored = reset_to(start_head, "after the stale seeds")
    summary(f"stale compiled seeds; nothing pushed{'' if restored else ' (HEAD NOT restored, see above)'}. Recompile them on the branch (log {log_path})")
    return 13


def genesis_summary(record):
    """The gate's genesis fuel per seed in one line (scene_gate.py, docs/TOOLING.md "Genesis fuel")."""
    if record.get("genesis_disabled"):
        return "genesis fuel check disabled (SLOP_GATE_GENESIS_CHECK=0)"
    seeds = []
    for g in record.get("genesis") or []:
        fuel = g.get("init_fuel")
        share = f"{fuel / 1e9:.3f}e9, {100 * fuel / g['budget']:.2f}%" if fuel is not None and g.get("budget") else "no fuel"
        steps = f", largest step {g['largest_step_share']:.2%}" if g.get("steps") else ""
        seeds.append(f"{g.get('seed')} {share}{steps} {'pass' if g.get('passed') else 'FAIL'}")
    return f"genesis init fuel per run: {'; '.join(seeds)}" if seeds else None


def scene_gate(merge_sha, base, gate_base, gate_json, log_path, start_head, attempt):
    """Run the scene gate on the checked merge; None when it passed (or was not needed this
    attempt), else the exit code after the summary."""
    tool = "living/tools/scene_gate.py"
    cmd = os.environ.get("LIVING_MERGE_SCENES_CMD")
    if not cmd and not os.path.isfile(tool):
        done.append(f"attempt {attempt}: no scene gate in this tree ({tool}); scenes not run")
        return None
    if gate_base and not cmd:
        # main moved since the gate passed: run it again only when the new main commits touch
        # behaviour (each came through its own gate when they did not touch it together)
        t = subprocess.run([sys.executable, tool, "touches", "--base", gate_base, "--head", base], capture_output=True, text=True)
        if t.returncode == 1:
            done.append(f"attempt {attempt}: scene gate kept from {gate_base[:10]} (main's new commits touch no behaviour)")
            return None
    cmd = cmd or f"{shlex.quote(sys.executable)} {tool} run --base {base} --json {shlex.quote(gate_json)}"
    os.environ["LIVING_MERGE_GATE_JSON"] = gate_json  # where the gate's record goes (a LIVING_MERGE_SCENES_CMD writes it there)
    try:
        os.remove(gate_json)  # an earlier attempt's record is not this run's
    except FileNotFoundError:
        pass
    code, secs = run_check(cmd, log_path, "scenes")
    record = {}
    try:
        with open(gate_json) as f:
            record = json.load(f)
    except (OSError, ValueError):
        pass
    fuel = genesis_summary(record)
    if fuel:
        done.append(f"attempt {attempt}: {fuel}")
    if code == 0:
        done.append(f"attempt {attempt}: scene gate {record.get('result', 'passed')} in {secs:.0f} s"
                    + (f" (evidence {record['evidence']})" if record.get("evidence") else ""))
        after = git("status", "--porcelain", "--untracked-files=all", quiet=True).stdout
        if out("rev-parse", "HEAD") != merge_sha or after.strip():
            print(after.rstrip())
            done.append(f"attempt {attempt}: the scene gate changed HEAD or the worktree (above)")
            summary("the scene gate changed the worktree; nothing pushed; HEAD left for a look")
            return 6
        return None
    done.append(f"attempt {attempt}: merge {merge_sha[:10]}; scene gate {record.get('result') or 'FAILED'} (exit {code}) after {secs:.0f} s"
                + (f"; evidence {record['evidence']}" if record.get("evidence") else ""))
    restored = reset_to(start_head, "after the failed scene gate")
    summary(f"scene gate failed; nothing pushed{'' if restored else ' (HEAD NOT restored, see above)'}. Inspect the merge with: "
            f"git checkout --detach {merge_sha[:10]}  (log {log_path})")
    return 10


def main(argv):
    try:
        return run(argv)
    except GitError as e:
        say(str(e))
        summary(f"stopped: {e}; HEAD is {git('rev-parse', 'HEAD', check=False, quiet=True).stdout.strip()[:10]}; nothing more was pushed")
        return 9


def run(argv):
    branch, message, retries, push, remote, into = None, None, 5, True, "origin", "main"
    scenes = os.environ.get("LIVING_MERGE_SCENES") == "1"
    args = list(argv)
    try:
        while args:
            a = args.pop(0)
            if a == "-m":
                message = args.pop(0)
            elif a == "--retries":
                retries = int(args.pop(0))
            elif a == "--no-push":
                push = False
            elif a == "--scenes":
                scenes = True
            elif a == "--remote":
                remote = args.pop(0)
            elif a == "--into":
                into = args.pop(0)
            elif a in ("-h", "--help"):
                print(__doc__)
                return 0
            elif a.startswith("-") or branch:
                raise ValueError(a)
            else:
                branch = a
        if not branch:
            raise ValueError("no branch")
    except (ValueError, IndexError) as e:
        print(f"usage error ({e})\n{__doc__}", file=sys.stderr)
        return 2
    t_start = time.time()
    budget = disk_budget()
    root = out("rev-parse", "--show-toplevel")
    os.chdir(root)
    real = os.path.realpath(root)
    if any(real == os.path.realpath(p) for p in PROTECTED):
        refuse(3, f"{root} is the owner's checkout; merge from a coordinator worktree")
    os.makedirs(STATE, exist_ok=True)
    lock = open(os.path.join(STATE, hashlib.sha1(real.encode()).hexdigest()[:16] + ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        refuse(3, f"another living-merge is running in {root}")
    dirty = git("status", "--porcelain", "--untracked-files=all", quiet=True).stdout
    if dirty.strip():
        print(dirty.rstrip())
        refuse(3, "the worktree is not clean (above); commit or move these changes first")
    gitdir = out("rev-parse", "--git-dir")
    for f in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
        if os.path.exists(os.path.join(gitdir, f)):
            refuse(3, f"a {f} is in progress in this worktree")
    current = git("symbolic-ref", "-q", "--short", "HEAD", check=False, quiet=True).stdout.strip() or None
    if current == into:
        refuse(3, f"this worktree has {into} checked out; run from a worktree on another branch or a detached HEAD")
    gate_server_alive(scenes)
    if budget is not None:
        problem = check_disk(root, budget, scenes)
        if problem:
            refuse(DISK_REFUSED, problem)
    into_ref = f"refs/remotes/{remote}/{into}"
    git("fetch", remote, f"+refs/heads/{into}:{into_ref}")
    if branch.startswith(f"{remote}/"):
        branch = branch[len(remote) + 1:]
    branch_ref = f"refs/remotes/{remote}/{branch}"
    lr = git("ls-remote", "--exit-code", remote, f"refs/heads/{branch}", check=False)
    if lr.returncode == 0:
        git("fetch", remote, f"+refs/heads/{branch}:{branch_ref}")
    elif lr.returncode == 2:
        branch_ref = None  # not on the remote: a local branch or a commit
    else:
        print(lr.stdout.rstrip())
        refuse(9, f"could not ask {remote} for {branch} (above)")
    for cand in ([branch_ref] if branch_ref else []) + [f"refs/heads/{branch}", branch]:
        if ok("rev-parse", "--verify", "-q", f"{cand}^{{commit}}"):
            branch_ref = cand
            break
    else:
        refuse(2, f"no branch or commit named {branch} (on {remote} or here)")
    branch_sha = out("rev-parse", f"{branch_ref}^{{commit}}")
    if not branch_ref.startswith(f"refs/remotes/{remote}/"):
        say(f"note: {branch} is not on {remote}; merging the local {branch_ref} ({branch_sha[:10]})")
    elif ok("rev-parse", "--verify", "-q", f"refs/heads/{branch}") and out("rev-parse", f"refs/heads/{branch}") != branch_sha:
        say(f"note: the local branch {branch} differs from {remote}/{branch}; merging {remote}'s {branch_sha[:10]}")
    done.append(f"branch {branch} = {branch_sha[:10]} ({branch_ref})")
    base = out("rev-parse", into_ref)
    start_head = out("rev-parse", "HEAD")
    ahead = out("rev-list", "--oneline", f"{base}..HEAD")
    if ahead:
        print(ahead)
        refuse(3, f"HEAD has commits that {remote}/{into} lacks (above); push or drop them before merging")
    if ok("merge-base", "--is-ancestor", branch_sha, base):
        say(f"{branch} ({branch_sha[:10]}) is already in {remote}/{into} ({base[:10]}); nothing to do")
        summary("nothing to merge")
        return 0
    message = message or f"Merge {branch}"
    log_path = os.path.join(STATE, time.strftime("%Y%m%d-%H%M%S") + f"-{branch.replace('/', '_')}.log")
    check_override = os.environ.get("LIVING_MERGE_CHECK")
    gate_json = log_path[:-4] + "-scenes.json"
    gate_base = None  # the main the scene gate last passed on
    attempt = 0
    while True:
        if attempt:
            gate_server_alive(scenes)
        if attempt and budget is not None:
            problem = check_disk(root, budget, scenes)
            if problem:
                reset_to(start_head, "after the disk refusal")
                refuse(DISK_REFUSED, problem)
        attempt += 1
        say(f"attempt {attempt}: merge {branch_sha[:10]} onto {remote}/{into} {base[:10]}")
        git("reset", "--keep", base)
        if ok("merge-base", "--is-ancestor", branch_sha, base):
            done.append(f"{branch_sha[:10]} is already in {remote}/{into} {base[:10]} (merged meanwhile)")
            summary(f"nothing to push: {branch} was merged into {into} by someone else meanwhile")
            return 0
        r = git("merge", "--no-ff", "--no-edit", "-m", message, branch_sha, check=False)
        print(r.stdout.rstrip(), flush=True)
        if r.returncode != 0:
            conflicts = out("diff", "--name-only", "--diff-filter=U")
            ab = git("merge", "--abort", check=False)
            if ab.returncode != 0 and os.path.exists(os.path.join(gitdir, "MERGE_HEAD")):
                print(ab.stdout.rstrip())
                done.append("git merge --abort failed (above)")
            restored = reset_to(start_head, "after the failed merge")
            state = "HEAD restored" if restored else "HEAD NOT restored, see above"
            if conflicts:
                done.append(f"attempt {attempt}: merge onto {base[:10]} conflicted in: {conflicts.replace(chr(10), ', ')}")
                summary(f"merge conflict; nothing pushed; {state}")
                return 4
            done.append(f"attempt {attempt}: git merge failed without conflicts (above)")
            summary(f"git merge failed; nothing pushed; {state}")
            return 9
        merge_sha = out("rev-parse", "HEAD")
        if out("rev-list", "--parents", "-n", "1", merge_sha).split()[1:] != [base, branch_sha]:
            done.append(f"attempt {attempt}: git merge did not make a two-parent merge of {base[:10]} and {branch_sha[:10]}")
            restored = reset_to(start_head, "after the odd merge")
            summary(f"no merge commit was made; nothing pushed{'' if restored else '; HEAD NOT restored, see above'}")
            return 9
        fresh = seeds_check(merge_sha, log_path, start_head, attempt)
        if fresh is not None:
            return fresh
        # the merged tree's own check; a tree from before check.py has the plain recipe
        check_cmd = check_override or (f"{shlex.quote(sys.executable)} living/tools/check.py" if os.path.isfile("living/tools/check.py") else "just living-check")
        try:
            code, secs = run_check(check_cmd, log_path)
        except KeyboardInterrupt:
            done.append(f"attempt {attempt}: check of {merge_sha[:10]} interrupted")
            restored = reset_to(start_head, "after the interrupt")
            summary(f"interrupted; nothing pushed{'' if restored else '; HEAD NOT restored, see above'}")
            return 130
        if code != 0:
            done.append(f"attempt {attempt}: merge {merge_sha[:10]} onto {base[:10]}; check FAILED (exit {code}) after {secs:.0f} s")
            restored = reset_to(start_head, "after the failed check")
            summary(f"check failed; nothing pushed{'' if restored else ' (HEAD NOT restored, see above)'}. Inspect the merge with: git checkout --detach {merge_sha[:10]}  (log {log_path})")
            return 5
        after = git("status", "--porcelain", "--untracked-files=all", quiet=True).stdout
        if out("rev-parse", "HEAD") != merge_sha:
            done.append(f"attempt {attempt}: the check moved HEAD away from the merge {merge_sha[:10]}")
            summary("the check changed HEAD; nothing pushed")
            return 6
        if after.strip():
            print(after.rstrip())
            done.append(f"attempt {attempt}: merge {merge_sha[:10]}; check passed in {secs:.0f} s but changed the worktree (above)")
            summary("the check changed tracked or untracked files; nothing pushed; HEAD left at the merge for a look")
            return 6
        done.append(f"attempt {attempt}: merge {merge_sha[:10]} onto {base[:10]}; check passed in {secs:.0f} s")
        bind = bindings_check(merge_sha, base, log_path, start_head, attempt)
        if bind is not None:
            return bind
        if scenes:
            gate = scene_gate(merge_sha, base, gate_base, gate_json, log_path, start_head, attempt)
            if gate is not None:
                return gate
            gate_base = base
        if not push:
            summary(f"checked, not pushed (--no-push); HEAD is the merge {merge_sha[:10]}")
            return 0
        r = git("push", "--porcelain", f"--force-with-lease=refs/heads/{into}:{base}", remote, f"{merge_sha}:refs/heads/{into}", check=False)
        print(r.stdout.rstrip(), flush=True)
        if r.returncode == 0:
            done.append(f"pushed {merge_sha[:10]} to {remote}/{into}")
            if scenes and os.path.isfile(gate_json) and into == "main":
                # the merge is main now: cases that passed in its gate leave the red-on-main list
                subprocess.run([sys.executable, "living/tools/scene_gate.py", "settle", "--record", gate_json, "--main", merge_sha])
            summary(f"merged {branch} into {into} as {merge_sha[:10]} in {time.time() - t_start:.0f} s ({attempt} attempt{'s' if attempt > 1 else ''})")
            return 0
        # judge by state, not by message: where is the remote main now?
        tip = remote_tip(remote, f"refs/heads/{into}")
        if tip == merge_sha:
            done.append(f"pushed {merge_sha[:10]} to {remote}/{into} (git push reported an error, but the remote has it)")
            summary(f"merged {branch} into {into} as {merge_sha[:10]}")
            return 0
        if tip is None or tip == base:
            done.append(f"push of {merge_sha[:10]} failed (not because {into} moved)")
            summary(f"push failed; HEAD is the checked merge {merge_sha[:10]}; push it only onto the main it was checked on with: "
                    f"git push --force-with-lease=refs/heads/{into}:{base} {remote} {merge_sha}:refs/heads/{into}")
            return 8
        if attempt > retries:
            done.append(f"push refused: {into} moved again; {retries} retries used")
            summary(f"gave up after {attempt} attempts; HEAD is the checked merge {merge_sha[:10]}")
            return 7
        done.append(f"push refused: {remote}/{into} moved; merging again")
        git("fetch", remote, f"+refs/heads/{into}:{into_ref}")
        base = out("rev-parse", into_ref)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
