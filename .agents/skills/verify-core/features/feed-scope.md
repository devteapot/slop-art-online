# Public-feed scoping

docs/FEED_SCOPING.md ("Authority shapes"). The `feed_scope_on` law takes a world from stage 0 (legacy public feeds) to 1 (scoped rows beside them) and, `feed_scope_grace_s` later, to 2 (legacy closed, canonical rows private, latched). One sight test (`scope::Eye::sees`, `living_rules::sight::sees` over the map with its cover) decides what a player's copies (`my_things`), a mind's noticing and scene, and both controllers' memory hold of sight-scoped kinds (everything but `store::MAP_KINDS`), gates' state and depleted resource nodes.

## Drive

On your own scratch server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`; see the entry point), a fresh run with the player joined:

```bash
V=.agents/skills/verify/scripts/verify.py
R=core-feed-$(date +%H%M%S); $V launch --run $R --seed cullet && $V player --run $R join "Feed Viewer"
python3 .agents/skills/verify-core/scripts/feed_scope.py --run $R --part body
R=core-feed-g$(date +%H%M%S); $V launch --run $R --seed island && $V player --run $R join "Feed Viewer"
python3 .agents/skills/verify-core/scripts/feed_scope.py --run $R --part gate
```

`--part body` uses Cullet's brush fixture (viewer (608.5, 479.5) outside the patch, the body at (608.5, 472.5) in it; docs/COVER_SIGHT.md), with facing and gaze off so cover alone decides, and waits for daylight. The spot inside the patch is calibrated with the living victim through the player's `seen_characters` before the kill. A stranger's remains is folded into the scene's `counted_remains` entry, so the scene check accepts the listing or the count. `--part gate` needs a town with gates (`--seed island`; Cullet has none) and a resident of the gate's community as keeper (`mind_act` close/open). Evidence: `feed-scope-proof.jsonl`, `feed-scope-<part>-results.json`, `feed_scope-actions.jsonl`.

## Not covered here

The memory going when a sighting of a remembered place finds the thing gone (needs a thing to vanish out of sight: rot or a take), owner labels (`my_owners`), the mind's scene fuel wording (verify-player `feed_scope.py`), and the client boundary (verify-client `feed_scope.py`). Cost is the cost gate's (`living/tools/feed_scope_cost.py`), not this skill's.
