#!/usr/bin/env python3
"""Self-test of living/tools/merge.py against a throwaway remote (docs/TOOLING.md).

Builds a bare "origin" and clones under a temporary directory, then drives merge.py through:
a dirty worktree (refused), local commits main lacks (refused), a conflict (nothing pushed),
a failing check (nothing pushed), a check that dirties the tree (nothing pushed), main moving
during the check (re-fetch, re-merge, re-check, push) and a clean merge (--no-ff, pushed).
Touches nothing outside the temporary directory. Usage: merge_selftest.py
"""
import os
import subprocess
import sys
import tempfile

MERGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merge.py")
failures = []


def sh(cmd, cwd, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    if check and r.returncode:
        raise RuntimeError(f"{cmd} in {cwd}: {r.stdout}")
    return r.stdout


def commit(repo, path, text, msg):
    with open(os.path.join(repo, path), "w") as f:
        f.write(text)
    sh(f"git add -A && git commit -qm {msg!r}", repo)


def merge(cwd, args, check_cmd="true", env_extra=None):
    env = {**os.environ, "LIVING_MERGE_CHECK": check_cmd, "XDG_STATE_HOME": os.path.join(os.path.dirname(cwd), "state"), **(env_extra or {})}
    r = subprocess.run([sys.executable, MERGE, *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    return r.returncode, r.stdout


def expect(name, cond, output=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        print(output)


def main():
    with tempfile.TemporaryDirectory(prefix="merge-selftest-") as t:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        os.environ.update({k: v for k, v in env.items() if k.startswith("GIT_")})
        origin = os.path.join(t, "origin.git")
        sh(f"git init -q --bare -b main {origin}", t)
        seed = os.path.join(t, "seed")
        sh(f"git clone -q {origin} seed", t)
        commit(seed, "a.txt", "a\n", "base")
        sh("git push -q origin HEAD:main", seed)
        # a feature branch and a conflicting branch
        sh("git switch -qc feature", seed)
        commit(seed, "f.txt", "feature\n", "feature work")
        sh("git push -q origin feature", seed)
        sh("git switch -q main && git switch -qc clash", seed)
        commit(seed, "a.txt", "clash\n", "clash work")
        sh("git push -q origin clash", seed)
        sh("git switch -q main", seed)
        commit(seed, "a.txt", "main moved\n", "main edits a")
        sh("git push -q origin HEAD:main", seed)

        coord = os.path.join(t, "coord")
        sh(f"git clone -q {origin} coord", t)
        sh("git switch -qc coord", coord)

        # 1. dirty worktree refused
        with open(os.path.join(coord, "stray.txt"), "w") as f:
            f.write("x")
        code, o = merge(coord, ["feature"])
        expect("dirty worktree refused (exit 3)", code == 3 and "not clean" in o, o)
        os.remove(os.path.join(coord, "stray.txt"))

        # 2. local commits that main lacks refused
        commit(coord, "local.txt", "l\n", "local only")
        code, o = merge(coord, ["feature"])
        expect("local commits refused (exit 3)", code == 3 and "lacks" in o, o)
        sh("git reset -q --hard HEAD~1", coord)

        # 3. conflict: nothing pushed, HEAD restored
        before = sh(f"git --git-dir={origin} rev-parse main", t).strip()
        head0 = sh("git rev-parse HEAD", coord).strip()
        code, o = merge(coord, ["clash"])
        expect("conflict stops (exit 4)", code == 4 and "a.txt" in o, o)
        expect("conflict pushed nothing", sh(f"git --git-dir={origin} rev-parse main", t).strip() == before)
        expect("conflict restored HEAD and left it clean", sh("git rev-parse HEAD", coord).strip() == head0 and not sh("git status --porcelain", coord).strip())

        # 4. failing check: nothing pushed
        code, o = merge(coord, ["feature"], check_cmd="echo boom; false")
        expect("failing check stops (exit 5)", code == 5 and "boom" in o, o)
        expect("failing check pushed nothing", sh(f"git --git-dir={origin} rev-parse main", t).strip() == before)

        # 5. a check that leaves the tree dirty: nothing pushed
        code, o = merge(coord, ["feature"], check_cmd="echo x > made-by-check.txt")
        expect("dirtying check stops (exit 6)", code == 6, o)
        expect("dirtying check pushed nothing", sh(f"git --git-dir={origin} rev-parse main", t).strip() == before)
        os.remove(os.path.join(coord, "made-by-check.txt"))
        sh(f"git reset -q --keep {head0}", coord)

        # 6. main moves while the first check runs: re-fetch, re-merge, re-check, push
        mover = os.path.join(t, "mover")
        sh(f"git clone -q {origin} mover", t)
        flag = os.path.join(t, "moved.flag")
        racer = (f"n=$(cat {t}/checks 2>/dev/null || echo 0); echo $((n+1)) > {t}/checks; "
                 f"if [ ! -e {flag} ]; then touch {flag}; cd {mover} && echo b > b.txt && git add b.txt && git commit -qm 'main moves' && git push -q origin HEAD:main; fi")
        code, o = merge(coord, ["feature", "-m", "Merge feature: the test"], check_cmd=racer)
        checks = int(open(os.path.join(t, "checks")).read())
        expect("moved main: merged after a retry (exit 0)", code == 0 and "merging again" in o and checks == 2, o)
        head = sh(f"git --git-dir={origin} log -1 --format=%P%n%s main", t).split("\n")
        parents = head[0].split()
        expect("pushed a --no-ff merge with two parents and the message", len(parents) == 2 and head[1] == "Merge feature: the test", o)
        feature = sh(f"git --git-dir={origin} rev-parse feature", t).strip()
        mover_head = sh("git rev-parse HEAD", mover).strip()
        expect("the merge sits on the moved main and has the branch", parents[0] == mover_head and parents[1] == feature, o)

        # 7. already merged: nothing to do
        code, o = merge(coord, ["feature"])
        expect("already merged is a no-op (exit 0)", code == 0 and "nothing to do" in o, o)

        # 8. a clean merge with no race; the worktree branch ends at the pushed merge
        sh("git switch -qc second origin/main", seed)
        sh("git pull -q origin main", seed)
        commit(seed, "s.txt", "s\n", "second work")
        sh("git push -q origin second", seed)
        code, o = merge(coord, ["second"])
        main_sha = sh(f"git --git-dir={origin} rev-parse main", t).strip()
        expect("clean merge pushed (exit 0)", code == 0 and sh("git rev-parse HEAD", coord).strip() == main_sha, o)
        expect("summary printed", "summary:" in o and "pushed" in o, o)

        # 9. main is rewound while the check runs: the lease refuses, it merges onto the rewound main
        sh("git fetch -q origin && git switch -qc third origin/main", seed)
        commit(seed, "t.txt", "t\n", "third work")
        sh("git push -q origin third", seed)
        sh("git fetch -q origin && git reset -q --hard origin/main", mover)
        rewound = sh("git rev-parse HEAD~1", mover).strip()
        flag2 = os.path.join(t, "rewound.flag")
        rewinder = f"if [ ! -e {flag2} ]; then touch {flag2}; cd {mover} && git push -q --force origin {rewound}:main; fi"
        code, o = merge(coord, ["third"], check_cmd=rewinder)
        parents = sh(f"git --git-dir={origin} log -1 --format=%P main", t).split()
        expect("rewound main: merged again onto the rewound main (exit 0)", code == 0 and "merging again" in o and parents[0] == rewound, o)

        # 10. someone else merges the branch while the check runs: nothing to push
        sh("git fetch -q origin && git switch -qc fourth origin/main", seed)
        commit(seed, "u.txt", "u\n", "fourth work")
        sh("git push -q origin fourth", seed)
        flag3 = os.path.join(t, "other.flag")
        other = (f"if [ ! -e {flag3} ]; then touch {flag3}; cd {mover} && git fetch -q origin && git reset -q --hard origin/main && "
                 f"git merge -q --no-ff -m other origin/fourth && git push -q origin HEAD:main; fi")
        before = sh(f"git --git-dir={origin} rev-parse main", t).strip()
        code, o = merge(coord, ["fourth"], check_cmd=other)
        after = sh(f"git --git-dir={origin} rev-parse main", t).strip()
        expect("merged meanwhile by someone else: exit 0, nothing pushed over it", code == 0 and "merged into main by someone else" in o
               and after != before and sh(f"git --git-dir={origin} log -1 --format=%s main", t).strip() == "other", o)

        # 11. --scenes: a failing scene gate stops the push (exit 10), a passing one pushes
        sh("git fetch -q origin && git switch -qc fifth origin/main", seed)
        commit(seed, "v.txt", "v\n", "fifth work")
        sh("git push -q origin fifth", seed)
        before = sh(f"git --git-dir={origin} rev-parse main", t).strip()
        code, o = merge(coord, ["fifth", "--scenes"], env_extra={"LIVING_MERGE_SCENES_CMD": "echo scene-gate: FAILED dealings; exit 1"})
        expect("failing scene gate stops (exit 10), nothing pushed", code == 10 and "scene gate failed" in o
               and sh(f"git --git-dir={origin} rev-parse main", t).strip() == before, o)
        code, o = merge(coord, ["fifth", "--scenes"], env_extra={"LIVING_MERGE_SCENES_CMD": "echo scene-gate: passed"})
        expect("passing scene gate pushes (exit 0)", code == 0 and "scene gate passed" in o
               and sh(f"git --git-dir={origin} rev-parse main", t).strip() != before, o)

        # 12. a branch that is on neither the remote nor here
        code, o = merge(coord, ["no-such-branch"])
        expect("unknown branch refused (exit 2)", code == 2, o)
    print("merge_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
