# Client protocol validation

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
