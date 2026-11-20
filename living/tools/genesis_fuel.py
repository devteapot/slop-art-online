#!/usr/bin/env python3
"""Genesis fuel per seed: `init` and each staged-genesis step against SpacetimeDB 2.14.1's per-call
budget (docs/STAGED_GENESIS.md §7; the format the Spark's genesis-fuel guard reads).

    LIVING_SEED=island LIVING_GENESIS_STEPPING=1 cargo build -p living-authority --target wasm32-unknown-unknown --release
    cp living/target/wasm32-unknown-unknown/release/living_authority.wasm <the server's /wasm>/genesis-island.wasm
    python3 living/tools/genesis_fuel.py --seed island --wasm genesis-island.wasm [--out FILE]

A measurement build (`LIVING_GENESIS_STEPPING=1`) schedules no step by itself: this tool publishes it
fresh on the worker's own server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`), reads `init`'s fuel
from the server's `reducer_wasmtime_fuel_used{reducer="init"}` counter (a fresh publish runs `init`
twice: the validity check's run on an in-memory database, then the real one; `init_fuel` is per
run), then runs the steps one at a time with the admin's `resume_genesis`, reading the
`genesis_step` counter before and after each. Fuel is deterministic for a module and a seed. The
database is deleted after (world_delete.py). Prints one JSON object:

    {"seed", "commit", "budget", "init_fuel", "init_runs",
     "steps": [{"phase", "label", "fuel", "reducer"}], "largest_step_share"}

and exits 1 when `init` or a step is above 90% of the budget (the guard's rule), 0 otherwise.
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--wasm", required=True, help="a stepping build of that seed, relative to the server's /wasm")
    ap.add_argument("--out")
    ap.add_argument("--max-steps", type=int, default=500)
    a = ap.parse_args()
    db = f"verify-lookcost-gfuel-{a.seed}-{time.strftime('%H%M%S')}"[:60]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    lc.stdb("publish", "-s", "local", "-b", str(Path("/wasm") / a.wasm), db, "--delete-data", "-y")
    try:
        token = lc.admin_token()
        ident = json.loads(lc.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
        fuel, calls = counters(ident)
        runs = int(calls.get("init", 0)) or 1
        out = {"seed": a.seed, "commit": commit, "budget": BUDGET, "init_fuel": round(fuel.get("init", 0) / runs), "init_runs": runs, "steps": []}
        for _ in range(a.max_steps):
            row = genesis_wait.genesis_row(lc.URL, db, token)
            if row is None or row.get("done"):
                break
            if str(row.get("label", "")).startswith("stopped"):
                raise SystemExit(f"{db}: genesis stopped: {row['label']}")
            before_step, label = row["step"], str(row["label"])
            f0 = counters(ident)[0].get("genesis_step", 0)
            lc.call(db, "resume_genesis", [], token)
            end = time.time() + 600
            while time.time() < end:
                now = genesis_wait.genesis_row(lc.URL, db, token)
                if now and (now["step"] != before_step or now.get("done") or str(now.get("label", "")).startswith("stopped")):
                    break
                time.sleep(0.05)
            f1 = counters(ident)[0].get("genesis_step", 0)
            # The row's label names the step just done; the last step's is "done" (a land's last
            # step is always populate; a seed without a land is made in its one `world` step).
            after = str((now or {}).get("label", ""))
            if (now or {}).get("done"):
                after = label if label.startswith("world") else "populate: people, animals and the settlements' life"
            out["steps"].append({"phase": after.split(":", 1)[0], "label": after, "fuel": round(f1 - f0), "reducer": "genesis_step"})
        out["largest_step_share"] = round(max((s["fuel"] for s in out["steps"]), default=0) / BUDGET, 4)
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
    sys.exit(1 if max([init_share] + [s["fuel"] / BUDGET for s in out["steps"]]) > FAIL_SHARE else 0)


if __name__ == "__main__":
    main()
