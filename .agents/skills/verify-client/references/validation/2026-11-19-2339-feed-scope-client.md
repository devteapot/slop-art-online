# Feed-scope client validation (verify-client)

Branch `feed-scope-client`: the game client's half of public-feed scoping (docs/FEED_SCOPING.md), on `feed-scope`. This was a scoped maintenance pass on the game client's subscription shape. The UI side is in verify-ui's record of the same name.

## What changed in the map

- [features/game-client.md](../../features/game-client.md) gains:
  - `feed_scope` in the static set;
  - the stage-chosen base queries: `gate` at stage 0, and `my_things`, `my_remembered_things`, `my_owners`, `my_stock`, `my_fuel_seen` and `my_contents_seen` at stage ≥ 1;
  - the near window's `map_resource`/`map_structure` at stage ≥ 1;
  - the make-before-break feed switch (`Net::switch_feed`), independent of the perception set.
- [features/feed-scope.md](../../features/feed-scope.md) points at verify-ui's feature for the client's side.

## Runs

- **`client-feed-235312`** (default seed, the merged authority at `43c06f3fb` = feed-scope `0a15453b` + main `50e17fca`):
  - `scripts/feed_scope.py`: 38/38.
  - Covered: private tables refused, legacy feeds empty at stage 2, `my_things` without unseen things against the owner's truth, a live insert in sight, and the copy and its memory in a reconnect's first result.
  - Cleaned up; evidence is in `.local/living/verify/client-feed-235312/`.
- **The game client's own subscriptions, through the real client** (verify-ui `feed-scope` and `feed-scope-gate`, see that record):
  - stage 0 is main's legacy set plus `feed_scope`;
  - a live 0 → 1 switch and the reverse, make-before-break;
  - a reconnect at stage 2 subscribes the scoped set only.
- **Unit tests** (`cargo test --release -p living-game`, 181 passed):
  - `net::feed_switch_tests::the_feed_and_perception_sets_combine_in_every_state` covers every stage (0, 1, 2), the four delivery-law states and both world kinds. It finds no duplicate query, perception streams that follow the laws alone, legacy tables only at stage 0, `gate` only on land, and the scoped views and map projections only at stage ≥ 1.
  - `a_window_key_carries_its_feed_and_the_lots_window_none` covers the window keys.

## Not covered

- `feed_scope.py` was not re-run on the Spark's rebased head `2ab63f48`. The client was re-run there through verify-ui.
- The fixed suite (`run.py`) was not run: no table, view or reducer of the authority changed in this branch.
