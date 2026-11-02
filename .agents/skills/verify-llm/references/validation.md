# Model integration validation

## 2026-10-04 pacing correction and authority verification

Product commit `47f3f9a18aa92111ec81b806ee9bc43a4feac42d` fixes rate collapse after simultaneous 429s, proportional recovery and the unconfigured ceiling. Runs used `/home/carlid/dev/sao-wt/llm-transport`, branch `llm/llm-transport`, rebased onto the living-core LoD and prompt fixes. No reference world, paid endpoint or Neo4j endpoint was contacted. No main-checkout `.env` or `.local` symlink was needed.

The data shape remains a per-profile `Rate` plus the typed `Lane` queue. `configured_ceiling: Option<f64>` distinguishes an explicit static override from the adaptive starting ceiling. `last_decrease: Option<Instant>` and ticket send times deduplicate responses from one congestion event. Constants are `RATE_START_RPM=600`, `RATE_DECREASE=0.5`, `RATE_FLOOR_FRACTION=0.05`, `RATE_RECOVERY_FRACTION=0.05`, `RATE_RECOVERY_INTERVAL=10s` and `RATE_HEADER_HEADROOM=0.9`. The floor and recovery step are at least one request/minute; a configured ceiling below one still wins. At a 400 ceiling, a decrease to 200 recovers in ten successful 10-second steps, or 100 seconds. Recovery still requires successful total-usage feedback. The start accommodates the audited world's roughly 400 successful calls/minute while unknown providers can reduce it through headers or 429s. This is policy, not evidence of quota or scale acceptance.

Commands driven:

```bash
cargo test --manifest-path living/Cargo.toml -p living-mind llm::tests -- --nocapture
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-20261004-pacing-r1
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-20261004-pacing-r2 --case outage
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-20261004-pacing-r3 --case outage
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-20261004-pacing-r1
.agents/skills/verify-minds/scripts/paid_safety.py --run minds-duel-safety-20261004-pacing
```

- PASS: release build, all 16 transport tests, 40 non-ignored mind tests and all nine fake contract scenarios. Five existing mind tests remain ignored.
- LLM first full suite: 14 PASS, one outage FAIL. Failure remains in `llm-20261004-pacing-r1-outage/`; the endpoint failed during compilation and no further request reached the restored server within the original 40-second recovery check. Other cases include the actual 180-second HTTP timeout, overflow, JSON repair, bounded retries, routing and missing-key refusal.
- PASS: outage retry `r2`, then final fixture `r3`. The fixture restores the provider after five seconds and sends a fresh addressed player question, avoiding a probe that finishes while the endpoint is still down. It requires restarted-provider requests, a successful post-restart exchange, positive held count and an accepted authority graph. `r3` proves the final fixture. The full `r1` invocation exited 1; these results are not a claim that one final full invocation exited 0.
- Minds: eight PASS, including roundtrip, acts, conversation, reconnect and LoD. Consolidation remains its documented XFAIL for no-store relations, beliefs, judgments and places. Its persona, consolidation thought and cursor assertions pass. Paid-wrapper guard and all five inert termination scenarios PASS, with no model calls.

Evidence is under `.local/living/verify/` in the named suite and case directories. Each case retains doctor output, authority snapshots, fake request logs, mind logs, source/binary hashes, journals when created and cleanup records. `llm-20261004-pacing-review/cleanup-audit.json` independently confirms HTTP SQL 404 for all 26 scratch databases, no owned PID or copied module remaining, and retained evidence. Startup refusal creates no journal. `results-review.json`, `retry-lanes.txt`, `source-pass.txt` and `compatibility-and-links.json` record result counts, runtime retry lanes, source maintenance and discovery checks.

Maintenance outcome is changed. One read-only source reader covered each of nine feature files; every local feature was driven. The paid feature's authorization prerequisite remains unmet. Shared standard skill discovery and Markdown links passed for Codex/Mistral Vibe sources and Claude/Cursor adapters. Actual invocation and instruction loading in all four runtimes remain unverified. No adapter shape changed.

Official [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [indexes](https://spacetimedb.com/docs/tables/indexes/) guidance was consulted. The workspace pins server/SDK 2.10.1; every doctor verified that server version. These changes add no table, query, index, subscription or reducer. The SDK's pinned `client_cache.rs::TableHandle::iter` clones all rows before filtering. Deliberation priority therefore costs approximately `400 × controlled characters` cloned experiences per call with full retained windows, or 86,400 for 216 characters. At 400 deliberations/minute that is about 34.6 million clones/minute, an estimate rather than a measurement. The authority has an observer index; generated client bindings do not expose it. Adding a maintained client index needs lifecycle/reconnect work and remains outside this correction.

The animal conflict matches living-core prompt order and preserves the lane through both think and compile calls; the release build passes. The suites select people, so animal desire-plan routine installation was not reproduced. A source reader flagged a possible existing missing routine-application path, also present on living-core; it is not a transport merge change.

Paid follow-up still needs explicit authorization and a reviewed active configuration. Measure real provider headers/quotas, 429s, queue and player latency, background progress, cache hits, split token usage and billing under the actual model workload. Free fixtures do not establish those, population performance, long-run stability or model judgment.

## 2026-10-04 transport stream

Product commit `e18d912e012c0fba0a8c6a648663aaeb2b78744f` replaces the old budget/window with profile pacing and typed priority admission. Checks below ran from `/home/carlid/dev/sao-wt/llm-transport` immediately before committing that exact product source. `living/` had the uncommitted transport edits, without authority or prompt changes. Earlier failed attempts remain in the `*-01` directories; they are not passing evidence.

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-transport-02
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-llm-transport-02
```

- PASS: release mind build; all 13 `llm::tests`; all 24 non-ignored mind tests. Five existing tests requiring other facilities remained ignored.
- PASS: all nine fake-server contract scenarios, including scripted Retry-After/rate-limit headers and cached usage.
- PASS: direct Rust/fake HTTP checks of paced 429 recovery, lane metadata, split usage, missing usage, stable cache keys and omission. Both suites retain the fake request log, exact journals and script under `direct-transport/`. Explicit-clock tests cover saturation order, reserved capacity, request and token pacing, usage reconciliation, rate adaptation and both Retry-After formats. Cancellation checks release tickets and outage probes.
- BLOCKED: all 15 authority LLM cases and all nine authority mind cases stopped before publication. The shared container mounts `/wasm` from `/home/carlid/dev/slop-art-online/living/target/wasm32-unknown-unknown/release`; this worktree builds to `/home/carlid/dev/sao-wt/llm-transport/living/target/wasm32-unknown-unknown/release`. The new preflight refuses this mismatch instead of publishing another checkout's module. Every case retains `mount-check.json`, `driver.log`, `failure.txt` and `cleanup.json` with `database_not_created: true`. No scratch database or case process was created, and the shared container was not restarted or changed.

Evidence is local to this worktree under `.local/living/verify/llm-transport-02/`, `llm-transport-02-fake-contract/`, `minds-llm-transport-02/` and their per-case directories. Source and binary hashes, build/test logs and suite `results.json` remain. No `.env` or `.local` symlinks from the main checkout were needed, and no live model or Neo4j endpoint was contacted.

The maintenance source pass covered every feature file, including the new pacing map. Its required authority live pass is blocked by the mount mismatch. Retest both full free tiers from a checkout that matches the container mount before claiming authority integration. The docs' corrected one-attempt fallback assertion and expanded basic journal/lane assertions have not been driven against the authority in this stream. Player-context classification, complete mind lifecycle and reconnect behavior remain unverified here.

Shared skill paths and Markdown links passed read-only checks for Codex, Claude Code, Cursor and Mistral Vibe, recorded in `.local/living/verify/llm-transport-review/compatibility-and-links.txt`. Runtime-specific invocation and instruction loading were not exercised. Claude and Cursor continue to resolve the shared sources through their existing links.

Paid measurement remains unauthorized. A future authorized run must review Mistral account quota and process shares, enable the optional cache key, measure 429 frequency, queue and end-to-end player latency, actual input/output/cached usage and billing, and check background starvation. Estimated tokens, process-local scheduling and string-based player causality do not establish provider limits, exact causation or scale acceptance.


## 2026-10-04 fix round

One final driver invocation covered all 15 local cases. It exited 0. These results come from `llm-1004-fix1`, with no rows borrowed from previous runs. The earlier c/d/e/f evidence and stitched `passing-cases.json` remain historical artifacts and are not acceptance evidence for this record.

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-1004-fix1
```

Host was Fedora with rootless podman and SELinux enforcing. Commit was `384fb50e379533b7db64698357efd0b2323f9452`, with pre-existing uncommitted `living/viewer/src/clock.rs`. Shared launch records the commit and dirty flag in every `state.json`. Each case has source and release-binary hashes. This round changed only the two owned verification skills. No product code, reference world or shared harness was edited.

The command built the release mind, passed the nine fake-server contract scenarios, passed four `llm::tests`, and launched and doctored every scratch database before driving it. All inference used loopback fake servers and dummy keys, through the real Rust mind's production HTTP boundary. Neo4j was off. Neither the local Codex proxy, remote model providers nor Neo4j A was contacted.

All paths below are under `.local/living/verify/`. A case directory is `llm-1004-fix1-<case>/`.

| Feature or case | Result | Evidence |
| --- | --- | --- |
| `basic`: four purposes, accepted graph, consolidation and speech | PASS | `llm-1004-fix1-basic/primary-requests.jsonl`, `journal/`, `thoughts.json`, `brain-after.json`, `routines-after.json`, `speech-after.json`, `talk-speech.json` |
| `routing-group`: group over stage and rotation | PASS | `llm-1004-fix1-routing-group/result.json`, `journal/`, `alternate-requests.jsonl` |
| `routing-assign`: named assignment over group | PASS | `llm-1004-fix1-routing-assign/result.json`, `journal/` |
| `routing-rotate`: actor ID modulo two | PASS | `llm-1004-fix1-routing-rotate/result.json`, `journal/` |
| `routing-child`: child stage over explicit assignment | PASS | `llm-1004-fix1-routing-child/result.json`, `journal/` |
| `routing-default`: disabled-key routes fall through | PASS | `llm-1004-fix1-routing-default/result.json`, `mind.log`, `journal/` |
| `missing-default-key`: refusal before any model call | PASS | `llm-1004-fix1-missing-default-key/result.json`, `mind.log`, `cleanup.json`. No requests or journal are expected. |
| `overflow`: HTTP 429 to alternate | PASS | `llm-1004-fix1-overflow/journal/`, `brain-after.json` |
| `retry-fallback`: four failed attempts, growing backoff, default success | PASS | `llm-1004-fix1-retry-fallback/journal/`, `thoughts.json` |
| `error-overflow`: HTTP 500 to alternate | PASS | `llm-1004-fix1-error-overflow/journal/`, `brain-after.json` |
| `outage`: gate holds callers and recovers | PASS | `llm-1004-fix1-outage/mind.log`, `primary-restarted-requests.jsonl`, `processes.json`, `journal/` |
| `repair`: fenced JSON, trailing comma and content array | PASS | `llm-1004-fix1-repair/primary-requests.jsonl`, `journal/`, `thoughts.json` |
| `deliberation-retry`: rejection feedback to default profile | PASS | `llm-1004-fix1-deliberation-retry/journal/`, `thoughts.json` |
| `retry-exhausted`: three rejected replies and authority error | PASS | `llm-1004-fix1-retry-exhausted/journal/`, `thoughts.json` |
| `timeout`: actual 180-second Rust HTTP timeout and fallback | PASS | `llm-1004-fix1-timeout/alternate-requests.jsonl`, `journal/`, `thoughts.json` |
| Model-client cargo tests | PASS, 4 passed | `llm-1004-fix1/cargo-tests.log` |
| Shared fake contract | PASS, 9 scenarios | `llm-1004-fix1-fake-contract/results.json`, per-scenario request logs |
| Live-probe guard and config precedence | PASS without requests | `minds-duel-safety-1004-final/live-probe-guard.log`, `config-checks.json`, `config-routes.json` |
| Paid provider access | NOT RUN | Specific paid-run authorization is required. |

## Changes and cleanup

The owned `Run` helper accepts only `llm` or `minds` caller prefixes. It shares environment setup, explicit LoD options, mind launch, restart configuration and private SQL with `verify-minds`. Admin SQL now uses `verify.py sql --as-admin`. Database cleanup uses shared `verify.py cleanup`, which confirms SQL 404 before setting `published` false. The helper records that verified state rather than duplicating the HTTP check. The obsolete claim that shared cleanup ignores deletion is removed.

Both paid commands use `scripts/models_config.py`. Explicit `--models` wins, then environment or non-overriding `.env` `LIVING_MODELS`, then the product's repository default. On this host the active file is `.local/living/models.json`, whose Luna profile uses `127.0.0.1:8787`. The repository example uses `codex.carlid.dev`. Following the active configuration keeps the probe and mind on the same route. Config precedence and routes were checked read-only; neither endpoint received a request.

`llm-1004-fix1/results.json` is the full acceptance list. `llm-1004-fix1/cleanup-audit.json` independently confirms all 15 databases answer SQL 404, every owned PID is gone, saved player tokens are removed, copied journals and evidence remain, and the shared service still answers ping. A JWT scan of the suite and case evidence was clean. Minds received SIGTERM by owned PID; this is recorded as a signal stop. The existing container was neither stopped nor restarted.

## Documentation and limits

Official [documentation](https://spacetimedb.com/docs/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [views](https://spacetimedb.com/docs/functions/views/) were consulted again before this fix round. Current pages label themselves 2.0.0. The authority and SDK are pinned to 2.10.1; doctor confirmed the running v2.10.1 image. The driver uses existing reducers, the version-pinned generated SDK and existing sender-scoped views. It waits for subscription readiness and checks accepted authority effects. No new schema or SDK API is assumed.

Each case had one mind subscription and no observer or full export. Most cases selected one adult; routing selected two adults and one child. The whole default seeded world continued ticking. The first subscription population per case is recorded in `cleanup-audit.json`; `people.json`, fake request logs and doctor output retain the actual setup and request counts. Scripts installed a think graph per selected actor, plus one addressed player conversation in `basic`. Fake-call concurrency was four with no rate limit. Local density was arranged only for that conversation. The two skill suites ran concurrently in separate databases, with a brief third reconnect probe. These are correctness scenes, not performance or scale measurements.

Frontmatter, Python syntax, relative links and the Claude/Cursor discovery links were checked read-only. Codex and Mistral share the standard `.agents/skills/` source. Interactive instruction loading in the other three runtimes remains unverified. Live access, full model workload, model judgment, high-concurrency overflow, durable memory and performance targets remain unverified. The neighbouring skills in `SKILL.md` own those checks.
