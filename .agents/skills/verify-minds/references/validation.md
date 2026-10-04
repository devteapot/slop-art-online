# Internal mind validation

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

## Known product findings

The no-store patch-loss defect remains open in [the handoff](../../../../docs/LIVING_HANDOFF.md), under "Still open". `living/mind/src/mind.rs:1607` applies the graph patch only with a store; `project` at line 825 publishes empty projections without it. The final run accepted an actual consolidation whose experience IDs include addressed player speech, changed the persona, advanced `mind_cursor` and deleted experiences at or below that cursor. None of the distinct relation, belief, judgment or place markers reached the authority. This is XFAIL rather than a red suite. Applying every marker would produce XPASS and require review. Projections WITH a store belong to `verify-knowledge`, which already proves them. This case gives no contradictory verdict about that path.

The LoD pending-reason defect is also open in the handoff. `living/mind/src/main.rs:165` subscribes with `on_insert`; the authority merges reasons into existing deliberations. The final run held a routine request off stage, released it after player contact, and merged `verify merged nonplan reason` during a four-second delayed compile. The released plan was accepted, but the new non-plan reason stayed in the authority row with no matching later deliberation thought during the ten-second observation. The map records XFAIL KNOWN ISSUE separately from the successful hold/release checks. Handling the reason would produce XPASS. The version-pinned generated view handle exposes insert/delete callbacks; this run does not establish that an `on_update` API is available or sufficient to fix the defect.

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
