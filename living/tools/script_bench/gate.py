#!/usr/bin/env python3
"""The fuel budget gate for the hot laws (docs/LIVING_CORE.md, "Fuel budgets").

Runs the Rhai bench module (living-rules' `Scripts` over living/scripts/skills.rhai, as the
authority calls it) under sb-host, wasmtime configured as SpacetimeDB 2.14.1 runs reducers,
and fails when a law takes more fuel (WASM instructions) per call than budgets.json allows.

The measurement does not move unless the code or the fixtures do:
  - every batch makes 64 calls, one pass over each fixture set, after one warm-up batch
    (sb-host --calls 64), so the count does not depend on how fast this machine is today;
  - Rhai's hashing keys are fixed. Unpinned, they are drawn at random when ahash is compiled,
    and they alone moved rates-law by 9% and perceived by 29% between compiles of the same
    source. Since det-1 the rules fix them for every engine of the game (the authority, the
    client and the mind: living_rules::script::HASHING_SEED), and the bench's key set 0 is that
    seed. A law's fuel is its fuel under key set 0: the cost the game pays, which is judged.
  - it also runs under 7 other fixed key sets (sb-host --seeds 8, sb_bench::fix_hashing), as a
    diagnostic: the mean and range over the 8 sets show how much of a law's fuel is where its
    entries happen to land, and each law's outputs must be the same under every set.

Usage: gate.py --host SB_HOST --module RHAI_WASM [--budgets budgets.json] [--out DIR] [--json PATH]
  --out   keep the raw lines (gate.jsonl) and sb-host's stderr (gate.err) in DIR
  --json  write the verdict (per law: fuel, budget, ok; the keys' range) to PATH
Exit 0 when every law is within budget, 1 when one is over or not measured, 2 when the
bench itself fails.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAWS = ["rates", "rates-law", "strike", "cooldown", "perceived", "hook", "senses", "senses-law", "moves"]
# Fixed, so the fuel is too: changing any of them changes every law's number a little (a batch
# can differ by a few fuel units from the next, when the module's memory grows).
CALLS, SEEDS, BATCHES = 64, 8, 4


def main(argv):
    args = {"--budgets": os.path.join(HERE, "budgets.json")}
    it = iter(argv)
    for a in it:
        if a in ("--host", "--module", "--budgets", "--out", "--json"):
            args[a] = next(it, None)
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"gate.py: unknown argument {a}\n{__doc__}", file=sys.stderr)
            return 2
    if not args.get("--host") or not args.get("--module"):
        print(__doc__, file=sys.stderr)
        return 2
    cmd = [args["--host"], args["--module"], "rhai", "--laws", ",".join(LAWS), "--calls", str(CALLS), "--seeds", str(SEEDS), "--batches", str(BATCHES)]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = args.get("--out")
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "gate.jsonl"), "w") as f:
            f.write(r.stdout)
        with open(os.path.join(out, "gate.err"), "w") as f:
            f.write(r.stderr)
    if r.returncode != 0:
        print(f"gate: the bench failed (exit {r.returncode}): {' '.join(cmd)}\n{r.stderr.strip()[-2000:]}")
        return 2
    try:
        rows = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    except ValueError as e:
        print(f"gate: unreadable bench output ({e})")
        return 2
    budgets = json.load(open(args["--budgets"]))["fuel_per_call"]
    verdict, fail = [], False
    for row in rows:
        if "error" in row:
            print(f"gate: {row.get('engine')}: {row['error']}")
            return 2
        law, mean = row["law"], row["fuel_per_call"]
        keys = row.get("fuel_seeds") or [mean]
        # Key set 0 is the game's own seed (HASHING_SEED); the fuel the game pays.
        fuel = round(keys[0])
        b = budgets.get(law)
        ok = b is not None and fuel <= b
        fail |= not ok
        verdict.append({"law": law, "fuel": fuel, "budget": b, "ok": ok, "keys_mean": mean, "keys_min": min(keys), "keys_max": max(keys), "p50_ns": row["p50_ns"]})
        print(f"{'ok  ' if ok else 'OVER'} {law:10} {fuel:>9,.0f} fuel/call  budget {b if b is None else format(b, ',')}"
              f"  (other keys: mean {mean:,.0f}, {min(keys):,.0f}..{max(keys):,.0f}; {row['p50_ns'] / 1000:.2f} us p50 here)")
    missing = sorted(set(budgets) - {v["law"] for v in verdict})
    if missing:
        print("not measured:", ", ".join(missing))
        fail = True
    if args.get("--json"):
        with open(args["--json"], "w") as f:
            json.dump({"laws": verdict, "missing": missing, "ok": not fail, "calls": CALLS, "seeds": SEEDS, "batches": BATCHES}, f, indent=1)
    print("gate: " + ("FAILED: " + "; ".join(
        [f"{v['law']} takes {v['fuel']:,.0f} fuel a call, over its budget of {v['budget']:,}" if v["budget"] is not None
         else f"{v['law']} has no budget" for v in verdict if not v["ok"]] + ([f"not measured: {', '.join(missing)}"] if missing else []))
        if fail else "every law within its budget"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
