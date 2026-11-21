#!/usr/bin/env python3
"""Genesis fuel per seed: `init` and each staged-genesis step against SpacetimeDB 2.14.1's per-call
budget (docs/STAGED_GENESIS.md §7; the format the Spark's genesis-fuel guard reads).

    python3 living/tools/genesis_fuel.py --seed island [--out FILE] [--check]          # as the guard calls it
    python3 living/tools/genesis_fuel.py --seed island --wasm genesis-island.wasm       # a stepping build already in /wasm

Without `--wasm` it builds the seed's stepping module itself (`LIVING_SEED=S LIVING_GENESIS_STEPPING=1`,
release wasm) in its own target directory (`$CARGO_TARGET_DIR/genesis-fuel`, or
`living/target/genesis-fuel`) and without sccache, so the measurement build never shares an
artifact with an ordinary one (the flag is an `option_env!`), copies it into the directory the
server's container mounts as `/wasm` (as `verify.py` finds it) and removes the copy after.

A measurement build (`LIVING_GENESIS_STEPPING=1`) schedules no step by itself: this tool publishes it
fresh on the worker's own server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`), reads `init`'s fuel
from the server's `reducer_wasmtime_fuel_used{reducer="init"}` counter (a fresh publish runs `init`
twice: the validity check's run on an in-memory database, then the real one; `init_fuel` is per
run), then runs the steps one at a time with the admin's `resume_genesis`, reading the
`genesis_step` counter before and after each. Fuel is deterministic for a module and a seed. The
database is deleted after (world_delete.py). Prints one JSON object:

    {"seed", "commit", "budget", "init_fuel", "init_runs",
     "steps": [{"phase", "label", "fuel", "reducer"}], "finish_fuel", "largest_step_share"}

(`steps` are the making steps; `finish_fuel` is the last `genesis_step` call, which only marks the
world done and starts its clock.)

on stdout and exits 0 when it measured (the guard judges the report); with `--check`, 1 when
`init` or a step is above 90% of the budget (the guard's rule).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost as lc  # noqa: E402
import genesis_wait  # noqa: E402

BUDGET = 120_000_000_000   # FunctionBudget::DEFAULT_BUDGET in SpacetimeDB 2.14.1
FAIL_SHARE = 0.9
WARN_SHARE = 0.5


def counters(ident):
    """(fuel, calls) per reducer for this database, from /v1/metrics."""
    text = urllib.request.urlopen(f"{lc.URL}/v1/metrics", timeout=60).read().decode()
    fuel, calls = {}, {}
    for line in text.splitlines():
        if ident not in line or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        if 'reducer="' not in name:
            continue
        reducer = name.split('reducer="', 1)[1].split('"', 1)[0]
        if name.startswith("reducer_wasmtime_fuel_used{"):
            fuel[reducer] = float(value)
        elif name.startswith("spacetime_reducer_plus_query_duration_sec_count{"):
            calls[reducer] = float(value)
    return fuel, calls


ROOT = Path(__file__).resolve().parents[2]


def build_stepping(seed):
    """The seed's stepping module, built apart from ordinary builds; its path."""
    base = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target")
    target = base / "genesis-fuel"
    env = dict(os.environ, LIVING_SEED=seed, LIVING_GENESIS_STEPPING="1", CARGO_TARGET_DIR=str(target))
    for name in ("RUSTC_WRAPPER", "LIVING_NO_TICK"):
        env.pop(name, None)
    # Through gate_pause.sh: a build started beside a scene gate waits and pauses while the gate
    # holds gate.lock; one the gate starts itself (scene_gate.py's genesis check) is never paused
    # (docs/TOOLING.md, "Heavy work during a gate").
    r = subprocess.run(["bash", str(ROOT / "living/tools/gate_pause.sh"), "--", "cargo", "build", "--manifest-path", str(ROOT / "living/Cargo.toml"), "-p", "living-authority",
                        "--target", "wasm32-unknown-unknown", "--release"], env=env, capture_output=True, text=True,
                        timeout=3600 + 5400)  # the build, plus gate_pause.sh's longest pause
    if r.returncode:
        raise SystemExit(f"genesis_fuel: the stepping build of {seed} failed:\n{r.stderr[-2000:]}")
    return target / "wasm32-unknown-unknown/release/living_authority.wasm"


def wasm_mount():
    """The host directory the server's container serves as /wasm (verify.py's rule)."""
    r = subprocess.run(["docker", "inspect", lc.CONTAINER, "--format", '{{range .Mounts}}{{if eq .Destination "/wasm"}}{{.Source}}{{end}}{{end}}'],
                       capture_output=True, text=True)
    src = r.stdout.strip().removeprefix("/host_mnt")
    if not src:
        raise SystemExit(f"genesis_fuel: {lc.CONTAINER} has no /wasm mount")
    return Path(src)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--wasm", help="a stepping build of that seed, relative to the server's /wasm (default: build it)")
    ap.add_argument("--check", action="store_true", help="exit 1 when init or a step is above 90%% of the budget")
    ap.add_argument("--out")
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--floor-seed", help="a floor module (built with LIVING_SEED=none): give it this seed JSON with create_floor after the publish; its fuel is reported as create_floor_fuel")
    a = ap.parse_args()
    db = f"verify-lookcost-gfuel-{a.seed}-{time.strftime('%H%M%S')}"[:60]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()   # the full sha (the guard matches it)
    copied = None
    if a.wasm:
        wasm = a.wasm
    else:
        built = build_stepping("none" if a.floor_seed else a.seed)
        wasm = f"genesis-fuel-{a.seed}-{os.getpid()}.wasm"
        copied = wasm_mount() / wasm
        copied.write_bytes(built.read_bytes())
    try:
        lc.stdb("publish", "-s", "local", "-b", str(Path("/wasm") / wasm), db, "--delete-data", "-y")
    finally:
        if copied:
            copied.unlink(missing_ok=True)   # the module is stored in the database once published
    try:
        token = lc.admin_token()
        ident = json.loads(lc.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
        fuel, calls = counters(ident)
        runs = int(calls.get("init", 0)) or 1
        out = {"seed": a.seed, "commit": commit, "budget": BUDGET, "init_fuel": round(fuel.get("init", 0) / runs), "init_runs": runs, "steps": []}
        if a.floor_seed:
            # A floor: the seed's check and rules run in create_floor (what init does for a compiled seed).
            seed_json = json.loads(Path(a.floor_seed).read_text())
            if seed_json.get("laws_file") and not str(seed_json.get("laws") or "").strip():
                seed_json["laws"] = (Path(__file__).resolve().parents[1] / "seeds" / seed_json["laws_file"]).read_text()
            lc.call(db, "create_floor", [json.dumps(seed_json)], token)
            out["create_floor_fuel"] = round(counters(ident)[0].get("create_floor", 0))
        for _ in range(a.max_steps):
            row = genesis_wait.genesis_row(lc.URL, db, token)
            if row is None or row.get("done"):
                break
            if str(row.get("label", "")).startswith("stopped"):
                raise SystemExit(f"{db}: genesis stopped: {row['label']}")
            before_step, label = row["step"], str(row["label"])
            f0, c0 = (lambda fc: (fc[0].get("genesis_step", 0), fc[1].get("genesis_step", 0)))(counters(ident))
            lc.call(db, "resume_genesis", [], token)
            # The step has run when the server counts one more `genesis_step` call: a step that
            # traps (out of energy) rolls everything back, so its row never moves.
            end = time.time() + 600
            now = None
            while time.time() < end:
                fc = counters(ident)
                if fc[1].get("genesis_step", 0) > c0:
                    now = genesis_wait.genesis_row(lc.URL, db, token)
                    break
                time.sleep(0.05)
            f1 = counters(ident)[0].get("genesis_step", 0)
            if now is None or (now["step"] == before_step and not now.get("done")):
                logs = lc.stdb("logs", "-s", "local", db, "-n", "200")
                trap = [l for l in logs.splitlines() if "genesis" in l.lower() or "energy" in l.lower() or "trap" in l.lower() or "panic" in l.lower()][-6:]
                out["steps"].append({"phase": "trapped", "label": f"after: {label}", "fuel": round(f1 - f0), "reducer": "genesis_step", "trapped": True, "log": trap})
                out["trapped_at_step"] = before_step + 1
                break
            # The row's label names the step just done. The call that marks the world done after
            # the last making step (populate, or a seed without a land's one `world` step) makes
            # nothing and moves no step: it is reported apart, so `steps` lists the making steps.
            if now.get("done"):
                out["finish_fuel"] = round(f1 - f0)
                break
            after = str(now.get("label", ""))
            out["steps"].append({"phase": after.split(":", 1)[0], "label": after, "fuel": round(f1 - f0), "reducer": "genesis_step"})
        out["largest_step_share"] = max((s["fuel"] for s in out["steps"]), default=0) / BUDGET
    finally:
        lc.delete_world(db)
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)
    init_share = out["init_fuel"] / BUDGET
    for what, share in [("init", init_share)] + [(f"step {i} ({s['phase']})", s["fuel"] / BUDGET) for i, s in enumerate(out["steps"])]:
        if share > WARN_SHARE:
            print(f"{'FAIL' if share > FAIL_SHARE else 'warn'}: {what} uses {share:.1%} of the budget", file=sys.stderr)
    sys.exit(1 if a.check and max([init_share] + [s["fuel"] / BUDGET for s in out["steps"]]) > FAIL_SHARE else 0)


if __name__ == "__main__":
    main()
