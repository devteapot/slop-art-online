#!/usr/bin/env python3
"""Self-test of living/tools/disk_clean.py in a throwaway home (docs/TOOLING.md, "Disk").

Builds a fake HOME with a repository, worktrees and fake Cargo target folders aged by
setting their times, then runs disk_clean.py (dry run, then --apply) and checks what went:
a merged worktree's idle target goes; a target a process works in, a fresh worktree on
main's line, a protected checkout, an untagged evidence folder, a folder with a foreign
CACHEDIR.TAG, a symlink and a nested repository stay; a target holding a log keeps the log.
Touches nothing outside the temporary directory. Usage: disk_clean_selftest.py
"""
import os
import subprocess
import sys
import tempfile
import time

CLEAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disk_clean.py")
SIG = "Signature: 8a477f597d28d172789f06886806bc55\n# This file is a cache directory tag created by cargo.\n"
failures = []


def sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd}: {r.stdout}")
    return r.stdout


def target(path, foreign=None, tag=SIG):
    os.makedirs(os.path.join(path, "debug", "deps"), exist_ok=True)
    with open(os.path.join(path, "CACHEDIR.TAG"), "w") as f:
        f.write(tag)
    if tag == SIG:
        open(os.path.join(path, ".rustc_info.json"), "w").write("{}")
        open(os.path.join(path, "debug", ".cargo-lock"), "w").close()
    with open(os.path.join(path, "debug", "deps", "libbig.rlib"), "wb") as f:
        f.write(os.urandom(200_000))
    for name in foreign or []:
        open(os.path.join(path, name), "w").write("evidence\n")


def age(path, hours):
    t = time.time() - hours * 3600
    for d, dirs, files in os.walk(path):
        for x in dirs + files:
            os.utime(os.path.join(d, x), (t, t), follow_symlinks=False)
    os.utime(path, (t, t))


def expect(name, cond, out=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        print(out)


def main():
    with tempfile.TemporaryDirectory(prefix="disk-selftest-") as home:
        env = {**os.environ, "HOME": home, "XDG_STATE_HOME": os.path.join(home, "state"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}  # no podman/docker in PATH
        os.environ.update({k: v for k, v in env.items() if k.startswith("GIT_")})
        origin = os.path.join(home, "origin.git")
        repo = os.path.join(home, "dev", "slop-art-online")
        os.makedirs(os.path.dirname(repo))
        sh(f"git init -q --bare -b main {origin} && git clone -q {origin} {repo}", home)
        sh("echo a > a && git add a && git commit -qm base && git push -q origin HEAD:main", repo)
        wts = os.path.join(home, "wt")
        # merged: a branch with a commit, merged --no-ff into main
        sh(f"git worktree add -q -b done {wts}/done origin/main", repo)
        sh("echo d > d && git add d && git commit -qm done && git push -q origin done", f"{wts}/done")
        sh("git fetch -q && git merge -q --no-ff -m 'Merge done' origin/done && git push -q origin HEAD:main && git fetch -q", repo)
        # busy: merged too, but a process works inside its target
        sh(f"git worktree add -q -b busy {wts}/busy origin/main", repo)
        sh("echo b > b && git add b && git commit -qm busy && git push -q origin busy", f"{wts}/busy")
        sh("git merge -q --no-ff -m 'Merge busy' origin/busy && git push -q origin HEAD:main && git fetch -q", repo)
        # fresh: a worktree sitting on main's own line, no commits of its own
        sh(f"git fetch -q && git worktree add -q -b fresh {wts}/fresh origin/main", repo)
        # old: an unmerged branch idle for two days, its target holds a log
        sh(f"git worktree add -q -b old {wts}/old origin/main", repo)
        sh("echo o > o && git add o && git commit -qm old", f"{wts}/old")
        # protected: ~/dev/slop-game as a worktree
        sh(f"git worktree add -q -b game {home}/dev/slop-game origin/main", repo)
        for w in ("done", "busy", "fresh", "old"):
            target(f"{wts}/{w}/.local/t", foreign=["build.log"] if w == "old" else None)
        target(f"{home}/dev/slop-game/living/target")
        target(f"{repo}/living/target")
        os.makedirs(f"{wts}/done/.local/evidence/run1")
        open(f"{wts}/done/.local/evidence/run1/journal.jsonl", "w").write("{}\n")
        target(f"{wts}/done/.local/notcargo", tag="Signature: 8a477f597d28d172789f06886806bc55\n# made by another tool\n")
        os.symlink(f"{wts}/old/.local/t", f"{wts}/done/.local/link-to-target")
        nested = f"{wts}/done/.local/nested"
        sh(f"git init -q {nested}", home)
        target(f"{nested}/target")
        for w in ("done", "busy", "fresh"):
            age(f"{wts}/{w}/.local", 3)
        age(f"{wts}/old/.local", 50)
        idx = sh("git rev-parse --absolute-git-dir", f"{wts}/old").strip()
        for f in ("index", "logs/HEAD", "HEAD"):
            p = os.path.join(idx, f)
            if os.path.exists(p):
                t = time.time() - 50 * 3600
                os.utime(p, (t, t))
        age(f"{home}/dev/slop-game/living/target", 100)
        age(nested, 100)
        busy = subprocess.Popen(["sleep", "300"], cwd=f"{wts}/busy/.local/t/debug")
        try:
            dry = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--floor-gb", "0", "--target-gb", "0"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            expect("dry run removes nothing", all(os.path.isdir(f"{wts}/{w}/.local/t/debug") for w in ("done", "busy", "fresh", "old")), dry)
            out = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "0"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        finally:
            busy.kill()
        expect("merged and idle: removed", not os.path.exists(f"{wts}/done/.local/t"), out)
        expect("a process inside: kept", os.path.isdir(f"{wts}/busy/.local/t/debug") and "in use" in out, out)
        expect("fresh worktree on main's line: kept", os.path.isdir(f"{wts}/fresh/.local/t/debug"), out)
        expect("idle 50 h with a log: Cargo entries gone, the log kept", not os.path.exists(f"{wts}/old/.local/t/debug") and os.path.isfile(f"{wts}/old/.local/t/build.log"), out)
        expect("protected checkout: never", os.path.isdir(f"{home}/dev/slop-game/living/target/debug") and "never" in out, out)
        expect("the repository's own checkout: never", os.path.isdir(f"{repo}/living/target/debug"), out)
        expect("evidence without a tag: untouched", os.path.isfile(f"{wts}/done/.local/evidence/run1/journal.jsonl"), out)
        expect("a tag not made by Cargo: untouched", os.path.isdir(f"{wts}/done/.local/notcargo/debug"), out)
        expect("a symlink: untouched", os.path.islink(f"{wts}/done/.local/link-to-target"), out)
        expect("a nested repository: untouched", os.path.isdir(f"{nested}/target/debug"), out)
        expect("no aside folders left", not any(".slop-reclaim-" in d for _, ds, _ in os.walk(home) for d in ds), out)
        expect("report written", os.listdir(os.path.join(home, "state", "slop-disk", "reports")), out)
        print(out)
    print("disk_clean_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
