#!/usr/bin/env python3
"""Self-test of living/tools/merge.py against a throwaway remote (docs/TOOLING.md).

Builds a bare "origin" and clones under a temporary directory, then drives merge.py through:
a dirty worktree (refused), local commits main lacks (refused), a conflict (nothing pushed),
a failing check (nothing pushed), a check that dirties the tree (nothing pushed), main moving
during the check (re-fetch, re-merge, re-check, push), a clean merge (--no-ff, pushed), and the
bindings check with a fake generator (changed bindings fail and are named, a failing generator
fails, unchanged bindings pass, a docs-only merge skips it). A fake df exercises the disk
pre-check at its boundary, on a separate target filesystem, with cold and warm targets, on retry, and with the overrides.
Touches nothing outside the temporary directory. Usage: merge_selftest.py
"""
import json
import os
from pathlib import Path
import plistlib
import shlex
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
    env = dict(os.environ)
    for key in ("CARGO_BUILD_TARGET_DIR", "SLOP_MERGE_FLOOR_GB", "SLOP_MERGE_CHECK_GB",
                "SLOP_MERGE_DISK_CHECK", "LIVING_MERGE_SCENES", "LIVING_MERGE_SCENES_CMD",
                "LIVING_MERGE_BINDINGS", "LIVING_MERGE_BINDINGS_CMD", "FAKE_DF_PRESSURE_FLAG"):
        env.pop(key, None)
    base = Path(cwd).parent
    env.update(HOME=str(base), XDG_CONFIG_HOME=str(base / ".config"), XDG_STATE_HOME=str(base / "state"),
               PATH=f"{base / 'bin'}{os.pathsep}{env['PATH']}", LIVING_MERGE_CHECK=check_cmd,
               CARGO_TARGET_DIR=str(base / "target-volume" / "new" / "target"),
               FAKE_DF_WORKTREE_GB="100", FAKE_DF_TARGET_GB="100")
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, MERGE, *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    return r.returncode, r.stdout


def expect(name, cond, output=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        print(output)


def disk_selftest(t, coord):
    fake_df = Path(t) / "bin/df"
    fake_df.parent.mkdir()
    (Path(t) / "target-volume").mkdir()
    fake_df.write_text("""#!/bin/sh
[ "$1" = -Pk ] || exit 1
case "$2" in
  */target-volume|*/target-volume/new/target) device=target; free=$FAKE_DF_TARGET_GB ;;
  */coord) device=worktree; free=$FAKE_DF_WORKTREE_GB ;;
  *) exit 1 ;;
esac
[ "$free" != error ] || exit 1
[ ! -f "$FAKE_DF_PRESSURE_FLAG" ] || free=${FAKE_DF_PRESSURE_GB:-1}
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
blocks=$(awk -v free="$free" 'BEGIN { printf "%.0f", free * 1048576 }')
echo "$device 104857600 0 $blocks 0% $2"
""")
    fake_df.chmod(0o755)
    fake_du = fake_df.with_name("du")
    fake_du.write_text("""#!/bin/sh
[ "$1" = -sk ] && [ -f "$2/size-kib" ] || exit 1
printf '%s\\t%s\\n' "$(cat "$2/size-kib")" "$2"
""")
    fake_du.chmod(0o755)
    fake_docker = fake_df.with_name("docker")
    fake_docker.write_text("""#!/bin/sh
[ "$1" = exec ] && [ "$6" = -Pk ] && [ "$7" = /home/spacetime ] || exit 1
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "$FAKE_SCENE_DEVICE 104857600 0 66060288 0% /home/spacetime"
""")
    fake_docker.chmod(0o755)
    head = sh("git rev-parse HEAD", coord)

    def probe(**env):
        # Stop after reaching the check so every case starts from the same clean HEAD.
        return merge(coord, ["feature"], check_cmd="echo reached-check; exit 1", env_extra=env)

    code, o = probe(FAKE_DF_WORKTREE_GB="62")
    expect("disk below default threshold refuses before fetch or check (exit 12)",
           code == 12 and "62.00 GB free; need 63 GB (45 GB floor + 18 GB check)" in o
           and "minus 0.00 GB already in Cargo target" in o and "$ git fetch" not in o and "reached-check" not in o and sh("git rev-parse HEAD", coord) == head, o)
    for free in ("63", "64"):
        code, o = probe(FAKE_DF_WORKTREE_GB=free, FAKE_DF_TARGET_GB=free)
        expect(f"disk with {free} GB reaches the check", code == 5 and "reached-check" in o, o)
    code, o = probe(FAKE_DF_TARGET_GB="62")
    expect("disk checks the target volume even when the target does not exist",
           code == 12 and "Cargo target" in o and "62.00 GB free" in o, o)
    code, o = probe(LIVING_MERGE_SCENES="1", FAKE_SCENE_DEVICE="target", FAKE_DF_TARGET_GB="63")
    expect("scenes add a reserve on the filesystem shared with the trial volume",
           code == 12 and "Cargo target" in o and "need 64 GB (45 GB floor + 18 GB check + 1 GB scenes)" in o, o)
    code, o = probe(LIVING_MERGE_SCENES="1", FAKE_SCENE_DEVICE="separate", FAKE_DF_TARGET_GB="63")
    expect("a separate trial volume leaves the host threshold unchanged", code == 5 and "reached-check" in o, o)
    code, o = probe(FAKE_DF_WORKTREE_GB="error")
    expect("a failed df refuses the merge (exit 12)", code == 12 and "could not determine free space" in o, o)

    target = Path(t) / "target-volume/new/target"
    target.mkdir(parents=True)
    size = target / "size-kib"
    size.write_text(str(10 * 1024 ** 2))
    code, o = probe(FAKE_DF_TARGET_GB="52")
    expect("warm target reduces the check allowance to 8 GB",
           code == 12 and "need 53 GB (45 GB floor + 8 GB check)" in o
           and "18 GB minus 10.00 GB already in Cargo target" in o, o)
    code, o = probe(FAKE_DF_WORKTREE_GB="53", FAKE_DF_TARGET_GB="53")
    expect("warm target reaches the check at the reduced threshold", code == 5 and "reached-check" in o, o)
    size.write_text(str(18 * 1024 ** 2))
    code, o = probe(FAKE_DF_TARGET_GB="46")
    expect("fully built target still needs the 2 GB minimum allowance",
           code == 12 and "need 47 GB (45 GB floor + 2 GB check)" in o
           and "18 GB minus 18.00 GB already in Cargo target" in o, o)
    size.unlink()
    target.rmdir()
    target.parent.rmdir()

    if sys.platform == "darwin":
        config = Path(t) / "Library/LaunchAgents/dev.slop.disk-clean.plist"
        config.parent.mkdir(parents=True)
        config.write_bytes(plistlib.dumps({"ProgramArguments": ["disk_clean.py", "--floor-gb", "60"]}))
    else:
        config = Path(t) / ".config/systemd/user/slop-disk-clean.service"
        config.parent.mkdir(parents=True)
        config.write_text("[Service]\nExecStart=python3 disk_clean.py --apply --floor-gb 60\n")
    code, o = probe(FAKE_DF_WORKTREE_GB="77")
    expect("disk uses the installed cleaner floor",
           code == 12 and "need 78 GB (60 GB floor + 18 GB check)" in o, o)
    code, o = probe(FAKE_DF_WORKTREE_GB="65", SLOP_MERGE_FLOOR_GB="48")
    expect("disk floor override takes precedence over installed floor",
           code == 12 and "need 66 GB (48 GB floor + 18 GB check)" in o, o)
    code, o = probe(FAKE_DF_TARGET_GB="80", SLOP_MERGE_CHECK_GB="21")
    expect("disk check cost override changes the threshold",
           code == 12 and "need 81 GB (60 GB floor + 21 GB check)" in o, o)
    code, o = probe(SLOP_MERGE_CHECK_GB="NaN")
    expect("disk rejects an invalid budget", code == 12 and "invalid floor or check cost" in o, o)
    code, o = probe(FAKE_DF_WORKTREE_GB="error", SLOP_MERGE_CHECK_GB="NaN", SLOP_MERGE_DISK_CHECK="0")
    expect("disabling disk check warns and reaches the check", code == 5 and "WARNING" in o and "reached-check" in o, o)


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
        disk_selftest(t, coord)

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
                 f"if [ ! -e {flag} ]; then touch {flag}; cd {mover} && echo b >> b.txt && git add b.txt && git commit -qm 'main moves' && git push -q origin HEAD:main; fi")
        pressure = os.path.join(t, "pressure.flag")
        code, o = merge(coord, ["feature"], check_cmd=f"{racer} && touch {pressure}",
                        env_extra={"FAKE_DF_PRESSURE_FLAG": pressure})
        expect("disk pressure on a retry restores HEAD and leaves the moved main in place (exit 12)",
               code == 12 and "merging again" in o and "1.00 GB free" in o
               and sh("git rev-parse HEAD", coord).strip() == head0
               and sh(f"git --git-dir={origin} rev-parse main", t) == sh("git rev-parse HEAD", mover), o)
        os.remove(flag)
        os.remove(os.path.join(t, "checks"))
        os.remove(pressure)
        warm_check = (f'{racer} && mkdir -p "$CARGO_TARGET_DIR" '
                      f'&& echo 18874368 > "$CARGO_TARGET_DIR/size-kib" && touch {pressure}')
        code, o = merge(coord, ["feature", "-m", "Merge feature: the test"], check_cmd=warm_check,
                        env_extra={"FAKE_DF_PRESSURE_FLAG": pressure, "FAKE_DF_PRESSURE_GB": "48.8",
                                   "SLOP_MERGE_FLOOR_GB": "45"})
        checks = int(open(os.path.join(t, "checks")).read())
        expect("moved main: retry succeeds at 48.8 GB after building an 18 GB target (exit 0)", code == 0 and "merging again" in o and checks == 2, o)
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
        # the gate's genesis fuel per seed is in the summary on a failure and on a pass
        record = json.dumps({"result": "failed genesis: island", "genesis": [
            {"seed": "island", "budget": 120000000000, "init_fuel": 118522397261.0, "passed": False},
            {"seed": "world", "budget": 120000000000, "init_fuel": 17300085371.0, "passed": True}]})
        code, o = merge(coord, ["fifth", "--scenes"], env_extra={"LIVING_MERGE_SCENES_CMD":
                        f"echo {shlex.quote(record)} > \"$LIVING_MERGE_GATE_JSON\"; echo scene-gate: FAILED genesis; exit 1"})
        expect("a failed genesis gate's fuel per seed is in the summary", code == 10
               and "genesis init fuel per run: island 118.522e9, 98.77% FAIL; world 17.300e9, 14.42% pass" in o, o)
        code, o = merge(coord, ["fifth", "--scenes"], env_extra={"LIVING_MERGE_SCENES_CMD": "echo scene-gate: passed"})
        expect("passing scene gate pushes (exit 0)", code == 0 and "scene gate passed" in o
               and sh(f"git --git-dir={origin} rev-parse main", t).strip() != before, o)

        # 12. a branch that is on neither the remote nor here
        code, o = merge(coord, ["no-such-branch"])
        expect("unknown branch refused (exit 2)", code == 2, o)

        # 13. the bindings check (a fake generator, LIVING_MERGE_BINDINGS_CMD): main holds
        # bindings; a branch touching the authority is regenerated, a docs branch is not
        gen = "living/bindings/src/generated"
        sh(f"git fetch -q origin && git switch -qc withbindings origin/main && mkdir -p {gen} living/authority/src docs", seed)
        commit(seed, f"{gen}/mod.rs", "// generated\n", "bindings on main")
        sh("git push -q origin HEAD:main", seed)
        sh("git switch -qc shape", seed)
        commit(seed, "living/authority/src/lib.rs", "// a new table\n", "shape work")
        sh("git push -q origin shape", seed)
        sh("git switch -q withbindings && git switch -qc docsonly", seed)
        commit(seed, "docs/NOTE.md", "a note\n", "docs work")
        sh("git push -q origin docsonly", seed)

        def main_tip():
            return sh(f"git --git-dir={origin} rev-parse main", t).strip()

        before = main_tip()
        code, o = merge(coord, ["shape"], env_extra={"LIVING_MERGE_BINDINGS_CMD": f"echo pub struct FightSeen; > {gen}/fight_seen.rs && echo // changed >> {gen}/mod.rs"})
        clean = not sh("git status --porcelain --untracked-files=all", coord).strip()
        expect("bindings that change fail the merge (exit 11), name the files, nothing pushed, worktree restored",
               code == 11 and "bindings not regenerated:" in o and f"{gen}/fight_seen.rs" in o and f"{gen}/mod.rs" in o
               and main_tip() == before and clean, o)
        code, o = merge(coord, ["shape"], env_extra={"LIVING_MERGE_BINDINGS_CMD": "echo living-generate: FAILED: container down >&2; exit 1"})
        expect("a failing generator fails the merge (exit 11: could not run), nothing pushed",
               code == 11 and "bindings check could not run" in o and main_tip() == before, o)
        code, o = merge(coord, ["shape"], env_extra={"LIVING_MERGE_BINDINGS_CMD": "true"})
        expect("unchanged bindings pass and push (exit 0)", code == 0 and "bindings regenerated from the merge" in o and main_tip() != before, o)
        before = main_tip()
        code, o = merge(coord, ["docsonly"], env_extra={"LIVING_MERGE_BINDINGS_CMD": "echo should not run; exit 1"})
        expect("a docs-only merge skips the bindings check and pushes", code == 0 and "bindings check skipped" in o
               and "should not run" not in o and main_tip() != before, o)
    print("merge_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
