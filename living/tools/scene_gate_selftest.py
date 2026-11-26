#!/usr/bin/env python3
"""Self-test of scene_gate.py's shared red-on-main list (the `red-on-main` branch), against a
throwaway bare remote and two clones standing for two machines (docs/TOOLING.md, "The scene gate").

Drives the real CLI: an add on one clone is seen on the other after a fetch, and the reverse;
--owner and --drop travel the same way; writers racing from both clones all land (a rejected
push fetches and retries); the branch holds one file and nothing else; a gate run reads the list
from the remote; with the remote unreachable a read falls back to the local cache and says so,
and a change fails without changing anything. Touches nothing outside a temporary folder.
Usage: scene_gate_selftest.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Barrier
from pathlib import Path

from urllib.error import HTTPError

import scene_gate
import seed_fresh
from scene_gate import (
    GENESIS_BUDGET, GENESIS_FUEL, GENESIS_RUNS, Runner, genesis_metrics, genesis_policy,
    genesis_baseline, genesis_result_line, genesis_threshold, load_genesis_baselines, staged_genesis_report,
)

GATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scene_gate.py")
failures = []


def sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd} in {cwd}: {r.stdout}{r.stderr}")
    return r.stdout


def gate(clone, cache, *args, wait=True, env_extra=None):
    env = {**os.environ, "LIVING_GATE_REDS_REPO": clone, "LIVING_GATE_REDS": cache, "LIVING_GATE_REDS_GIT": "1",
           "LIVING_GATE_PASSES": cache + ".passes", **(env_extra or {})}
    p = subprocess.Popen([sys.executable, GATE, *args], cwd=clone, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if not wait:
        return p
    out = p.communicate()[0]
    return p.returncode, out


def listed(clone, cache):
    code, out = gate(clone, cache, "reds", "--json")
    start = out.index("{")
    return json.loads(out[start:]), out


def expect(name, cond, out=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)
        print(out)


def check_run_part():
    """Case and group names become valid verify.py run-name parts (lowercase, digits, single hyphens)."""
    for name, want in (("motion_tables", "motion-tables"), ("mind-unit", "mind-unit"), ("cues", "cues"),
                       ("generation-cullet", "generation-cullet"), ("A__b:c", "a-b-c")):
        got = scene_gate.run_part(name)
        expect(f"run part: {name} -> {want}", got == want and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", got), got)


def check_genesis():
    identity = "a" * 64
    other = "b" * 64
    labels = f'db="{identity}",reducer="init"'

    def metrics(fuel):
        return (f'{GENESIS_FUEL}{{db="{other}",reducer="init"}} 999999999999\n'
                f'{GENESIS_RUNS}{{db="{other}",reducer="init"}} 1\n'
                f'{GENESIS_FUEL}{{{labels}}} {2 * fuel}\n'
                f'{GENESIS_RUNS}{{{labels}}} 2\n')

    def genesis_measurement(text, identity, threshold, baseline):
        measurement = genesis_metrics(text, identity)
        return {**measurement, **genesis_policy(measurement, threshold, baseline)}

    threshold = genesis_threshold({})
    good = genesis_measurement(metrics(108_000_000_000), identity, threshold, None)
    expect("genesis: 10% headroom passes; fuel is divided by this database's init count",
           good["passed"] and good["init_fuel"] == 108_000_000_000 and good["init_runs"] == 2, good)
    bad = genesis_measurement(metrics(108_000_000_001), identity, threshold, None)
    expect("genesis: under 10% headroom (over 90% of the budget) fails", not bad["passed"], bad)
    over = genesis_measurement(metrics(119_000_000_000), identity, threshold, None)
    expect("genesis: an over-90% seed with no recorded baseline fails and says so",
           not over["passed"] and "no recorded baseline" in over["failures"][0], over)
    line = genesis_result_line(dict(seed="island", commit="c" * 40, budget=GENESIS_BUDGET, **over))
    expect("genesis: the result line names the fuel, limit and verdict",
           line.startswith("genesis island: init 119.000e9 fuel per run (2 init runs)") and "limit 108.000e9" in line
           and line.endswith("— FAIL"), line)
    expect("genesis: over 50% of the budget warns", len(good["warnings"]) == 1 and "over 50%" in good["warnings"][0], good)
    quiet = genesis_measurement(metrics(60_000_000_000), identity, threshold, None)
    expect("genesis: 50% of the budget passes without a warning", quiet["passed"] and not quiet["warnings"], quiet)
    override = genesis_threshold({"SLOP_GATE_GENESIS_HEADROOM": "5"})
    raised = genesis_measurement(metrics(110_000_000_000), identity, override, None)
    expect("genesis: configured headroom is used", raised["passed"], raised)
    expect("genesis: check can be disabled", genesis_threshold({"SLOP_GATE_GENESIS_CHECK": "0"}) is None)
    for bad_value in ("abc", "-1", "101"):
        try:
            genesis_threshold({"SLOP_GATE_GENESIS_HEADROOM": bad_value})
        except ValueError:
            expect(f"genesis: SLOP_GATE_GENESIS_HEADROOM={bad_value} is refused", True)
        else:
            expect(f"genesis: SLOP_GATE_GENESIS_HEADROOM={bad_value} is refused", False)
    baseline = 119_500_000_000
    for fuel, passed in ((119_000_000_000, True), (119_619_499_999, True), (119_619_500_000, True),
                         (119_619_500_001, False), (119_900_000_000, False)):
        result = genesis_measurement(metrics(fuel), identity, threshold, baseline)
        expect(f"genesis: must not rise, baseline 119.5e9: {fuel / 1e9:.9f}e9 {'passes' if passed else 'fails'}",
               result["passed"] == passed and result["policy"] == "baseline + 0.1%", result)
    graduated = genesis_measurement(metrics(108_000_000_000), identity, threshold, baseline)
    expect("genesis: enough headroom uses the standard rule even with a baseline",
           graduated["passed"] and graduated["policy"] == "10% minimum headroom", graduated)
    for name in (GENESIS_FUEL, GENESIS_RUNS):
        try:
            genesis_measurement("\n".join(line for line in metrics(108_000_000_000).splitlines()
                                          if not line.startswith(f"{name}{{{labels}}}")), identity, threshold, None)
        except ValueError as error:
            expect(f"genesis: missing {name} fails loudly", name in str(error), error)
        else:
            expect(f"genesis: missing {name} fails loudly", False)


def check_genesis_baselines():
    """Baselines are per seed and per rustc: another toolchain's module counts other fuel."""
    ours, theirs = "rustc 1.99.1 (58cf8f9c3 2026-10-13)", "rustc 1.97.1 (aaaaaaaaa 2026-08-01)"
    with tempfile.TemporaryDirectory(prefix="genesis-baselines-selftest-") as t:
        path = Path(t) / "baselines.json"
        path.write_text(json.dumps({"island": {theirs: {"init_fuel": 118_900_000_000, "commit": "c" * 40}}}))
        baselines = load_genesis_baselines(path)
        baseline, missing = genesis_baseline(baselines, "island", ours)
        expect("baselines: another rustc's baseline is not used, and the note names it",
               baseline is None and theirs in missing, missing)
        result = genesis_policy(dict(init_fuel=118_000_000_000, init_runs=2, steps=[]), 10, baseline, missing)
        expect("baselines: an over-90% seed with a baseline only for another rustc fails and says which",
               not result["passed"] and "recorded for rustc 1.97.1" in result["failures"][0], result)
        expect("baselines: the recorded rustc's baseline is used",
               genesis_baseline(baselines, "island", theirs) == (118_900_000_000, ""))
        for bad in ({"island": 118e9}, {"nowhere": {ours: {"init_fuel": 1}}}, {"island": {ours: {"init_fuel": 121e9}}},
                    {"island": {"gcc": {"init_fuel": 1}}}, []):
            path.write_text(json.dumps(bad))
            try:
                load_genesis_baselines(path)
            except ValueError:
                expect(f"baselines: refuses {json.dumps(bad)[:40]}", True)
            else:
                expect(f"baselines: refuses {json.dumps(bad)[:40]}", False)
        # genesis-baseline records from a gate's genesis.json, for that record's rustc, and refuses a broken one
        record = Path(t) / "genesis.json"
        island = dict(seed="island", commit="c" * 40, toolchain=ours, init_fuel=117_812_345_678.0, init_runs=2, passed=False)
        world = dict(seed="world", commit="c" * 40, toolchain=ours, init_runs=1, error="missing metric", passed=False)
        record.write_text(json.dumps(dict(seeds=[island, world])))
        path.write_text(json.dumps({"island": {theirs: {"init_fuel": 118_900_000_000}}}))
        r = subprocess.run([sys.executable, GATE, "genesis-baseline", str(record), "island", "--file", str(path)],
                           capture_output=True, text=True)
        saved = load_genesis_baselines(path)
        expect("genesis-baseline: records the seed for the record's rustc, keeping the other rustc's",
               r.returncode == 0 and saved["island"][ours]["init_fuel"] == 117_812_345_678.0
               and saved["island"][theirs]["init_fuel"] == 118_900_000_000, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, GATE, "genesis-baseline", str(record), "world", "--file", str(path)],
                           capture_output=True, text=True)
        expect("genesis-baseline: refuses a seed without a clean two-run measurement",
               r.returncode == 1 and "world" not in load_genesis_baselines(path), r.stdout + r.stderr)


def check_genesis_live():
    """Runner.genesis on a fake server: the launch writes state.json, the metrics come from a string."""
    identity = "d" * 64
    commit = "e" * 40

    def metrics(fuel_total, runs):
        lines = [f'{GENESIS_FUEL}{{db="{"f" * 64}",reducer="init"}} 5',
                 f'{GENESIS_RUNS}{{db="{"f" * 64}",reducer="init"}} 2']
        if fuel_total is not None:
            lines.append(f'{GENESIS_FUEL}{{db="{identity}",reducer="init"}} {fuel_total}')
        if runs is not None:
            lines.append(f'{GENESIS_RUNS}{{db="{identity}",reducer="init"}} {runs}')
        return "\n".join(lines) + "\n"

    class Fake(Runner):
        def __init__(self, root, published, metrics_text, cleanup_code=0):
            super().__init__("fixture", dict(os.environ, LIVING_STDB_URL="http://fake", CARGO_TARGET_DIR="/nowhere"),
                             root, root / "reds.json")
            self.published, self.metrics_text, self.cleanup_code, self.cleaned = published, metrics_text, cleanup_code, []
            self.launched = False

        def sh(self, cmd, root, log, timeout, stdout=None):
            run = cmd[cmd.index("--run") + 1]
            if cmd[2] == "launch":
                self.launched = True
                state = Path(root) / ".local/living/verify" / run / "state.json"
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text(json.dumps(dict(published=self.published, db=f"verify-{run}",
                                                 **({"database_identity": identity} if self.published else {}))))
                return 0 if self.published else 1
            if cmd[2] == "cleanup":
                self.cleaned.append(run)
                return self.cleanup_code
            raise AssertionError(cmd)

    def http(runner):
        def get(url):
            if url.endswith("/identity"):
                if runner.launched:  # the name stays reserved by a refused publish
                    return identity
                raise HTTPError(url, 404, "not found", None, None)
            assert url == "http://fake/v1/metrics", url
            return runner.metrics_text
        return get

    original = scene_gate.genesis_http
    try:
        with tempfile.TemporaryDirectory(prefix="genesis-live-selftest-") as t:
            root = Path(t)
            cases = [
                ("a fresh publish's fuel and two init runs pass", True, metrics(2 * 17_300_000_000, 2), 0, None,
                 lambda r: r["passed"] and r["init_fuel"] == 17_300_000_000 and r["init_runs"] == 2),
                ("a missing fuel metric fails loudly", True, metrics(None, 2), 0, None,
                 lambda r: not r["passed"] and GENESIS_FUEL in r["error"]),
                ("a missing call-count metric fails loudly", True, metrics(2 * 17_300_000_000, None), 0, None,
                 lambda r: not r["passed"] and GENESIS_RUNS in r["error"]),
                ("one init run on a fresh publish fails", True, metrics(17_300_000_000, 1), 0, None,
                 lambda r: not r["passed"] and "expected two init runs" in r["error"]),
                ("over the budget with a baseline but a refused publish fails, with its fuel", None,
                 metrics(GENESIS_BUDGET, 1), 0, 119_000_000_000,
                 lambda r: not r["passed"] and r["init_fuel"] == GENESIS_BUDGET and "fresh publish not confirmed" in r["error"]),
                ("a failed pause-confirm-delete fails", True, metrics(2 * 17_300_000_000, 2), 1, None,
                 lambda r: not r["passed"] and "pause-confirm-delete failed" in r["error"]),
            ]
            for i, (name, published, text, cleanup_code, baseline, ok) in enumerate(cases):
                runner = Fake(root, published, text, cleanup_code)
                runner.stamp = f"fixture{i}"
                scene_gate.genesis_http = http(runner)
                result = runner.genesis(root, "island", commit, 10, baseline)
                fields = {"seed", "commit", "init_fuel", "init_runs", "steps", "largest_step_share", "budget"}
                named = name.startswith(("a missing", "a failed pause")) or fields <= set(result)
                expect(f"genesis live: {name}", ok(result) and named
                       and runner.cleaned == ([f"gate-fixture{i}-fuel-island"] if published else []), result)
    finally:
        scene_gate.genesis_http = original


def check_seed_fresh():
    """seed_fresh.py on a throwaway worlds tree: each block stale and fresh, by name."""
    original = seed_fresh.ROOT, seed_fresh.WORLDS, dict(seed_fresh.PLAN_CHECKS), seed_fresh.compile_seed
    with tempfile.TemporaryDirectory(prefix="seed-fresh-selftest-") as t:
        root = Path(t)
        wd = root / "living/seeds/worlds/town"
        (wd / "sheets").mkdir(parents=True)
        looks = {"looks": {"generation": "c4-new", "pool": [1]}, "residents": {"Ann": "a-1", "Bo": "b-1"}}
        ways = {"common": {"eat": 1}, "occupations": {"smith": 2}, "work": {"smith": ["forge"]}}
        sheets = {"Ann": {"narrative": "Ann's story"}, "Bo": {"narrative": "Bo's story"}}
        seed = {"looks": dict(looks["looks"]), "ways": {"common": {"eat": 1, "old": 0}, "occupations": {"smith": 2}},
                "town_life": {"work": {"smith": ["forge"], "baker": ["oven"]}},
                "towns": [{"name": "T", "residents": [{"name": n, "look": looks["residents"][n], "sheet": sheets[n]} for n in sheets]}]}
        (wd / "cast.json").write_text(json.dumps({"into": "town"}))
        (wd / "looks.json").write_text(json.dumps(looks))
        (wd / "ways.json").write_text(json.dumps(ways))
        (wd / "sheets/house.json").write_text(json.dumps(sheets))
        seed_path = root / "living/seeds/town.json"

        def stale(change=None):
            s = json.loads(json.dumps(seed))
            if change:
                change(s)
            seed_path.write_text(json.dumps(s))
            return seed_fresh.check_world(wd)

        # The fixture world is not a real authored world, so the whole-seed compile is the
        # fixture's own seed as its sources would compile it (by default) or what a case says.
        compiled = {"seed": seed}
        seed_fresh.compile_seed = lambda wd, into: compiled["seed"] if isinstance(compiled["seed"], str) else json.loads(json.dumps(compiled["seed"]))
        seed_fresh.ROOT, seed_fresh.WORLDS = root, root / "living/seeds/worlds"
        try:
            expect("seed freshness: a seed as compiled from its sources is fresh", stale()[:2] == ("town", []), stale())
            cases = [
                ("an older look generation", lambda s: s["looks"].update(generation="c4-old"), "looks", "look generation c4-old in the seed, c4-new"),
                ("the same generation with another pool", lambda s: s["looks"].update(pool=[2]), "looks", "same generation c4-new"),
                ("a resident's look", lambda s: s["towns"][0]["residents"][1].update(look="b-0"), "looks", "1 residents' look differ"),
                ("a way", lambda s: s["ways"]["occupations"].update(smith=3), "ways", "ways.occupations.smith"),
                ("a workplace", lambda s: s["town_life"]["work"].update(smith=["mill"]), "ways", "town_life.work.smith"),
                ("a resident without a drafted sheet", lambda s: s["towns"][0]["residents"].append({"name": "Cy", "sheet": {}}), "residents", "1 residents have no drafted sheet"),
                ("a drafted sheet with no resident", lambda s: s["towns"][0]["residents"].pop(), "residents", "1 drafted sheets have no resident"),
                ("a sheet's narrative", lambda s: s["towns"][0]["residents"][0]["sheet"].update(narrative="old"), "residents", "sheet narratives differ"),
            ]
            for name, change, block, words in cases:
                got = stale(change)[1]
                named = [g for g in got if g[0] != "compile"]
                expect(f"seed freshness: {name} is a stale {block} block, and says so",
                       len(named) == 1 and named[0][0] == block and words in named[0][1], got)
                expect(f"seed freshness: {name} also differs from a fresh compile", any(g[0] == "compile" for g in got), got)
            # A field the compiler learned after the seed was compiled: only the whole-seed compile sees it.
            learned = json.loads(json.dumps(seed))
            learned["towns"][0]["residents"][0]["sheet"]["pastimes"] = ["fishing"]
            compiled["seed"] = learned
            got = stale()[1]
            expect("seed freshness: a field only a fresh compile writes is a stale compile block, and says where",
                   len(got) == 1 and got[0][0] == "compile" and "pastimes only in the source" in got[0][1], got)
            compiled["seed"] = "author_world.py town --compile-only exit 1: no bible.md"
            got = stale()[1]
            expect("seed freshness: a compile that fails is a stale compile block with its error",
                   len(got) == 1 and got[0][0] == "compile" and "no bible.md" in got[0][1], got)
            compiled["seed"] = seed
            # A derived seed (its run names the world, its file is not the world's seed) carries the
            # compiled world's residents exactly.
            variant = json.loads(json.dumps(seed))
            variant.update(run="town", rules={"x": 1})
            variant_path = root / "living/seeds/town-variant.json"
            variant_path.write_text(json.dumps(variant))
            expect("seed freshness: a derived seed with the compiled residents is fresh", seed_fresh.check_derived({"town": seed}) == [],
                   seed_fresh.check_derived({"town": seed}))
            variant["towns"][0]["residents"][0]["sheet"]["pastimes"] = ["old"]
            variant_path.write_text(json.dumps(variant))
            got = seed_fresh.check_derived({"town": seed})
            expect("seed freshness: a derived seed whose residents differ is stale, and names the run",
                   len(got) == 1 and got[0][0] == "town-variant" and got[0][1] == "town" and "1 residents differ" in got[0][2], got)
            variant_path.unlink()
            tool = root / "plan_check.py"
            tool.write_text("import sys; print('differs: plan.json'); sys.exit(1)")
            seed_fresh.PLAN_CHECKS["town"] = [str(tool), "--check"]
            got = stale()[1]
            expect("seed freshness: a plan compiler's failing --check is a stale plan block",
                   len(got) == 1 and got[0][0] == "plan" and "differs: plan.json" in got[0][1], got)
            expect("seed freshness: the recompile command names the plan compiler and the seed compiler",
                   seed_fresh.recompile("town") == f"python3 {tool} && python3 living/tools/author_world.py town --compile-only")
        finally:
            seed_fresh.ROOT, seed_fresh.WORLDS = original[:2]
            seed_fresh.PLAN_CHECKS.clear()
            seed_fresh.PLAN_CHECKS.update(original[2])
            seed_fresh.compile_seed = original[3]


def check_flake_scope():
    """A passing rerun excuses a first failure only when every failed part matches the case's
    recorded flake (general coordinator, 2026-11-22: a combat `wolves` failure was excused under
    combat's unrelated flake). The parts come from each case's own result files."""
    cs, fv = scene_gate.case_status, scene_gate.flake_verdict
    tick = "pause stops ticks, housekeeping and completion"
    expect("flakes: a recorded flake part, rerun passing, is a flaky-pass that does not block",
           cs("tick", False, True, [tick])[:2] == ("flaky-pass", False), cs("tick", False, True, [tick]))
    wolves = "wolves:bold wolves attack a healthy adult player"
    expect("flakes: combat failing in wolves, rerun passing, blocks as fail-unrecorded-flake",
           cs("combat", False, True, [wolves])[:2] == ("fail-unrecorded-flake", True), cs("combat", False, True, [wolves]))
    expect("flakes: a recorded part plus an unrecorded one blocks",
           cs("tick", False, True, [tick, "nominal 60 Hz ticks advance"])[:2] == ("fail-unrecorded-flake", True))
    expect("flakes: unknown failed parts (no result file), rerun passing, blocks",
           cs("tick", False, True, None)[:2] == ("fail-unrecorded-flake", True) and "could not be read" in cs("tick", False, True, None)[2])
    expect("flakes: a case with no flake record, rerun passing, blocks",
           cs("sight", False, True, ["anything"])[:2] == ("fail-unrecorded-flake", True) and "no flake is recorded" in fv("sight", ["x"])[1])
    expect("flakes: a pass is a pass; a double failure goes to main's verdict as before",
           cs("tick", True, None, None)[:2] == ("pass", False) and cs("tick", False, False, [tick], "red-on-main")[:2] == ("red-on-main", False)
           and cs("tick", False, False, [tick], "branch")[:2] == ("fail", True) and cs("tick", False, False, [tick])[:2] == ("fail-unjudged", True))
    expect("flakes: the recorded mind tests and minds timeouts match by name; others do not",
           fv("mind-unit", ["llm::tests::unreachable_provider_holds_calls"])[0]
           and not fv("mind-unit", ["llm::tests::something_else"])[0]
           and fv("dealings", ["RuntimeError: timed out after 60s waiting for demand record"])[0]
           and not fv("dealings", ["RuntimeError: timed out after 90s waiting for demand met"])[0])
    expect("flakes: every recorded flake has a why and a parts list; combat excuses nothing",
           all(isinstance(c.get("flaky"), dict) and "why" in c["flaky"] and isinstance(c["flaky"].get("parts"), list)
               for c in scene_gate.CASES.values() if "flaky" in c) and scene_gate.CASES["combat"]["flaky"]["parts"] == [])
    with tempfile.TemporaryDirectory(prefix="flake-selftest-") as t:
        root = Path(t)
        (root / "failure.txt").write_text("Traceback (most recent call last):\n  File \"x.py\", line 1, in f\n"
                                          "    assert len([e for e in run.exchanges() if e['purpose'] == 'talk']) == count\nAssertionError\n")
        parts = scene_gate.minds_parts({"status": "fail", "error": "AssertionError: "}, root)
        expect("flakes: a bare minds assert is named by its source line, and conversation's recorded one matches",
               parts and parts[-1].startswith("AssertionError at: assert len(") and fv("conversation", parts)[0], parts)
        reds = root / "reds.json"
        reds.write_text("{}")

        class Fake(Runner):
            def __init__(self):
                super().__init__("fixture", dict(os.environ), root, reds)

            def world(self, root, run, seed, log, *args):
                return True

            def cleanup(self, root, run, log):
                return 0

            def sh(self, cmd, cwd, log, timeout, stdout=None, env=None):
                ev = Path(cwd) / ".local/living/verify" / f"gate-fixture-{self.tag}"
                ev.mkdir(parents=True, exist_ok=True)
                if any(str(x).endswith("combat.py") for x in cmd):
                    (ev / "combat.json").write_text(json.dumps([{"scene": "wolves", "check": "bold wolves attack a healthy adult player", "ok": False},
                                                                {"scene": "kill", "check": "dies", "ok": True}]))
                    return 1
                if any(str(x).endswith("scenes.py") for x in cmd):
                    (ev / "tick-results.json").write_text(json.dumps({"checks": {tick: {"passed": False}, "scene actors created": {"passed": True}}}))
                    return 1
                return 0

        r = Fake()
        r.tag = "a-player"
        got = scene_gate.run_cases(r, root, ["combat"], "a")
        expect("flakes: combat's failed parts are read from combat.json as scene:check",
               r.case_parts.get(("a", "combat")) == [wolves], (got, r.case_parts))
        r.tag = "a-core"
        scene_gate.run_cases(r, root, ["tick"], "a")
        expect("flakes: a verify-core scene's failed parts are its failed checks",
               r.case_parts.get(("a", "tick")) == [tick], r.case_parts)

        class Raised(Fake):
            def sh(self, cmd, cwd, log, timeout, stdout=None, env=None):
                ev = Path(cwd) / ".local/living/verify" / f"gate-fixture-{self.tag}"
                ev.mkdir(parents=True, exist_ok=True)
                if any(str(x).endswith("scenes.py") for x in cmd):
                    (ev / "tick-results.json").write_text(json.dumps({"checks": {"scene actors created": {"passed": True}},
                                                                     "error": "TimeoutError: tick: condition did not become true in 30 s"}))
                    return 1
                return 0

        r2 = Raised()
        r2.tag = "a-core"
        scene_gate.run_cases(r2, root, ["tick"], "a")
        raised = r2.case_parts.get(("a", "tick"))
        expect("flakes: a scene that stopped on an exception names it as a failed part (not 'could not be read')",
               raised == ["error: TimeoutError: tick: condition did not become true in 30 s"]
               and "could not be read" not in scene_gate.flake_verdict("tick", raised)[1], raised)


def check_generation_group():
    """The generation cases: the genesis worlds' smoke first, a world of their own otherwise; a
    failing check passes only when the red-on-main list holds it as a part."""
    with tempfile.TemporaryDirectory(prefix="generation-selftest-") as t:
        root = Path(t)
        reds = root / "reds.json"
        reds.write_text(json.dumps({"generation-cullet:cullet-laws:laws composed": {"case": "generation-cullet:cullet-laws:laws composed"}}))

        class Fake(Runner):
            def __init__(self, smokes):
                super().__init__("fixture", dict(os.environ), root, reds)
                self.smokes, self.launched = smokes, []

            def world(self, root, run, seed, log, *args):
                self.launched.append(seed)
                return True

            def generation_smoke(self, root, run):
                return self.smokes[run.rsplit("-", 1)[-1] if not run.endswith("cullet-laws") else "cullet-laws"]

            def cleanup(self, root, run, log):
                return 0

        smokes = {"world": ([], "w"), "island": ([], "i"), "cullet": ([], "c"), "laws": ([], "l"),
                  "cullet-laws": (["laws composed"], "cl")}
        runner = Fake(smokes)
        runner.smoke = {(str(root), "world"): ([], "w"), (str(root), "cullet"): ([], "c"), (str(root), "cullet-laws"): (["laws composed"], "cl")}
        got = runner.group(root, "generation", ["generation-default", "generation-island", "generation-cullet"], "a-generation")
        expect("generation: the first pass reads the genesis worlds' smoke, launching only for a seed without one",
               runner.launched == ["island"] and got["generation-default"][0] and got["generation-island"][0], (runner.launched, got))
        expect("generation: a failing check listed red on main as a part passes, and the note names it",
               got["generation-cullet"][0] and "only listed red checks failed: cullet-laws:laws composed"
               in runner.notes[("a-generation", "generation-cullet")], runner.notes)
        smokes["cullet"] = (["the cases are of the world's generation"], "c")
        runner = Fake(smokes)
        got = runner.group(root, "generation", ["generation-cullet"], "b-generation-cullet-generation")
        expect("generation: a retry launches its own worlds, and an unlisted failing check fails the case",
               runner.launched == ["cullet", "cullet-laws"] and not got["generation-cullet"][0]
               and "cullet:the cases are of the world's generation" in runner.notes[("b-generation-cullet-generation", "generation-cullet")],
               (runner.launched, got, runner.notes))
        smokes["world"] = (None, "no result")
        got = Fake(smokes).group(root, "generation", ["generation-default"], "b-x")
        expect("generation: a smoke that did not run fails the case", not got["generation-default"][0], got)


def check_staged_genesis():
    commit = "c" * 40
    step = dict(phase="terrain", label="generate 1", reducer="genesis_step", fuel=108_000_000_000)
    report = dict(seed="island", commit=commit, budget=GENESIS_BUDGET, init_runs=2,
                  init_fuel=14_000_000_000, steps=[step], largest_step_share=0.9)
    data = staged_genesis_report(report, "island", commit)
    result = genesis_policy(data, 10, None)
    expect("staged genesis: step at 90% passes with a warning", result["passed"] and len(result["warnings"]) == 1,
           result)
    step["fuel"] += 1
    report["largest_step_share"] = step["fuel"] / GENESIS_BUDGET
    result = genesis_policy(staged_genesis_report(report, "island", commit), 10, 119_500_000_000)
    expect("staged genesis: step over 90% fails even when an init baseline exists",
           not result["passed"] and "terrain / generate 1 (genesis_step)" in result["failures"][0], result)
    step["fuel"] = 60_000_000_000
    report["largest_step_share"] = 0.5
    result = genesis_policy(staged_genesis_report(report, "island", commit), 10, None)
    expect("staged genesis: step at 50% passes without warnings", result["passed"] and not result["warnings"], result)
    for change in (dict(commit="d" * 40), dict(budget=100), dict(largest_step_share=0.1), dict(steps=[])):
        try:
            staged_genesis_report({**report, **change}, "island", commit)
        except ValueError:
            expect(f"staged genesis: rejects invalid {next(iter(change))}", True)
        else:
            expect(f"staged genesis: rejects invalid {next(iter(change))}", False)

    with tempfile.TemporaryDirectory(prefix="staged-genesis-selftest-") as t:
        root = Path(t)
        tool = root / "living/tools/genesis_fuel.py"
        tool.parent.mkdir(parents=True)
        tool.write_text(
            "import sys\n"
            "assert sys.argv[1:] == ['--seed', 'island']\n"
            f"print({json.dumps(report)!r})\n"
            "print('progress is on stderr', file=sys.stderr)\n"
        )
        runner = Runner("fixture", os.environ.copy(), root, root / "reds.json")
        result = runner.genesis(root, "island", commit, 10, None)
        expect("staged genesis: detects and runs the reporter, keeping stderr out of its JSON",
               result["passed"] and result["steps"] == report["steps"]
               and "progress is on stderr" in (root / "genesis-island.log").read_text(), result)


def check_render_selection():
    """Drawing paths select the render group by half: character paths looks, hair and seat; camera,
    LOD and sight paths camera-faces, camera-lod and far; shaders, the manifest and the verify-ui
    drivers (or one path of each half) all six; other paths none."""
    sel = scene_gate.render_selection
    char, cam = ["looks", "hair", "seat"], ["camera-faces", "camera-lod", "far"]
    expect("render halves: the cases split three and three, character then camera",
           scene_gate.HALF_CASES == {"character": char, "camera": cam} and scene_gate.RENDER_CASES == char + cam,
           str(scene_gate.HALF_CASES))
    g = "living/game/src/"
    for path, want in (
            *((g + p, char) for p in ("characters/compose.rs", "characters/palette.rs", "characters/book.rs", "handmade.rs",
                                     "compose.rs", "lookdev.rs", "looks.rs", "style.rs", "characters.rs", "bodies.rs",
                                     "anim.rs", "gait.rs", "ik.rs", "twist.rs", "mouth.rs", "facing.rs", "post.rs",
                                     "hair.rs", "characters/hair_cards.rs")),
            *((g + p, cam) for p in ("camera.rs", "perf.rs", "fade.rs", "envs.rs", "sightfield.rs", "sightedge.rs")),
            *((g + p, char + cam) for p in ("toon.wesl", "toon_light.wesl", "edges.wesl", "terrain.wesl", "sky.wesl",
                                           "water.wesl", "record_frames.wesl", "hair.wesl")),
            ("living/game/Cargo.toml", char + cam), (".agents/skills/verify-ui/scripts/check.py", char + cam),
            (".agents/skills/verify-ui/scripts/drive.py", char + cam)):
        got = sel([path])
        expect(f"render selection: {path} -> {'all six' if len(want) == 6 else want[0] + ' half'}", got == want, str(got))
    for path in ("living/game/src/ui/win.rs", "living/game/src/net.rs", "living/game/src/characters.rs.orig",
                 "living/game/src/sub/toon.wesl", "docs/CHARACTERS.md", "living/authority/src/frame.rs",
                 ".agents/skills/verify-ui/SKILL.md", "living/game/assets/envs/cullet.json", "living/game/src/sight.rs"):
        expect(f"render selection: {path} draws nothing", sel([path]) == [] and scene_gate.render_halves([path]) == [], str(sel([path])))
    for paths, want, name in (
            ([g + "camera.rs", g + "handmade.rs"], char + cam, "a character and a camera path together select both halves"),
            ([g + "handmade.rs", g + "characters/outfit.rs", "docs/TOOLING.md"], char, "two character paths and a doc select the character half"),
            ([g + "fade.rs", g + "ui/win.rs", "living/authority/src/lib.rs"], cam, "a camera path beside non-drawing paths selects the camera half"),
            ([g + "perf.rs", g + "toon.wesl"], char + cam, "a camera path and a shader select both halves")):
        got = sel(paths)
        expect(f"render selection: {name}", got == want and scene_gate.halves_of(got) == scene_gate.render_halves(paths), str(got))
    expect("render selection: the render cases run in the render group on their seeds",
           all(scene_gate.CASES[c]["group"] == "render" and scene_gate.CASES[c]["world"] in scene_gate.RENDER_SEEDS for c in char + cam)
           and scene_gate.CASES["looks"]["world"] == "cullet")

    class A:
        cases, force, render_only = None, False, False
    expect("plan: a client-only shader diff runs both halves alone (no scenes, no genesis)",
           scene_gate.plan_cases(A, [g + "toon.wesl"], []) == ([], scene_gate.RENDER_CASES))
    expect("plan: a character diff runs the character half alone", scene_gate.plan_cases(A, [g + "handmade.rs"], []) == ([], char))
    expect("plan: a camera diff runs the camera half alone", scene_gate.plan_cases(A, [g + "camera.rs"], []) == ([], cam))
    scenes, render = scene_gate.plan_cases(A, ["living/authority/src/lib.rs"], ["living/authority/src/lib.rs"])
    expect("plan: a behavioural diff runs the scenes, no render case and no smoke",
           render == [] and "tick" in scenes and not set(scenes) & {"render-smoke", *scene_gate.RENDER_CASES}, str(scenes))
    expect("plan: a battle-fixture diff runs sides_battle", "sides_battle" in scenes, str(scenes))
    expect("plan: a battle-fixture diff runs sides_layout after sides_battle", "sides_layout" in scenes and scenes.index("sides_layout") > scenes.index("sides_battle"), str(scenes))
    scenes, render = scene_gate.plan_cases(A, ["living/authority/src/act.rs"], ["living/authority/src/act.rs"])
    expect("plan: a behavioural diff outside its paths skips sides_battle", "tick" in scenes and "sides_battle" not in scenes, str(scenes))
    scenes, render = scene_gate.plan_cases(A, ["living/authority/src/lib.rs", g + "sightedge.rs"], ["living/authority/src/lib.rs"])
    expect("plan: a behavioural and camera diff runs the scenes and the camera half", "tick" in scenes and render == cam, str(render))
    expect("plan: a diff that touches neither runs nothing", scene_gate.plan_cases(A, ["docs/TOOLING.md"], []) == ([], []))
    A.render_only = True
    expect("plan: --render-only runs the selected half and no scene",
           scene_gate.plan_cases(A, [g + "envs.rs", "living/authority/src/lib.rs"], ["living/authority/src/lib.rs"]) == ([], cam))
    A.force = True
    expect("plan: --render-only --force runs all six (a manual full pass), whatever the diff selects",
           scene_gate.plan_cases(A, ["living/authority/src/lib.rs"], ["living/authority/src/lib.rs"]) == ([], scene_gate.RENDER_CASES)
           and scene_gate.plan_cases(A, [g + "handmade.rs"], []) == ([], scene_gate.RENDER_CASES))
    A.render_only, A.force, A.cases = False, False, "tick,hair,render-smoke"
    expect("plan: --cases names them exactly", scene_gate.plan_cases(A, [], []) == (["tick", "render-smoke"], ["hair"]))


def check_speech_selection():
    """The speech group (say, heard_first, audience) and the steering group (flee_wall,
    pursue_last_seen): selected by their paths, and the speech group also by speech words in the
    changed hunks of brain.rs, perceive.rs and skills.rhai (gate-say-path: say-once changed
    speech.rs and brain.rs, and no gate case ran `say` for ten days)."""
    class A:
        cases, force, render_only = None, False, False
    speech, steering = ["say", "heard_first", "audience"], ["flee_wall", "pursue_last_seen"]
    brain, rhai = "living/authority/src/brain.rs", "living/scripts/skills.rhai"
    expect("speech: its cases run in their own groups on fresh default-seed worlds",
           all(scene_gate.CASES[c]["group"] == "speech" for c in speech) and all(scene_gate.CASES[c]["group"] == "steering" for c in steering))

    def plan(paths, hunks=None):
        return scene_gate.plan_cases(A, paths, scene_gate.behavioural(paths), hunks)[0]
    for path in ("living/authority/src/speech.rs", "living/authority/src/earshot.rs", "living/rules/src/normalize.rs",
                 "living/rules/src/script/speech.rs"):
        got = plan([path], {})
        expect(f"speech: {path} selects the speech group", set(speech) <= set(got) and not set(steering) & set(got), str(got))
    for path in ("living/authority/src/motion.rs", "living/rules/src/steer.rs", "living/rules/src/nav.rs"):
        got = plan([path], {})
        expect(f"steering: {path} selects the steering group", set(steering) <= set(got) and not set(speech) & set(got), str(got))
    got = plan(["living/authority/src/act.rs"], {})
    expect("speech: a behavioural diff outside both selects neither", "tick" in got and not set(speech + steering) & set(got), str(got))
    say_once = "@@ -745,6 +745,12 @@\n+                if to != 0 && self.from_mind() && crate::speech::said_to_recently(self.ctx, self.me.id, to, &s.text, self.now) {"
    got = plan([brain], {brain: say_once})
    expect("speech: say-once's brain.rs hunk (said_to_recently) selects the speech group", set(speech) <= set(got), str(got))
    got = plan([brain], {brain: "@@ -10,3 +10,3 @@\n-    let cap = 256;\n+    let cap = 2048;\n     prune_familiar(ctx);"})
    expect("speech: a brain.rs hunk with no speech word does not", not set(speech) & set(got), str(got))
    got = plan([rhai], {rhai: "@@ -21,1 +21,1 @@\n-        whisper_speech: 0.2,\n+        whisper_speech: 0.3,"})
    expect("speech: a skills.rhai hunk naming a way of speaking selects it (identifiers by their parts)", set(speech) <= set(got), str(got))
    got = plan([rhai], {rhai: "@@ -21,1 +21,1 @@\n-        slow_radius: 1.2,\n+        slow_radius: 1.0,"})
    expect("speech: a skills.rhai hunk with no speech word does not", not set(speech) & set(got), str(got))
    got = plan([brain])
    expect("speech: without hunk text a touched hunk file selects it (the safe side)", set(speech) <= set(got), str(got))
    acting, fight = ["act_gaps", "act_replace", "truthful_refusals"], ["committed", "dodge_told", "health_seen", "seize", "outcomes"]
    expect("speech: speak and told run in the speech group as verify-player scripts",
           all(scene_gate.CASES[c]["group"] == "speech" and scene_gate.CASES[c]["skill"] == "verify-player" for c in ("speak", "told")))
    expect("step 1: the acting and fight groups, outcomes on its own island world",
           all(scene_gate.CASES[c]["group"] == "acting" for c in acting)
           and all(scene_gate.CASES[c]["group"] == "fight" for c in fight[:4])
           and scene_gate.CASES["outcomes"]["group"] == "outcomes")
    for path in ("living/authority/src/acts.rs", "living/rules/src/acts.rs", "living/authority/src/outcomes.rs", "living/rules/src/outcome.rs"):
        got = plan([path], {})
        expect(f"step 1: {path} selects the acting group", set(acting) <= set(got) and not set(fight) & set(got), str(got))
    for path in ("living/authority/src/combat.rs", "living/authority/src/codes.rs", "living/rules/src/combat.rs"):
        got = plan([path], {})
        expect(f"step 1: {path} selects the fight group and outcomes", set(fight) <= set(got) and not set(acting) & set(got), str(got))
    got = plan(["living/authority/src/act.rs"], {})
    expect("step 1: act.rs alone (too broad) selects neither", not set(acting + fight) & set(got), str(got))
    expect("cap: 10 groups at once by default (LIVING_GATE_GROUPS unset)",
           os.environ.get("LIVING_GATE_GROUPS") is not None or scene_gate.GROUP_CAP == 10, str(scene_gate.GROUP_CAP))
    cap = scene_gate.GROUP_CAP
    try:
        scene_gate.GROUP_CAP = 0
        uncapped = scene_gate.workers(9)
        scene_gate.GROUP_CAP = 4
        expect("cap: LIVING_GATE_GROUPS bounds the groups at once; 0 runs all", uncapped == 9 and scene_gate.workers(9) == 4 and scene_gate.workers(2) == 2)
    finally:
        scene_gate.GROUP_CAP = cap


def check_scene_waves():
    class FakeRunner:
        notes = {}
        parts = {("a-steering", "flee_wall"): ["named failure"]}

        def __init__(self):
            self.case_parts = {}
            self.finished = set()
            self.first_wave = Barrier(2)

        def group(self, root, group, cases, tag):
            if group in {"core", "island"}:
                self.first_wave.wait(5)
            elif group in scene_gate.SECOND_WAVE_GROUPS:
                assert {"core", "island"} <= self.finished
            elif group == "render":
                assert scene_gate.SECOND_WAVE_GROUPS <= self.finished
            self.finished.add(group)
            return {case: (case != "flee_wall", tag, 0.0) for case in cases}

    runner = FakeRunner()
    cases = ["say", "tick", "flee_wall", "act_gaps", "committed", "outcomes", "skirmish", "looks"]
    cap = scene_gate.GROUP_CAP
    try:
        scene_gate.GROUP_CAP = 2
        got = scene_gate.run_cases(runner, None, cases, "a")
    finally:
        scene_gate.GROUP_CAP = cap
    expect("waves: existing groups run concurrently, then all new groups, then render",
           set(got) == set(cases) and all(got[c][0] for c in cases if c != "flee_wall"), str(got))
    expect("waves: a second-wave failure preserves its named parts for the flake rule",
           not got["flee_wall"][0] and runner.case_parts[("a", "flee_wall")] == ["named failure"])


def check_render_logs():
    """The client log's verdicts: shader/pipeline, asset, set stale and panics; WARN never fails."""
    t = "2026-11-20T20:01:16.183575Z"
    lines = {
        "shader": [f"{t} ERROR wgpu_core::device::global: Device::create_render_pipeline error: Validation Error",
                   f"{t} ERROR naga::front::wgsl: expected expression",
                   f"\x1b[2m{t}\x1b[0m \x1b[31mERROR\x1b[0m \x1b[2mbevy_render::render_resource::pipeline_cache\x1b[0m\x1b[2m:\x1b[0m failed to process shader",
                   f"{t} ERROR bevy_pbr::material: something",
                   f"{t} ERROR living_game::style: the toon pipeline could not be made"],
        "asset": [f"{t} ERROR bevy_asset::server: Asset path \"/x/strands.png\" is unapproved",
                  f"{t} ERROR bevy_asset::server: Path not found: /x/lookdev/vroid-Vivi.glb"],
        "stale": [f"{t}  WARN living_game::characters::book: looks: lk_0123456789abcdef is not in the look book; drawn as a VRoid base",
                  f"{t}  WARN living_game::characters::seen: looks: the world was made with look generation c4-x, which the look book (c4-y) does not hold; people it lacks are drawn as VRoid bases"],
        "panic": ["thread 'main' panicked at living/game/src/live.rs:12:5:"],
    }
    quiet = [f"{t}  WARN bevy_light::cascade: ShadowLodOrigin", f"{t}  WARN wgpu_hal::vulkan: something benign",
             f"{t}  WARN bevy_egui: bindless", f"{t}  WARN winit: Destroyed", f"{t}  INFO bevy_render::renderer: AdapterInfo",
             f"{t}  WARN living_game::view: no clip or view", f"{t}  WARN living_game::live: no UI node",
             f"{t}  WARN bevy_asset::server: a warning only", "TU: error: ../src/freedreno/vulkan/tu_knl.cc:387: failed to open device"]
    for verdict, ls in lines.items():
        for line in ls:
            got = scene_gate.scan_log(line)
            expect(f"log: {verdict}: {line[-60:]!r}", got[verdict] and sum(map(len, got.values())) == 1, str(got))
    for line in quiet:
        got = scene_gate.scan_log(line)
        expect(f"log: never fails: {line[-50:]!r}", not any(got.values()), str(got))
    got = scene_gate.scan_log("\n".join(lines["stale"]), stale_exempt=True)
    expect("log: a drive that leaves a key out on purpose is not stale", not any(got.values()), str(got))
    with tempfile.TemporaryDirectory() as t2:
        for drive, text in (("looks", lines["stale"][0]), ("hair", lines["stale"][0]), ("far", lines["shader"][0])):
            d = Path(t2, "ui", drive)
            d.mkdir(parents=True)
            (d / "client.log").write_text(text + "\n")
        got = scene_gate.scan_logs(list(scene_gate.client_logs(t2)))
        expect("logs: stale only outside the exempt drives, each line named by its drive",
               [x.split(":")[0] for x in got["stale"]] == ["hair"] and [x.split(":")[0] for x in got["shader"]] == ["far"], str(got))


def make_glb(path, animations):
    doc = json.dumps({"asset": {"version": "2.0"}, "nodes": [], "animations": [{"channels": []}] * animations}).encode()
    doc += b" " * (-len(doc) % 4)
    import struct
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(doc)) + struct.pack("<II", len(doc), 0x4E4F534A) + doc)


def make_render_set(t, repo, book_generations=("c4-a", "c4-b")):
    """A synthetic render asset set built by the real render_set.py from `repo` (a checkout whose
    HEAD the bundle names) and a stand-in bundle; returns the set's root (sets/current)."""
    import tarfile
    a = Path(repo) / "living/game/assets"
    make_glb(a / "lookdev/vroid-Fake.glb", 0)
    make_glb(a / "lookdev/anim/vroid-Fake.glb", 2)
    # Clip files carry their .clips.json sidecar (render_set.py refuses a set without one since
    # clip-markers; docs/CLIP_MARKERS.md). No looping gaits here, so marker_check has nothing to fault.
    (a / "lookdev/anim/vroid-Fake.clips.json").write_text("{}\n")
    for d, f in (("view", "v.glb"), ("textures", "ground.png"), ("envs/cullet", "quay.glb")):
        (a / d).mkdir(parents=True, exist_ok=True)
        (a / d / f).write_bytes(d.encode())
    commit = sh("git rev-parse HEAD", repo).strip()
    trees = " ".join(f"{d}={sh(f'git rev-parse HEAD:living/tools/{d}', repo).strip()}" for d in ("blender", "characters", "textures"))
    b = Path(t, "bundle")
    make_glb(b / "living/game/assets/lookdev/anim/own-clips.glb", 3)
    (b / "living/game/assets/lookdev/anim/own-clips.clips.json").write_text("{}\n")
    (b / "living/game/assets/lookdev/types").mkdir(parents=True)
    (b / "living/game/assets/lookdev/types/adult-f.glb").write_bytes(b"type")
    (b / "living/game/assets/characters").mkdir(parents=True)
    (b / "living/game/assets/characters/looks.json").write_text(json.dumps({"generation": book_generations[-1], "generations": list(book_generations)}))
    (b / "MANIFEST.txt").write_text(f"commit {commit}\nport: off\npictures: ktx2\ngenerator trees: {trees}\n\n")
    tar = Path(t, "bundle-fake-ktx2.tar.gz")
    with tarfile.open(tar, "w:gz") as out:
        for f in sorted(b.rglob("*")):
            if f.is_file():
                out.add(f, arcname=str(f.relative_to(b)))
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(GATE), "render_set.py"), "build", "--bundle", str(tar),
                        "--repo", str(repo), "--root", str(Path(t, "sets")), "--pin"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"render_set.py build: {r.stdout}{r.stderr}")
    return Path(t, "sets/current")


def writable(root):
    for p in [Path(root), *Path(root).rglob("*")]:
        if p.is_dir() and not p.is_symlink():
            os.chmod(p, 0o755)


def check_render_set():
    """The gate's setup on render_set.py: a set it built checks ok and links; corrupt, stale and
    absent sets are named as such, never a silent pass."""
    tools = os.path.dirname(GATE)
    real = str(Path(tools).parents[1])
    t = tempfile.mkdtemp(prefix="gate-render-set-")
    try:
        repo = os.path.join(t, "repo")
        sh(f"git init -q -b main {repo}", t)
        for d in ("blender", "characters", "textures"):
            os.makedirs(os.path.join(repo, "living/tools", d))
            Path(repo, "living/tools", d, "x.py").write_text(d)
        # The synthetic clip files have no gaits to check: the checkout's marker_check.py (which
        # render_set.py runs) passes them, as the real one does a set whose markers are sound.
        Path(repo, "living/tools/marker_check.py").write_text("print('markers: ok (selftest stand-in)')\n")
        for w, g in (("cullet", "c4-b"), ("island", "c4-a")):
            os.makedirs(os.path.join(repo, "living/seeds/worlds", w))
            Path(repo, "living/seeds/worlds", w, "looks.json").write_text(json.dumps({"looks": {"generation": g}}))
        sh("git add -A && git -c user.name=t -c user.email=t@t commit -q -m one", repo)
        cur = make_render_set(t, repo)
        shutil.rmtree(os.path.join(repo, "living/game/assets"))  # a gate's checkout holds no generated assets of its own
        verdict, meta, why = scene_gate.render_set_check(repo, cur, tool_repo=real)
        expect("render set: one render_set.py built checks ok, read through `current`",
               verdict == "ok" and meta and meta.get("dir") == str(cur.resolve()) and meta.get("id"), f"{verdict} {why}")
        ok, said = scene_gate.render_set_link(real, repo, meta["dir"])
        a = Path(repo, "living/game/assets")
        expect("render set: linked into the checkout by render_set.py link",
               ok and (a / "lookdev").is_symlink() and (a / "characters/looks.json").is_symlink() and (a / "envs/cullet").is_symlink(), said)
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "living/game/assets/lookdev", "living/game/assets/envs/cullet",
                                  "living/game/assets/textures", "living/game/assets/view", "living/game/assets/characters/looks.json"], cwd=real, capture_output=True, text=True)
        expect("render set: the links are ignored in this repository (no untracked noise after a gate)",
               ignored.returncode == 0 and len(ignored.stdout.split()) == 5, ignored.stdout + ignored.stderr)
        # stale: the tree under test changed a generator, or a world wears a generation the book lacks
        Path(repo, "living/tools/blender/x.py").write_text("changed")
        sh("git -c user.name=t -c user.email=t@t commit -q -am gen", repo)
        verdict, _, why = scene_gate.render_set_check(repo, cur, tool_repo=real)
        expect("render set: a changed generator tree is stale", verdict == "stale" and any("generator tree" in w for w in why), f"{verdict} {why}")
        sh("git reset -q --hard HEAD~1", repo)
        Path(repo, "living/seeds/worlds/island/looks.json").write_text(json.dumps({"looks": {"generation": "c4-z"}}))
        verdict, _, why = scene_gate.render_set_check(repo, cur, tool_repo=real)
        expect("render set: a world at a generation the book lacks is stale", verdict == "stale" and any("c4-z" in w for w in why), f"{verdict} {why}")
        sh("git checkout -q -- living/seeds", repo)
        # corrupt: a file changed, added or removed
        f = cur.resolve() / "assets/textures/ground.png"
        os.chmod(f.parent, 0o755)
        os.chmod(f, 0o644)
        f.write_bytes(b"other")
        verdict, _, why = scene_gate.render_set_check(repo, cur, tool_repo=real)
        expect("render set: a changed file is corrupt", verdict == "corrupt" and any("ground.png" in w for w in why), f"{verdict} {why}")
        f.unlink()
        verdict, _, why = scene_gate.render_set_check(repo, cur, tool_repo=real)
        expect("render set: a missing file is corrupt", verdict == "corrupt" and any("missing textures/ground.png" in w for w in why), f"{verdict} {why}")
        os.chmod(cur.resolve(), 0o755)
        os.rename(cur.resolve() / "set.json", cur.resolve() / "set.json.away")
        verdict, _, why = scene_gate.render_set_check(repo, cur, tool_repo=real)
        expect("render set: a set without its set.json is corrupt (the check could not run)", verdict == "corrupt" and why, f"{verdict} {why}")
        expect("render set: no set is absent, a dangling `current` is present (and then corrupt)",
               not scene_gate.render_set_present(os.path.join(t, "nothing/current")) and scene_gate.render_set_present(cur))
        os.symlink(os.path.join(t, "gone"), os.path.join(t, "dangling"))
        expect("render set: a dangling link is present", scene_gate.render_set_present(os.path.join(t, "dangling")))
    finally:
        writable(t)
        shutil.rmtree(t, ignore_errors=True)


def check_smoke_links():
    """render-smoke's own lookdev link goes in and out; a real folder is never replaced."""
    with tempfile.TemporaryDirectory() as t:
        src = Path(t, "smoke/lookdev")
        src.mkdir(parents=True)
        game = Path(t, "wt")
        a = game / "living/game/assets"
        (a / "characters").mkdir(parents=True)
        (a / "characters/recipes.json").write_text("{}")
        made = scene_gate.link_set(game, src.parent, ["lookdev"])
        expect("smoke links: lookdev points at the smoke's folder", os.readlink(a / "lookdev") == str(src), str(made))
        scene_gate.unlink_set(made)
        expect("smoke links: removed afterwards, the worktree's own files kept", not (a / "lookdev").exists() and (a / "characters/recipes.json").exists())
        (a / "lookdev").mkdir()
        try:
            scene_gate.link_set(game, src.parent, ["lookdev"])
            refused = False
        except RuntimeError as e:
            refused = "exists and is not a link" in str(e)
        expect("smoke links: a real folder is never replaced", refused and (a / "lookdev").is_dir() and not (a / "lookdev").is_symlink())


def check_render_load():
    """The load around render and render-smoke runs: warned over LOAD_WARN (8), at the start or end;
    kept on the runner for the record."""
    w = scene_gate.load_warnings
    expect("load: 8 is the default threshold", scene_gate.LOAD_WARN == 8)
    expect("load: under 8 at both ends warns nothing", w([{"group": "render", "tag": "a", "start": 3.2, "end": 7.9}]) == [])
    expect("load: over 8 at the start warns, naming the group, the host and the value",
           w([{"group": "render", "tag": "a", "start": 22.4, "end": 2}], "dev-box")
           == ["WARNING render (a): dev-box's 1-minute load was over 8 (start 22.4); its cases are timing-sensitive, so a failure here may be load-made"])
    expect("load: over 8 at the end warns", len(w([{"group": "render-smoke", "tag": "b", "start": 1, "end": 8.5}])) == 1)
    expect("load: a missing reading warns nothing", w([{"group": "render", "tag": "a", "start": None, "end": None}]) == [] and w(None) == [])
    expect("load: the reading is a number", isinstance(scene_gate.load1(), float))
    t = tempfile.mkdtemp(prefix="gate-load-")
    try:
        runner = Runner("s", {}, Path(t), os.path.join(t, "reds.json"))
        real = scene_gate.load1
        scene_gate.load1 = lambda: 12.0
        try:
            runner.note_load("render-smoke", "a", 3.0)
        finally:
            scene_gate.load1 = real
        expect("load: a run's start and end go on the runner", runner.loads == [{"group": "render-smoke", "tag": "a", "start": 3.0, "end": 12.0}],
               str(runner.loads))
    finally:
        shutil.rmtree(t, ignore_errors=True)


def check_recorded_verdicts():
    """How a recorded pass's cases are read: passed, red on main (only while listed), or uncovered."""
    entry = {"cases": {"looks": "pass", "hair": "flaky-pass", "seat": "red-on-main", "far": "fail"}}
    reds = {"seat": {"skill": "verify-ui", "owner": "dev-box", "first_seen": "2026-11-20", "last_evidence": "x"}}
    v = scene_gate.recorded_verdicts(entry, ["looks", "hair", "seat", "far", "camera-lod"], reds)
    expect("recorded: pass and flaky-pass are recorded-pass", v["looks"][0] == v["hair"][0] == "recorded-pass")
    expect("recorded: red on main while listed is recorded-red-on-main with its owner, not a pass",
           v["seat"][0] == "recorded-red-on-main" and "owner dev-box" in v["seat"][1], str(v["seat"]))
    expect("recorded: failed or missing is uncovered", v["far"] == ("uncovered", "recorded fail") and v["camera-lod"] == ("uncovered", "not recorded"))
    v = scene_gate.recorded_verdicts(entry, ["seat"], {})
    expect("recorded: red on main no longer listed is uncovered", v["seat"][0] == "uncovered" and "no longer holds" in v["seat"][1])
    v = scene_gate.recorded_verdicts(entry, ["seat"], {"seat": {"skill": "verify-ui", "owner": None}})
    expect("recorded: a listed case without an owner names its skill as owner, as the list does", "owner verify-ui" in v["seat"][1], str(v))
    expect("recorded: no entry covers nothing", scene_gate.recorded_verdicts(None, ["looks"], reds) == {"looks": ("uncovered", "not recorded")})


def check_render_passes(t):
    """Recorded render passes: shared through their own branch like the red-on-main list; a pass
    covers the cases it names and the halves all of whose cases it names; a merge's content key
    ignores everything outside living/ and the skills."""
    expect("passes: a pass covers its cases", scene_gate.pass_covers({"cases": {"hair": "pass", "looks": "flaky-pass", "far": "red-on-main"}}, ["hair", "looks", "far"]))
    expect("passes: a missing or failed case is not covered",
           not scene_gate.pass_covers({"cases": {"hair": "pass"}}, ["hair", "looks"])
           and not scene_gate.pass_covers({"cases": {"hair": "fail"}}, ["hair"]) and not scene_gate.pass_covers(None, ["hair"]))
    full = {"cases": dict.fromkeys(scene_gate.RENDER_CASES, "pass")}  # dev-box's 2ed2d93d65c7, before the split: no `halves`
    character = {"cases": {"looks": "pass", "hair": "flaky-pass", "seat": "red-on-main"}, "halves": ["character"]}
    camera = {"cases": {"camera-faces": "pass", "camera-lod": "pass", "far": "pass"}, "halves": ["camera"]}
    partial = {"cases": {"looks": "pass", "hair": "pass", "camera-faces": "pass", "camera-lod": "pass", "far": "fail"}}
    hc = scene_gate.halves_covered
    for name, entry, need, want in (
            ("a full pass from before the split covers the character half", full, ["character"], True),
            ("a full pass from before the split covers the camera half", full, ["camera"], True),
            ("a full pass from before the split covers both halves", full, ["character", "camera"], True),
            ("a character-half pass covers a character change", character, ["character"], True),
            ("a character-half pass does not cover a camera change", character, ["camera"], False),
            ("a character-half pass does not cover a change needing both", character, ["character", "camera"], False),
            ("a camera-half pass does not cover a character change", camera, ["character"], False),
            ("a camera-half pass covers a camera change", camera, ["camera"], True),
            ("a half with a case missing or failed is not covered", partial, ["character"], False),
            ("... nor the other with a failed case", partial, ["camera"], False),
            ("no pass covers nothing", None, ["character"], False),
            ("a change needing no half is covered by anything", None, [], True)):
        expect(f"passes: {name}", hc(entry, need) == want, str(scene_gate.pass_halves(entry)))
    merged = {"cases": {**character["cases"], **camera["cases"]}}
    expect("passes: a character pass and a camera pass recorded for one content together cover both halves",
           hc(merged, ["character", "camera"]) and scene_gate.pass_halves(merged) == ["character", "camera"])
    repo = os.path.join(t, "keys")
    sh(f"git init -q -b main {repo}", t)
    for d in ("living/game/src", ".agents/skills/verify/scripts", ".agents/skills/verify-ui/scripts", "docs"):
        os.makedirs(os.path.join(repo, d), exist_ok=True)
        Path(repo, d, "f").write_text(d)
    sh("git add -A && git commit -q -m one", repo)
    k1 = scene_gate.render_key("HEAD", cwd=repo)
    Path(repo, "docs/f").write_text("other")
    sh("git commit -q -am docs", repo)
    k2 = scene_gate.render_key("HEAD", cwd=repo)
    Path(repo, "living/game/src/f").write_text("other")
    sh("git commit -q -am game", repo)
    k3 = scene_gate.render_key("HEAD", cwd=repo)
    expect("passes: the key keeps through a docs commit and changes with the client", k1 == k2 != k3, f"{k1} {k2} {k3}")
    # the list on its own branch, written from one clone and read from the other
    code = ("import json,sys,scene_gate as g\n"
            "def ch(p):\n    p['k'] = {'cases': {'hair': 'pass'}, 'host': 'devbox'}\n    return True\n"
            "g.update_reds(sys.argv[1], ch, 'render pass: k', branch='render-passes', file='render-passes.json')\n"
            "print(json.dumps(g.fetch_reds('render-passes', 'render-passes.json')[0]))")
    tools = os.path.dirname(GATE)
    env = {**os.environ, "LIVING_GATE_REDS_REPO": os.path.join(t, "devbox"), "PYTHONPATH": tools}
    r = subprocess.run([sys.executable, "-c", code, os.path.join(t, "devbox-passes.json")], env=env, capture_output=True, text=True, cwd=tools)
    env["LIVING_GATE_REDS_REPO"] = os.path.join(t, "spark")
    r2 = subprocess.run([sys.executable, "-c", "import json,scene_gate as g;print(json.dumps([g.fetch_reds('render-passes','render-passes.json')[0], g.fetch_reds()[0]]))"],
                        env=env, capture_output=True, text=True, cwd=tools)
    try:
        passes, reds = json.loads(r2.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        passes, reds = None, None
    expect("passes: written on one clone's render-passes branch, read on the other, the red-on-main list untouched",
           r.returncode == 0 and passes and passes.get("k", {}).get("host") == "devbox" and "k" not in (reds or {}), r.stderr + r2.stderr + r2.stdout)
    files = sh("git ls-tree --name-only origin/render-passes", os.path.join(t, "spark")).split()
    expect("passes: the branch holds its one file", files == ["render-passes.json"], str(files))
    check_render_passes_cli(t, tools)


def record_pass(t, tools, key, cases, legacy=False, extra=None):
    """dev-box's side, written from the devbox clone to the shared branch: the gate's own
    record_render_pass for `cases` of content `key`, or with `legacy` a raw entry as recorded before
    the split (its cases, a list of passes or {case: status}, no `halves`; `extra` fields added)."""
    code = ("import json,sys,scene_gate as g\n"
            "key, cases, extra = sys.argv[2], json.loads(sys.argv[3]), json.loads(sys.argv[5])\n"
            "class A:\n    passes = sys.argv[1]\n"
            "if sys.argv[4] == '1':\n"
            "    def ch(p):\n        p[key] = {'cases': cases if isinstance(cases, dict) else dict.fromkeys(cases, 'pass'), "
            "'host': 'dev-box', 'head': 'h', 'at': 'then', 'set': 's', **extra}\n        return True\n"
            "    g.update_reds(A.passes, ch, 'render pass', branch='render-passes', file='render-passes.json')\n"
            "else:\n"
            "    g.record_render_pass(A, key, 'h' * 40, cases, {'base': 'b', 'evidence': 'e', 'cases': {c: {'status': 'pass'} for c in cases}, "
            "'load': [{'group': 'render', 'tag': 'a', 'start': 1.5, 'end': 2.0}, {'group': 'render-smoke', 'tag': 'a', 'start': 1, 'end': 1}]}, {'id': 's'})\n")
    env = {**os.environ, "LIVING_GATE_REDS_REPO": os.path.join(t, "devbox"), "PYTHONPATH": tools}
    r = subprocess.run([sys.executable, "-c", code, os.path.join(t, "devbox-passes.json"), key,
                        json.dumps(cases if isinstance(cases, dict) else list(cases)), "1" if legacy else "0", json.dumps(extra or {})],
                       env=env, capture_output=True, text=True, cwd=tools)
    if r.returncode or "pass recorded" not in r.stdout + r.stderr and not legacy:
        raise RuntimeError(r.stdout + r.stderr)


def check_render_passes_cli(t, tools):
    """The Spark's gate (no asset set) reads dev-box's recorded passes by (content, half) through the
    real CLI: a character-half pass does not let a camera change through, and the refusal names the
    missing half (and, when the other half is recorded, only the missing half's cases to run); the camera half recorded too, or one full pass from before
    the split, lets it through. (The run then stops at the missing SpacetimeDB container, exit 2:
    the render decision is printed and recorded before.)"""
    spark, cache = os.path.join(t, "spark"), os.path.join(t, "spark.json")
    g = Path(spark, "living/game/src")
    g.mkdir(parents=True, exist_ok=True)
    for f in ("camera.rs", "handmade.rs"):
        (g / f).write_text("// one\n")
    sh("git add -A living && git commit -q -m 'drawing base'", spark)
    base = sh("git rev-parse HEAD", spark).strip()
    (g / "camera.rs").write_text("// two\n")
    sh("git commit -q -am 'camera change'", spark)
    key = scene_gate.render_key("HEAD", cwd=spark)
    env = {"LIVING_GATE_RENDER_ASSETS": os.path.join(t, "no-render-set"), "LIVING_GATE_RENDER_HOST": "dev-box"}

    def run():
        code, out = gate(spark, cache, "run", "--base", base, "--stdb-container", "no-such-gate-container", env_extra=env)
        records = sorted(Path(spark, ".local/living/verify").glob("gate-*/gate.json"), key=os.path.getmtime)
        return code, out, json.loads(records[-1].read_text()).get("render", {}) if records else {}
    record_pass(t, tools, key, ["looks", "hair", "seat"])
    code, out, rec = run()
    expect("cli: a camera change with only a character-half pass recorded is refused, naming the camera half and its cases",
           "render: not run here; needs a pinned asset set (dev-box)" in out and "this content's camera half" in out
           and "recorded: the character half" in out and "--cases" not in out
           and rec.get("halves") == ["camera"] and rec.get("recorded_halves") == ["character"], out)
    record_pass(t, tools, key, ["camera-faces", "camera-lod", "far"])
    code, out, rec = run()
    expect("cli: with the camera half recorded too, the same content's camera change is let through",
           "recorded a pass for this content" in out and "covering the camera half" in out
           and "needs a pinned asset set" not in out and rec.get("recorded_halves") == ["character", "camera"], out)
    (g / "handmade.rs").write_text("// two\n")
    sh("git commit -q -am 'character change too'", spark)
    key2 = scene_gate.render_key("HEAD", cwd=spark)
    record_pass(t, tools, key2, ["looks", "hair", "seat"])
    code, out, rec = run()
    expect("cli: a change touching both halves with one half recorded is refused, naming the other",
           "this content's camera half" in out and "--cases camera-faces,camera-lod,far" in out
           and rec.get("halves") == ["character", "camera"], out)
    record_pass(t, tools, key2, scene_gate.RENDER_CASES, legacy=True)  # one full pass as before the split (no `halves`)
    code, out, rec = run()
    expect("cli: a full pass (all six) lets a both-halves change through",
           "covering the character and camera halves" in out and "needs a pinned asset set" not in out, out)
    passes = json.loads(sh("git show origin/render-passes:render-passes.json", os.path.join(t, "devbox")))
    expect("cli: the shared entries are keyed by content alone, each naming the halves it covers",
           set(passes) >= {key, key2} and passes[key].get("halves") == ["character", "camera"]
           and set(passes[key]["cases"]) == set(scene_gate.RENDER_CASES) and "halves" not in passes[key2], json.dumps(passes)[:800])
    expect("cli: a recorded pass keeps the render group's load (not render-smoke's)",
           passes[key].get("load") == [{"group": "render", "tag": "a", "start": 1.5, "end": 2.0}], json.dumps(passes[key])[:500])

    # a half with one case red on main (dev-box's seat, 2026-11-20): covered while the shared
    # red-on-main list holds it, reported loudly and never as passed; load over 8 there is warned
    (g / "handmade.rs").write_text("// three\n")
    sh("git commit -q -am 'character change, seat red on main'", spark)
    gate(spark, cache, "reds", "--add", "seat", "--skill", "verify-ui", "--who", "dev-box", "--reason", "cloth under the ground")
    (g / "camera.rs").write_text("// one\n")  # back to the base: the diff is the character half alone
    sh("git commit -q -am 'camera back'", spark)
    key3 = scene_gate.render_key("HEAD", cwd=spark)
    record_pass(t, tools, key3, {"looks": "pass", "hair": "flaky-pass", "seat": "red-on-main"}, legacy=True,
                extra={"load": [{"group": "render", "tag": "a", "start": 22.4, "end": 15.1}]})
    code, out, rec = run()
    gj = sorted(Path(spark, ".local/living/verify").glob("gate-*/gate.json"), key=os.path.getmtime)[-1]
    cases = json.loads(gj.read_text()).get("cases", {})
    expect("cli: a half with one case red on main (listed, with its owner) is covered, says loudly the case did not pass, "
           "and records it recorded-red-on-main, the others recorded-pass",
           "needs a pinned asset set" not in out and "passed looks, hair; red on main, NOT passed: seat" in out
           and "WARNING render: seat did not pass in dev-box's recorded pass" in out and "owner dev-box" in out
           and {c: v.get("status") for c, v in cases.items()} == {"looks": "recorded-pass", "hair": "recorded-pass", "seat": "recorded-red-on-main"}
           and rec.get("recorded_halves") == ["character"], out)
    expect("cli: the recorded pass's load over 8 is shown and warned about",
           "dev-box's 1-minute load around its render (a): start 22.4, end 15.1" in out
           and "WARNING render (a): dev-box's 1-minute load was over 8 (start 22.4, end 15.1)" in out
           and rec.get("recorded_load") == [{"group": "render", "tag": "a", "start": 22.4, "end": 15.1}], out)
    gate(spark, cache, "reds", "--drop", "seat")
    code, out, rec = run()
    expect("cli: once main is green for it (dropped from the list), the recorded red-on-main case no longer covers its half",
           "needs a pinned asset set (dev-box)" in out and "this content's character half" in out
           and "seat not covered by the recorded pass: recorded red on main, but the red-on-main list no longer holds it" in out
           and "--cases seat" in out, out)


def main():
    check_run_part()
    check_genesis()
    check_genesis_baselines()
    check_genesis_live()
    check_seed_fresh()
    check_generation_group()
    check_flake_scope()
    check_staged_genesis()
    check_render_selection()
    check_speech_selection()
    check_scene_waves()
    check_render_load()
    check_recorded_verdicts()
    check_render_logs()
    check_render_set()
    check_smoke_links()
    with tempfile.TemporaryDirectory(prefix="gate-reds-selftest-") as t:
        os.environ.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        origin = os.path.join(t, "origin.git")
        sh(f"git init -q --bare -b main {origin}", t)
        a, b = os.path.join(t, "spark"), os.path.join(t, "devbox")
        sh(f"git clone -q {origin} spark", t)
        sh("git commit -q --allow-empty -m base && git push -q origin HEAD:main", a)
        sh(f"git clone -q {origin} devbox", t)
        ca, cb = os.path.join(t, "spark.json"), os.path.join(t, "devbox.json")

        # no branch yet: an empty list, read without a fallback
        reds, out = listed(b, cb)
        expect("no branch yet: an empty list, no fallback", reds == {} and "could not read" not in out, out)

        # spark adds; devbox sees it after its fetch
        code, out = gate(a, ca, "reds", "--add", "takeover", "--skill", "verify-minds", "--who", "dev-box", "--reason", "cadence race", "--main", "abc123")
        expect("add on one clone: committed and pushed (exit 0)", code == 0 and "takeover" in out, out)
        reds, out = listed(b, cb)
        expect("an add on one clone is seen on the other after a fetch", reds.get("takeover", {}).get("owner") == "dev-box"
               and reds["takeover"].get("reason") == "cadence race", out)
        expect("the other clone's cache is rewritten from the remote", json.load(open(cb)).get("takeover", {}).get("owner") == "dev-box")

        # the other direction: devbox sets the owner and adds a case, spark sees both
        gate(b, cb, "reds", "--owner", "takeover", "dev-box (through the general coordinator)")
        gate(b, cb, "reds", "--add", "greet", "--skill", "verify-minds", "--who", "dev-box", "--reason", "parked line")
        reds, out = listed(a, ca)
        expect("the other direction: --owner and --add on the second clone are seen on the first",
               reds.get("takeover", {}).get("owner") == "dev-box (through the general coordinator)" and "greet" in reds, out)
        code, out = gate(a, ca, "reds", "--drop", "greet")
        reds, out2 = listed(b, cb)
        expect("--drop travels too", code == 0 and "greet" not in reds and "takeover" in reds, out + out2)
        code, out = gate(a, ca, "reds", "--drop", "no-such-case")
        expect("dropping a case not listed fails and changes nothing", code == 1 and "not on the red-on-main list" in out, out)

        # racing writers from both clones: every add lands (a rejected push fetches and retries)
        procs = [gate(c, cache, "reds", "--add", f"race-{c[-6:]}-{i}", "--skill", "verify-minds", "--who", "x", "--reason", "race", wait=False)
                 for i in range(4) for c, cache in ((a, ca), (b, cb))]
        codes = [p.wait() for p in procs]
        for p in procs:
            p.stdout.close()
        reds, out = listed(a, ca)
        races = [k for k in reds if k.startswith("race-")]
        expect(f"8 racing writers on two clones: all exit 0 and all 8 land ({len(races)})", codes == [0] * 8 and len(races) == 8, out)

        # the branch: one file, a linear history, never main
        files = sh("git ls-tree --name-only origin/red-on-main", a).split() if not sh("git fetch -q origin", a) else []
        main_files = sh("git ls-tree -r --name-only origin/main", a).split()
        expect("the branch holds red-on-main.json alone; main untouched", files == ["red-on-main.json"] and main_files == [], f"{files} {main_files}")
        merges = sh("git rev-list --merges origin/red-on-main", a).split()
        expect("its history is linear (no merges, every write on the one before)", merges == [])

        # a gate run reads the list from the remote (spark's cache is stale until it runs)
        gate(b, cb, "reds", "--add", "late", "--skill", "verify-minds", "--who", "y", "--reason", "seen by the run")
        code, out = gate(a, ca, "run", "--base", "HEAD", "--head", "HEAD")
        expect("a gate run (skipped) prints the list as on the remote", code == 0 and "skipped" in out and "late (verify-minds; owner y)" in out, out)

        # seed freshness through the CLI: a stale block fails unless the list holds it as a part
        tool = Path(a, "living/tools/seed_fresh.py")
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text("import json, sys\n"
                        "report = {'fresh': [], 'stale': {'cullet': {'world': 'cullet', 'recompile': 'x', 'stale': {'looks': ['gen']}}}}\n"
                        "open(sys.argv[sys.argv.index('--json') + 1], 'w').write(json.dumps(report))\n"
                        "print('stale cullet looks: gen; recompile: x'); sys.exit(1)\n")
        code, out = gate(a, ca, "seeds")
        expect("seeds: a stale block fails (exit 1) and the line names the seed, block and command",
               code == 1 and "stale cullet looks: gen; recompile: x" in out and "FAILED, stale: cullet:looks" in out, out)
        gate(b, cb, "reds", "--add", "seeds:cullet:looks", "--skill", "seed-freshness", "--who", "dev-box", "--reason", "recompiling")
        code, out = gate(a, ca, "seeds")
        expect("seeds: a stale block listed red on main is reported and does not fail",
               code == 0 and "cullet:looks is stale and listed red on main (owner dev-box; recompiling)" in out, out)
        tool.unlink()

        # the genesis overrides through the real CLI (no server needed for either)
        code, out = gate(a, ca, "run", "--base", "HEAD", "--head", "HEAD", "--genesis-only",
                         "--stdb-container", "no-such-container", env_extra={"SLOP_GATE_GENESIS_CHECK": "0"})
        records = sorted(Path(a, ".local/living/verify").glob("gate-*/gate.json"))
        record = json.loads(records[-1].read_text()) if records else {}
        expect("SLOP_GATE_GENESIS_CHECK=0: the check is skipped with a warning (exit 0), and the record says so",
               code == 0 and "WARNING genesis fuel check disabled" in out and record.get("genesis_disabled") is True
               and record.get("genesis") == [] and record.get("result") == "genesis skipped", out)
        code, out = gate(a, ca, "run", "--base", "HEAD", "--head", "HEAD", "--genesis-only",
                         env_extra={"SLOP_GATE_GENESIS_HEADROOM": "ten"})
        expect("SLOP_GATE_GENESIS_HEADROOM that is not a percentage is a setup error (exit 2)",
               code == 2 and "genesis setup error" in out, out)

        # remote unreachable: the read falls back to the cache and says so; a change fails cleanly
        sh(f"git remote set-url origin {os.path.join(t, 'gone.git')}", b)
        before = open(cb).read()
        reds, out = listed(b, cb)
        expect("unreachable remote: the read falls back to the local cache and says so",
               "could not read the red-on-main list" in out and "using the local cache" in out and "late" in reds, out)
        code, out = gate(b, cb, "reds", "--add", "offline", "--skill", "verify-minds", "--who", "z", "--reason", "r")
        expect("unreachable remote: a change fails (exit 1), the cache is unchanged", code == 1 and "FAILED to change the shared list" in out
               and open(cb).read() == before, out)
        code, out = gate(b, cb, "run", "--base", "HEAD", "--head", "HEAD")
        expect("unreachable remote: a gate run still runs and prints the cached list, saying so", code == 0 and "using the local cache" in out
               and "late (verify-minds" in out, out)
        sh(f"git remote set-url origin {origin}", b)
        reds, out = listed(b, cb)
        expect("reachable again: the remote's list, without the offline change", "offline" not in reds and "late" in reds, out)
        check_render_passes(t)
    print("scene_gate_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
