#!/usr/bin/env python3
"""Self-test of living/tools/disk_clean.py in a throwaway home (docs/TOOLING.md, "Disk").

Builds a fake HOME with a repository, worktrees and fake Cargo target folders aged by
setting their times, then runs disk_clean.py (dry run, then --apply) and checks what went:
a merged worktree's idle target goes; a target a process works in, a fresh worktree on
main's line, a protected checkout, an untagged evidence folder, a folder with a foreign
CACHEDIR.TAG, a symlink and a nested repository stay; a target holding a log keeps the log.
The machine's protected paths: worktrees named in ~/.config/slop-disk/protect.txt or with
--protect, and a target holding a protected path, stay and are reported with their source;
an invalid protect file stops the run with nothing removed.
Touches nothing outside the temporary directory. Usage: disk_clean_selftest.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

CLEAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disk_clean.py")
SIG = "Signature: 8a477f597d28d172789f06886806bc55\n# This file is a cache directory tag created by cargo.\n"
failures = []

CONTAINERS = r"""
import json, platform, sys
sys.path.insert(0, sys.argv[1])
import disk_clean
platform.system = lambda: sys.argv[2]
srcs = disk_clean.container_mounts()
print(json.dumps({"srcs": srcs, "notes": disk_clean.NOTES, "warnings": disk_clean.WARNINGS}))
"""
NO_MACHINE = ("#!/bin/sh\ncase \"$1 $2\" in 'machine list') {machines}; exit 0 ;; esac\n"
              "echo 'Cannot connect to Podman. Please verify your connection to the Linux system using `podman system connection list`, "
              "or try `podman machine init` and `podman machine start` to manage a new Linux VM' >&2\nexit 125\n")
DOCKER_UP = "#!/bin/sh\nexit 0\n"
DOCKER_DOWN = "#!/bin/sh\necho 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?' >&2\nexit 1\n"


def containers(home, system, podman, docker):
    bin_ = os.path.join(home, "fakebin-" + str(len(os.listdir(home))))
    os.makedirs(bin_)
    for name, text in (("podman", podman), ("docker", docker)):
        if text is None:
            continue  # not installed
        with open(os.path.join(bin_, name), "w") as f:
            f.write(text)
        os.chmod(os.path.join(bin_, name), 0o755)
    r = subprocess.run([sys.executable, "-I", "-c", CONTAINERS, os.path.dirname(CLEAN), system], env={**os.environ, "HOME": home, "PATH": bin_},  # only the fakes
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": r.stdout}


def container_cases(home):
    r = containers(home, "Darwin", NO_MACHINE.format(machines="true"), None)
    expect("podman with no machine (macOS), no docker: a note, not a warning", not r.get("warnings") and any("no machine" in n for n in r.get("notes", [])), r)
    r = containers(home, "Darwin", NO_MACHINE.format(machines="echo podman-machine-default"), DOCKER_UP)
    expect("podman down but docker answers: a note, not a warning", not r.get("warnings") and any("docker answered" in n for n in r.get("notes", [])), r)
    r = containers(home, "Linux", NO_MACHINE.format(machines="true"), DOCKER_DOWN)
    expect("neither answers (Linux): still a warning", r.get("warnings") and not r.get("srcs"), r)


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
        # protected by this machine: merged worktrees named in the protect file and by --protect,
        # and a merged one whose target holds a protected path
        for w, where in (("trials", f"{home}/dev/slop-trials"), ("play", f"{home}/dev/slop-play"), ("holds", f"{wts}/holds")):
            sh(f"git fetch -q && git worktree add -q -b {w} {where} origin/main", repo)
            sh(f"echo {w} > {w} && git add {w} && git commit -qm {w} && git push -q origin {w}", where)
            sh(f"git fetch -q && git merge -q --no-ff -m 'Merge {w}' origin/{w} && git push -q origin HEAD:main && git fetch -q", repo)
            target(f"{where}/living/target")
            os.makedirs(f"{where}/living/target/release/keep-me")
            age(f"{where}/living/target", 50)
        os.makedirs(f"{home}/.config/slop-disk")
        with open(f"{home}/.config/slop-disk/protect.txt", "w") as f:
            f.write("# never touch these on this machine\n\n~/dev/slop-trials   # 14 GB, the trials\n"
                    f"{wts}/holds/living/target/release/keep-me\n")
        # a target with a file written "after" the scan started: idle 0.0 h, never negative
        sh(f"git worktree add -q -b now {wts}/now origin/main", repo)
        target(f"{wts}/now/.local/t")
        t = time.time() + 3600
        os.utime(f"{wts}/now/.local/t/debug/deps/libbig.rlib", (t, t))
        with open(f"{home}/bad-protect.txt", "w") as f:
            f.write("~/dev/slop-trials\ndev/slop-play\n")
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
        protect = ["--protect", "~/dev/slop-play"]  # expanded by disk_clean, not by a shell
        try:
            bad = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "0", "--protect-file", f"{home}/bad-protect.txt"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            expect("an invalid protect file: exit 2, nothing removed", bad.returncode == 2 and "line 2" in bad.stdout
                   and os.path.isdir(f"{wts}/done/.local/t/debug") and os.path.isdir(f"{home}/dev/slop-play/living/target/debug"), bad.stdout)
            listed = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--list-protected", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            expect("--list-protected: built-in, file and --protect paths with their sources",
                   "~/dev/slop-game  (built in)" in listed and "~/dev/slop-trials  (~/.config/slop-disk/protect.txt, line 3)" in listed
                   and "~/dev/slop-play  (--protect)" in listed, listed)
            dry = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--floor-gb", "0", "--target-gb", "0", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            expect("dry run removes nothing", all(os.path.isdir(f"{wts}/{w}/.local/t/debug") for w in ("done", "busy", "fresh", "old")), dry)
            out = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "0", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        finally:
            busy.kill()
        expect("merged and idle: removed", not os.path.exists(f"{wts}/done/.local/t"), out)
        expect("a process inside: kept", os.path.isdir(f"{wts}/busy/.local/t/debug") and "in use" in out, out)
        expect("fresh worktree on main's line: kept", os.path.isdir(f"{wts}/fresh/.local/t/debug"), out)
        expect("idle 50 h with a log: Cargo entries gone, the log kept", not os.path.exists(f"{wts}/old/.local/t/debug") and os.path.isfile(f"{wts}/old/.local/t/build.log"), out)
        expect("protected checkout: never", os.path.isdir(f"{home}/dev/slop-game/living/target/debug") and "never" in out, out)
        expect("the repository's own checkout: never", os.path.isdir(f"{repo}/living/target/debug"), out)
        expect("a worktree in the protect file: never, with its source", os.path.isdir(f"{home}/dev/slop-trials/living/target/debug")
               and "protected: ~/dev/slop-trials (~/.config/slop-disk/protect.txt, line 3)" in out, out)
        expect("a worktree given with --protect: never", os.path.isdir(f"{home}/dev/slop-play/living/target/debug") and "protected: ~/dev/slop-play (--protect)" in out, out)
        expect("a target holding a protected path: never", os.path.isdir(f"{wts}/holds/living/target/release/keep-me") and os.path.isdir(f"{wts}/holds/living/target/debug"), out)
        expect("the report lists the protected paths and the size method", "protected (never removed" in out and "\nsizes: " in out, out)
        expect("evidence without a tag: untouched", os.path.isfile(f"{wts}/done/.local/evidence/run1/journal.jsonl"), out)
        expect("a tag not made by Cargo: untouched", os.path.isdir(f"{wts}/done/.local/notcargo/debug"), out)
        expect("a symlink: untouched", os.path.islink(f"{wts}/done/.local/link-to-target"), out)
        expect("a nested repository: untouched", os.path.isdir(f"{nested}/target/debug"), out)
        expect("a file newer than the scan: idle 0.0 h, not negative", "active (idle 0.0 h)" in out and "-0.0" not in out, out)
        # pressure: free space is always under a huge target, so an applied run measures before
        # each removal and removes the idle folders under that rule (the fresh worktree's)
        hp = subprocess.run([sys.executable, CLEAN, "--repo", repo, "--floor-gb", "0", "--target-gb", "1000000", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        ha = subprocess.run([sys.executable, CLEAN, "--apply", "--repo", repo, "--floor-gb", "0", "--target-gb", "1000000", *protect], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        expect("pressure: projected in the dry run, measured before each removal when applied",
               "under pressure (free under 1000000 GB)" in hp and "under pressure (free measured at" in ha and not os.path.exists(f"{wts}/fresh/.local/t/debug")
               and os.path.isdir(f"{home}/dev/slop-trials/living/target/debug") and os.path.isdir(f"{wts}/now/.local/t/debug"), hp + ha)
        expect("no aside folders left", not any(".slop-reclaim-" in d for _, ds, _ in os.walk(home) for d in ds), out)
        expect("report written", os.listdir(os.path.join(home, "state", "slop-disk", "reports")), out)
        container_cases(home)
        print(out)
    print("disk_clean_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
