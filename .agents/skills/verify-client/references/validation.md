# Client protocol validation

## 2026-11-12 attention-cues: the `cue` table and `mind_update` with cues (Spark)

After merging main `c67bb6e1` (move-intents, births-2-prep, fix-unseen-killer-id): `client-cuesm-071859` 43/43 (main's 42 and the cue check).

Branch `attention-cues` (origin/main `49dfc2cd` merged), the trial service, `scoped`. `client-cuesf-064543`: 43/43 PASS (before the merge `client-cues-061552`: 43/43). `cue` is in `PRIVATE` and refused to anonymous and player identities over WebSocket and HTTP SQL (`visibility.json`, 79 tables); the permission matrix (229 calls, 0 mismatches) sends `mind_update` with a cue, refused for another's character and for anonymous; for a player's own character it succeeds and keeps no cue (`cues-owner.json`: 0 rows on the three played characters). The probe's owner snapshot carries `cues`.
## 2026-11-12 far-handle (Spark)

Branch `far-handle`: `far_label.py` 3/3 (players' rows are unchanged: they keep real ids).

## 2026-11-12 fix-unseen-killer-id (Spark)

Branch `fix-unseen-killer-id` from `7729fc9b`, the trial service `slop-trials-stdb`. `run.py` fixed suite, `client-unseen-061951`: 42/42 (no schema change: `vitals.hurt_by`, `act_outcome.other` and `combat_seen.target` keep their columns; private tables and caller-scoped views as before).


## 2026-11-12 owner-known (Spark)

Branch `owner-known` from `deb96e94`, the trial service `slop-trials-stdb`. `run.py` fixed suite, `client-owner4-050631`: 42/42 (`land_plan` private; `my_known_names` returns only the caller's own known names). An earlier run, `client-owner-043942`, failed "own mind and player effects" once: the first identity's `{"wait":30}` command had ended (28 s passed before the effects probe on a loaded machine) and its plan was back to "waiting for you"; on rerun the gap was 7 s and it passed. That is a harness timing gap, not this change; the drive's 30 s command is short for a slow machine.

## 2026-11-12 far-label (Spark) After merging main (`03d32e09`, `client-far3-031340`): `far_label.py` 3/3.

Branch `far-label` (`2095a272`/`18b7754b`), the trial service `slop-trials-stdb`. `run.py` fixed suite, `client-farlabel-023653`: exit 0. New `far_label.py`, `client-far2-024145`: 3/3 (through the SDK probe the player's `seen_characters` labels a stranger at 2 m "a stranger", one at 6 m "someone too far away to make out", neither named; the far one brought to 2 m becomes "a stranger"). The first attempt (`client-far-024057`) read the probe's events wrongly (the rows were right); the script now reads `tables`.

## 2026-11-12 stamina-1 (Spark)

Branch `stamina-1` with look-2 merged; trial service `slop-trials-stdb`, scoped build. `client-st1c`: **42 of 42**. The new checks:

- **`my_vitals`.** It carries breath and focus (`stamina`, `stamina_max`, `stamina_rate`, `stamina_from_ms`, the same four for `focus`) for the caller's character only, and none to an anonymous client.
- **`skill_card.pool`.** It names each cost's pool (dodge: stamina, 20; firebolt: focus).
- **`running`.** `my_body` and `seen_bodies` rows (`Moving`) carry it as a bool.

The driver's `SCOPED` gained `audience`. That table came from main (exp-greet), and the inventory check had stopped on it (`client-st1b`).


## 2026-11-11 the scoped inventory gains `audience` (mind-act-outcome-far, Spark)

`drive.py`'s `SCOPED` lacked the `audience` table that exp-greet added under the `LIVING_PERCEPTION` switch, so `run.py` stopped at the inventory guard ("scoped table inventory changed") on origin/main `3216b06d` too (`client-far2-233156`, drive.log). With `audience` added: `client-far3-234118` on branch `mind-act-outcome-far` at 3328c7bb, every check passes (39), the reducer permission matrix 229 calls and 0 mismatches, 77 tables private in the scoped build; `my_act_outcomes` gives only the caller's character's rows.

## 2026-11-11 look-2 (dev-box)

Branch `look-2` (from main `017286a1`, `origin/main` `1b1414a3` merged as `d609819d`) on the dev-box, own container `look2-stdb` (2.14.1, port 3330, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped` unless named, no model calls. Evidence under the worktree's `.local/living/verify/`.

- `seen_bodies` and `my_body` return `Moving` (the facing fields added) and `motion_seen` gains three columns; bindings regenerated. `run.py` `client-look2-m` (merged build, `scoped`): 39 of 39. `LIVING_PERCEPTION=open` `client-look2-open`: 39 of 39.
- Migration: `origin/main`'s module published on a scratch world with a player joined, then this module over it without deleting data: accepted in place, rows kept; the server reported that all clients are disconnected (the views' row type changed).

## 2026-11-11 rules-senses-outcomes: my_senses, my_act_outcomes (Spark)

Branch `rules-senses-outcomes` on the Spark, the trial server `slop-trials-stdb` (2.14.1, port 3320), private `CARGO_TARGET_DIR`, `scoped`, fake models only, at `7eae101e` (origin/main `7c6a92b6` merged). Evidence under `.local/living/verify/`. A maintain pass scoped to this change (perception and visibility; the inventories and own-state check), without the per-feature reader fan-out.

- `run.py` `client-sso-214657`: every check passes (39). `my_senses` gives each player one row, its own (sight 11, hearing 9), anonymous none; `my_act_outcomes` only the caller's character's rows (the reducer matrix's `human_act` calls left `act`/`unreadable` rows); `character_senses` and `act_outcome` refused to subscribers (`visibility.json`).
- In-place update (`client-migrate-214519`): origin/main `7c6a92b6`'s module published fresh, a player joined and acted, then this branch's module published with `--keep-data`: 265 characters kept, the player's character kept and ticking, `my_senses` and `my_act_outcomes` rows written after it (`before-*.json`, `after-*.json`).

## 2026-11-11 speech-2 (Spark)

Branch `speech-2` (from `speech-1`) on the Spark, the trial server `slop-trials-stdb` (2.14.1, port 3320), private `CARGO_TARGET_DIR`, `scoped`, fake models only. Evidence under `.local/living/verify/`.

- `run.py` `client-speech4`: every check passes (33), with three `speech_card` rows. `client-speech2` ran on a module rebuilt in the middle of the refusal refactor and is superseded.
- After merging origin/main (`93019a3`): `client-speech6`, every check passes (34, `my_offers` and `my_heard` both in the own-state views).
- After merging origin/main (`48cd022`, fov-1): `client-speech9`, every check passes (39); `heard` (fov-1's) and `line_heard` (who heard a line) both private, `heard_sounds` and `my_heard` both scoped.

## 2026-11-11 speech-1: heard, my_heard, speech_card (Spark)

Branch `speech-1` (from `a107fdf`) on the Spark, the trial server `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence under `.local/living/verify/`.

- `run.py` (`client-speech1`): every check passes, including the new "speech_card is public (the ways of speaking)" and "my_heard holds each player's own lines, and none for an anonymous client" (each identity 2 lines). The reducer matrix had 221 calls, 0 mismatches: `human_speak` is accepted for a joined identity, refused for an unknown way, and refused for an anonymous one. Private table visibility covers 71 tables, `heard` among them. The probe's target dir was linked to the worker's own (`.local/living/verify/target-client` → `$CARGO_TARGET_DIR/client`).

## 2026-11-11 fov-1: the field of view (dev-box)

Branch `fov-1` (from main `f2d803fa`, goods-1 merged), own container `fov1-stdb` (2.14.1, port 3318, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, fake model only. The host ran seven other workers (load average 17–60). Evidence under the worktree's `.local/living/verify/` (git-ignored).

- `client-face1-a` (`human_face` added to the player reducers, `PLAYER` in `drive.py`): 36 of 36. Each player's `human_face` is accepted, and an anonymous caller's is refused ("you have no living character").
- `client-fov1-m` (after merging `origin/main` `accf27c8`): 36 of 36, presence included (eye-2's probe fix).
- `client-fov1-a` (`run.py`, scoped build, before the merge): 35 of 36. New and passing: the private inventory with `heard`, `hear_salt` and `law_change` (refused to anonymous clients; `heard` and `law_change` refused to the player), `heard_sounds` in the views, `set_world_law` refused to players and anonymous callers ("admin only"), and five field-of-view checks over real subscriptions (`field.json`).
- One failure: presence counts each open connection (`presence.json`: 1 → 2 → 0). The "one closed" step read 0 connections, as if the held connection had already timed out on the loaded host. The change touches nothing in presence. Not rerun.
- Not run: the `LIVING_PERCEPTION=open` build; `game-client`.

## 2026-11-11 lives-3: four `rhythm` columns (dev-box)

Branch `lives-3` (four columns appended with defaults to the private `rhythm` table; bindings regenerated), own container `lives3-stdb` (2.14.1, port 3321), scoped build. `client-l3-180756`: private table visibility passes (70 tables; `rhythm` refused to an anonymous subscription and to SQL), the reducer matrix 214 calls with no mismatch; "combat feed scoped to its viewer" failed (player-2 received no row) while two other island scenes and builds loaded the machine. `client-l3b-182752` on a quiet machine: that check passed, and "presence counts each open connection of the person" failed (`1 → 2 → 0`); 30 checks pass. Neither failing check touches this change (combat feed and presence timing); each passed in the other run. Not rerun further.


## 2026-11-11 rules-offers: `my_offers` (Spark)

Branch `rules-offers` (from main `74a6d8a`, then `35c0717` merged), on the Spark, in the trial container `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped` unless named, no model calls. Every scratch database answered 404 after cleanup. The driver's view inventory and own-state set gained `my_offers`, and the probe reads it. A new offers step runs after `in-sight` ([perception.md](../features/perception.md)). `client-offers-20261111-184207` (scoped): 34 rows, all PASS. `client-offers-open-20261111-184616` (open): `my_offers` PASS, but "combat feed scoped to its viewer" FAILED: player-2's `my_combat` rows (kept 4 s) were gone before its probe, while a cargo build ran beside the suite. `client-offers-open2-20261111-184926` (open, rerun alone): all PASS but the known open-build `experience` XFAIL.

## 2026-11-11 eye-2: tile classes a client receives; presence timing (dev-box)

Branch `eye-2` (from main `eead7a29`), own container `eye2-stdb` (2.14.1, port 3317, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no model calls. Every scratch database answered 404 after cleanup.
- Tile classes (new, [game-client.md](../features/game-client.md#tile-classes), `scripts/tile_classes.py`): every `terrain_chunk` of an island world through the probe (16,384 chunks). `client-eye2-tiles1` (drop-1's hosting): 4,116 drop and 61 low tiles, the rules' counts. `client-eye2v-tiles` (eye-2): 4,116 drop, 9,153 low and 35,161 wall tiles, the rules' counts.
- Fixed suite: `client-eye2v` and `client-eye2v2` each failed one check, "presence counts each open connection" (1 → 1 → 0, then 1 → 2 → 0; the dev-box was at load 45). The probe's holds counted from its own start, so the first connection closed before or right after the second opened. Presence is unchanged on this branch. The driver now waits up to 15 s for each expected count and holds the connections 30 s and 6 s (features/presence.md). `client-eye2v3`: 30 PASS, presence 1 → 2 → 1.

## 2026-11-11 goods-1 (dev-box)

Own container `goods1-stdb` (port 3313), `scoped`. `client-g1-11111438` (before merging rules-1) and `client-g3-11111529` (merged): 31 of 31 pass, including the new "fire and shared-stock signals public to anonymous SQL" (`fire-signal.json`: `structure.lit_until_ms` and `resource_node.pool` reach anonymous SQL) and the permission matrix with `place_resource` (admin only; 214 calls, no mismatch).

## 2026-11-11 every person a mind (lives-2, dev-box)

On the dev-box worktree `~/dev/slop-lives2`, branch `lives-2` (d87310d unit 1, 6157bf0/055d80e/efcd489 units 2-4, 45d4ac6 the new-day fix), own container `lives2-stdb` (2.14.1, port 3461, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only. Several suites ran at once (load 25-45); one batch failed on a full disk (`No space left on device`, the whole dev-box at 98 %) and was rerun.

- `run.py` (`client-l2c4-031533`, scoped build): 30 of 30. Private table visibility: 63 tables, `rhythm` refused to anonymous clients and to the player; `woken`, `prior` and `prior_head` are gone. The reducer matrix first failed 10 `mind_update` calls (`client-l2c3-030713`): the driver's `PersonaIn` lacked `pastimes` and `calling`; fixed in `drive.py`.

## 2026-11-11 laws-2 (dev-box)

Branch `laws-2` (from `445db09`), worktree `~/dev/slop-laws2`, own container `laws2-stdb` (2.14.1, port 3447, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence archived on the Mac under `.local/living/laws-2/verify/`. `run.py` 30 PASS (`client-j1`). `world_law` is in `PRIVATE`. The first run (`client-l6`) stopped at the inventory check before the list had the table; `client-l6c` failed one check, "presence counts each open connection" (1 → 2 → 0 instead of 1): presence code is unchanged here, and the rerun passed.

## 2026-11-10 client feel (Mac)

Branch `fix-client-feel` (from `6c8d1002`; client-only changes, authority, rules and scripts identical to `origin/main`), shared container (2.14.1), `scoped`: 30 PASS, exit 0 (`client-feel-1110-231833/`, archived under `.local/living/fix-client-feel/`). The game client was driven headless and windowed on scratch island world `verify-feel-1` with the new `key:`, `mouse:` and `chat:` script steps and a TCP proxy that cuts the connection (features/game-client.md): no bodies are drawn while offline, a notice shows, and the client resubscribes and sends the held intent again after reconnecting.

## 2026-11-10 records private, `my_records` (Mac)

Branch `rules-2` (`eaee6b0`), own container `sao-rules2-stdb` (2.14.1, port 3342), `scoped`: 30 PASS, exit 0 (`client-rules2-4/`). Harness fixes in this change:

- `run.py` and `drive.py` accept any loopback server from `LIVING_STDB_URL`, and the drop proxy forwards to its port.
- The private-table inventory reads every authority source file (the records tables are in `records.rs`).
- `PRIVATE`, `ADMIN` and the scheduled reducers gained the floor module's `floor_seed`, `genesis_timer`, `create_floor` and `genesis_step`, missing since floors merged: on main the driver stopped at its reducer inventory.

`record`, `record_party` and `record_clock` are refused to anonymous clients and players; `my_records` is in the view inventory, and verify-player `deal.py` proves its rows.

## 2026-11-10 frames: per-viewer copies behind the views (dev-box)

Own scratch container `scale-verify` (image `v2.14.1`, port 3427) named by `LIVING_STDB_CONTAINER` and `LIVING_STDB_URL` (no name shim: `run.py` and `drive.py` now take any local server the harness names); worktree `~/dev/slop-scale`, branch `scale-1` from `1693f3e` with the frames change (docs/PERCEPTION.md, "Frames": the private `motion_seen`, `fighter_seen`, `doing_seen` and `line_seen` tables, `projected.by_viewer_body`); bindings regenerated.

- `client-scale-scoped-011217` (`run.py`, scoped default): 30 of 30. Private table visibility: 62 tables. Reducer permission matrix: 194 calls, 0 mismatches.
- `client-scale-open-011435` (`LIVING_PERCEPTION=open`): 30 PASS and the known XFAIL (anonymous `experience` in the open build).
- After merging main `fe6ec66` (megacity-1, soak-1): `client-scale-merge-scoped-091456` 30 of 30; private table visibility 63 tables; permission matrix 206 calls, 0 mismatches. The run before it stopped at the reducer inventory: megacity's `create_floor` (admin only, now in `ADMIN`) and `genesis_step` (scheduled only, now in `SCHEDULED` with `tick` and `housekeeping`) were not listed on main either.
- The two runs before stopped at the driver's inventories: the four new private tables, and `judged` (table) and `mind_judged` (reducer) from the harness merge, which the driver did not list. Both inventories now name them; `mind_judged` is called with one judgment for the caller's own character and refused for others'.
## 2026-11-10 `guest`, and harness-1's `judged` and `mind_judged` (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), branch `townlife-2` (main `015707b`, the `harness-1` merge, merged in) in a worktree: town life layer 2, phase 2 (docs/TOWN_LIFE.md): woken minds made from facts and their ring, the `woken` route, the stage cap, `host`, the `habit` engagement class, names only when known (a feeling is no longer an introduction).

- `run.py` stopped at the inventory on main as merged: `judged` (table) and `mind_judged` (reducer) from `harness-1` were missing from `PRIVATE` and `MIND`; added with `guest`.
- `client-tl2d` on the final code: 30 of 30; private table visibility 59 tables (`guest` refused to the player too); permission matrix 194 calls, 0 mismatches.

## 2026-11-09 town life layer 2, phase 1 (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `14f3a72` plus the uncommitted town life layer 2 phase 1 change (docs/TOWN_LIFE.md, "Layer 2"): the `woken`, `prior` and `prior_head` tables, the `wakes` and `woken_ring` laws. Free tier only; no model calls.

- `run.py` (`client-l2`, scoped build): 30 of 30. Private table visibility: 57 tables, `woken`, `prior` and `prior_head` refused to anonymous clients and to the player. Reducer permission matrix: 184 calls, 0 mismatches (no reducer added).

## 2026-11-09 the scoped default and the game client on the views (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `acbbda7` plus the uncommitted change that lands the perception client and makes `scoped` the default build (docs/PERCEPTION.md, "Third change"). Fake model only; private `CARGO_TARGET_DIR`s; every scratch database answered 404 after cleanup. `client-sd-scoped-181103` (no `LIVING_PERCEPTION`: the default, recorded `perception scoped`): 30 PASS, no XFAIL. `client-sd-open-181103` (`LIVING_PERCEPTION=open`): 30 PASS and the known XFAIL (anonymous `experience`). Both published the module built in their own `CARGO_TARGET_DIR` (the harness now uses it on the default seed). The game client (`game-client.md`), headless on scoped island runs (`client-sd-game`): digests match; `live: cache body` 1 at the arrival, 13–18 in a town square; residents drawn in their towns' dress; a resident labelled `a stranger` in the bubble and log until its line "Well met. I'm Renferen.", then `Renferen`; V/`gesture:appraise` showing `96 / 96` under the nameplate for the reveal, gone after; nobody drawn behind a stall's or a fence's wall tiles or rock 2–3 tiles away while someone 4 tiles away in the open is; the wolf pack drawn with its clips; the death screen naming the killer and witnesses as perceived (`a wolf`), after a fix (it showed the authority's cause text, `Rook the wolf`). `spacetime_active_queries` 20 for the game client throughout (21 for `acbbda7`'s client on an open build). Bytes per client through the perception bench's proxy, two windows per arm: calm village 2.37/1.73 → 0.23/0.48 kB/s, busy fantasy square at midday 2.78/3.48 → 1.22/0.66 kB/s (`client-sd-before*`, `client-sd-after*`). The lab observer's query set passed as the owner in both suites; a browser screenshot was not taken (no Chromium on this Mac).

## 2026-11-09 minds' sight, the projection and presence (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `81b9dd8`/`dc5e41b` plus the uncommitted minds'-sight, projection and presence change (docs/PERCEPTION.md, "Second change"; docs/PLAYER_MEMORY.md, "Presence and the offline character"). Fake model only; every scratch database answered 404 after cleanup. `client-perc2-scoped2` (`LIVING_PERCEPTION=scoped`): 29 PASS, no XFAIL, including the new `seen_characters` projection check and the five presence checks (1 → 2 → 1 connections, takeover after 30 s, handback on a new connection, presence private). `client-perc2-open`: 30 PASS and the known `experience` XFAIL. A first scoped run (`client-perc2-scoped`) stopped at the inventory check: `projected` was missing from `PRIVATE`; fixed. The patched game client ran headless on a scoped island run (`perc2/game/`: digests match, 1–9 perceived characters, dress from `folk`/`style`).


## 2026-11-09 town life tables and reducer (dev-box)

Own scratch container `slop-townlife-stdb` (image `v2.14.1`) through a `docker` name shim; worktree `~/dev/slop-townlife`, branch `townlife-1` from `b12fa45` with the town-life change uncommitted; bindings regenerated (7 new files: `act_card`, `doing`, `weather` tables and types, the `set_weather` reducer; `mind_state` gained `hailed_ms` and `hailer`).

- **`client-town-1`** (`run.py`, default seed) exited 0: every check passed except the two known XFAILs (anonymous `experience` and `thought`). The permission matrix made 184 calls with 0 mismatches (the 180 before plus `set_weather` from each non-admin identity, refused "admin only"). New check: `act_card`, `doing` and `weather` are public (`town-public.json`: 17 cards, 44 `doing` rows, 1 weather row).

## 2026-11-09 connected game client on the island (dev-box)

The dev-box ran its own scratch container `slop-live-stdb` (image `v2.14.1`, own volume, `/wasm` from the worktree) through a `docker` name shim. The other worktrees' containers were not touched. The worktree was `c5a2c00`, with uncommitted `living/game` changes (the connected game client); the authority, rules and bindings were unchanged. Evidence was copied to the dev-box's `~/live-evidence/` before the worktree was removed.

- **`client-live-suite`** (`run.py`, default seed) exited 0, with 13 PASS and the two known XFAILs. The base subscription received 685 body and 4 stats updates. The permission matrix made 164 calls with 0 mismatches. Reconnect recorded 1 drop and 2 connections.
- **`client-live-1`** (`--seed island`) ran [game-client.md](../features/game-client.md):
  - The real game client ran headless nine times. Every run logged `world kind: Land` and `digests match` (tiles `9d1884118850c39c`, heights `f860069dd92e1341`, layout `f59dcf9649678035`), with the land regenerated in 1.4 to 1.5 s.
  - It joined at the arrival point (512.5, 174.5), walked into the town through `goto` and `human_move`, and spoke. It received a line from the harness player (heard bubble and chat log), and after an admin `kill` showed the death screen, rejoined and played a new character.
  - Through the probe, `controller = :sender` returned only the player's character. The character ⋈ body join with `OR`ed chunk ranges returned 72 characters for 72 bodies.
  - **Volume at the town square** (one probe at a time, 72 bodies):

    | Query | Initial | Live |
    |---|---|---|
    | `body` window (±5 chunks) | 5.3 kB | 10.4 and 9.7 kB/s (2,055 and 1,836 events in 30 s) |
    | character join | 7.1 kB | 33 B/s |
    | `terrain_chunk` (±5 chunks) | 32 kB | none |
    | `terrain_chunk` (±3, what the client now uses) | about 13 kB for 49 rows (estimated from the ±5 figure, not measured) | none |
    | `lot` (±11 chunks) | 21.8 kB | none |
  - **Whole walk** (146 s, arrival to square and streets, one client): 296 kB subscribe, 230 kB unsubscribe and 1.59 MB updates, about 14.5 kB/s in all. `spacetime_active_queries` stayed at 12.
- **Harness defect:** `verify.py cleanup` decides whether other `verify-*` databases are live from `spacetime list`. On this 2.14.1 server that prints "No databases found" for the CLI identity, so cleanup of `live-1` stopped the container while `verify-client-live-1` was live. The container was restarted by hand, and no data was lost.


## 2026-11-09 island land worlds (dev-box)

Host: the dev-box (Fedora, rootless podman, SELinux), scratch container `slop-game-stdb` (image `v2.14.1`) through a `docker` name shim (`docs/ISLAND_AUTHORITY.md`, "Verification"). `living/` had the uncommitted island change on `dc34fdf`.

- **`client-20261109-021430`** (`run.py`, default seed) exited 0. It recorded 13 PASS and the two known XFAILs (anonymous `experience` and `thought`), and cleanup was confirmed by SQL 404. The new public tables `land`, `settlement` and `lot` did not change the private-table or reducer inventories.
- **The probe now reads and counts `land`, `settlement` and `lot`.** Before that, an ad-hoc `lot` query applied and the server sent 5,662 bytes, but `tables` came back empty.
- **`client-island-1`** (`--seed island`) ran chunk-window queries through `drive.py --query`. Rows and bytes are in `client-island-1/subs.txt` and `docs/ISLAND_AUTHORITY.md`: the whole `terrain_chunk` is 16,384 rows (4.3 MB), and a 22 × 22 window is 484 rows (128 kB).

## 2026-11-08 SpacetimeDB 2.14.1 upgrade (macOS)

Host: Apple Silicon laptop, Docker Desktop. Image `v2.14.1` on a fresh data volume (`living-stdb-2`). SDK, SATS and generated bindings were 2.14.1, and the bindings were regenerated with the in-container 2.14.1 CLI. `living/` had uncommitted upgrade changes on top of `0ea349c`.

- **First attempt failed** (`client-20261108-192719`). The probe passed the connection token back through `/proc/self/fd/N`, which exists only on Linux. On macOS that panicked with `credential pipe: … No such file or directory`, and `drive.py` failed to parse the empty output.
- **The fix:** the probe now writes to `/dev/fd/N`, which works on Linux and macOS. This was a portability bug, not an upgrade regression.
- **Second run** (`client-20261108-192909`) exited 0. Its results match the 2026-10-04 baseline: 13 PASS and two XFAIL, the known anonymous `experience` and `thought` leaks.
  - The base subscription received live updates: 839 body updates and 4 stats updates.
  - The reducer permission matrix made 164 calls with 0 mismatches.
  - Reconnect recorded 1 drop and 2 connections.
  - Cleanup deleted the scratch database.

## 2026-10-04 fix round

Host: Fedora, rootless podman, SELinux enforcing. The existing `sao-living_spacetimedb_1` container served `http://127.0.0.1:3300`, image `v2.10.1`. SDK, SATS and generated bindings were 2.10.1. Commit: `384fb50e379533b7db64698357efd0b2323f9452`. `living/` had the user's uncommitted viewer clock change. This fix round changed only `.agents/skills/verify-client/`.

The full skill ran with:

```bash
.agents/skills/verify-client/scripts/run.py --run client-fix-1004-adhoc-suite
```

It exited 0 with 13 PASS and two XFAIL results. Evidence remains in `.local/living/verify/client-fix-1004-adhoc-suite/`. Launch, doctor, the primary player join and cleanup used the shared harness. Doctor verified server image and module freshness, and observed ticks 48 to 287 over its four-second check.

The initial base subscription received one world, 267 characters and 266 bodies. The suite used the exact 27 viewer queries, three actor-specific inspector queries, individual private-table queries and identity-scoped views. It made 164 permission calls plus one authorized admin scene call and the added harness speech call. Base live observation lasted 4,012 ms; the view fixture waited 30,790 ms; reconnect observed about two seconds before the drop and four seconds after resubscription; the ad-hoc speech stream lasted four seconds. No browser observer, mind service, model calls or Neo4j access ran. These are diagnostic workload counts, not performance evidence.

A separate manual run, `client-fix-1004-query`, used shared launch and doctor, then the documented `drive.py --query` commands. Evidence remains in `.local/living/verify/client-fix-1004-query/`. Its `triage-results.json` records seven PASS checks. It joined one player while an anonymous speech subscription was live and used two pairs of admin `set_paused` calls on that scratch world for callback fixtures.

## Ad-hoc client triage

All evidence in this table is under `client-fix-1004-query/`, except the automatic suite row.

| Check | Result | Evidence |
| --- | --- | --- |
| Anonymous initial snapshot and live speech insert | PASS. After `initial`, the harness joined `ClientTriage`, actor 268, then said `VERIFY_CLIENT_TRIAGE_SPEECH`. Chronicle insert id 204 arrived with kind `speech` and the exact marker | `speech-anonymous.jsonl`, `player-join.log`, `player-say.log` |
| Full old and new rows on update | PASS. `SELECT * FROM world` received `paused: false` to `true`, then `true` to `false`, as two `update` events | `world-updates.jsonl`, `paused.log`, `unpaused.log` |
| Deletes and inserts at a query boundary | PASS. `SELECT * FROM world WHERE paused = false` received a `delete` when paused, then an `insert` when unpaused | `world-filter.jsonl`, `actions.log` |
| Player identity and initial rows | PASS. `--as-player --seconds 0` used the identity in harness `state.json` and received the earlier speech in its initial snapshot | `speech-player.jsonl` |
| Private-table refusal | PASS. `SELECT * FROM clock` recorded the SDK's private-table refusal and the driver exited 1 | `private-refusal.jsonl`, `private-refusal.log` |
| Applied query with no matches | PASS. The query for kind `no-such-kind` recorded empty initial `tables`, completed and exited 0 | `empty-query.jsonl` |
| Evidence overwrite refusal | PASS. Reusing `--save speech-player` exited 1 and left the original JSONL bytes unchanged | `overwrite-refusal.log` |
| Automatic suite's live speech check | PASS. The harness's `player say` produced a matching live chronicle insert after the subscription applied | `client-fix-1004-adhoc-suite/adhoc-suite.jsonl`, `adhoc-suite.log` |

The anonymous stream observed speech for ten seconds. Update and filter streams each observed three seconds. Initial-only and refusal checks used zero live seconds. Initial callbacks were suppressed until the initial cache snapshot had been printed. The speech marker occurred once as a live insert, rather than being counted as an initial insert.

`drive.py` supplies the Rust probe's request on stdin. The agent-facing commands need no knowledge of that internal format and expose no token arguments. Stream evidence includes full rows serialized from generated SATS types. Keyless views report insert/delete callbacks. A filter delete records removal from the client's result, not deletion from authority storage.

## Anonymous observer subscriptions

| Check | Result | Evidence in `client-fix-1004-adhoc-suite/` |
| --- | --- | --- |
| Viewer query and permission inventories match source | PASS | `source-inventory.json` |
| Initial applied base subscription | PASS. One world and nonempty character rows | `anonymous-base.json` |
| Live base updates | PASS. 706 body updates, four stats updates, ticks 348 to 588 | `anonymous-base.json` |
| Actor-specific filters and routine-stat join | PASS. Actor 18, seven experiences, eight routines and one matching stat row | `inspected-character.json` |

These are real Rust SDK WebSocket observations after `on_applied`. Admin SQL does not establish client receipt.

## Table visibility

| Check | Result | Evidence in `client-fix-1004-adhoc-suite/` |
| --- | --- | --- |
| Ten private-table WebSocket refusals | PASS. Every query rejected with a private-table error | `visibility.json`, `private-*.json` |
| Ten private-table anonymous HTTP refusals | PASS | `visibility.json` |
| Anonymous experience privacy | XFAIL, KNOWN ISSUE. 3,374 received perceptions for 260 observers | `privacy-experience.json` |
| Anonymous thought privacy | XFAIL, KNOWN ISSUE. Twelve thoughts for three actors, including scripted raw-detail markers | `privacy-thought.json` |

Both XFAILs track [LIVING_HANDOFF.md, Still open](../../../../docs/LIVING_HANDOFF.md). `living/authority/src/tables.rs:417` makes `experience` public and `tables.rs:588` makes `thought` public. Both privacy assertions still require denial. They become XPASS and make the driver exit 1 when access is fixed. Missing foreign fixtures or a transport failure remains FAIL. Product code was unchanged.

## Identity-scoped deliberations

| Check | Result | Evidence in `client-fix-1004-adhoc-suite/` |
| --- | --- | --- |
| Positive admin view | PASS. Initially empty; five requests arrived, including actor 18. Each controller matched the SDK connection identity | `view-admin.json` |
| Three player views and a fresh anonymous view | PASS. All applied and returned zero deliberations | `view-player-1.json`, `view-player-2.json`, `view-anonymous-connected.json`, `view-anonymous.json` |
| Foreign empty views sampled between occupied admin views | PASS. Five requests remained afterward | `view-admin-after-players.json` |

The shared `verify.py call --as-admin` set actor 18's behavior to a `think` node. The authority's tick created the requests. The SDK view connection obtained its admin token through the harness's `admin_token()` helper. HTTP SQL was not substituted for the identity-scoped subscription.

## Reducer permissions and effects

| Caller or check | Result | Evidence in `client-fix-1004-adhoc-suite/` |
| --- | --- | --- |
| Identity created by anonymous SDK connect | PASS. 46 calls | `reducers.json`, `reducers.md` |
| Primary player | PASS. 44 calls, plus its initial harness join | `reducers.json`, `player-join.log` |
| Second player | PASS. 45 calls | `reducers.json` |
| Tokenless HTTP calls | PASS. 29 calls | `reducers.json` |
| Combined permission matrix | PASS. 164 calls, zero mismatches | `reducers.json`, `results.md` |
| Authorized admin view setup | PASS. Separate harness call | `admin-scene-setup.log`, `actions.log` |
| Own-character reducer effects received | PASS. Each persistent identity's routine, scripted thought, human command plan and speech appeared in subscriptions | `reducer-effects.json` |

All 16 admin reducers refused non-admin calls with HTTP 530 and `admin only`. All seven `mind_*` reducers refused AI or foreign-player targets with HTTP 530 and `not your character`. They accepted the caller's own player character. `living/authority/src/mind.rs:75` checks ownership without requiring `ai = true`; this is current policy, not a newly classified defect.

External `tick` and `housekeeping` returned HTTP 404 with `No such procedure`. These calls do not execute the internal scheduled sender guards on 2.10.1. The matrix preserves arguments, exact HTTP bodies and expectations. No identity token appears in it.

## Reconnect

| Check | Result | Evidence in `client-fix-1004-adhoc-suite/` |
| --- | --- | --- |
| One real network drop | PASS. Relay closed its client socket pair; SDK recorded `connection closed` | `reconnect.json`, `results.json` |
| Three-second retry and resubscription | PASS. Exactly two relay connections; base and inspector queries applied again | `reconnect.json`, `results.json` |
| Live changes after reconnect | PASS. 763 body updates, five stats updates, 18 inspected experiences; final tick 3,467 exceeded round one's 2,987 | `reconnect.json` |

The relay never stopped or restarted the server. This drives SDK recovery, not Bevy's `Net::pump`.

## Changes and cleanup

Changes in this fix round:

- Added `--query`, `--as-player`, `--seconds` and `--save` to the driver, with immutable JSONL evidence and live output.
- Added full-row SATS serialization and real insert, update and delete callbacks to the Rust probe. Pinned SATS 2.10.1 in the standalone manifest and lockfile.
- Added an automatic speech-insert check, a triage feature map and exact manual commands.
- Removed the runner's separate container check, HTTP implementation and publication recovery rewrite. The runner uses the shared container and HTTP helpers; cleanup trusts the harness's successful SQL-404 confirmation.
- Removed JWT parsing from the driver. Admin scene setup uses the shared call command; the admin SDK connection uses the shared token helper.
- Replaced the stale harness description. Current `verify.py launch` saves `published = true` before publishing, and records container ownership after starting it. `cleanup` deletes the run's database, confirms SQL 404, removes the primary token and retains evidence. This task needs no shared harness change.

The initial Rust build exposed that SATS `SerdeError` has no `Debug` implementation. The probe's serializer failure handling was corrected, then the locked build and full run passed. No database had been launched for that build attempt.

| Run | Cleanup result | Retained evidence |
| --- | --- | --- |
| `client-fix-1004-adhoc-suite` | PASS. Harness confirmed SQL 404; `published` false; player token removed; shared container up; `.local/living/token` unchanged | `cleanup.log`, `cleanup-proof.json`, all feature evidence |
| `client-fix-1004-query` | PASS. Harness confirmed SQL 404; `published` false; player token removed; all seven proof artifacts still exist | `cleanup.log`, `state.json`, `triage-results.json`, all query evidence |

Both scratch databases were deleted. The existing shared container remained running. No reference world was published, deleted or resumed. Earlier validation runs remain on disk as history; this record describes only the current scripts and fix-round runs.

## Documentation and compatibility

Rechecked the official [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [Rust SDK](https://spacetimedb.com/docs/clients/rust/) documentation before designing the ad-hoc mode. Their design implication is to read initial cache rows after subscription application, then use row callbacks for changes. The current docs show 2.0.0, so the [official table source at the released 2.10.1 commit](https://github.com/clockworklabs/SpacetimeDB/blob/3d7607082ab47257adeb7c25164536511237f2b5/sdks/rust/src/table.rs) and the installed 2.10.1 source verified callback availability. The probe retains the pinned SDK's WebSocket negotiation and decoding. It makes one requested subscription and writes matching changes incrementally. `chronicle.kind` is unindexed, so the speech filter requires an initial scan of that bounded table.

Shared frontmatter, executable Python helpers, all four required feature headings, local documentation links, Python syntax, the standalone locked Rust build and formatting, and whitespace checks passed. Claude and Cursor discovery links resolve to this shared skill; Codex and Mistral Vibe use `.agents/skills/`. No adapter changes were needed.

## Remaining limits

- No second positive AI controller view was created. The admin controls seeded AI actors; joined players do not receive deliberation requests.
- The manual ad-hoc stream's unexpected disconnect and live keyless-view changes were not separately driven. The full suite drove the actual connection drop and occupied identity-scoped view through its existing probe mode.
- No supported agent runtime was relaunched to test its live skill menu. Only file discovery and instruction links were checked for Claude, Cursor, Codex and Mistral Vibe.
- Browser presentation and Bevy reconnect policy have no verification skill until the proper UI exists. Authentic inference and personal learning belong to `verify-minds`, `verify-llm` and `verify-knowledge`; gameplay outcomes belong to `verify-core` and `verify-player`.
- These short scratch runs establish no population, latency, memory or retention acceptance. No new product defect was found beyond the two existing privacy XFAILs.


## Infant private-table verification, 2026-10-04

Runs `client-infant-visibility-01` on `llm/baby-warmth` at `b2f115c` and `client-infant-visibility-02` after the evaluator-timer fix at `6001413` used the documented `scripts/run.py` wrapper. In each run, all eleven private tables, including `infant_cry`, refused anonymous SDK WebSocket subscriptions and HTTP SQL. The infant table returned the pinned server's private-table error through both transports. The full suite also passed 164 reducer-permission calls with zero mismatches, identity-scoped views, per-character reads, live updates, reconnect and ad-hoc speech. The existing public `experience` and `thought` leaks remained XFAIL.

Evidence is `.local/living/verify/client-infant-visibility-{01,02}/{visibility.json,private-infant_cry.json,results.md,cleanup-proof.json}`. Both cleanups confirmed SQL 404, removed the player tokens and preserved the running shared container and existing living token. No model service or inference ran.

The scoped maintenance source wave checked the visibility map against the private-table inventory and runtime discovery links. Shared skill discovery, executable helpers and frontmatter were checked for Codex, Claude, Cursor and Mistral. Live runtime menu/instruction-loading checks were not run. Unchanged client features were covered by the full suite; no new product fix was needed.

## 2026-11-09 combat tables and views (dev-box)

Own scratch container `slop-combat-stdb` (v2.14.1) via `~/combat-shim`; worktree at `e0c9d1f` plus the combat change. `run.py --run client-combat-20261109-060621`: 16 PASS and the 2 known XFAILs; cleanup confirmed by SQL 404. New checks: the four private combat tables refused; `my_combat` scoped to its viewer (each player received only its own `REFUSED`, anonymous none); `my_skill_uses` scoped to own characters; `fighter` and `skill_card` public (6 cards); `use_skill` and `release_skill` in the permission matrix (180 calls, 0 mismatches). The first run (`client-combat-20261109-054716`) failed the feed check because the refusals were made a minute before the probe and the feed keeps rows 4 s; the driver now refuses a strike just before probing.
