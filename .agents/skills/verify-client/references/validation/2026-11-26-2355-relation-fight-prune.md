# relation-fight-prune: client visibility & inventory after indexing relation_fight.other

Branch `relation-fight-prune` from `origin/main` (`18564737a`), Spark (`aarch64`), private SpacetimeDB 2.14.1 container `slop-retfix-20261126` (`127.0.0.1:3621`). Launches under `trial-activity.lock`.

**Change:** Added `#[index(btree)]` on `RelationFight.other` and regenerated `living/bindings` (`RelationFightIxCols.other` added). No table visibility, view, reducer, or subscription changed.

| Check | Result |
|---|---|
| `verify-client` (`client-rf-20261126-230823`, scoped build) | PASS (source inventory unchanged; `relation_fight` remains private and refused to anonymous/player clients; presence, sight, field, offers, reconnect, ad-hoc speech all pass; cleanup proof ok) |

**Evidence archive:** `~/slop-evidence/relation-fight-prune-20261126.tar.zst` (+ `.sha256`).

**Not covered:** `LIVING_PERCEPTION=open` diagnostic build (visibility of `relation_fight` is private in both builds); Bevy UI rendering.
