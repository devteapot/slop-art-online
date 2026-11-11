# Internal mind validation

## 2026-11-11 every person a mind (lives-2, dev-box)

On the dev-box worktree `~/dev/slop-lives2`, branch `lives-2` (d87310d unit 1, 6157bf0/055d80e/efcd489 units 2-4, 45d4ac6 the new-day fix), own container `lives2-stdb` (2.14.1, port 3461, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only. Several suites ran at once (load 25-45); one batch failed on a full disk (`No space left on device`, the whole dev-box at 98 %) and was rerun.

- `resident` (new, replaces `wake`): `minds-l2res-014448` and in the full suite `minds-l2c-030713` pass. The first try (`minds-l2res-014127`) failed: a seeded resident's starting graph counted as its last thought, so for 20 s its deliberation requests were dropped; fixed in the authority (a new character's first request is not held back by `think_min_s`).
- `lives_mind.py` (replaces `lives_wake.py`): 32 of 32 (`minds-l2lives-014653`, again `minds-l2clives-030713`). Its first form checked people in the first prompt, which for a mind already living is a talk turn; it now asks for a deliberation with an admin `set_behavior` think node after the player's line.
- Full suite `minds-l2c-030713` on the fixed build: roundtrip, acts, conversation, prune, reject, only, reconnect, lod, takeover, sight, resident, night, rethink and rethink-llm pass; consolidation is its known XFAIL; `jev` and `dealings` timed out under load and pass alone (`minds-l2c-jev-033522`, `minds-l2c-deal2-*`). An earlier suite (`minds-l2b-022738`) on the build before 45d4ac6 failed consolidation, prune, only, reconnect and lod: every person felt "A new day begins" on every evaluation for three game hours (a mark the brain did not write back), so a pending request was always there; fixed in 45d4ac6.
- `animals`: **known gap.** The case's last step (the lead asked again with nothing new lives by instinct, no call) relied on the dawn broadcast's urgency to pass the deer's 240 s `think_min_s`. Without it, only urgent reasons pass the throttle and every urgent reason is news to the salience check; waiting the throttle out (`minds-l2c-animals2-033522`) the deer grew hungrier, also news, so it chose with a call. The first two steps (one `choose` call; the pack reusing it) pass. Proving the salient path needs a fixture with a shorter deer `think_min_s` or a needs scene reducer.

## 2026-11-11 laws-2 (dev-box)

Branch `laws-2` (from `445db09`), worktree `~/dev/slop-laws2`, own container `laws2-stdb` (2.14.1, port 3447, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence archived on the Mac under `.local/living/laws-2/verify/`. `verify_minds.py` with the fake model (`minds-l6c`): roundtrip (with the new check that every think and deliberate prompt carries the SENSES, MOVING, FOOD and SETTLEMENTS sections built from the laws), acts, conversation, prune, reject, only, reconnect, lod, takeover, sight, wake, animals, night, rethink, rethink-llm and dealings pass; consolidation its known XFAIL; `jev` timed out waiting for a judgment in that run and passed alone (`minds-j1`). The first run (`minds-l6`) died when the disk filled.

## 2026-11-10 rules2-r2 fixes (dev-box)

On the dev-box worktree `~/dev/slop-mind-small`, branch `fix-mind-small`, own container `mind-small-stdb` (2.14.1, port 3427, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only.

- Full suite `minds-ms-full`, run beside the llm and knowledge suites (load 15–28): 16 cases pass, `consolidation` is its known XFAIL; `takeover` and `dealings` failed on timeouts.
- `dealings` passed alone (`minds-ms-re-dealings`): a timing failure.
- `takeover` failed alone too (`minds-ms-re-takeover`), and that one was the branch's fault: the joined player's character, with no sheet, background or seed entry, was sent to a model-written identity (an extra `consolidate` call), which pushed its second decision into the think node's 45 s quiet window. Fixed in 7a3b425 (nothing is written for such a person, as before); `minds-ms-re2` `takeover`, `wake` and `roundtrip` pass.

## 2026-11-10 dealings (Mac)

Branch `rules-2` (`eaee6b0`), own container `sao-rules2-stdb` (2.14.1, port 3342), fake model. `dealings` (new) passed on the fourth attempt (`minds-rules2-4-dealings/`). The earlier attempts failed on the driver: the demander's own graph kept its body busy; the thinking cadence dropped the rules' ask after the mind's first thought, so the case now requests the next thought; and the fake rule did not allow for the quoted reason in the dealing's words. `acts`, `roundtrip`, `conversation` pass (`minds-rules2-1-*/`).

## 2026-11-10 mind feedback (Mac)

On the Mac (Docker Desktop), branch `feedback-1` (ffb4280 on main 6de2bad) in a worktree, against its own server `feedback-verify-stdb` (2.14.1, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL=http://127.0.0.1:3343`), private target: docs/MIND_FEEDBACK.md.

- Full suite `minds-fb1-005416`: roundtrip (now also the body line in think and compile requests), conversation, prune, reject, only, reconnect, lod, takeover, sight, wake, animals, night and jev pass; consolidation is its known XFAIL. `acts` failed on its new check's wait condition (it waited for `#id` in the outcome, which names the resolved kind: "gather → boulder (+1 stone)") and passed on `minds-fb1acts-011707` after the fix.

## 2026-11-10 woken minds (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), branch `townlife-2` (main `015707b`, the `harness-1` merge, merged in) in a worktree: town life layer 2, phase 2 (docs/TOWN_LIFE.md): woken minds made from facts and their ring, the `woken` route, the stage cap, `host`, the `habit` engagement class, names only when known (a feeling is no longer an introduction).

- Full suite `minds-tl2c-*` on the final code: roundtrip, acts, conversation, prune, reject, only, reconnect, lod, takeover, sight, wake, animals, night and jev pass; consolidation is its known XFAIL. Earlier runs on this branch (`minds-tl2-220630`, `minds-tl2b-*`) the same.

## 2026-11-09 the rethink gate, rethink-1 (dev-box)

- **Setup:** private container `rethink-stdb` (2.14.1) on 3397, private `CARGO_TARGET_DIR`, fake model and fake Jev; no paid calls.
- **New cases `rethink` and `rethink-llm`:** they failed four times, each on a harness fault:
  - the fake's Jev endpoint read `health` as a number, while the gate sends words, so it crashed (the mind's fallback path held);
  - a poll on the pending row raced the fake mind (the case now waits on the `rethink-gate` journal);
  - `max_hold_s` 25 released the request mid-case (now 90);
  - an assertion ran before the mind's start-up line (now a wait).
- **Passes:** `minds-rethink-230515` passed both cases.
- **Full suite `minds-full-232622`:** all 17 cases pass (roundtrip, acts, conversation, prune, reject, only, reconnect, lod, takeover, sight, wake, animals, night, jev, rethink, rethink-llm); consolidation is its known XFAIL.
- **After merging main** (townlife-2, trials-1): `minds-merged-010653` passed rethink, rethink-llm, wake, conversation, lod, roundtrip and jev.
- **Final, after merging main `fe6ec66`** (feedback-1, iter-6, lives-1, soak-1): `minds-final-091241` passed all 17 cases; consolidation is its known XFAIL.
- **SELinux:** on this Fedora host the container's `/wasm` bind mount needs the `z` label, or `spacetime publish` fails with "Permission denied".

## 2026-11-09 town life layer 2, phase 1 (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `14f3a72` plus the uncommitted town life layer 2 phase 1 change (docs/TOWN_LIFE.md, "Layer 2"): the `woken`, `prior` and `prior_head` tables, the `wakes` and `woken_ring` laws. Free tier only; no model calls.

- `wake` (new case, island): `minds-wake-203130` failed (the line arriving while the woken resident deliberated is left to that deliberation; the fixture answered only through talk), `minds-wake-203416` failed (the answer comes from the think step's `say`), `minds-wake-203552` failed (no-store projection does not replace places; the case now sends the replacing `mind_update` itself), `minds-wake-203725` pass.
- Full suite `minds-l2-210035`: roundtrip, acts, conversation, prune, reject, only, reconnect, lod, takeover, sight and wake pass; consolidation is its known XFAIL.

## 2026-11-09 the Rhai boundary, rhai-1 (dev-box)

- **Setup:** private container `rhai-stdb` (2.14.1), fake model, no paid calls. The mind compiles the installed script through the rules crate for `skill_io` and the combat shapes, so this checks that the new compile (analysis, name tables) serves it.
- `minds-rhai1-184757` on `1bc1327`: roundtrip, acts, conversation, prune, reject, only, reconnect, lod, takeover and sight pass. Consolidation is its known XFAIL.
- `minds-rhai1-sight-192712` on `33e3185` (main merged): sight passes.

## 2026-11-09 takeover on the scoped default (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `acbbda7` plus the uncommitted change that lands the perception client and makes `scoped` the default build (docs/PERCEPTION.md, "Third change"). Fake model only; private `CARGO_TARGET_DIR`s; every scratch database answered 404 after cleanup. `minds-sd-182208 --case takeover` with `CARGO_TARGET_DIR` private: pass (takeover after 30.0 s, the held graph kept and reinstalled, a reply in flight refused); the mind's cargo tests 49 passed. The driver now runs the binary it built in `CARGO_TARGET_DIR` (`source-hashes.json` names it); before, it ran `living/target/release/living-mind` whatever it had built.

## 2026-11-09 minds' sight and the offline player's character (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `81b9dd8`/`dc5e41b` plus the uncommitted minds'-sight, projection and presence change (docs/PERCEPTION.md, "Second change"; docs/PLAYER_MEMORY.md, "Presence and the offline character"). Fake model only; every scratch database answered 404 after cleanup. `minds-perc2`: `sight` (new), `roundtrip`, `acts`, `conversation` pass; `consolidation` its known XFAIL. `takeover` (new) passed on `minds-perc2c` after a driver fix (the minds' plan is a desires top level with a "current plan" routine, not a graph holding the wait) and an authority fix (a second takeover asked for a deliberation after reinstalling the held graph, inside `think_min_s`; the order is now request, then reinstall).

## 2026-11-09 `minds-20261109-110024` (DGX Spark, trial container) and trials

The suite ran on the DGX Spark against the trial service (`VERIFY_STDB_CONTAINER=slop-trials-stdb VERIFY_STDB_PORT=3320`, since replaced by main's `LIVING_STDB_CONTAINER` and `LIVING_STDB_URL`; the Spark's `sao-living_spacetimedb_1` belongs to other work), on `trials-1` before the town-life merge. Eight cases pass; `consolidation` stays XFAIL (the Neo4j-off known issue). Evidence: `.local/living/verify/minds-20261109-110024*/` in `~/dev/slop-trials` on the Spark.

Trials (`living/tools/trials.py`, [trials](../features/trials.md)) were driven by fake batches `dry1`–`dry8`: setup and timeline steps, sampling, journal copy, death stop, `resume` after the runner was killed (minds adopted by pid and start time, clocks kept), a killed mind restarted by a life run, the same model routing as the real file in fake mode (wolves: impulse `ministral-8b`, compile and consolidation `ministral-14b`; people: the variant's profile), a wolf pack as the subject, and `clean` (SQL 404, Neo4j nodes removed). `spawn_newcomer` was refused to an anonymous caller (`admin only`). Real batches `b1`–`b4` and life runs `l1`–`l3` are in `docs/TRIALS.md`.

## 2026-10-18 `minds-20261018-205441` (macOS, Docker Desktop)

After the knowledge-transmission changes (consolidation attributes provenance and marks childhood memories; the consolidation prompt names `know:<technique>` anchors and an off-by-default lesson clause). Commit `f3595c3` plus uncommitted changes. Eight cases pass; `consolidation` stays XFAIL (the Neo4j-off known issue). Every case's database answered 404 after cleanup; no mind or fake process survived. The first attempt (`minds-20261018-205344`) failed every case before publishing: `verify_llm.py` read Docker Desktop's `/host_mnt/...` mount path. It now strips that prefix, as the shared harness does.

## 2026-10-04 LOD replacement fix

The `llm/lod-fix` worktree changes pending deliberations to a current row, `Ready` / `Waiting { until }` / `InFlight` state and one wake notification per actor. Inserts refresh the row; obsolete deletes match the full old row rather than its timestamp. Merges, withdrawal and player contact wake delayed work. The generated `my_deliberations` view lacks a primary key, so [SDK 2.10.1](https://docs.rs/spacetimedb-sdk/2.10.1/src/spacetimedb_sdk/table.rs.html#153-178) supplies insert/delete callbacks rather than `on_update`. Its local versioned callback source confirms inserts are dispatched before deletes. The authority's `clear_deliberation` can strip old plan reasons while retaining `updated_ms`, which explains the lost replacement.

`cargo test --manifest-path living/Cargo.toml -p living-mind -- --nocapture` passed 17 tests with five store-dependent tests ignored. Evidence is `.local/living/verify/lod-fix-unit/cargo-tests.log` in that worktree. New unit checks cover a plain merge, an urgent upgrade waking the delayed worker, a changed scene, and same-timestamp row replacement. LOD remains opt-in. The live `lod` case now requires these merged reasons and urgent release to pass instead of accepting XFAIL.

Live verification from the worktree, after the shared harness learned to publish a worktree's own module (`b05c78b`):

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-lod-fix-02 --case lod
```

It passed. A plain merged reason stayed held offstage; an urgent reason merged into the held request started a thought 0.14 s later and the accepted thought carried both reasons; the merged non-plan reason was reconsidered; a player's contact released the character. Evidence is `minds-lod-fix-02/results.json` and `minds-lod-fix-02-lod/lod.json` under `.local/living/verify/`. The scratch database was deleted.

Targeted LOD map maintenance updated the script, skill and feature description. Claude and Cursor links still resolve to the shared source; Codex and Mistral use `.agents/skills` directly. Interactive runtime loading and a complete all-feature maintenance pass were not exercised. The full-suite evidence below is historical and remains intact.

## 2026-10-04 fix round

The final driver ran the complete nine-case mind map once as `minds-1004-fix3`. It exited 0 with seven PASS cases and two XFAIL KNOWN ISSUE cases. Every ordinary assertion passed, including the persona and cursor checks within consolidation and the hold/release checks within LoD. This table uses only that full run. Earlier attempts are history, not stitched acceptance evidence.

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-1004-fix3
.agents/skills/verify-minds/scripts/paid_safety.py --run minds-duel-safety-1004-final
```

Commit was `384fb50e379533b7db64698357efd0b2323f9452`, with pre-existing uncommitted `living/viewer/src/clock.rs`. The host was Fedora with rootless podman and SELinux enforcing. Every launch recorded the commit and dirty flag. Suite `source-hashes.json` matches the actual sources, shared fake/helper, final driver and release binary. No product source, seed, reference world, shared harness or other skill was edited. This fix round owned `verify-minds` and `verify-llm` together.

The command built the real release mind and passed 15 non-ignored mind tests; five store-dependent tests remained ignored. Each scratch database was launched and doctored through shared `verify.py`. The real Rust SDK subscribed and the production mind reducers applied replies. Every inference request used the local fake model server and a dummy key. `LIVING_ONLY` selected one actor, `LIVING_NEO4J=off` disabled the store, and the admin token stayed in memory and `LIVING_TOKEN`. No paid or remote model calls were made. Neo4j A was not contacted.

All paths below are under `.local/living/verify/`. Each case directory is `minds-1004-fix3-<case>/`.

| Feature or case | Result | Evidence |
| --- | --- | --- |
| `roundtrip`: request, think, compile, install, routine, activity and speech | PASS | `minds-1004-fix3-roundtrip/pending-first.json`, `brain-before.json`, `brain-after.json`, `routines-after.json`, `activity-after.json`, `thoughts.json`, `speech-after.json`, `pending-after.json`, `journal/` |
| `acts`: give, offer and impossible give | PASS | `minds-1004-fix3-acts/receiver-inventory-before.json`, `receiver-inventory-after.json`, `offers-after.json`, `act-experiences.json`, `fake-requests.jsonl` |
| `conversation`: addressed receipt, reply and closed repeat | PASS | `minds-1004-fix3-conversation/heard-speech.json`, `talk-speech.json`, `thoughts-after-end.json`, `mind.log`, `journal/` |
| `consolidation`: accepted addressed experiences and persona change | PASS | `minds-1004-fix3-consolidation/experiences-before.json`, `thoughts.json`, `persona-before.json`, `persona-after.json`, `journal/` |
| `consolidation`: strictly advancing cursor and consumed inbox | PASS | `minds-1004-fix3-consolidation/cursor-before.json`, `cursor-after.json`, `integrated-experiences-after.json` |
| `consolidation`: no-store relation, belief, judgment and place patch | XFAIL KNOWN ISSUE | `minds-1004-fix3-consolidation/result.json`, the four projection `*-before.json`/`*-after.json` pairs and exact patch in `thoughts.json` |
| `prune`: unknown skill removed, valid wait runs | PASS | `minds-1004-fix3-prune/brain-after.json`, `routines-after.json`, `activity-after.json`, `journal/` |
| `reject`: three invalid attempts, error and original revision | PASS | `minds-1004-fix3-reject/brain-before.json`, `brain-after.json`, `thoughts.json`, `pending-after.json`, `journal/` |
| `only`: excluded actor remains unserved | PASS | `minds-1004-fix3-only/excluded-pending-after.json`, `excluded-brain-after.json`, `excluded-thoughts.json`, `journal/` |
| `reconnect`: same-run update preserves installed graph, pending request and cursor | PASS | `minds-1004-fix3-reconnect/survival-graph-before.json`, `survival-graph-after.json`, `survival-pending-before.json`, `survival-pending-after.json`, `survival-cursor-before.json`, `survival-cursor-after.json` |
| `reconnect`: new process/subscription restores cursor and accepts fresh reason | PASS | `minds-1004-fix3-reconnect/reconnect.json`, `reconnect-audit.json`, `mind.log`, `thoughts-after-update.json` |
| `lod`: off-stage routine hold and player-contact release | PASS | `minds-1004-fix3-lod/offstage-held.json`, `onstage-thoughts.json`, `lod.json`, `journal/` |
| `lod`: merged non-plan reason is reconsidered | XFAIL KNOWN ISSUE | `minds-1004-fix3-lod/merged-pending.json`, `onstage-pending-after.json`, `merged-thoughts-after.json`, `lod.json`, `result.json` |
| Mind unit tests | PASS, 15 passed and 5 ignored | `minds-1004-fix3/cargo-tests.log` |
| Paid-wrapper guard and five inert termination scenarios | PASS without model calls | `minds-duel-safety-1004-final/guard.log`, `results.json`, per-scenario `duel-cleanup.json`, `process-audit.json` |
| Shared config selection and live-probe guard | PASS without requests | `minds-duel-safety-1004-final/config-checks.json`, `config-routes.json`, `live-probe-guard.log` |
| Real-model duel | NOT RUN | Specific authorization and `--allow-live` are required. |

## Product findings in the historical run

The no-store patch-loss defect remains open in [the handoff](../../../../docs/LIVING_HANDOFF.md), under "Still open". `living/mind/src/mind.rs:1607` applies the graph patch only with a store; `project` at line 825 publishes empty projections without it. The final run accepted an actual consolidation whose experience IDs include addressed player speech, changed the persona, advanced `mind_cursor` and deleted experiences at or below that cursor. None of the distinct relation, belief, judgment or place markers reached the authority. This is XFAIL rather than a red suite. Applying every marker would produce XPASS and require review. Projections WITH a store belong to `verify-knowledge`, which already proves them. This case gives no contradictory verdict about that path.

The historical LoD run held a routine request off stage, released it after player contact, and merged `verify merged nonplan reason` during a four-second delayed compile. The released plan was accepted, but the new non-plan reason stayed in the authority row with no matching later deliberation thought during the ten-second observation. That run recorded XFAIL KNOWN ISSUE separately from its successful hold/release checks. The implementation fix and the pending live re-verification are recorded above.

No new product defect was found in this round. The two additional failures were driver bugs fixed below.

## Fixes and failed attempts

`minds-1004-fix1` ran all nine cases. Reconnect failed while taking `max` of an empty inbox because bootstrap had already consolidated it. Setup now uses the largest actual inbox ID or existing consolidated cursor. Every failed case was cleaned up and its original `failure.txt`, result and journal remain.

The focused `minds-1004-reconnect2` update preserved all three snapshots but left the same connection alive. That was insufficient to prove reconnection. The current driver always requires a new PID and a new subscription-ready log. If a module update exits the binary, it requires exit 2. An identical publish may keep the socket; then the driver stops only its owned mind with SIGTERM and restarts after three seconds, following `run-mind.sh`. `reconnect.json` labels which route ran. Both final and focused `minds-1004-reconnect3` runs used this controlled restart. A module-induced disconnect was not reproduced.

`minds-1004-finalfix` ran all nine cases but its reconnect assertion missed a short-lived pending request already answered by the fake. The final driver submits the post-update think graph and waits for the durable accepted thought with the exact reason. The focused `minds-1004-reconnect3` and the full `minds-1004-fix3` both passed. Only the latter supplies this record's acceptance rows.

A pending request for an excluded actor avoids racing state preservation with a model answer. The served actor's installed graph and explicitly seeded cursor are saved before and after `launch --keep-data` on the same run. A short authority pause freezes setup while the original mind remains alive. After restarting, the log reports the exact saved cursor; unpause, doctor and a fresh accepted reason prove resumed service.

The owned shared `Run` helper now validates `llm` or `minds` prefixes and accepts explicit LoD options. Both skills reuse its environment, launch and restart setup. Private SQL uses shared `sql --as-admin`; cleanup uses the shared verified deletion result. Direct CLI token reading remains necessary to pass `LIVING_TOKEN` to the binary without writing it. The previously requested keep-data and admin-SQL harness features exist and were used here. No shared-harness change is requested.

## Paid safety and configuration

`real_models.py` refuses live mode without `--allow-live` before reading run state, model config or keys. Its detached guardian has its own monotonic deadline: 90 seconds including duel setup, with a 60-second collection window and four calls per minute. These are configured limits, not a token or currency budget. The guardian owns the new driver group, detects wrapper death through pipe EOF, terminates the group even after the driver exits, escalates when needed and uses Linux child-subreaper mode to reap orphaned descendants.

The final dry proof used inert children with a three-second watchdog and no database or model requests. All five scenarios checked the group gone: normal driver exit with a surviving child, SIGKILL of the driver, watchdog expiry, SIGKILL of the wrapper and SIGTERM of the wrapper. The inert child ignores SIGTERM, exercising SIGKILL escalation. A subsequent `process-audit.json` confirmed every guardian, driver and child PID was gone. The absent-flag guard created no run directory. Earlier `minds-duel-safety-1004-fix1` evidence remains historical; the current guardian's race-safe signaling and exit-status accounting were rerun in `minds-duel-safety-1004-final`.

Both paid scripts share `verify-llm/scripts/models_config.py`. Explicit `--models` wins, then active environment or non-overriding `.env` `LIVING_MODELS`, then `living/configs/models.json`. On this host the active file is `.local/living/models.json`, routing Luna to `127.0.0.1:8787`; the repository example routes Luna to `codex.carlid.dev`. Using the active config keeps the live probe and mind on the selected host route. Config precedence and routes were checked read-only. Neither route received a request.

## Cleanup, compatibility and limits

`minds-1004-fix3/results.json` contains the full results. `cleanup-audit.json` independently confirms all nine databases answer SQL 404, every owned PID is gone, tokens were removed from saved state, journals and evidence remain, source hashes match and the shared service still answers ping. Prior-attempt cleanup audits retain proof of deletion after failures. The existing SpacetimeDB container was neither stopped nor restarted. No forced service stop was called graceful.

Official [documentation](https://spacetimedb.com/docs/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [views](https://spacetimedb.com/docs/functions/views/) were consulted before changing the driver. Pages label themselves 2.0.0; the authority, SDK and running image are 2.10.1. Existing version-pinned bindings, reducers and sender-scoped views were used. Diagnostic queries filter by actor, observer or owner. No schema, binding or subscription changed.

Each case used one mind connection, one selected adult and a local fake server. Reconnect briefly replaced its mind connection. The default seeded world continued ticking except for its short update pause. Initial subscription populations are retained in `cleanup-audit.json`; scene populations and actual requests remain in `people.json`, doctor output and fake logs. Player scenes place one player beside the actor. Scripted action rates vary by case; fake concurrency is four with no rate limit. No observer or full export ran. The LLM suite and focused reconnect probes overlapped some attempts on separate databases. No resource, latency, scale or long-duration claim follows from these scenes.

Frontmatter, Python syntax, relative links, executable scripts and existing Claude/Cursor discovery links were checked. Codex and Mistral use the shared `.agents/skills/` tree. Interactive instruction loading in the other runtimes remains unverified. Paid model behavior, a module-induced disconnect, full LoD gap expiry, urgent live exceptions, off-stage talk/consolidation pacing, infant/newborn minds and store-dependent tests remain unverified. Store-backed projections and persistence belong to `verify-knowledge`; transport belongs to `verify-llm`. Other neighbouring checks are named in `SKILL.md`.


## 2026-11-09, branch harness-1 (animals, night, jev)

Private container `harness-stdb`. New cases: `night` and `jev` passed in `minds-h1-204530`; `animals` passed in `minds-h2-210016` after two fixes to the case (dawn reasons, since installing a graph counts as having just thought; the herd gathered in the open) and one to the fake server (a distinctive prompt wins over a purpose-named effort). The earlier cases were not rerun on this branch; the mind changes they touch (model routing through mixes, the `reorganize` purpose) are covered by verify-llm.

## 2026-11-10, branch fix-host-example

Shared container `sao-living_spacetimedb_1`, laptop. `conversation` passed in `minds-host-20261110-201010` with the new check: the recorded talk request contains `"do": "host"`. The unit test `talk_examples_show_every_shown_act` fails with "host is not shown in the talk turn's examples" when the example line is removed (main before this branch), and passes with it.
