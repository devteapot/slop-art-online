#!/usr/bin/env python3
"""Merge a branch into main the coordinators' way, end to end (docs/TOOLING.md).

In the current worktree, which must be clean and have no commits that main lacks:
  1. fetch; move HEAD to origin/main (git reset --keep);
  2. git merge --no-ff the branch, pinned to the commit it had when this started;
  3. run the check (`living/tools/check.py`: `just living-check` with step stamps), and
     stop without pushing if it fails or leaves the worktree dirty;
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
LIVING_MERGE_SCENES_CMD replaces the scene gate command (for tests).
Exit codes: 0 merged and pushed (or nothing to merge), 2 usage, 3 refused (worktree), 4 merge
conflict, 5 check failed, 6 check left the worktree dirty, 7 main kept moving, 8 push failed,
9 another git command failed, 10 the scene gate failed (or could not run).

The push is a compare-and-swap (--force-with-lease on the main it merged onto): it lands only
when main is still exactly the commit that was merged and checked, never over a main that
moved or was rewound meanwhile.
"""
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
# Checkouts this command never merges in: the owner's own.
PROTECTED = [os.path.join(HOME, "dev/slop-art-online")]
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state"), "slop-merge")
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
    code, secs = run_check(cmd, log_path, "scenes")
    record = {}
    try:
        with open(gate_json) as f:
            record = json.load(f)
    except (OSError, ValueError):
        pass
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
