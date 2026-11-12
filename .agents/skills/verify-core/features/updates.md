# Module updates in place

Since `look-1-auth` (2026-11-12, docs/LOOK.md §7 "The update panic, traced"). Publishing a module over a ticking world with its data kept (`just living-publish`, `$V launch --keep-data`): SpacetimeDB 2.14.1 applies the schema steps in one transaction and swaps the new module in after it. The outgoing module can still fire one scheduled reducer after the commit, and the bindings cache table and index ids per instance (`static OnceLock`). After an update that rewrites a table (a column appended with an incompatible layout: new table id, new index ids), that last call's first lookup panics "No such index". The authority's update guard (`common::schema_moved`, first in `tick`, `housekeeping` and `genesis_step`) fingerprints `st_table` at an instance's first scheduled call and returns at once from a later call whose fingerprint moved, touching nothing.

## Sub-features

- An update from a module without the guard to one that rewrites `world` logs one `PANIC` (the old module's), and the world ticks on: `world` row, characters and both timers kept.
- An update from a module with the guard logs no `PANIC` and one guard line ("the database's tables changed under this module instance …").
- An update with no schema change (main → main + guard) logs neither.
- After an update, `relook(GEN)` gives a world from before looks its seed's looks, with no panic.

## Driving it

The modules are built beforehand into the server's `/wasm` mount (a seed per build, `LIVING_SEED`; each workspace in its own `CARGO_TARGET_DIR`, since two workspaces sharing one share the authority's build-script output and its compiled seed):

```bash
.agents/skills/verify-core/scripts/updates.py --run core-updates-$(date +%m%d-%H%M%S) --relook fixture-1 \
  --chain main-plan,look-plan --chain main-plan,main-guard,look-plan --chain main-guard,look-plan,look-col --chain look-plan,look-col
```

`main-plan` is main on plan-test, `main-guard` main plus the guard alone, `look-plan` this branch, `look-col` this branch plus one column appended to `world` (a stand-in for the next schema change, not committed). Evidence: `updates.json` (each step's panics, guard lines, ticks, world row, counts, timers, and the relook), and `chain<n>-step<i>-<module>.log` (the module log since the step).

## Gotchas

- A trapped call's own log lines are not kept. Only the panic line, and a panic hook's output, reach the module log. A panic hook that names its module is how the old module was identified.
- SQL DML is refused (HTTP 400), so the clocks cannot be stopped from outside before an update. Pausing does not help either: a tick reads `world` before it checks `paused`.
