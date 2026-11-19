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
import subprocess
import sys
import tempfile
from pathlib import Path

from scene_gate import (
    GENESIS_BUDGET, GENESIS_FUEL, GENESIS_RUNS, Runner, genesis_metrics, genesis_policy,
    genesis_threshold, staged_genesis_report,
)

GATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scene_gate.py")
failures = []


def sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd} in {cwd}: {r.stdout}{r.stderr}")
    return r.stdout


def gate(clone, cache, *args, wait=True):
    env = {**os.environ, "LIVING_GATE_REDS_REPO": clone, "LIVING_GATE_REDS": cache, "LIVING_GATE_REDS_GIT": "1"}
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
    expect("genesis: under 10% with no baseline fails", not bad["passed"], bad)
    override = genesis_threshold({"SLOP_GATE_GENESIS_HEADROOM": "5"})
    raised = genesis_measurement(metrics(110_000_000_000), identity, override, None)
    expect("genesis: configured headroom is used", raised["passed"], raised)
    expect("genesis: check can be disabled", genesis_threshold({"SLOP_GATE_GENESIS_CHECK": "0"}) is None)
    baseline = 119_500_000_000
    for fuel, passed in ((119_619_499_999, True), (119_619_500_000, True), (119_619_500_001, False)):
        result = genesis_measurement(metrics(fuel), identity, threshold, baseline)
        expect(f"genesis: baseline comparison for {fuel}", result["passed"] == passed, result)
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
    check_genesis()
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
