# Feed-scope client validation (verify-ui)

Branch `feed-scope-client`: the game client's half of public-feed scoping ([features/feed-scope.md](../../features/feed-scope.md), docs/FEED_SCOPING.md).

- **First series:** on `43c06f3fb`, which is feed-scope `0a15453b` with main `50e17fca` merged in by this branch.
- **Rebased:** the client commits were then rebased onto the Spark's iteration-2 head `2ab63f48`, which adds `my_contents_seen`, and re-run there.

## Setup

- **Hardware and server:** an Apple laptop, headless Bevy 0.20.1 clients, and the shared SpacetimeDB 2.14.1 at `:3300`.
- **Builds:**
  - release builds through `build-slot` (`BUILD_SLOTS=1`);
  - a private `CARGO_TARGET_DIR` of `.local/target`;
  - modules built per run with `--target-dir`.
- **Assets:** linked read-only. For the first island runs they came from the main checkout. From the seat rerun on, they came from `slop-play10`: `lookdev`, `textures`, `characters/looks.json` and `envs/*`.
- **Model calls:** none. All worlds were scratch `verify-ui-*` worlds, deleted through cleanup.

## Results

### New scenarios

- **`feed-scope`** (Cullet):
  - `ui-fsc-1119-2313`: 24/26, which found two fixture errors, fixed in the script.
  - `ui-fsc-1119-2322`: 27/27.
  - `ui-fsc-1120-0001`: 27/27 (on the old head).
  - New head `ui-fsc2-0017`: 27/29. The two failures were fixture assumptions about structure rows: that arrival window held only resources. They were fixed, and `ui-fsc3-0029` then gave **29/29**.
  - **Switch times:** 0 → 1 in 60–84 ms, and 1 → 0 in 67–77 ms.
  - **The reverse switch** (law off at stage 1): the client's scoped rows went to 0 before the legacy set arrived. The authority clears the map projections in the transaction that sets stage 0, so in `ui-fsc2-0017` 79 rows were gone. The drawing held the 48 drawn things (`feed::switching`), and no drawn map thing was lost at any logged line.
  - **The remains:** "not looked inside" before looking, then "3 berries when you looked inside, 3 s ago".
  - **The lamp:** "burning" before looking it over, then "about 28 h of fuel left, as of when you looked it over, 2 s ago".
  - **The boulder:** after one stone it was live at 5/6, fill 0.83.
- **`feed-scope-gate`** (island):
  - 9/9 on `ui-fsi-1119-2324` (old head), after one fixture fix: the island's gates belong to one community.
  - 9/9 on `ui-fsi2-0018` (new head).

### Regressions on the old head, stage 0

- **Cullet `ui-fsc-1119-2322`:** cover and gaze 133/133.
- **Island `ui-fsi-1119-2324`:** windows, talk, look-walk, camera and law-override (the frame-tier live toggles) all passed; seat had 8 failures.
- **Seat, re-run** with main's `be1668c31` seat-check fix applied in a scratch copy and the `slop-play10` assets: 18/20.
  - `be1668c31` changed exactly the "renewed rest" checks: since doing-renew, a renewal extends the row in place.
  - The 2 remaining failures are `_f` clip-variant selection. They need the archived `own-clips-24e58dc75.glb` that the seat record names, which was not found here. The check selects clips by look line and does not touch the feed.

### Regressions at stage 2

- **Island:** talk and windows passed.
- **Island law-override:** first a harness failure, then 2 fixture failures.
  - **The harness failure:** the scenario's `wait_for` matched the previous run's `client.log` before drive.py replaced it, so every toggle was sent before the client started. This is fixed in check.py, which now clears the stale log and `.go` files.
  - **The fixture failures:** after the fix, the two "creature kept across the switch" checks fail whenever no creature is in sight at arrival. That was 0 others in `ui-fsi-1119-2324` at stage 2, and in `ui-fsi2-0018` at stage 0 too. No run showed a missing creature.
- **Cullet `ui-fsc-1120-0001`:** cover passed. Gaze failed one check, because resident #5 was not at its exact placed spot. The Shade and the authority agreed at every probe.

### Regressions on the new head, stage 0

- Cullet `ui-fsc2-0017`: cover passed.
- Island `ui-fsi2-0018`: law-override had the same 2 fixture failures as above.

### Unit tests

- `cargo test --release -p living-game`: 181 passed.
- `cargo test --release -p living-rules`: 349 passed, including `ui::tests::the_game_client_names_no_new_skills`.

## Maintenance (scoped to this change)

- **Added:** `features/feed-scope.md`, its row in the map, a SKILL.md paragraph, and the two scenarios, registered with `@scenario`.
- **Harness:** the law-override stale-log fix.
- **Not re-read from source:** the other feature files.

## Not covered

- A fresh connection's join/reclaim wait (`feed::settled`) was exercised only through reconnect at stage 2.
- Owner labels from `my_owners` on screen.
- Tile worlds.
- Stage 0 byte-for-byte against main's binary. The query set is main's plus `feed_scope` (unit test), and the regressions passed.
