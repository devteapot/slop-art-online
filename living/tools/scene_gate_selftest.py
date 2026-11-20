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
import subprocess
import sys
import tempfile
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
           **(env_extra or {})}
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
    original = seed_fresh.ROOT, seed_fresh.WORLDS, dict(seed_fresh.PLAN_CHECKS)
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

        seed_fresh.ROOT, seed_fresh.WORLDS = root, root / "living/seeds/worlds"
        try:
            expect("seed freshness: a seed as compiled from its sources is fresh", stale() == ("town", []), stale())
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
                expect(f"seed freshness: {name} is a stale {block} block, and says so",
                       len(got) == 1 and got[0][0] == block and words in got[0][1], got)
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


def main():
    check_run_part()
    check_genesis()
    check_genesis_baselines()
    check_genesis_live()
    check_seed_fresh()
    check_generation_group()
    check_staged_genesis()
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
    print("scene_gate_selftest:", "FAILED " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
