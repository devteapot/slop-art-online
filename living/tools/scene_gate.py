#!/usr/bin/env python3
"""The merge's scene gate: a curated set of real scenes on scratch `verify-gate-*` databases
(docs/TOOLING.md, "Scene gate"; .agents/skills/verify/SKILL.md, "Scene gate").

`just living-check` builds and runs cargo tests; no scene runs against a live authority. A change
that moves bodies can pass it and still break a scene (fix-place-free, e3f0527f: verify-minds
`dealings` and verify-player combat staging went red on main). This gate runs, when a merge
touches behaviour, these cases with the fake model only:

  verify-core    tick, sight, senses, refusal (one default-seed world), skirmish (an island world),
                 mechanics (its own default-seed world)
  verify-minds   roundtrip, acts, dealings, conversation (each its own world, the real living-mind)
  verify-player  combat (combat.py --scene all: the staged fights, an island world)
  verify-client  cues (cues.py: the cue event tables reach only their viewer under row-level
                 security, on and with the `cue_transport_on` law off; near_tier.py: whoever is
                 engaged with a player is first in its near tier), motion_tables (motion_tables.py: the
                 public copy tables, motion and projections, reach only their viewer under row-level
                 security, and each law off empties its table at once); one default-seed world, the SDK probe
  living-mind    mind-unit: its cargo tests (`just living-check` builds the mind, tests only the rules)
  verify-generation  generation-default, generation-island, generation-cullet (generation.py --smoke:
                 its per-world checks, the seed's laws composed over the shipped script among them,
                 on the world, island, cullet and cullet-laws genesis worlds; a failing check is a
                 part `<case>:<seed>:<check>` the red-on-main list can hold)

The world groups and the tests run at once. A case whose only failures are parts on the red-on-main
list (a mind test `living-mind::<test>`, a combat scene `combat:<scene>`) passes and says which. Flakes: a failing case runs again once, alone, on a fresh scratch
database; it fails the gate only when it fails twice. A case that failed twice is then judged on
main (the merge's first parent): from the cache of main's results, from the red-on-main list
when nothing behavioural changed since that entry was last seen red, or by running it on main's
own checkout and build (twice at most). Red on main too: the case is reported and does not
block, and the persistent red-on-main list records it until it passes on main. Red only on the
branch: the gate fails.

Before the scenes, genesis fuel (docs/TOOLING.md, "Genesis fuel"): each seed in GENESIS_SEEDS is
published fresh and its `init` fuel per run read from the server's metrics (or, once
living/tools/genesis_fuel.py exists, from its report, steps included). Over 90% of the reducer
budget fails (SLOP_GATE_GENESIS_HEADROOM), except a seed with a baseline for this rustc in
genesis_fuel_baselines.json, which may not rise more than 0.1% above it. A missing metric fails.
Every seed's fuel is printed (`scene-gate: genesis SEED: …`) and kept in genesis.json and gate.json.

Usage:
  scene_gate.py run [--base REF] [--head REF] [--force] [--cases a,b] [--no-main-check]
                    [--stdb-container NAME] [--stdb-url URL] [--reds PATH] [--main-dir DIR]
                    [--json PATH] [--genesis-only] [--genesis-fuel-report JSON]...
      --base REF  what the change is measured against (default: HEAD^1 when HEAD is a merge,
                  else origin/main); the run and the main check use its commit
      --head REF  the tree under test; must be the checked-out HEAD (default HEAD)
      --force     run even when no behavioural path changed
      --genesis-only  the genesis fuel publishes alone: no scenes, no red-on-main list
      --genesis-fuel-report JSON  a staged genesis_fuel.py report for its seed (repeatable)
  scene_gate.py seeds [--json PATH]   compiled seeds against their living/seeds/worlds/ sources
                  (seed_fresh.py, files only); a stale block listed red on main as
                  `seeds:<seed>:<block>` does not fail. living-merge runs it before the check
  scene_gate.py genesis-baseline RECORD SEED... [--note TEXT]   record SEEDs' init fuel from a
                  gate's genesis.json or gate.json as their baselines for its rustc
  scene_gate.py touches --base A --head B   exit 0 when A..B touches behaviour, 1 when not
  scene_gate.py reds [--reds PATH] [--json] [--owner CASE WHO] [--drop CASE]
                  [--add CASE --skill S --who OWNER --reason WHY [--main SHA] [--evidence PATH]]
                  the red-on-main list (for the daily digest); --add lists a case known red
  scene_gate.py recheck [--main REF]   run every listed case on main (origin/main): drop the
                  green ones, renew the red ones; the gate's cases and any verify-minds case
  scene_gate.py settle --record JSON --main SHA   after a push: drop the red-on-main entries of
                  the cases that passed in that gate run (the pushed merge is now main)

The red-on-main list is shared through git: the branch `red-on-main` (one file, red-on-main.json,
never merged into main). Every command reads it after a fetch; every change is a commit pushed to
it without force (retried after a fetch when another writer got there first). The local file is a
cache, read when the fetch fails (the gate says so).

Environment: LIVING_GATE_STDB_CONTAINER / LIVING_GATE_STDB_URL (default the Spark's trial server
slop-trials-stdb on http://127.0.0.1:3320), SLOP_GATE_GENESIS_HEADROOM (percent; default 10),
SLOP_GATE_GENESIS_CHECK=0 (disable with a warning), LIVING_GATE_REDS (the list's local cache; default
~/slop-mq/red-on-main.json when ~/slop-mq exists, else the state folder below),
LIVING_GATE_REDS_REMOTE / _BRANCH (origin, red-on-main), LIVING_GATE_REDS_REPO (the repository that
reaches it; default this file's), LIVING_GATE_REDS_GIT=0 (the cache alone, no git), LIVING_GATE_MAIN_DIR (main's checkout for
the main check; its build folder is <dir>-target). State: ~/.local/state/slop-merge/scene-gate/.
Exit: 0 passed, skipped, or scenes failed only where main fails too; 1 genesis failed, or a
scene failed only on the branch (or could not be judged on main); 2 usage or setup error.
No case uses Neo4j (the minds cases run LIVING_NEO4J=off). It never touches a database outside
verify-gate-<this run>-*: not the paid verify-trial-* batches, nor sao-living_*.
"""
import concurrent.futures
import datetime
import json
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

HOME = Path.home()
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "slop-merge" / "scene-gate"
REDS_DEFAULT = HOME / "slop-mq/red-on-main.json" if (HOME / "slop-mq").is_dir() else STATE / "red-on-main.json"

# What a merge must touch for the gate to run: the rules, the authority, the scripts, the mind,
# seeds, their configs and dependencies, and the drivers the gate runs. Client, viewer, docs,
# other tools and verify-ui changes skip it.
BEHAVIOUR = ("living/authority/", "living/rules/", "living/scripts/", "living/mind/", "living/seeds/",
             "living/configs/", "living/bindings/", "living/Cargo.toml", "living/Cargo.lock",
             "living/tools/scene_gate.py", "living/tools/genesis_fuel.py", "living/tools/genesis_fuel_baselines.json",
             "living/tools/install_script.py", "living/tools/stdb", "living/tools/verify_mechanics.py",
             ".agents/skills/verify/scripts/", ".agents/skills/verify-core/scripts/",
             ".agents/skills/verify-minds/scripts/", ".agents/skills/verify-player/scripts/",
             ".agents/skills/verify-llm/scripts/", ".agents/skills/verify-client/scripts/")

# Each case: its surface skill and the world group it runs in. Known flakes are from the skills'
# validation records (each skill's references/validation/); they get the same one retry, never a pass.
CASES = {
    "tick":         {"skill": "verify-core", "group": "core",
                     "flaky": "the pause landed after the giver's 3 s wait once: verify-core validation, rates-2"},
    "sight":        {"skill": "verify-core", "group": "core"},
    "senses":       {"skill": "verify-core", "group": "core"},
    "refusal":      {"skill": "verify-core", "group": "core"},
    "skirmish":     {"skill": "verify-core", "group": "island"},
    "mechanics":    {"skill": "verify-core", "group": "mechanics"},
    "roundtrip":    {"skill": "verify-minds", "group": "minds"},
    "acts":         {"skill": "verify-minds", "group": "minds"},
    "dealings":     {"skill": "verify-minds", "group": "minds",
                     "flaky": "times out under load (the demand act or the rules' ask late): verify-minds validation, recipes-1, l2c, fix-death-labels"},
    "conversation": {"skill": "verify-minds", "group": "minds",
                     "flaky": "the talk-turn count assertion once under load, passed on its retry (scene gate, 2026-11-12)"},
    "combat":       {"skill": "verify-player", "group": "player",
                     "flaky": "staged fights in town geometry (a bolt into a passer-by, an arrow into a wall): verify-player validation, l2; "
                              "the kill scene 34/35 then 2/2 (stamina-1)"},
    # Row-level security on the cue event tables is a perception boundary (frame-views): every
    # behavioural merge proves no other identity receives a player's cues.
    "cues":         {"skill": "verify-client", "group": "client"},
    # The same for the public motion copies (battle-views, `seen_body_copy`).
    "motion_tables": {"skill": "verify-client", "group": "client"},
    # verify-generation's light smoke (generation.py --smoke): its per-world checks, the seed's laws
    # composed over the shipped script among them, one case per seed family. The first pass reads
    # the genesis fuel worlds before they are deleted; a retry or main's run launches its own.
    # A failing check is a part, `<case>:<seed>:<check>`, that the red-on-main list can hold.
    "generation-default": {"skill": "verify-generation", "group": "generation", "seeds": ("world",)},
    "generation-island":  {"skill": "verify-generation", "group": "generation", "seeds": ("island",)},
    "generation-cullet":  {"skill": "verify-generation", "group": "generation", "seeds": ("cullet", "cullet-laws")},
    # living-mind's own cargo tests: `just living-check` builds the mind but tests only living-rules.
    "mind-unit":    {"skill": "living-mind", "group": "unit",
                     "flaky": "timing bounds under load: llm::tests::unreachable_provider_holds_calls (1.97 s against 2 s), "
                              "fake_transport_records_caching_usage_and_paced_429_recovery (the 180 ms queue wait)"},
}
# Parts of a case listed on the red-on-main list by key: `living-mind::<test>` (a mind-unit test)
# and `combat:<scene>` (a verify-player combat scene). A case whose only failures are listed parts
# passes, saying so; `recheck` cannot run them, so they are dropped by hand when green.
# The skills name no owners; the surface is the owner until `reds --owner` names one.
ORDER = list(CASES)
V = ".agents/skills/verify/scripts/verify.py"
GEN = ".agents/skills/verify-generation/scripts/generation.py"
LOCK = threading.RLock()  # say() inside the list updates takes it again


# SpacetimeDB v2.14.1 FunctionBudget::DEFAULT_BUDGET (client-api-messages/src/energy.rs).
GENESIS_BUDGET = 120_000_000_000
# The gate's scene worlds (combat and minds use island), Cullet and the player fixtures
# (verify-player's plan-test and cullet-laws). The default world goes last: its build in
# CARGO_TARGET_DIR is the one the core, mechanics and client scenes then launch.
GENESIS_SEEDS = ("island", "cullet", "cullet-laws", "plan-test", "world")
GENESIS_FUEL = "reducer_wasmtime_fuel_used"
GENESIS_RUNS = "spacetime_reducer_plus_query_duration_sec_count"
GENESIS_BASELINE_FILE = Path(__file__).with_name("genesis_fuel_baselines.json")


def genesis_threshold(env):
    if env.get("SLOP_GATE_GENESIS_CHECK") == "0":
        return None
    try:
        threshold = float(env.get("SLOP_GATE_GENESIS_HEADROOM", "10"))
    except ValueError:
        raise ValueError("SLOP_GATE_GENESIS_HEADROOM must be a percentage between 0 and 100") from None
    if not 0 <= threshold <= 100:
        raise ValueError("SLOP_GATE_GENESIS_HEADROOM must be a percentage between 0 and 100")
    return threshold


def genesis_metrics(metrics, identity):
    samples = {}
    for line in metrics.splitlines():
        match = re.fullmatch(r'([^{}]+)\{([^{}]*)\}\s+(\S+)', line)
        if not match or match[1] not in (GENESIS_FUEL, GENESIS_RUNS):
            continue
        labels = dict(re.findall(r'(\w+)="([^"]*)"', match[2]))
        if labels.get("db") == identity and labels.get("reducer") == "init":
            value = float(match[3])
            if match[1] in samples or not math.isfinite(value) or not 0 < value < 2**64 or not value.is_integer():
                raise ValueError(f"invalid or duplicate {match[1]} for init on {identity}")
            samples[match[1]] = int(value)
    for name in (GENESIS_FUEL, GENESIS_RUNS):
        if name not in samples:
            raise ValueError(f"missing or empty metric {name} for init on {identity}")
    runs = samples[GENESIS_RUNS]
    return dict(init_fuel=samples[GENESIS_FUEL] / runs, init_runs=runs,
                steps=[], largest_step_share=0.0)


def staged_genesis_report(report, seed, commit):
    if not isinstance(report, dict) or any(report.get(key) != value for key, value in
                                          dict(seed=seed, commit=commit, budget=GENESIS_BUDGET).items()):
        raise ValueError("staged genesis report must match the seed, commit and budget")
    runs, fuel, steps = (report.get(key) for key in ("init_runs", "init_fuel", "steps"))
    if type(runs) is not int or runs != 2 or not valid_fuel(fuel) or not isinstance(steps, list) or not steps:
        raise ValueError("staged genesis report needs two init runs, positive init fuel and measured steps")
    for step in steps:
        if (not isinstance(step, dict) or not valid_fuel(step.get("fuel"))
                or any(not isinstance(step.get(key), str) or not step[key] for key in ("phase", "label", "reducer"))):
            raise ValueError("staged genesis step needs a phase, label, positive fuel and reducer")
    largest = max(step["fuel"] for step in steps) / GENESIS_BUDGET
    if type(report.get("largest_step_share")) not in (float, int) or not math.isclose(
        largest, report["largest_step_share"], rel_tol=1e-9
    ):
        raise ValueError("largest_step_share does not match the measured steps")
    return dict(init_fuel=fuel, init_runs=runs, steps=steps, largest_step_share=largest)


def valid_fuel(fuel):
    return type(fuel) in (int, float) and 0 < fuel < 2**64


def genesis_toolchain(env, root):
    """`rustc --version` for the module build: fuel counts wasm instructions, so a module built by
    another rustc counts differently (the island: 118.735e9 on rustc 1.99.1 aarch64, 119.79e9 on
    rustc 1.97.1 x86_64 with the same seed and source)."""
    got = subprocess.run(["rustc", "--version"], cwd=Path(root) / "living", env=env, capture_output=True, text=True)
    if got.returncode or not got.stdout.strip():
        raise ValueError(f"rustc --version failed: {got.stderr.strip()[-300:]}")
    return got.stdout.strip()


def load_genesis_baselines(path):
    """{seed: {toolchain: {"init_fuel": per-run fuel, "commit": …, "recorded": …}}}; checked."""
    baselines = json.loads(Path(path).read_text())
    if not isinstance(baselines, dict):
        raise ValueError(f"{path} must hold an object of seeds")
    for seed, by_toolchain in baselines.items():
        if seed not in GENESIS_SEEDS or not isinstance(by_toolchain, dict):
            raise ValueError(f"{path}: {seed!r} is not a gate seed with baselines by toolchain")
        for toolchain, entry in by_toolchain.items():
            if (not toolchain.startswith("rustc ") or not isinstance(entry, dict) or not valid_fuel(entry.get("init_fuel"))
                    or entry["init_fuel"] > GENESIS_BUDGET):
                raise ValueError(f"{path}: {seed} / {toolchain!r} needs a positive init_fuel within the budget")
    return baselines


def genesis_baseline(baselines, seed, toolchain):
    """(baseline fuel or None, a note when the seed has baselines only for other toolchains)."""
    by_toolchain = baselines.get(seed) or {}
    if toolchain in by_toolchain:
        return by_toolchain[toolchain]["init_fuel"], ""
    return None, (f" for {toolchain} (recorded for {', '.join(sorted(by_toolchain))})" if by_toolchain else "")


def genesis_policy(measurement, threshold, baseline, missing=""):
    fuel = measurement["init_fuel"]
    headroom = 100 * (GENESIS_BUDGET - fuel) / GENESIS_BUDGET
    # The interim rule (docs/TOOLING.md, "Genesis fuel"): a seed with a recorded baseline that is
    # short of the headroom may not rise more than 0.1% above it; with the headroom it graduates.
    use_baseline = headroom < threshold and baseline is not None
    init_passed = fuel * 1000 <= baseline * 1001 if use_baseline else headroom >= threshold
    limit = baseline * 1.001 if use_baseline else GENESIS_BUDGET * (100 - threshold) / 100
    failures, warnings = [], []
    if not init_passed:
        why = ("more than 0.1% above its recorded baseline" if use_baseline else
               f"under {threshold:g}% headroom" + ("" if baseline is not None else
                                                    f" and no recorded baseline in {GENESIS_BASELINE_FILE.name}{missing}"))
        failures.append(f"init {fuel / 1e9:.3f}e9 is over its limit {limit / 1e9:.3f}e9: {why}")
    if fuel > GENESIS_BUDGET / 2:
        warnings.append(f"init uses {fuel / 1e9:.3f}e9 fuel, over 50% of its budget")
    for step in measurement["steps"]:
        step_fuel = step["fuel"]
        detail = f"step {step['phase']} / {step['label']} ({step['reducer']}) uses {step_fuel / 1e9:.3f}e9 fuel"
        step_headroom = 100 * (GENESIS_BUDGET - step_fuel) / GENESIS_BUDGET
        if step_headroom < threshold:
            failures.append(f"{detail} ({step_headroom:.2f}% headroom, requires {threshold:g}%)")
        if step_fuel > GENESIS_BUDGET / 2:
            warnings.append(f"{detail}, over 50% of its budget")
    return dict(headroom_pct=headroom, policy="baseline + 0.1%" if use_baseline else f"{threshold:g}% minimum headroom",
                baseline_fuel=baseline, limit_fuel=limit, warnings=warnings, failures=failures, passed=not failures)


def genesis_result_line(result):
    def e9(fuel):
        return f"{fuel / 1e9:.3f}e9"
    line = f"genesis {result['seed']}: "
    if "headroom_pct" in result:
        line += (f"init {e9(result['init_fuel'])} fuel per run ({result['init_runs']} init run{'s' if result['init_runs'] != 1 else ''}), "
                 f"{100 - result['headroom_pct']:.2f}% of the {result['budget'] / 1e9:g}e9 budget, "
                 f"{result['headroom_pct']:.2f}% headroom; rule {result['policy']}, limit {e9(result['limit_fuel'])}")
        if result["baseline_fuel"] is not None:
            line += f" (recorded baseline {e9(result['baseline_fuel'])})"
    else:
        line += "init fuel unavailable"
    if result.get("steps"):
        line += f"; largest of {len(result['steps'])} steps {result['largest_step_share']:.2%} of its budget"
    for detail in [*result.get("failures", []), result.get("error")]:
        if detail:
            line += f"; {detail}"
    return line + (" — PASS" if result["passed"] else " — FAIL")


def genesis_http(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode()


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
                   f"(main {(e.get('first_main') or '?')[:10]}), last {e.get('last_seen')} (main {(e.get('last_main') or '?')[:10]}); "
                   f"evidence {e.get('last_evidence') or '-'}" + (f"\n    why: {e['reason']}" if e.get("reason") else ""))
    return out


def spec(case, skill=None):
    """How the gate runs a case: one of its own, or any verify-minds case (its own world)."""
    if case in CASES:
        return CASES[case]
    if (skill or "verify-minds") == "verify-minds":
        return {"skill": "verify-minds", "group": "minds"}
    return None


# The list lives in git, so every machine's gate shares it: the branch `red-on-main` (never merged
# into main) holds one file, red-on-main.json. Reads fetch it; writes commit to it with plumbing
# (no checkout, from any worktree) and push without force, fetching and retrying when another
# writer got there first. The local file (--reds) is a cache: read when the fetch fails (saying so),
# rewritten after every good read and write.
REDS_REPO = os.environ.get("LIVING_GATE_REDS_REPO") or str(Path(__file__).resolve().parents[2])
REDS_REMOTE = os.environ.get("LIVING_GATE_REDS_REMOTE", "origin")
REDS_BRANCH = os.environ.get("LIVING_GATE_REDS_BRANCH", "red-on-main")
REDS_FILE = "red-on-main.json"
REDS_GIT = os.environ.get("LIVING_GATE_REDS_GIT", "1") != "0"


def rgit(*args, input=None, timeout=60):
    return subprocess.run(["git", "-C", REDS_REPO, *args], input=input, capture_output=True, text=True, timeout=timeout)


class RedsLock:
    """One reader or writer of the list at a time per clone (its git dir): concurrent fetches into
    the same remote-tracking ref fail on git's ref lock."""

    def __enter__(self):
        import fcntl
        common = rgit("rev-parse", "--git-common-dir").stdout.strip() or ".git"
        path = Path(common if os.path.isabs(common) else os.path.join(REDS_REPO, common)) / "scene-gate-reds.lock"
        self.f = open(path, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        self.f.close()


def fetch_reds():
    """(the list on the remote, its commit or None when the branch does not exist yet), or raise."""
    ref = f"refs/remotes/{REDS_REMOTE}/{REDS_BRANCH}"
    for attempt in range(3):
        r = rgit("fetch", "-q", REDS_REMOTE, f"+refs/heads/{REDS_BRANCH}:{ref}")
        if r.returncode == 0:
            break
        there = rgit("ls-remote", "--exit-code", REDS_REMOTE, f"refs/heads/{REDS_BRANCH}").returncode
        if there == 2:
            rgit("update-ref", "-d", ref)
            return {}, None  # reachable, no list yet
        if there != 0:  # unreachable (or another error): no retry
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"git fetch exit {r.returncode}")
        time.sleep(0.2)  # the branch appeared between the fetch and ls-remote: fetch again
    else:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"git fetch exit {r.returncode}")
    sha = rgit("rev-parse", ref).stdout.strip()
    show = rgit("show", f"{sha}:{REDS_FILE}")
    if show.returncode:
        raise RuntimeError(f"{REDS_BRANCH} {sha[:10]} has no {REDS_FILE}")
    return json.loads(show.stdout), sha


def refresh_reds(cache):
    """Read the list from the remote into the cache; on failure keep the cache and say so."""
    if not REDS_GIT:
        return load_json(cache, {})
    try:
        with RedsLock():
            reds, sha = fetch_reds()
    except Exception as e:  # unreachable remote, a timeout, a broken branch: the cache stands in
        say(f"note: could not read the red-on-main list from {REDS_REMOTE}/{REDS_BRANCH} ({e}); using the local cache {cache}"
            + (f" (written {time.strftime('%Y-%m-%d %H:%M', time.localtime(Path(cache).stat().st_mtime))})" if Path(cache).exists() else " (none: empty)"))
        return load_json(cache, {})
    save_json(cache, reds)
    return reds


def update_reds(cache, change, message, tries=8):
    """Apply change(reds) -> True when it changed something, commit it to the branch and push;
    retried on a non-fast-forward. Returns the list as now on the remote. Raises when the remote
    cannot be written: the change is then not made anywhere (the cache is left as read)."""
    with LOCK:
        if not REDS_GIT:
            reds = load_json(cache, {})
            if change(reds):
                save_json(cache, reds)
            return reds
        for attempt in range(tries):
            with RedsLock():  # this clone's other writers wait; other machines are caught by the push
                reds, base = fetch_reds()
                if not change(reds):
                    save_json(cache, reds)
                    return reds
                if push_reds(reds, base, message, cache):
                    return reds
            time.sleep(0.2 * (attempt + 1))  # another machine got there first: read again
        raise RuntimeError(f"{REDS_REMOTE}/{REDS_BRANCH} kept moving: {tries} tries")


def push_reds(reds, base, message, cache):
    """Commit the list on `base` and push it without force: True when it landed, False when the
    branch moved meanwhile; raise on any other failure."""
    blob = rgit("hash-object", "-w", "--stdin", input=json.dumps(reds, indent=2, sort_keys=True) + "\n").stdout.strip()
    tree = rgit("mktree", input=f"100644 blob {blob}\t{REDS_FILE}\n").stdout.strip()
    commit = rgit("commit-tree", tree, *(["-p", base] if base else []), "-m",
                  f"{message}\n\n(scene_gate.py on {os.uname().nodename})").stdout.strip()
    if not (blob and tree and commit):
        raise RuntimeError(f"could not make the commit for {REDS_BRANCH}")
    # without force: lands only on the commit just read (a new branch only if none exists)
    push = rgit("push", "--porcelain", REDS_REMOTE, f"{commit}:refs/heads/{REDS_BRANCH}")
    if push.returncode == 0:
        rgit("update-ref", f"refs/remotes/{REDS_REMOTE}/{REDS_BRANCH}", commit)
        save_json(cache, reds)
        return True
    if not re.search(r"rejected|fetch first|non-fast-forward|stale info", push.stdout + push.stderr):
        raise RuntimeError(f"git push to {REDS_REMOTE}/{REDS_BRANCH} failed: {(push.stderr or push.stdout).strip()[-300:]}")
    return False


def mark_red(reds_path, case, main_sha, evidence):
    def change(reds):
        e = reds.get(case) or {"case": case, "skill": spec(case)["skill"], "owner": None, "reason": None,
                               "first_seen": now(), "first_main": main_sha}
        e.update(last_seen=now(), last_main=main_sha, last_evidence=evidence, times=e.get("times", 0) + 1)
        reds[case] = e
        return True
    try:
        update_reds(reds_path, change, f"red on main: {case} (main {main_sha[:10]})")
    except Exception as e:
        say(f"WARNING: {case} is red on main but the shared list could not be written ({e}); add it with `reds --add`")


def drop_red(reds_path, case, why):
    dropped = []

    def change(reds):
        if case in reds:
            dropped.append(reds.pop(case))
            return True
        return False
    try:
        update_reds(reds_path, change, f"green on main: {case} ({why})")
    except Exception as e:
        say(f"WARNING: {case} passes on main ({why}) but the shared list could not be written ({e}); drop it with `reds --drop {case}`")
        return
    if dropped:
        say(f"{case} passes on main ({why}): dropped from the red-on-main list")


# ---------------------------------------------------------------- running scenes

def listed_parts(reds_path, prefix):
    return {k[len(prefix):] for k in load_json(reds_path, {}) if k.startswith(prefix)}


class Runner:
    def __init__(self, stamp, env, out, reds_path):
        self.stamp, self.env, self.out, self.reds_path = stamp, env, out, reds_path
        self.runs = []  # every gate run name launched, for the final sweep
        self.procs = set()
        self.notes = {}  # (tag, case) -> what a passing run with listed failures failed
        self.smoke_seeds = set()  # seeds whose genesis world the generation smoke reads first
        self.smoke = {}  # (root, seed) -> (failed checks or None when it did not run, evidence)
        self.fresh = 0  # numbers the generation cases' own worlds

    def sh(self, cmd, root, log, timeout, stdout=None):
        """Run one command in its own process group, output appended to log; return its code."""
        with open(log, "a") as f:
            f.write(f"$ {' '.join(map(str, cmd))}\n")
            f.flush()
            p = subprocess.Popen([str(c) for c in cmd], cwd=root, env=self.env, stdout=stdout or f, stderr=f,
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

    def world(self, root, run, seed, log, *launch_args):
        """Launch a fresh scratch world; True when launch and doctor pass."""
        with LOCK:
            self.runs.append((root, run))
        args = ["--seed", seed] if seed != "world" else []
        if self.sh([sys.executable, V, "launch", "--run", run, *args, *launch_args], root, log, 1500):
            return False
        return self.sh([sys.executable, V, "doctor", "--run", run], root, log, 300) == 0

    def genesis(self, root, seed, commit, threshold, baseline, report=None, toolchain=None, missing=""):
        tool = Path(root) / "living/tools/genesis_fuel.py"
        if report is None and not tool.is_file():
            result = self.genesis_live(root, seed, commit, threshold, baseline, toolchain, missing)
        else:
            result = dict(seed=seed, commit=commit, budget=GENESIS_BUDGET, toolchain=toolchain, passed=False)
            try:
                if report is None:
                    report = self.out / f"genesis-{seed}-staged.json"
                    log = self.out / f"genesis-{seed}.log"
                    result["log"] = str(log)
                    with report.open("w") as output:
                        code = self.sh([sys.executable, tool, "--seed", seed], root, log, 1500, stdout=output)
                    if code:
                        raise ValueError(f"{tool.name} exited {code}; see {log}")
                result["staged_report"] = str(report)
                result.update(staged_genesis_report(json.loads(report.read_text()), seed, commit))
                result.update(genesis_policy(result, threshold, baseline, missing))
            except (OSError, ValueError) as error:
                result["error"] = str(error)
        # scene-gate: lines are what the merge queue forwards, on a pass and on a failure.
        say(genesis_result_line(result))
        for warning in result.get("warnings", []):
            say(f"WARNING genesis {seed}: {warning}")
        return result

    def genesis_live(self, root, seed, commit, threshold, baseline, toolchain=None, missing=""):
        run = f"gate-{self.stamp}-fuel-{seed}"
        db = f"verify-{run}"
        log = self.out / f"genesis-{seed}.log"
        run_dir = Path(root) / ".local/living/verify" / run
        self.runs.append((root, run))
        result = dict(seed=seed, commit=commit, database=db, budget=GENESIS_BUDGET, toolchain=toolchain, passed=False, log=str(log),
                      world_guard_log=str(run_dir / "world-guard.log"))
        url = self.env["LIVING_STDB_URL"].rstrip("/")
        identity_url = f"{url}/v1/database/{db}/identity"
        try:
            # A unique name must be unused, including names reserved by a failed publish.
            try:
                genesis_http(identity_url)
            except HTTPError as e:
                if e.code != 404:
                    raise
            else:
                raise ValueError(f"scratch database name already exists: {db}")
            code = self.sh([sys.executable, V, "launch", "--run", run, "--seed", seed,
                            "--target-dir", self.env["CARGO_TARGET_DIR"], "--driver-pid", os.getpid()],
                           root, log, 1500)
            state = load_json(run_dir / "state.json", {})
            published = state.get("published", False)
            try:
                identity = state.get("database_identity") or genesis_http(identity_url).strip()
                if not re.fullmatch(r"[0-9a-f]{64}", identity):
                    raise ValueError(f"invalid identity for {db}")
                metrics = genesis_http(f"{url}/v1/metrics")
                # Keep the measured series as evidence without retaining unrelated databases' metrics.
                series = self.out / f"genesis-{seed}.prom"
                series.write_text("".join(line + "\n" for line in metrics.splitlines()
                                          if line.startswith((GENESIS_FUEL + "{", GENESIS_RUNS + "{"))
                                          and f'db="{identity}"' in line and 'reducer="init"' in line))
                result.update(database_identity=identity, metrics=str(series))
                result.update(genesis_metrics(series.read_text(), identity))
                result.update(genesis_policy(result, threshold, baseline, missing))
                if result["init_runs"] != 2 and published:
                    raise ValueError(f"expected two init runs for a fresh publish, got {result['init_runs']}")
            except (OSError, ValueError) as e:
                result.update(passed=False, error=str(e))
            if not published:
                detail = f"fresh publish not confirmed (launch exit {code}; see {log} and {result['world_guard_log']})"
                result.update(passed=False, error="; ".join(filter(None, (detail, result.get("error")))))
            elif seed in self.smoke_seeds:
                # The generation cases' first pass, on this world before it is deleted.
                self.smoke[(str(root), seed)] = self.generation_smoke(root, run)
        except (OSError, ValueError) as e:
            result.update(passed=False, error=str(e))
        finally:
            state = load_json(run_dir / "state.json", {})
            if state.get("published") and self.cleanup(root, run, log):
                result.update(passed=False, error=f"pause-confirm-delete failed; see {log}")
        return result

    def generation_smoke(self, root, run):
        """generation.py --smoke on a launched run: (failed check names, or None when it did not run; evidence)."""
        ev = Path(root) / ".local/living/verify" / run
        code = self.sh([sys.executable, GEN, "--run", run, "--smoke"], root, ev / "generation-smoke.log", 600)
        got = load_json(ev / "smoke.json", {})
        if code and not got.get("failed"):
            return None, f"{ev / 'generation-smoke.log'} (exit {code}; no result)"
        return list(got.get("failed", [])), str(ev / "checks.json")

    def cleanup(self, root, run, log):
        return self.sh([sys.executable, V, "cleanup", "--run", run], root, log, 300)

    def group(self, root, group, cases, tag):
        """Run `cases` of one group on fresh worlds; {case: (ok, evidence, seconds)}."""
        t0 = time.time()
        res = {}
        if group == "unit":
            log = self.out / f"{tag}.log"
            code = self.sh(["cargo", "test", "--manifest-path", "living/Cargo.toml", "-p", "living-mind"], root, log, 2400)
            text = log.read_text(errors="replace")
            failed = sorted(set(re.findall(r"^test (\S+) \.\.\. FAILED$", text, re.M)))
            listed = listed_parts(self.reds_path, "living-mind::")
            ok = code == 0 or (bool(failed) and set(failed) <= listed)
            if code and ok:
                self.notes[(tag, "mind-unit")] = f"only listed red tests failed: {', '.join(failed)}"
            elif code and failed:
                self.notes[(tag, "mind-unit")] = f"failed: {', '.join(failed)}" + (f" (listed: {', '.join(sorted(set(failed) & listed))})" if set(failed) & listed else "")
            return {"mind-unit": (ok, str(log), time.time() - t0)}
        if group == "generation":
            for c in cases:
                failed, evidence = [], []
                for seed in CASES[c]["seeds"]:
                    got = self.smoke.pop((str(root), seed), None) if tag.startswith("a-") else None
                    if got is None:  # a retry, main's run, or no genesis world: a world of its own
                        with LOCK:
                            self.fresh += 1
                            run = f"gate-{self.stamp}-g{self.fresh}-{seed}"
                        log = self.out / f"{tag}-{seed}.log"
                        try:
                            got = self.generation_smoke(root, run) if self.world(root, run, seed, log) else \
                                (None, f"{log} (launch or doctor failed)")
                        finally:
                            if load_json(Path(root) / ".local/living/verify" / run / "state.json", {}).get("published"):
                                self.cleanup(root, run, log)
                    evidence.append(got[1])
                    failed += [f"{seed}:{name}" for name in got[0]] if got[0] is not None else [f"{seed}:(did not run)"]
                listed = listed_parts(self.reds_path, f"{c}:")
                ok = not failed or (set(failed) <= listed and not any(f.endswith(":(did not run)") for f in failed))
                if failed:
                    self.notes[(tag, c)] = ("only listed red checks failed: " if ok else "failed: ") + "; ".join(failed)
                res[c] = (ok, ", ".join(evidence), time.time() - t0)
            return res
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
        seed = "world" if group in {"core", "mechanics", "client"} else "island"
        # Mechanics uses the raw CLI, so the gate process supervises its world instead of an inactivity lease.
        launch_args = ("--driver-pid", str(os.getpid())) if group == "mechanics" else ()
        try:
            if not self.world(root, run, seed, log, *launch_args):
                return {c: (False, f"{log} (launch or doctor failed)", time.time() - t0) for c in cases}
            if group == "mechanics":
                report = ev / "mechanics.json"
                code = self.sh([sys.executable, "living/tools/verify_mechanics.py", "--gate-world",
                                "--db", f"verify-{run}", "--out", report], root, ev / "mechanics.txt", 900)
                ok = code == 0 and report.is_file()
                return {"mechanics": (ok, str(report if report.exists() else ev / "mechanics.txt"), time.time() - t0)}
            if group == "client":
                probe = ".agents/skills/verify-client/scripts/probe/Cargo.toml"
                env_dir = str(Path(root) / ".local/living/verify/target-client")
                if self.sh(["env", f"CARGO_TARGET_DIR={env_dir}", "cargo", "build", "--locked", "--manifest-path", probe], root, log, 1500):
                    return {c: (False, f"{log} (probe build failed)", time.time() - t0) for c in cases}
                if "cues" in cases:
                    code = self.sh([sys.executable, ".agents/skills/verify-client/scripts/cues.py", "--run", run], root, ev / "cues.txt", 600)
                    tier = self.sh([sys.executable, ".agents/skills/verify-client/scripts/near_tier.py", "--run", run], root, ev / "near_tier.txt", 300)
                    res["cues"] = (code == 0 and tier == 0, str(ev / "cues.json"), time.time() - t0)
                if "motion_tables" in cases:
                    code = self.sh([sys.executable, ".agents/skills/verify-client/scripts/motion_tables.py", "--run", run], root, ev / "motion_tables.txt", 300)
                    res["motion_tables"] = (code == 0, str(ev / "motion_tables.json"), time.time() - t0)
                return res
            if group == "player":
                if self.sh([sys.executable, V, "player", "--run", run, "join", "GateTester"], root, log, 120):
                    return {"combat": (False, f"{log} (join failed)", time.time() - t0)}
                code = self.sh([sys.executable, ".agents/skills/verify-player/scripts/combat.py", "--run", run, "--scene", "all"],
                               root, ev / "combat.txt", 1500)
                bad = [r for r in load_json(ev / "combat.json", []) if not r.get("ok")]
                scenes = sorted({str(r.get("scene")) for r in bad})
                listed = listed_parts(self.reds_path, "combat:")
                ok = code == 0 or (bool(bad) and set(scenes) <= listed)
                if code:
                    self.notes[(tag, "combat")] = (f"only listed red scenes failed: " if ok else "failed in scenes: ") + \
                        ", ".join(f"{s} ({sum(1 for r in bad if str(r.get('scene')) == s)})" for s in scenes)
                return {"combat": (ok, str(ev / "combat.json"), time.time() - t0)}
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
        groups.setdefault(spec(c)["group"], []).append(c)
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(groups))) as ex:
        futs = {ex.submit(runner.group, root, g, cs, f"{tag}-{g}"): g for g, cs in groups.items()}
        for f in concurrent.futures.as_completed(futs):
            try:
                got = f.result()
            except Exception as e:  # a driver crash is the group's failure, never the gate's crash
                got = {c: (False, f"gate error: {type(e).__name__}: {e}", 0.0) for c in groups[futs[f]]}
            for c, (ok, ev, secs) in got.items():
                # a note (listed red parts that failed, or which parts failed) travels with the evidence
                note = runner.notes.get((f"{tag}-{futs[f]}", c))
                ev = f"{ev} [{note}]" if note else ev
                say(f"{tag}: {c} {'passed' if ok else 'FAILED'} in {secs:.0f} s ({ev})")
                out[c] = (ok, ev, secs)
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
        if "mechanics" in todo and "--gate-world" not in (root / "living/tools/verify_mechanics.py").read_text():
            verdict["mechanics"] = ("unknown", "", f"main {base[:10]}'s mechanics driver predates gate integration")
            todo.remove("mechanics")
        for need in ("gate-", "--no-unit-tests"):
            if need not in (root / ".agents/skills/verify-minds/scripts/verify_minds.py").read_text():
                for c in todo:
                    verdict[c] = ("unknown", "", f"main {base[:10]}'s drivers predate the scene gate")
                todo = []
                break
    if todo:
        say(f"judging {', '.join(todo)} on main {base[:10]} (checkout {root}, build {a.main_dir}-target)")
        env = dict(runner.env, CARGO_TARGET_DIR=f"{a.main_dir}-target")
        main_runner = Runner(runner.stamp, env, runner.out, runner.reds_path)
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
    report_paths = [Path(path).resolve() for path in a.genesis_fuel_report]
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
    if not touched and not (a.force or a.genesis_only):
        say(f"skipped: {base[:10]}..{head[:10]} changes {len(paths)} path{'s' if len(paths) != 1 else ''}, none behavioural "
            f"({', '.join(paths[:5])}{', …' if len(paths) > 5 else ''})")
        record.update(result="skipped", seconds=round(time.time() - t0))
        return finish(a, record, 0)
    container = a.stdb_container
    stamp = time.strftime("%m%d%H%M%S") + "-" + secrets.token_hex(3)
    out = Path(repo) / ".local/living/verify" / f"gate-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    record["evidence"] = str(out)
    env = dict(os.environ, LIVING_STDB_CONTAINER=container, LIVING_STDB_URL=a.stdb_url, PYTHONDONTWRITEBYTECODE="1")
    env.setdefault("CARGO_TARGET_DIR", str(Path(repo) / "living/target"))
    work = "genesis publishes" if a.genesis_only else "genesis publishes and " + ", ".join(cases)
    say(f"{base[:10]}..{head[:10]} touches {len(touched)} behavioural path{'s' if len(touched) != 1 else ''} "
        f"({', '.join(touched[:4])}{', …' if len(touched) > 4 else ''}); running {work} on {container} ({a.stdb_url}), "
        f"databases verify-gate-{stamp}-*, evidence {out}")
    runner = Runner(stamp, env, out, a.reds)
    try:
        try:
            threshold = genesis_threshold(env)
            baselines = load_genesis_baselines(GENESIS_BASELINE_FILE) if threshold is not None else {}
            toolchain = genesis_toolchain(env, repo) if threshold is not None else None
            reports = {}
            for report_path in report_paths if threshold is not None else []:
                data = json.loads(report_path.read_text())
                seed = data.get("seed") if isinstance(data, dict) else None
                if seed not in GENESIS_SEEDS or seed in reports:
                    raise ValueError(f"unknown or duplicate seed in {report_path}")
                reports[seed] = report_path
        except (OSError, ValueError) as e:
            say(f"genesis setup error: {e}")
            record.update(result="genesis setup error", genesis_error=str(e))
            return finish(a, record, 2)
        if not a.genesis_only or (threshold is not None and len(reports) != len(GENESIS_SEEDS)):
            up = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container], capture_output=True, text=True)
            if up.stdout.strip() != "true":
                say(f"setup error: the SpacetimeDB container {container} is not running (--stdb-container, LIVING_GATE_STDB_CONTAINER)")
                record.update(result="setup error")
                return finish(a, record, 2)
        if threshold is None:
            say("WARNING genesis fuel check disabled by SLOP_GATE_GENESIS_CHECK=0: init fuel is not measured")
        if not a.genesis_only:
            runner.smoke_seeds = {seed for c in cases if CASES[c]["group"] == "generation" for seed in CASES[c]["seeds"]}
        measurements = []
        for seed in GENESIS_SEEDS if threshold is not None else ():
            baseline, missing = genesis_baseline(baselines, seed, toolchain)
            measurements.append(runner.genesis(repo, seed, head, threshold, baseline, reports.get(seed), toolchain, missing))
        record.update(genesis=measurements, genesis_disabled=threshold is None)
        save_json(out / "genesis.json", dict(head=head, base=base, disabled=threshold is None, toolchain=toolchain,
                                            minimum_headroom_pct=threshold, seeds=measurements))
        failed_seeds = [item["seed"] for item in measurements if not item["passed"]]
        if failed_seeds:
            record.update(result="failed genesis: " + ", ".join(failed_seeds), seconds=round(time.time() - t0))
            return finish(a, record, 1)
        if a.genesis_only:
            record.update(result="passed genesis" if threshold is not None else "genesis skipped",
                          seconds=round(time.time() - t0))
            return finish(a, record, 0)
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


def cmd_genesis_baseline(a):
    """Record seeds' measured init fuel from a gate record as their baselines for its toolchain."""
    record = load_json(a.record, {})
    measured = {g.get("seed"): g for g in record.get("seeds") or record.get("genesis") or []}
    path = Path(a.file)
    baselines = load_genesis_baselines(path) if path.exists() else {}
    for seed in a.seeds:
        g = measured.get(seed)
        if not g or g.get("error") or g.get("init_runs") != 2 or not valid_fuel(g.get("init_fuel")) or not g.get("toolchain"):
            say(f"genesis-baseline: {a.record} has no clean two-run measurement of {seed}; nothing recorded")
            return 1
        entry = dict(init_fuel=g["init_fuel"], commit=g.get("commit"), recorded=datetime.date.today().isoformat())
        if a.note:
            entry["note"] = a.note
        baselines.setdefault(seed, {})[g["toolchain"]] = entry
        say(f"genesis-baseline: {seed} {g['init_fuel'] / 1e9:.3f}e9 for {g['toolchain']} (commit {str(g.get('commit'))[:10]})")
    path.write_text(json.dumps(baselines, indent=2, sort_keys=True) + "\n")
    load_genesis_baselines(path)
    return 0


def cmd_seeds(a):
    """Seed freshness (living/tools/seed_fresh.py, files only), with the red-on-main list: a stale
    block listed as `seeds:<seed>:<block>` is reported and does not fail."""
    repo = git("rev-parse", "--show-toplevel")
    tool = Path(repo) / "living/tools/seed_fresh.py"
    if not tool.is_file():
        say("seeds: no living/tools/seed_fresh.py in this tree; skipped")
        return 0
    import tempfile
    with tempfile.TemporaryDirectory(prefix="seed-fresh-") as t:
        record = Path(a.json).resolve() if a.json else Path(t) / "seeds.json"
        got = subprocess.run([sys.executable, str(tool), "--json", str(record)], cwd=repo, capture_output=True, text=True, timeout=300)
        report = load_json(record, None)
    for line in got.stdout.splitlines() + got.stderr.splitlines():
        say(f"seeds: {line}")
    if got.returncode not in (0, 1) or report is None:
        say(f"seeds: the freshness check could not run (exit {got.returncode})")
        return 2
    stale = sorted(f"{seed}:{block}" for seed, r in report.get("stale", {}).items() for block in r.get("stale", {}))
    reds = load_json(a.reds, {})
    listed = sorted(p for p in stale if f"seeds:{p}" in reds)
    blocking = [p for p in stale if p not in listed]
    for p in listed:
        e = reds[f"seeds:{p}"]
        say(f"seeds: {p} is stale and listed red on main (owner {e.get('owner') or '-'}; {e.get('reason') or 'no reason'}); not blocking")
    if blocking:
        say(f"seeds: FAILED, stale: {', '.join(blocking)}")
        return 1
    say("seeds: passed" + (f" (listed red on main: {', '.join(listed)})" if listed else ""))
    return 0


def cmd_touches(a):
    t = behavioural(changed(a.base, a.head))
    print("\n".join(t) if t else "no behavioural path")
    return 0 if t else 1


def cmd_reds(a):
    """Print the list (read from the branch), or change it there: --add, --drop, --owner."""
    if a.add and not spec(a.add, a.skill):
        print(f"note: `recheck` cannot run {a.add} ({a.skill}); drop it by hand when it is green (reds --drop {a.add})")
    missing = []

    def change(reds):
        if a.add:
            e = reds.get(a.add) or {"case": a.add, "skill": a.skill or spec(a.add)["skill"], "first_seen": now(),
                                    "first_main": a.main, "last_seen": now(), "last_main": a.main, "times": 0}
            e.update({k: v for k, v in (("owner", a.who), ("reason", a.reason), ("last_evidence", a.evidence)) if v})
            e.setdefault("owner", None)
            reds[a.add] = e
        for case in [c for c in (a.drop, a.owner and a.owner[0]) if c]:
            if case not in reds:
                missing.append(case)
        if missing:
            return False
        if a.drop:
            reds.pop(a.drop)
        if a.owner:
            reds[a.owner[0]]["owner"] = a.owner[1]
        return True
    what = "; ".join(x for x in (a.add and f"add {a.add}", a.drop and f"drop {a.drop}",
                                 a.owner and f"owner of {a.owner[0]}: {a.owner[1]}") if x)
    if what:
        try:
            reds = update_reds(a.reds, change, f"red-on-main: {what}")
        except Exception as e:
            print(f"scene-gate: FAILED to change the shared list ({what}): {e}; nothing was changed", file=sys.stderr)
            return 1
        if missing:
            print(f"scene-gate: {', '.join(missing)} is not on the red-on-main list; nothing was changed", file=sys.stderr)
            return 1
    else:
        reds = load_json(a.reds, {})
    where = f"{REDS_REMOTE}/{REDS_BRANCH} (cache {a.reds})" if REDS_GIT else str(a.reds)
    if a.as_json:
        print(json.dumps(reds, indent=2))
    else:
        print(f"{where}:")
        print("\n".join(reds_lines(reds)))
    return 0


def cmd_recheck(a):
    """Run every case on the red-on-main list on main (origin/main by default) in main's checkout:
    a pass drops it, a failure renews it. For the daily digest, so a case nobody merges over still
    turns green."""
    repo = git("rev-parse", "--show-toplevel")
    git("fetch", "-q", "origin", "main", cwd=repo)
    base = git("rev-parse", a.main or "origin/main", cwd=repo)
    reds = load_json(a.reds, {})
    cases = [c for c in reds if spec(c, reds[c].get("skill"))]
    for c in set(reds) - set(cases):
        say(f"{c}: the gate cannot run it; drop it by hand when it is green (reds --drop {c})")
    if cases:
        root = main_checkout(repo, a.main_dir, base)
        env = dict(os.environ, LIVING_STDB_CONTAINER=a.stdb_container, LIVING_STDB_URL=a.stdb_url, PYTHONDONTWRITEBYTECODE="1",
                   CARGO_TARGET_DIR=f"{a.main_dir}-target")
        stamp = time.strftime("%m%d%H%M%S")
        out = Path(root) / ".local/living/verify" / f"gate-{stamp}"
        out.mkdir(parents=True, exist_ok=True)
        say(f"rechecking {', '.join(cases)} on main {base[:10]} (checkout {root}), databases verify-gate-{stamp}-*")
        runner = Runner(stamp, env, out, a.reds)
        try:
            got = retry_each(runner, root, cases, "recheck")
        finally:
            runner.sweep()
        for c in cases:
            if got[c][0]:
                drop_red(a.reds, c, f"recheck on main {base[:10]}")
            else:
                mark_red(a.reds, c, base, got[c][1])
    for line in reds_lines(load_json(a.reds, {})):
        say(line)
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
    r.add_argument("--genesis-fuel-report", action="append", default=[], metavar="JSON",
                   help="read a staged genesis_fuel.py report for its seed; repeat for other seeds")
    r.add_argument("--genesis-only", action="store_true", help="measure fresh publishes without running scenes")
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
    s.add_argument("--add", metavar="CASE", help="list a case known red on main (with --skill, --who, --reason, --main, --evidence)")
    s.add_argument("--skill")
    s.add_argument("--who")
    s.add_argument("--reason")
    s.add_argument("--main")
    s.add_argument("--evidence")
    s.add_argument("--drop", metavar="CASE")
    s.set_defaults(f=cmd_reds)
    rc = sub.add_parser("recheck")
    rc.add_argument("--main", help="the commit to recheck on (default origin/main, fetched)")
    rc.add_argument("--stdb-container", default=os.environ.get("LIVING_GATE_STDB_CONTAINER", "slop-trials-stdb"))
    rc.add_argument("--stdb-url", default=os.environ.get("LIVING_GATE_STDB_URL", "http://127.0.0.1:3320"))
    rc.add_argument("--main-dir", default=os.environ.get("LIVING_GATE_MAIN_DIR", str(STATE / "main")))
    rc.set_defaults(f=cmd_recheck)
    st = sub.add_parser("settle")
    st.add_argument("--record", required=True)
    st.add_argument("--main", required=True)
    st.set_defaults(f=cmd_settle)
    sd = sub.add_parser("seeds", help="seed freshness against living/seeds/worlds/ (files only), with the red-on-main list")
    sd.add_argument("--json")
    sd.set_defaults(f=cmd_seeds)
    gb = sub.add_parser("genesis-baseline", help="record seeds' init fuel from a gate record (genesis.json or gate.json)")
    gb.add_argument("record")
    gb.add_argument("seeds", nargs="+")
    gb.add_argument("--file", default=str(GENESIS_BASELINE_FILE))
    gb.add_argument("--note")
    gb.set_defaults(f=cmd_genesis_baseline)
    for p in (r, t, s, st, rc, gb, sd):  # --reds is accepted after the command too
        p.add_argument("--reds", default=argparse.SUPPRESS)
    a = ap.parse_args(argv or ["run"])
    if not getattr(a, "f", None):
        ap.print_help()
        return 2
    if (a.f is cmd_run and not a.genesis_only) or a.f in (cmd_recheck, cmd_seeds) or (a.f is cmd_reds and not (a.add or a.drop or a.owner)):
        refresh_reds(a.reds)  # the shared list from git into the cache (or the cache, said so)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
