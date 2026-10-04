# Mind level of detail

## Sub-features

- The first off-stage deliberation runs immediately.
- A subsequent routine request remains pending off stage during the 600-second think gap.
- Contact with a player puts the character on stage and releases the held request.
- A plain reason merged into a held row refreshes the pending request without releasing it.
- An urgent reason merged into that row releases it within five seconds, before the 600-second gap expires. The accepted thought includes the plain reason too.
- A non-plan reason merged during compilation must be reconsidered after the first install.
- Urgent upgrades, refreshed scenes, same-timestamp replacements and off-stage gaps have focused tests in `living/mind/src/mind/lod.rs`.

## How to get to it (user POV)

Start the service with `LIVING_LOD=1`. Characters away from players keep living by their graphs and think less often. A player entering their experience brings them on stage.

## Driving it with verify_minds.py

```bash
R=minds-lod-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case lod
```

The driver runs the first deliberation, waits 46 seconds for the authority's think guard, then requests another. For seven seconds, the second request must remain in `offstage-held.json` without another think exchange. It merges `verify plain merged reason`, checks another two seconds of holding, then merges `Wolf is attacking you! verify urgent upgrade`. A think exchange must start within five seconds. The accepted thought in `urgent-thoughts.json` must contain both merged markers. `plain-merged-pending.json` records the authority row before the upgrade.

After another 46 seconds, a fresh off-stage request must remain held for three seconds. A shared player joins, admin `place_near` brings it beside the AI, and addressed speech supplies player contact. A new think exchange and accepted thought must appear within 15 seconds. While the on-stage compile is delayed four seconds, the driver merges `verify merged nonplan reason` into the authority row. After the first install, that reason must appear in a later accepted thought. `merged-pending.json`, `onstage-pending-after.json` and `merged-thoughts-after.json` capture the result. `lod.json` records the release time, counts and snapshots. Every assertion must pass.

## Gotchas

- Player contact comes from experience callbacks in `living/mind/src/main.rs` and sets a sticky on-stage window in `living/mind/src/mind.rs`. Both experience and scene checks share `lod::is_player`, an indexed character lookup followed by `!ai && controller != mind_identity`. Benchmark characters on instinct also qualify; this is not an exact human-only signal.
- LoD changes call frequency. It does not replace real-time graph execution.
- This scene proves a short hold and release, not expiry of the full 600-second gap, off-stage talk pacing, consolidation pacing or thousands of characters.
- Mind unit tests run automatically with every suite. If the live scene fails, report the blocker and unit results separately.
- The [Rust callback documentation](https://spacetimedb.com/docs/clients/rust/#callback-on_update) and [pinned SDK 2.10.1 source](https://docs.rs/spacetimedb-sdk/2.10.1/src/spacetimedb_sdk/table.rs.html#153-178) require a known primary key for `on_update`. The generated `my_deliberations` view has none, so replacements use insert/delete callbacks. The SDK dispatches inserts before deletes. The authority can strip obsolete plan reasons without changing `updated_ms`; the old timestamp-only delete check therefore removed the replacement. Deletes now match the complete old row. Merges and player contact notify the waiting worker to re-evaluate its current row immediately.
