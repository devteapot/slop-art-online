# Core validation record

## 2026-10-04 fix round

Ran the skill on Fedora with rootless podman and SELinux enforcing. Branch `living-core`, commit `384fb50e379533b7db64698357efd0b2323f9452`. The existing `living/viewer/src/clock.rs` change was preserved. This task changed only `.agents/skills/verify-core/`. No product source, shared harness, adapter, reference world or Neo4j A was changed.

The running container and CLI are SpacetimeDB 2.10.1. The CLI commit is `3d7607082ab47257adeb7c25164536511237f2b5`. Version evidence is in `core-fix-20261004-impl/stdb-version-flag.txt`. The unsuccessful `stdb version` probe is also retained; the supported flag is `--version`.

Evidence paths below are relative to `.local/living/verify/`. The baseline run is `core-fix-20261004-impl`. Its fresh companion worlds are `-life`, `-steering`, `-mechanics-1` through `-mechanics-4`, and `core-fix-20261004-impl-retry-wildlife`. Every database has the `verify-core-*` prefix.

| Feature | Result | Current evidence |
| --- | --- | --- |
| Tick, housekeeping, pause and resume | PASS, exit 0. The cadence probe observed 324 ticks over 5.4 seconds of authority time. Paused clock, stats and activity stayed unchanged; resume completed the gift. Actual profiling spans were retained. | `core-fix-20261004-impl/tick-results.json`, `tick-actions.jsonl`, paused snapshots, `tick-profile.txt`, `tick-exit.txt` |
| Graph parsing, normalization, evaluation and routines | PASS in Cargo, live mechanics and steering. Installed graphs and full routine rows are retained. | `core-fix-20261004-impl/rules.txt`; `core-fix-20261004-impl-mechanics-4/installed-brain-*.json`, `installed-routine-*.json`, `stdb-actions.jsonl`; `core-fix-20261004-impl-steering/stdb-actions.jsonl` |
| Skills, laws and exchanges | The four mechanics attempts passed 21/23, 23/23, 16/23 and 23/23. The complete four-attempt results appear below. Steering passed runtime law replacement and input refusals. | `core-fix-20261004-impl-mechanics-*/mechanics.json`, `mechanics.txt`, `stdb-actions.jsonl`; `core-fix-20261004-impl-steering/steering.txt` |
| Needs over time | PASS, exit 0. Hunger, idle energy, rest and eating changed as expected. The cloak increased night healing rate from 1.5143297 to 3.5143297. | `core-fix-20261004-impl/needs-results.json`, `needs-actions.jsonl`, idle, rest, food, cold and cloaked snapshots, `needs-exit.txt` |
| Life course | PASS, exit 0. A new infant was born, pregnancy was removed, rearing began, birth was chronicled and the seeded infant aged to child. Mechanics attempt 4 passed death cleanup and expecting-parent retention. | `core-fix-20261004-impl-life/lifecycle-results.json`, `lifecycle-actions.jsonl`, born, expecting, rearing and aging snapshots; `core-fix-20261004-impl-mechanics-4/mechanics.json` |
| Wildlife and ecology | PASS, exit 0. All 13 checks passed on the documented fresh wildlife world. Five adult founders arrived after the real cooldown; all spawned on edge grass and the next minute kept the same founders. | `core-fix-20261004-impl-retry-wildlife/wildlife.txt`, `wildlife-actions.jsonl`, `wildlife-results.json`, grazing, extinction, newcomers, chronicle and cooldown snapshots, `wildlife-exit.txt` |
| Combat and graded force | PASS for five ordinary scene checks. Healthy yielded seize was `XFAIL KNOWN ISSUE` until the 2026-10-04 fix (`act.rs` `skill_ctx`), after which `core-seize-01` showed it passing and it became an ordinary check. Mechanics attempt 4 passed threat, hurt, yield and wolf reluctance. | `core-fix-20261004-impl/seize-results.json`, `seize-actions.jsonl`, `seize-yielded-seize-feedback.json`, yield, inventory, witness and killed snapshots, `seize-exit.txt`; `core-fix-20261004-impl-mechanics-4/mechanics.json` |
| Deliberate acts | All five reported checks passed in mechanics attempt 4. Attempt 1's conception failed; its gift reported PASS despite a blocked-path refusal. The weak gift predicate limits what its PASS establishes. Cargo passed single-node act validation. | `core-fix-20261004-impl-mechanics-4/mechanics.json`, `stdb-actions.jsonl`; `core-fix-20261004-impl-mechanics-1/diagnostic-walkers.json`; `core-fix-20261004-impl/rules.txt` |
| Steering and viewer display sync | PASS, exit 0. All five live steering checks and three display-sync tests passed. This is all the viewer code covered by this skill: `living/viewer/src/sync.rs`. | `core-fix-20261004-impl-steering/steering.txt`, `stdb-actions.jsonl`, `steering-exit.txt`; `core-fix-20261004-impl/viewer-sync.txt` |

## Offline checks

`cargo_checks.py` ran its four documented commands. No ignored tests ran. No mind service or model provider ran.

| Package and filter | Result | Evidence in `core-fix-20261004-impl/` |
| --- | --- | --- |
| `living-rules` | 45 passed, one ignored | `rules.txt` |
| `living-authority --lib seed::tests` | Five passed | `authority-seed.txt` |
| `living-mind` | 15 passed, five ignored | `mind.txt` |
| `living-viewer sync::tests` | Three passed | `viewer-sync.txt` |

All four exits were 0, recorded in `cargo-results.json`. The status-contract probe in `known-status-contract.json` separately verified XFAIL exits 0 and XPASS exits 1 without changing the product. The real seizure scene exercised XFAIL; a product-fixed XPASS scene was not available.

The cadence window had 173 living people and 82 animals. It used admin SQL, no body subscription or observer, and a short profiling interval after the cadence probe. Other verification databases shared the service. This short functional check does not establish latency, memory, resource or population acceptance. Steering uses a real body subscription; life and wildlife use admin calls and SQL on the eight-person, 16-deer, three-wolf `stage1-acts` seed.

## Historical 16/23 failure

This is history, retained for comparison. The unchanged driver passed 23/23 in `core-1004-tests/`, 16/23 in `core-1004-proof-mechanics/`, then 23/23 in `core-1004-final-mechanics/`. The preserved failed run contains the following exact failed keys.

| Failed check | Recorded output and state in `core-1004-proof-mechanics/` |
| --- | --- |
| `tablet written and given` | `false` in `mechanics.json`, `FAIL` in `mechanics.txt`. Artifact 5 stayed with holder 259, Walker1, rather than 260, Walker2. Chronicle recorded the tablet write six times. |
| `reading taught spear` | `false` and `FAIL`. Walker2's know-how query returned only `writing` from `granted`, without `spear`. |
| `learned technique used (spear crafted)` | `false` and `FAIL`. Repeated inventory queries returned berries 3, stone 3 and wood 4, without a spear. |
| `atomic trade` | `false` and `FAIL`. No trade chronicle appeared. Walker2's feedback later said "You failed to accept → Walker1: they moved away". |
| `teaching` | `false` and `FAIL`. Walker2's know-how remained only the granted writing entry, without planting. |
| `act: conception chosen by both as acts` | `false` and `FAIL`. The expected Walker3/Walker4 pregnancy never appeared. The retained expecting rows were unrelated animals. |
| `death clears the body's rows; an expecting parent keeps its genes` | `false` and `FAIL`. The diagnostic printed `lived True`, all five cleared-table counts 0, and `parent kept False`. There was no qualifying walker pregnancy. |

The raw SQL and calls are in `stdb-actions.jsonl`. The relevant original actor feedback was extracted, without changing the original evidence, to `core-fix-20261004-impl/historical-experience-259.txt`, `historical-experience-260.txt` and `historical-experience-261.txt`. Successful CLI calls did not establish the expected physical outcomes.

## Four fresh mechanics runs

Each run published a fresh database, used the unmodified `living/tools/verify_mechanics.py`, saved calls, SQL and installed graph rows through the recorder, then used shared cleanup. Product source was unchanged between runs. Counts are driver-reported results, subject to the weak predicates below.

| Run | Pass count | Exit | Failing checks |
| --- | --- | --- | --- |
| `core-fix-20261004-impl-mechanics-1` | 21/23 | 1 | `act: conception chosen by both as acts`; `death clears the body's rows; an expecting parent keeps its genes` |
| `core-fix-20261004-impl-mechanics-2` | 23/23 | 0 | None |
| `core-fix-20261004-impl-mechanics-3` | 16/23 | 1 | The same seven keys as the historical 16/23 run above |
| `core-fix-20261004-impl-mechanics-4` | 23/23 | 0 | None |

Every row has its own `mechanics.json`, `mechanics.txt`, `mechanics-exit.txt`, `stdb-actions.jsonl` and `cleanup.txt`. Failures remain FAIL. They were not turned into expected failures or removed after a passing retry.

## Likely causes and driver limits

The fresh attempt 1 diagnostic gives a concrete route failure. Walker3's feedback says "give berries → Walker4: the way is blocked" and "conceive → Walker4: the way is blocked". Walker4 says "conceive → Walker3: cannot reach them". Those rows are in `core-fix-20261004-impl-mechanics-1/diagnostic-walkers.json`; its wall and gate setup is preserved in `stdb-actions.jsonl` and `diagnostic-structures.json`.

Placement and unsynchronized setup are likely contributors. `living/authority/src/lib.rs:123,124` randomizes spawn positions. `living/authority/src/seed.rs:679` randomizes genes. `living/authority/src/lib.rs:132` installs a forager repertoire; the driver waits at `living/tools/verify_mechanics.py:77,79`, then leaves later scene actors running instincts until their turn. `place_near` at `living/authority/src/lib.rs:262` places a body one tile east without checking that the tile is free. The driver builds wall and gate tiles at `living/tools/verify_mechanics.py:164,165`, then places the act pair in that area at `living/tools/verify_mechanics.py:185,186`. Blocked routes in fresh attempt 1 are observed. Exact overlap with a particular wall or terrain tile, and the original tablet failure's cause, are not proven by the retained snapshots.

`living/authority/src/act.rs:794` rechecks distance at completion and reports a moved-away target. `living/authority/src/brain.rs:365,366` restarts a failed sequence. That explains how a failed give can repeat writing, but does not identify which refusal caused the original give failure. Nearby AI activity, fixed waits such as `living/tools/verify_mechanics.py:113`, and terrain-dependent movement remain plausible contributors rather than established causes of every failure.

Two driver predicates can report PASS without the named outcome. The gift predicate at `living/tools/verify_mechanics.py:197` accepts any berries in Walker4's inventory, including spawn or gathered berries. The feedback predicate at `living/tools/verify_mechanics.py:199` can match the preceding successful eat. Fresh attempt 1 therefore reported gift PASS while actor feedback recorded its refusal.

The conception predicate at `living/tools/verify_mechanics.py:141` accepts any pregnancy. In fresh attempt 1 it returned animal rows before either walker had conceived. The next scene replaced their graphs at `living/tools/verify_mechanics.py:147,148`. Its final death check selected no expecting walker, so the failure does not by itself establish broken inheritance retention. Attempt 2 drove a real expecting walker and passed retention.

[mechanics.md](../features/mechanics.md) tells readers how to recognize the intermittent failures, preserve dependencies and distinguish them from a possible regression under controlled preconditions. These findings are recorded here; the product driver and authority were not patched.

## Changes made in this round

- `scenes.py` writes PASS, FAIL, XFAIL and XPASS statuses. Ordinary failures and XPASS exit 1; XFAIL alone does not fail the run.
- `scenes.py` reads the installed brain row after every graph replacement. `record_stdb.py` reads complete brain rows after `set_behavior` and complete routine rows after actor-specific routine probes. Reducer acceptance cannot substitute for checking normalized graphs.
- The recorder retains cleanup ownership after the driver deletes its database so the shared harness confirms HTTP 404. Mechanics attempt 2 exercised this path.
- All feature file-and-line references were checked against source. Seize witnesses are at `living/authority/src/act.rs:913,917`; life-stage changes start at `living/authority/src/tick.rs:213`. Needs and real-time act references were corrected too. The 52-reference audit is in `core-fix-20261004-impl/source-reference-audit.json`.
- `SKILL.md` states that `just living-check` builds authority WASM, mind and both viewer targets, while its test step runs only rules tests. It includes startup preconditions, removes "now verifies", and limits viewer coverage to `living/viewer/src/sync.rs`.
- The graph map describes lenient normalization and discarded warnings in `living/rules/src/graph.rs:385,386,459,460`, rather than a strict parser.
- Wildlife was driven on its own fresh documented world. The first attempt, `core-fix-20261004-impl-wildlife`, timed out waiting for grazing after delayed setup. It was cleaned up and its files remain. The complete retry uses its own launch, doctor, grazing, migration and cleanup evidence. No other scene's files were renamed into its run.

## Documentation and compatibility

Consulted the [official documentation](https://spacetimedb.com/docs/), [reducers](https://spacetimedb.com/docs/functions/reducers/), [scheduled reducers](https://spacetimedb.com/docs/functions/reducers/lifecycle/) and [indexes](https://spacetimedb.com/docs/tables/indexes/). The served pages identify version 2.0.0. Actual APIs, tables and flags were checked against pinned and running 2.10.1 source and CLI.

Design implications remain the same. A reducer transaction can accept an intention before its later physical result. Let the real scheduled reducers execute, inspect actor-indexed outcomes and retain original refusals. No authority schema, index, subscription or persistence design changed. Whole-population queries are bounded fixture setup or diagnostics, and scratch cleanup limits active data retention.

The shared skill source, frontmatter, feature headings, links, executable flags and Python syntax were checked. Claude Code and Cursor links resolve to the same `.agents/skills/verify-core/` source that Codex and Mistral Vibe discover. `core-fix-20261004-impl/discovery-audit.json` records these static checks. Live registration and invocation in the four runtimes remain unverified. No adapter changes were needed.

The recorder keeps using `living/tools/stdb` for admin scenes and the existing drivers' CLI subscription protocol. It does not duplicate token parsing or container ownership checks. Launch, doctor and cleanup remain with the shared harness. No shared-harness change was requested.

## Cleanup and remaining limits

All nine owned databases are absent with SQL HTTP 404, including the failed wildlife attempt and all four mechanics worlds. Their evidence and cleanup transcripts remain. `core-fix-20261004-impl/cleanup-audit.json` records each database and its retained result files. The already-running shared container remains up; no observer process was started or stopped. `product-state-start.json` and `product-state-finish.json` confirm unchanged product source hashes and the preserved unrelated viewer change.

The known healthy-yielded seizure defect remains open at `living/authority/src/act.rs:238` and `living/scripts/skills.rhai:496,500`. Mechanics is intermittent, and its gift and broad conception predicates can overstate coverage. The exact original tablet-transfer failure remains unresolved.

This run does not establish sustained performance, resource bounds, long-term ecology, wolf migration, every graph combination, natural old-age death, act queue limits, genuine model inference, player permissions, private subscriptions, or observer UI behavior. Use the neighbouring skills listed in `SKILL.md`. Display-sync tests are the entire viewer coverage here.


## Infant thermal perception and cry requests, 2026-10-04

The scoped `baby-warmth` pass added `scenes.py infant`, `scripts/infant.json` and the documented infant baseline. Product commit `6001413` fixes an evaluator-timer defect found during the live run. The thermal phase used the original infant implementation at `b2f115c`; the final cry interval used that implementation plus the exact product changes subsequently committed as `6001413`. The baseline authority was built from `6db8d1f` in the temporary `baby-baseline` worktree. The verification driver and fixture were shared; no baseline product changes were applied.

### Scene and predicates

The seed has four adult family members and their infant. The scene adds a caring witness and a remote shelter anchor. It holds behavior on rest and waits for real night and hunger at least 70, suppressing positive healing. There is no time-setting reducer; `set_paused` was used during diagnosis and the in-place fix, outside the final interval. Species, rules and vitals were not patched.

The sheltered infant's parent-visible `looks` was `warm, hungry`, with HP rate 0. The exposed infant's `looks` was `cold, hungry`, with HP rate -2 per minute. Derived HP fell from 100.93207 to 100.6487 across the exposure probe. Thermal predicates passed on both authorities; the old authority omitted the new appearance assertion.

The cry phase feeds adults to suppress their own survival alarms, cloaks the infant and gives a bounded berry meal. Hunger then crosses 55 through real rates. An explicit signal/wait graph emits cries about every seven seconds. For a 250-second window, one parent acknowledges through `mind_skip`; the other leaves its request pending. No minds connect and no model calls occur. The changed authority passed parent-only routing, one prompt for the pending parent, an answered-parent reminder gap of 126.453 seconds, an unchanged hunger-only cause for over 120 seconds, and a caring witness receiving signal experiences without crying deliberations. With parents and witness over 75 tiles away, caring adults at one and two tiles yielded exactly one cry request for the nearest adult.

### Counts and method

| Authority/run | Valid windows | Authority seconds | Created | Merged | Prompts per infant per minute |
| --- | --- | --- | --- | --- | --- |
| `6db8d1f`, `core-infant-before-01` | 1 | 251.704 | 5 | 13 | 4.290754 |
| `6001413` product, `core-infant-after-01` | 1 | 251.572 | 3 | 0 | 0.715501 |

Each window contains one crying infant and seven live characters: infant, parents, witness, two fallback adults and the remote anchor. Six dead preparation actors remain as retained rows, so each world has 13 character rows. Four actors occupy the local cry site; alternatives are remote during measurement. Admin SQL polls at about 1 Hz plus CLI overhead; there are no core SDK subscriptions, model service or observer. This is a bounded prompt-workload comparison, not a performance or model-call claim. The initial prompt is included; fallback is outside the rate window.

The changed branch counts `InfantCry.prompted` stamps matched to actual crying request rows. The baseline matches signal `experience.at_ms` to a request containing the baby's crying reason whose requested/updated interval spans that stamp. Actor/stamp pairs are deduplicated. This excludes unrelated dawn and reflection request updates while preserving those raw observations. Per-event records carry the full corresponding request and classify creation versus merge using `requested_ms`.

There were three preparation interruptions and two invalid/interrupted measurement attempts per authority, retained in `preparation-*` and `measurement-*`. Attempt 1 counted unrelated request updates; attempt 2 missed the initial stamp because the driver captured its start clock after installing the signal graph. The final driver captures time first and uses cry-specific stamps. One valid interval per revision completed after these corrections. `--resume-infant` reused the thermal checkpoint on the same owned world. `infant-verification.json` combines the original passed thermal checks with the final cry checks and points to both source result files; original failures remain intact.

### Evaluator-timer defect and fix

`mind_state.marks` holds graph evaluator markers alongside action-owned markers. The merge retained only evaluator IDs below `0xD000`, dropping reserved root-completion, failure and reflection timers at `0xFFFE`, `0xFFFD` and `0xFFFC`. After quiet reflection became due, a pending request refreshed roughly every two seconds. `6001413` preserves these evaluator timers through merges and clears them on graph replacement, while retaining action-owned markers below that reserved range. No schema or bindings changed. Both `reflection-proof.json` files preserve the comparison: baseline lacks the reflection marker and advances request `updated_ms` during ten seconds; the changed branch retains it and leaves `updated_ms` unchanged. Independent source review found no remaining concrete defect in this fix or the corrected cry counter.

### Baseline, visibility and evidence

`core-smoke-infant-{01,02}` ran Cargo, tick, needs and seize before and after the fix. Every command exited 0. Both runs passed rules 47 (one ignored), authority 9, mind 28 (five ignored) and viewer sync 3. Tick, needs and seize each passed six live predicates. `baseline-exits.json`, `cargo-results.json`, transcripts and individual scene results retain the outcomes. The scoped graph and needs maps were maintained; unrelated core features were not re-audited or driven in this pass.

`client-infant-visibility-{01,02}` ran the entire documented client wrapper before and after the fix: all eleven private tables, including `infant_cry`, refused anonymous SDK subscriptions and HTTP SQL; all 164 reducer-permission calls matched. Views, live updates, reconnect and ad-hoc speech passed. Public `experience` and `thought` leaks remain known XFAILs. See the client validation record.

Evidence lives under `.local/living/verify/`. Infant runs retain `infant-verification.json`, `infant-prompt-rate.json`, `infant-prompt-events.jsonl`, `infant-request-observations.jsonl`, thermal/cry/fallback snapshots, action transcripts, diagnostics and cleanup. `.local/living/verify/baby-live/report.md` records commands, commits and limits. The baseline evidence was copied into the branch before removing its temporary worktree.

### Documentation, compatibility, cleanup and limits

Consulted official [documentation](https://spacetimedb.com/docs/), [tables](https://spacetimedb.com/docs/tables/), [indexes](https://spacetimedb.com/docs/tables/indexes/), [performance](https://spacetimedb.com/docs/tables/performance/), [views](https://spacetimedb.com/docs/functions/views/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) before the authority fix. Served docs identify 2.0.0; pinned/running 2.10.1 was checked against [official versioned Rust bindings](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.1/crates/bindings/src/lib.rs). The fix keeps the existing row-local mind-state representation. Diagnostics read a bounded fixture, with primary-key vitals/cry queries and small request/experience snapshots. No production tables, indexes, subscription recipients or retention policy changed.

Shared discovery links, frontmatter, executable helpers, local documentation links and Python syntax were checked for Codex, Claude, Cursor and Mistral Vibe. Scoped source-reader reviews checked needs, graph markers and client visibility. The existing adapters resolve to shared files and required no edits. Live runtime menu and instruction-loading checks remain unverified.

All six scratch databases were deleted with SQL HTTP 404. Their evidence remains; module copies and player tokens were removed. The baseline worktree was removed. The shared server stayed running; reference worlds and Neo4j were untouched. There were no new environment symlinks or real model calls.

Live winter damage, infant campfire placement, starvation, wounds, urgent changed-cause routing, connected mind responses, multi-infant rates, long-term survival, scale/resource acceptance and browser presentation remain unproven here. Rule/authority unit checks cover some policy variants; they do not establish those live outcomes.
