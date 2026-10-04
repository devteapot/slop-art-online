# Mind level of detail

## Sub-features

- The first off-stage deliberation runs immediately.
- A subsequent routine request remains pending off stage during the 600-second think gap.
- Contact with a player puts the character on stage and releases the held request.
- A merged non-plan reason must be reconsidered after the held request is released. The missing update callback is XFAIL KNOWN ISSUE.
- Urgent reasons and off-stage gaps have focused tests, `living/mind/src/mind/lod.rs:122`.

## How to get to it (user POV)

Start the service with `LIVING_LOD=1`. Characters away from players keep living by their graphs and think less often. A player entering their experience brings them on stage.

## Driving it with verify_minds.py

```bash
R=minds-lod-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case lod
```

The driver runs the first deliberation, waits 46 seconds for the authority's think guard, then requests another. For seven seconds, the second request must remain in `offstage-held.json` without another think exchange. A shared player joins, admin `place_near` brings it beside the AI, and addressed speech supplies player contact. A new think exchange and accepted thought must appear within 15 seconds. While the on-stage compile is delayed four seconds, the driver merges `verify merged nonplan reason` into the authority row. After the first install, that reason must appear in a later accepted thought. `merged-pending.json` proves the update, and `onstage-pending-after.json` plus `merged-thoughts-after.json` show whether it remained stale. `lod.json` records the counts, gap and reason snapshots. Hold and release must pass. An unhandled retained reason produces XFAIL KNOWN ISSUE; handling it produces XPASS for review.

## Gotchas

- Player contact comes from experience callbacks, `living/mind/src/main.rs:149`, and sets a sticky on-stage window, `living/mind/src/mind.rs:921`.
- LoD changes call frequency. It does not replace real-time graph execution.
- This scene proves a short hold and release, not expiry of the full 600-second gap, off-stage talk pacing, consolidation pacing or thousands of characters.
- Mind unit tests run automatically with every suite. If the live scene fails, report the blocker and unit results separately.
- `my_deliberations` has only `on_insert` in `living/mind/src/main.rs:165`. The authority merges newer reasons with an update, and the LoD pending copy misses it. This defect is recorded in [the handoff](../../../../docs/LIVING_HANDOFF.md), under "Still open", and reproduced separately from the successful plan-completion hold and release.
