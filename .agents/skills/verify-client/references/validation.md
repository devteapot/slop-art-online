# Client protocol validation

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
