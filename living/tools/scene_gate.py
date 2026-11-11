#!/usr/bin/env python3
"""The merge's scene gate: a curated set of real scenes on scratch `verify-gate-*` databases
(docs/TOOLING.md, "Scene gate"; .agents/skills/verify/SKILL.md, "Scene gate").

`just living-check` builds and runs cargo tests; no scene runs against a live authority. A change
that moves bodies can pass it and still break a scene (fix-place-free, e3f0527f: verify-minds
`dealings` and verify-player combat staging went red on main). This gate runs, when a merge
touches behaviour, these cases with the fake model only:

  verify-core    tick, sight, senses, refusal (one default-seed world), skirmish (an island world)
  verify-minds   roundtrip, acts, dealings, conversation (each its own world, the real living-mind)
  verify-player  combat (combat.py --scene all: the staged fights, an island world)

The four worlds run at once. Flakes: a failing case runs again once, alone, on a fresh scratch
database; it fails the gate only when it fails twice. A case that failed twice is then judged on
main (the merge's first parent): from the cache of main's results, from the red-on-main list
when nothing behavioural changed since that entry was last seen red, or by running it on main's
own checkout and build (twice at most). Red on main too: the case is reported and does not
block, and the persistent red-on-main list records it until it passes on main. Red only on the
branch: the gate fails.

Usage:
  scene_gate.py run [--base REF] [--head REF] [--force] [--cases a,b] [--no-main-check]
                    [--stdb-container NAME] [--stdb-url URL] [--reds PATH] [--main-dir DIR]
                    [--json PATH]
      --base REF  what the change is measured against (default: HEAD^1 when HEAD is a merge,
                  else origin/main); the run and the main check use its commit
      --head REF  the tree under test; must be the checked-out HEAD (default HEAD)
      --force     run even when no behavioural path changed
  scene_gate.py touches --base A --head B   exit 0 when A..B touches behaviour, 1 when not
  scene_gate.py reds [--reds PATH] [--json] [--owner CASE WHO]   the red-on-main list
  scene_gate.py settle --record JSON --main SHA   after a push: drop the red-on-main entries of
                  the cases that passed in that gate run (the pushed merge is now main)

Environment: LIVING_GATE_STDB_CONTAINER / LIVING_GATE_STDB_URL (default the Spark's trial server
slop-trials-stdb on http://127.0.0.1:3320), LIVING_GATE_REDS (default ~/slop-mq/red-on-main.json
when ~/slop-mq exists, else the state folder below), LIVING_GATE_MAIN_DIR (main's checkout for
the main check; its build folder is <dir>-target). State: ~/.local/state/slop-merge/scene-gate/.
Exit: 0 passed, skipped, or failed only where main fails too; 1 a case failed on the branch
only (or could not be judged on main); 2 usage or setup error (no server, a dirty main checkout).
No case uses Neo4j (the minds cases run LIVING_NEO4J=off). It never touches a database outside
verify-gate-<this run>-*: not the paid verify-trial-* batches, nor sao-living_*.
"""
import concurrent.futures
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "slop-merge" / "scene-gate"
REDS_DEFAULT = HOME / "slop-mq/red-on-main.json" if (HOME / "slop-mq").is_dir() else STATE / "red-on-main.json"

# What a merge must touch for the gate to run: the rules, the authority, the scripts, the mind,
# seeds, their configs and dependencies, and the drivers the gate runs. Client, viewer, docs,
# other tools and verify-ui changes skip it.
BEHAVIOUR = ("living/authority/", "living/rules/", "living/scripts/", "living/mind/", "living/seeds/",
             "living/configs/", "living/bindings/", "living/Cargo.toml", "living/Cargo.lock",
             "living/tools/scene_gate.py", "living/tools/install_script.py", "living/tools/stdb",
             ".agents/skills/verify/scripts/", ".agents/skills/verify-core/scripts/",
             ".agents/skills/verify-minds/scripts/", ".agents/skills/verify-player/scripts/",
             ".agents/skills/verify-llm/scripts/")

# Each case: its surface skill and the world group it runs in. Known flakes are from the skills'
# validation records (references/validation.md); they get the same one retry, never a pass.
CASES = {
    "tick":         {"skill": "verify-core", "group": "core",
                     "flaky": "the pause landed after the giver's 3 s wait once: verify-core validation, rates-2"},
    "sight":        {"skill": "verify-core", "group": "core"},
    "senses":       {"skill": "verify-core", "group": "core"},
    "refusal":      {"skill": "verify-core", "group": "core"},
    "skirmish":     {"skill": "verify-core", "group": "island"},
    "roundtrip":    {"skill": "verify-minds", "group": "minds"},
    "acts":         {"skill": "verify-minds", "group": "minds"},
    "dealings":     {"skill": "verify-minds", "group": "minds",
                     "flaky": "times out under load (the demand act or the rules' ask late): verify-minds validation, recipes-1, l2c, fix-death-labels"},
    "conversation": {"skill": "verify-minds", "group": "minds"},
    "combat":       {"skill": "verify-player", "group": "player",
                     "flaky": "staged fights in town geometry (a bolt into a passer-by, an arrow into a wall): verify-player validation, l2"},
}
# The skills name no owners; the surface is the owner until `reds --owner` names one.
ORDER = list(CASES)
V = ".agents/skills/verify/scripts/verify.py"
LOCK = threading.Lock()


def say(msg):
    with LOCK:
        print(f"scene-gate: {msg}", flush=True)


def git(*args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"scene-gate: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def changed(base, head, cwd=None):
    return [p for p in git("diff", "--name-only", base, head, cwd=cwd).splitlines() if p]


def behavioural(paths):
    return [p for p in paths if p.startswith(BEHAVIOUR)]


# ---------------------------------------------------------------- the red-on-main list

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def reds_lines(reds):
    if not reds:
        return ["red on main: none"]
    out = [f"red on main: {len(reds)} case{'s' if len(reds) != 1 else ''}"]
    for case, e in sorted(reds.items(), key=lambda kv: kv[1].get("first_seen", "")):
        out.append(f"  {case} ({e.get('skill')}; owner {e.get('owner') or e.get('skill')}): red on main since {e.get('first_seen')} "
                   f"(main {e.get('first_main', '?')[:10]}), last {e.get('last_seen')} (main {e.get('last_main', '?')[:10]}); evidence {e.get('last_evidence')}")
    return out


def mark_red(reds_path, case, main_sha, evidence):
    with LOCK:
        reds = load_json(reds_path, {})
        e = reds.get(case) or {"case": case, "skill": CASES[case]["skill"], "owner": None,
                               "first_seen": now(), "first_main": main_sha}
        e.update(last_seen=now(), last_main=main_sha, last_evidence=evidence, times=e.get("times", 0) + 1)
        reds[case] = e
        save_json(reds_path, reds)


def drop_red(reds_path, case, why):
    with LOCK:
        reds = load_json(reds_path, {})
        if case in reds:
            reds.pop(case)
            save_json(reds_path, reds)
            say(f"{case} passes on main ({why}): dropped from the red-on-main list")


# ---------------------------------------------------------------- running scenes

class Runner:
    def __init__(self, stamp, env, out):
        self.stamp, self.env, self.out = stamp, env, out
        self.runs = []  # every gate run name launched, for the final sweep
        self.procs = set()

    def sh(self, cmd, root, log, timeout):
        """Run one command in its own process group, output appended to log; return its code."""
        with open(log, "a") as f:
            f.write(f"$ {' '.join(map(str, cmd))}\n")
            f.flush()
            p = subprocess.Popen([str(c) for c in cmd], cwd=root, env=self.env, stdout=f, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            with LOCK:
                self.procs.add(p)
            try:
                return p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                f.write(f"\n[scene-gate: stopped after {timeout} s]\n")
                return 124
            finally:
                with LOCK:
                    self.procs.discard(p)

    def world(self, root, run, seed, log):
        """Launch a fresh scratch world; True when launch and doctor pass."""
        with LOCK:
            self.runs.append((root, run))
        args = ["--seed", seed] if seed != "world" else []
        if self.sh([sys.executable, V, "launch", "--run", run, *args], root, log, 1500):
            return False
        return self.sh([sys.executable, V, "doctor", "--run", run], root, log, 300) == 0

    def cleanup(self, root, run, log):
        self.sh([sys.executable, V, "cleanup", "--run", run], root, log, 300)

    def group(self, root, group, cases, tag):
        """Run `cases` of one group on fresh worlds; {case: (ok, evidence, seconds)}."""
        t0 = time.time()
        res = {}
        if group == "minds":
            suite = f"gate-{self.stamp}-{tag}"
            ev = Path(root) / ".local/living/verify" / suite
            log = self.out / f"{tag}.log"
            cmd = [sys.executable, ".agents/skills/verify-minds/scripts/verify_minds.py", "--run", suite, "--no-unit-tests"]
            for c in cases:
                cmd += ["--case", c]
            with LOCK:
                self.runs += [(root, f"{suite}-{c}") for c in cases]
            code = self.sh(cmd, root, log, 2400)
            got = {r["case"]: r for r in load_json(ev / "results.json", [])}
            for c in cases:
                r = got.get(c)
                ok = bool(r) and r.get("status") in ("pass", "xfail")
                res[c] = (ok, str(Path(root) / ".local/living/verify" / f"{suite}-{c}") if r else f"{log} (exit {code}; no result)",
                          time.time() - t0)
            return res
        run = f"gate-{self.stamp}-{tag}"
        ev = Path(root) / ".local/living/verify" / run
        ev.mkdir(parents=True, exist_ok=True)
        log = ev / "gate.log"
        seed = "world" if group == "core" else "island"
        try:
            if not self.world(root, run, seed, log):
                return {c: (False, f"{log} (launch or doctor failed)", time.time() - t0) for c in cases}
            if group == "player":
                if self.sh([sys.executable, V, "player", "--run", run, "join", "GateTester"], root, log, 120):
                    return {"combat": (False, f"{log} (join failed)", time.time() - t0)}
                code = self.sh([sys.executable, ".agents/skills/verify-player/scripts/combat.py", "--run", run, "--scene", "all"],
                               root, ev / "combat.txt", 1500)
                return {"combat": (code == 0, str(ev / "combat.json"), time.time() - t0)}
            for c in cases:
                code = self.sh([sys.executable, ".agents/skills/verify-core/scripts/scenes.py", c, "--run", run], root,
                               ev / f"{c}.txt", 900)
                res[c] = (code == 0, str(ev / f"{c}-results.json"), time.time() - t0)
            return res
        finally:
            self.cleanup(root, run, log)

    def sweep(self):
        """Delete any database of this gate run still live (a driver that died before its cleanup)."""
        for root, run in self.runs:
            st = load_json(Path(root) / ".local/living/verify" / run / "state.json", {})
            if st.get("published") and st.get("db", "").startswith(f"verify-gate-{self.stamp}-"):
                say(f"sweep: {st['db']} is still published; cleaning it up")
                self.cleanup(root, run, self.out / "sweep.log")


def run_cases(runner, root, cases, tag):
    """All `cases` at once, one task per world group; {case: (ok, evidence, seconds)}."""
    groups = {}
    for c in cases:
        groups.setdefault(CASES[c]["group"], []).append(c)
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(groups))) as ex:
        futs = {ex.submit(runner.group, root, g, cs, f"{tag}-{g}"): g for g, cs in groups.items()}
        for f in concurrent.futures.as_completed(futs):
            try:
                got = f.result()
            except Exception as e:  # a driver crash is the group's failure, never the gate's crash
                got = {c: (False, f"gate error: {type(e).__name__}: {e}", 0.0) for c in groups[futs[f]]}
            for c, (ok, ev, secs) in got.items():
                say(f"{tag}: {c} {'passed' if ok else 'FAILED'} in {secs:.0f} s ({ev})")
            out.update(got)
    return out


def retry_each(runner, root, cases, tag):
    """Each case alone on its own fresh world, all at once."""
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cases))) as ex:
        futs = {ex.submit(run_cases, runner, root, [c], f"{tag}-{c}"): c for c in cases}
        for f in concurrent.futures.as_completed(futs):
            out.update(f.result())
    return out


# ---------------------------------------------------------------- main's verdict

def main_checkout(repo, main_dir, sha):
    """main_dir at `sha` (a detached worktree of this repository, made when missing)."""
    main_dir = Path(main_dir)
    if not (main_dir / ".git").exists():
        main_dir.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "--detach", str(main_dir), sha, cwd=repo)
        return main_dir
    dirty = git("status", "--porcelain", "--untracked-files=no", cwd=main_dir)
    if dirty:
        raise SystemExit(f"scene-gate: main's checkout {main_dir} has changes; refusing to move it:\n{dirty}")
    git("checkout", "-q", "--detach", sha, cwd=main_dir)
    return main_dir


def judge_on_main(a, runner, repo, base, cases, record):
    """For cases that failed twice: 'red-on-main', 'branch' (passes on main) or 'unknown'."""
    cache_path = STATE / "main-results.json"
    cache = load_json(cache_path, {})
    reds = load_json(a.reds, {})
    verdict, todo = {}, []
    for c in cases:
        hit = cache.get(base, {}).get(c)
        if hit:
            verdict[c] = (hit["status"], hit["evidence"], f"main {base[:10]} cached")
            continue
        e = reds.get(c)
        if e and e.get("last_main") and git("cat-file", "-t", e["last_main"], cwd=repo, check=False) == "commit":
            moved = behavioural(changed(e["last_main"], base, cwd=repo))
            if not moved:
                verdict[c] = ("red-on-main", e["last_evidence"],
                              f"listed red on main {e['last_main'][:10]}; nothing behavioural changed since")
                continue
        todo.append(c)
    if todo and a.no_main_check:
        for c in todo:
            verdict[c] = ("unknown", "", "--no-main-check")
        todo = []
    if todo:
        root = main_checkout(repo, a.main_dir, base)
        for need in ("gate-", "--no-unit-tests"):
            if need not in (root / ".agents/skills/verify-minds/scripts/verify_minds.py").read_text():
                for c in todo:
                    verdict[c] = ("unknown", "", f"main {base[:10]}'s drivers predate the scene gate")
                todo = []
                break
    if todo:
        say(f"judging {', '.join(todo)} on main {base[:10]} (checkout {root}, build {a.main_dir}-target)")
        env = dict(runner.env, CARGO_TARGET_DIR=f"{a.main_dir}-target")
        main_runner = Runner(runner.stamp, env, runner.out)
        t0 = time.time()
        first = retry_each(main_runner, root, todo, "main")
        again = [c for c in todo if not first[c][0]]
        second = retry_each(main_runner, root, again, "main2") if again else {}
        main_runner.sweep()
        record["main_check_seconds"] = round(time.time() - t0)
        cache = load_json(cache_path, {})
        for c in todo:
            red = c in second and not second[c][0]
            ev = second[c][1] if red else (second.get(c) or first[c])[1]
            status = "red-on-main" if red else "branch"
            evs = [first[c][1]] + ([second[c][1]] if c in second else [])
            verdict[c] = (status, ev, f"run on main {base[:10]}: {'failed twice' if red else 'passed'} ({'; '.join(evs)})")
            cache.setdefault(base, {})[c] = {"status": status, "evidence": ev, "at": now()}
        # keep the cache small: the last 30 mains
        for k in sorted(cache, key=lambda k: max(v["at"] for v in cache[k].values()))[:-30]:
            cache.pop(k)
        save_json(cache_path, cache)
    for c, (status, ev, why) in verdict.items():
        if status == "red-on-main":
            mark_red(a.reds, c, base, ev)
        elif status == "branch":
            drop_red(a.reds, c, f"run on main {base[:10]}")
    return verdict


# ---------------------------------------------------------------- commands

def cmd_run(a):
    repo = git("rev-parse", "--show-toplevel")
    os.chdir(repo)
    head = git("rev-parse", a.head or "HEAD")
    if head != git("rev-parse", "HEAD"):
        raise SystemExit("scene-gate: --head must be the checked-out HEAD (the scenes run on this tree)")
    if a.base:
        base = git("rev-parse", a.base)
    else:
        parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        base = parents[0] if len(parents) > 1 else git("rev-parse", "origin/main")
    record = {"head": head, "base": base, "started": now(), "cases": {}, "reds_file": str(a.reds)}
    t0 = time.time()
    paths = changed(base, head)
    touched = behavioural(paths)
    cases = [c for c in (a.cases.split(",") if a.cases else ORDER)]
    bad = [c for c in cases if c not in CASES]
    if bad:
        raise SystemExit(f"scene-gate: unknown case {bad}; cases: {ORDER}")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        say(f"note: the tree has uncommitted changes; they are what is tested:\n{dirty}")
    if not touched and not a.force:
        say(f"skipped: {base[:10]}..{head[:10]} changes {len(paths)} path{'s' if len(paths) != 1 else ''}, none behavioural "
            f"({', '.join(paths[:5])}{', …' if len(paths) > 5 else ''})")
        record.update(result="skipped", seconds=round(time.time() - t0))
        return finish(a, record, 0)
    container = a.stdb_container
    up = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container], capture_output=True, text=True)
    if up.stdout.strip() != "true":
        say(f"setup error: the SpacetimeDB container {container} is not running (--stdb-container, LIVING_GATE_STDB_CONTAINER)")
        record.update(result="setup error")
        return finish(a, record, 2)
    stamp = time.strftime("%m%d%H%M%S")
    out = Path(repo) / ".local/living/verify" / f"gate-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    record["evidence"] = str(out)
    env = dict(os.environ, LIVING_STDB_CONTAINER=container, LIVING_STDB_URL=a.stdb_url, PYTHONDONTWRITEBYTECODE="1")
    env.setdefault("CARGO_TARGET_DIR", str(Path(repo) / "living/target"))
    say(f"{base[:10]}..{head[:10]} touches {len(touched)} behavioural path{'s' if len(touched) != 1 else ''} "
        f"({', '.join(touched[:4])}{', …' if len(touched) > 4 else ''}); running {', '.join(cases)} on {container} ({a.stdb_url}), "
        f"databases verify-gate-{stamp}-*, evidence {out}")
    runner = Runner(stamp, env, out)
    try:
        first = run_cases(runner, repo, cases, "a")
        record["first_seconds"] = round(time.time() - t0)
        failed = [c for c in cases if not first[c][0]]
        second = {}
        if failed:
            say(f"re-running {', '.join(failed)} once, each on a fresh world")
            second = retry_each(runner, repo, failed, "b")
        twice = [c for c in failed if not second[c][0]]
        on_main = judge_on_main(a, runner, repo, base, twice, record) if twice else {}
    finally:
        runner.sweep()
    blocking = []
    for c in cases:
        runs = [first[c][1]] + ([second[c][1]] if c in second else [])
        if first[c][0]:
            status = "pass"
        elif second[c][0]:
            status = "flaky-pass"
        else:
            status = {"red-on-main": "red-on-main", "branch": "fail"}.get(on_main[c][0], "fail-unjudged")
            if status != "red-on-main":
                blocking.append(c)
        record["cases"][c] = {"status": status, "skill": CASES[c]["skill"], "evidence": runs,
                              **({"main": {"verdict": on_main[c][0], "evidence": on_main[c][1], "how": on_main[c][2]}} if c in on_main else {}),
                              **({"known_flake": CASES[c]["flaky"]} if "flaky" in CASES[c] and status != "pass" else {})}
    record["seconds"] = round(time.time() - t0)
    say(f"results ({record['seconds']} s; first pass {record['first_seconds']} s):")
    for c in cases:
        r = record["cases"][c]
        line = f"  {c:<13} {r['status']:<14} {' | '.join(r['evidence'])}"
        if "main" in r:
            line += f"\n  {'':<13} on main: {r['main']['how']}"
        if r["status"] == "flaky-pass":
            line += f"\n  {'':<13} failed once, passed alone: a flake{' (recorded: ' + r['known_flake'] + ')' if 'known_flake' in r else ', not one the skill records'}"
        if r["status"] == "red-on-main":
            line += f"\n  {'':<13} red on main too: not this branch's failure; it does not block"
        say(line)
    if blocking:
        record["result"] = "failed: " + ", ".join(blocking)
        say(f"FAILED: {', '.join(blocking)} failed twice on the branch and "
            + ("pass on main" if all(record["cases"][c]["status"] == "fail" for c in blocking) else "could not be judged on main"))
        return finish(a, record, 1)
    reds = [c for c in cases if record["cases"][c]["status"] == "red-on-main"]
    record["result"] = "passed" + (f" (red on main too: {', '.join(reds)})" if reds else "")
    say(record["result"])
    return finish(a, record, 0)


def finish(a, record, code):
    for line in reds_lines(load_json(a.reds, {})):
        say(line)
    if a.json:
        save_json(a.json, record)
    if record.get("evidence"):
        save_json(Path(record["evidence"]) / "gate.json", record)
    return code


def cmd_touches(a):
    t = behavioural(changed(a.base, a.head))
    print("\n".join(t) if t else "no behavioural path")
    return 0 if t else 1


def cmd_reds(a):
    reds = load_json(a.reds, {})
    if a.owner:
        case, who = a.owner
        if case not in reds:
            raise SystemExit(f"{case} is not on the red-on-main list ({a.reds})")
        reds[case]["owner"] = who
        save_json(a.reds, reds)
    if a.as_json:
        print(json.dumps(reds, indent=2))
    else:
        print(f"{a.reds}:")
        print("\n".join(reds_lines(reds)))
    return 0


def cmd_settle(a):
    record = load_json(a.record, {})
    for c, r in record.get("cases", {}).items():
        if r.get("status") in ("pass", "flaky-pass"):
            drop_red(a.reds, c, f"passed in the gate of {a.main[:10]}, now main")
    return 0


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reds", default=os.environ.get("LIVING_GATE_REDS", str(REDS_DEFAULT)))
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--base")
    r.add_argument("--head")
    r.add_argument("--force", action="store_true")
    r.add_argument("--cases")
    r.add_argument("--no-main-check", action="store_true")
    r.add_argument("--stdb-container", default=os.environ.get("LIVING_GATE_STDB_CONTAINER", "slop-trials-stdb"))
    r.add_argument("--stdb-url", default=os.environ.get("LIVING_GATE_STDB_URL", "http://127.0.0.1:3320"))
    r.add_argument("--main-dir", default=os.environ.get("LIVING_GATE_MAIN_DIR", str(STATE / "main")))
    r.add_argument("--json")
    r.set_defaults(f=cmd_run)
    t = sub.add_parser("touches")
    t.add_argument("--base", required=True)
    t.add_argument("--head", default="HEAD")
    t.set_defaults(f=cmd_touches)
    s = sub.add_parser("reds")
    s.add_argument("--json", dest="as_json", action="store_true")
    s.add_argument("--owner", nargs=2, metavar=("CASE", "WHO"))
    s.set_defaults(f=cmd_reds)
    st = sub.add_parser("settle")
    st.add_argument("--record", required=True)
    st.add_argument("--main", required=True)
    st.set_defaults(f=cmd_settle)
    for p in (r, t, s, st):  # --reds is accepted after the command too
        p.add_argument("--reds", default=argparse.SUPPRESS)
    a = ap.parse_args(argv or ["run"])
    if not getattr(a, "f", None):
        ap.print_help()
        return 2
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
