# TypeSafe shadow trial: real participant context

2026-09-17 · `codex/integration-exploration` · exploratory, not performance acceptance.

**Still a maybe, with a narrower next experiment.** The first actual-authority
trial preserved Luna's control and sent Jev copies of the same personal contexts.
Jev returned four valid responses; two requests exceeded its token limit. The four
responses took 0.526–1.175 seconds. This supports investigating bounded asynchronous
judgments, but does not support replacing the controller or using Jev to suppress
generative turns yet. See the earlier [architecture evaluation](TYPESAFE_EVALUATION.md)
for candidate uses and the separate synthetic screen.

## What ran

Retained evidence: [trial directory](../output/typesafe-shadow/trial-03/),
[manifest](../output/typesafe-shadow/trial-03/manifest.json),
[paired comparison](../output/typesafe-shadow/trial-03/comparison.json), and
[finalization](../output/typesafe-shadow/trial-03/finalization.json).
These ignored local artifacts include actual requests, raw replies, receipts,
the final World, contiguous audit, service data and binary hashes.

- Actual SpacetimeDB authority, isolated service/database; four characters in the
  existing shared-garden scenario, initially together at position 84 in a 16×12 map.
- Actors 1 and 3 each completed one behavior, communication and learning turn using
  the existing Luna profile. Actors 2 and 4 continued their installed seed policies.
- Primary: configured `gpt-5.6-luna`; one attempt, frozen 60-second deadline.
  Jev: pinned `jev-1.13.0`; one attempt, 10-second deadline; no fallback.
- Per actor: one primary and at most one shadow request in flight, one queued
  shadow sample, three calls, one-second interval after each primary completion.
  Across both actors: at most two primary and two shadow requests in flight.
- The shadow asked whether this responsibility warranted an operation, whether
  personal evidence was sufficient, and how urgent reconsideration was. These are
  independent Noul/Noul/Score questions, not generated behavior trees or dialogue.
- Six of six shadow records contain exactly the same personal context as their
  paired primary record. No observer World was used as model input.
- Approximately 89.25 seconds from clock start to confirmed pause; 180-second
  maximum live wall time. Configured world interval 50 ms, debug builds. The final
  world reached only tick 35. This does **not** demonstrate real-time execution or
  the project's 60 Hz / 216-character / 2,000-character acceptance targets.
- Existing scoped participant/controller subscriptions and the developer host's
  export loop remained active. No browser observer was attached. Final owner
  export occurred after producers stopped; it was never a model input.

## Results

| Character / responsibility | Luna proposal and receipt | Jev probability of operating | Jev HTTP time |
| --- | --- | ---: | ---: |
| Mira / behavior | Keep current policy; no operation | 0.26 | 1.167 s |
| Mira / communication | Speak; accepted, subsequently emitted | 0.38 | 0.592 s |
| Mira / learning | Reflect; client receipt accepted | 0.27 | 0.526 s |
| Iri / behavior | Patch subtree; rejected by validation | 0.22 | 1.175 s |
| Iri / communication | Speak; accepted, subsequently emitted | No answer: HTTP 400 | 0.520 s to error |
| Iri / learning | Reflect; client receipt accepted | No answer: HTTP 400 | 0.480 s to error |

Both HTTP 400 bodies were exactly
`{"detail":{"error_type":"max_tokens_exceeded"}}`. Successful requests reported
11,065–30,923 input tokens. Failed requests contained approximately 112–117 KB of
serialized state, but the service did not return their token counts. The error
establishes a context-budget problem for these requests, not a verified numerical
token limit. They were below the trial's separate 256 KiB request cap.

The four successful HTTP latencies have an arithmetic median of **0.880 seconds**;
nearest-rank p50 is 0.592 seconds and p95/p99 are both the maximum, 1.175 seconds.
With four samples these are descriptive statistics, not reliable tail estimates.
Successful decision ages including shadow dispatch/serialization were 0.534–1.181
seconds. The earlier synthetic screen's roughly 0.26-second median understated
latency for this full-context workload; different conditions preclude attributing
the entire difference to context length.

At a reporting-only threshold of 0.5, Jev chose no operation on every successful
response: **1/4 coarse agreements** with Luna's proposed operation/no-operation.
That is neither accuracy nor evidence that Luna was right. Luna's rejected patch
reported `condition location outside known world bounds`; Jev did not inspect
that generated patch, so its no-operation answer is not proof it detected the
defect. Suppressing speech or reflection could remove useful behavior; that needs
independent labels and downstream evaluation. Noul is a probability of yes, not
a separate confidence measure. No threshold here controlled the game.

Primary turns took 6.909–44.078 seconds, including observation, open-ended
generation and submission. Jev only answered bounded questions. **No equivalent-task
speedup or replacement-quality claim follows from those timings.**

Successful Jev responses reported 77,653 input tokens total, approximately
**$0.00326** at the vendor's published $0.042/million input-token rate with free
outputs ([vendor launch report](https://typesafe.ai/blog/introducing-system-one-models-and-jev)).
This is an estimate, not an invoice; failed-call usage was unavailable. Primary
usage is retained per call; its gateway cost was not established.

## Authority and evidence

Only the existing primary harness submitted proposals. The shadow worker has no
ParticipantService or database handle, and all six records say `applied:false`.
The queue uses `try_send`: a full/closed shadow queue records a skip without awaiting
inference. Copying and serializing context still consumes local resources; this
experiment does not prove zero overhead.

The final audit contains 1,514 contiguous events: 117 skill attempts, 115 skill
results, 130 participant commands, 12 shelter contributions and two emitted
speeches. This is roughly 1.31 skill attempts/second across the whole run, not a
controlled offered load. Seed policies remained responsible for routine execution.
The two speeches have primary receipt events 577 and 1113 and emitted events 580
and 1116. Their observed delivery is stronger evidence than an acceptance receipt.
The two reflection receipts have client fingerprints and event 0; this report
does not promote them to authority physical outcomes or established learning quality.
All four characters survived; survival in this short trial is not controller-quality
or sustainable-population evidence.

Both model workers finished normally. The host stopped on SIGINT, the world was
confirmed paused, all four grants were revoked and zero grants remained before
the final coherent capture. The owned service exited 0 after SIGINT; no forced
kill or restart concealed growth. Reducer queue/execution latency, subscription
bytes, memory and retained-data growth were not profiled, so no scale claim is made.

## Implementation and limitations

The [primary tap](../server/bridge/src/agent_harness.rs),
[shadow worker](../server/bridge/src/typesafe_shadow.rs) and
[trial example](../server/bridge/examples/participant_shadow_trial.rs) are opt-in.
Existing `deliberate_once` callers pass no shadow. Production controller selection,
authority tables and generated bindings are unchanged. Exact input/output journals,
bounded request/response sizes, cancellation and owned worker draining are included.

The original `trial-03` manifests say `completed`: that version counted finished
HTTP attempts, including errors. **That label is process completion, not six
successful comparisons.** Original evidence is preserved. The derived comparison
explicitly reports four successes, two errors and one rejected primary operation.
After inspecting the run, the worker/example were corrected to count successes,
errors and skips separately and return an incomplete trial on missing successful
samples. Served-model pin checking and source snapshots were also added for future
runs. These follow-up changes passed local checks but have not had another paid
live trial. Trial-03 retains hashes of the binaries actually used; its source was
uncommitted and was not separately snapshotted at execution time.

Two earlier setup failures are retained: `trial-01` selected an actor whose scenario
role was external and was rejected before inference; `trial-02` used a nonexistent
resume reducer and failed before inference. The supervisor now selects builtin
actors 1 and 3 and starts the existing `sim_operator_clock`. Trial-02 was paused,
revoked and captured at tick 0; both isolated services stopped without forced kills.

Official [subscription](https://spacetimedb.com/docs/clients/subscriptions/) and
[table performance](https://spacetimedb.com/docs/tables/performance/) documentation
were checked, with installed official SDK 2.1.0 source used to verify the pinned
subscription API. The trial used service/publish CLI 2.1.0 and control CLI 2.7.1.
No new table scans or subscriptions were introduced by the shadow; it consumes a
copy of the primary's scoped observation. Full exports remain diagnostic finalization.
TypeSafe's [API](https://docs.typesafe.ai/api.md),
[Noul](https://docs.typesafe.ai/primitives/noul.md) and
[Score](https://docs.typesafe.ai/primitives/score.md) contracts guided the adapter,
using the installed [TypeSafe skill](../.agents/skills/typesafe-ai/SKILL.md).

## Reproduce and next decision

Prerequisites: the two versioned CLIs above, Rust WASM target, and local `.env`
entries `TYPESAFE_API_KEY` and `CARLID_NPC_API_KEY`. Keep credentials out of commits.
Use a fresh output basename; private owner/session material is stored under
`.local/credentials/` and run evidence under ignored `output/`.

```sh
cargo build --locked -p server_module -p controller_module --target wasm32-unknown-unknown
cargo build --locked -p bridge --bin sao-dev-client --example participant_shadow_trial
python3 experiments/typesafe/run_shadow.py --out output/typesafe-shadow/new-trial
python3 experiments/typesafe/summarize_shadow.py output/typesafe-shadow/new-trial
```

Validation: both authority WASM modules and the host/example built; the final bridge
library suite passed **40/40** serially. An earlier concurrent test run had one
deadline/cancellation timing failure in an existing streaming test; its focused
rerun and both serial full-suite runs passed. The added shadow checks cover queue
saturation/closure, identical context, invalid responses and oversized-input
journaling without network dispatch. Python parsing and comparison edge cases were
checked locally. No simulation mechanics changed.

For the next trial, freeze a small purpose-specific projection of legitimate
personal evidence: the event under consideration, applicable goal/current policy,
relevant actor state and linked source IDs. Preserve the complete source journal
and explicit missing evidence. Test one narrow judgment such as whether a particular
event merits reflection, or rank existing evidence for an LLM turn. Label held-out
cases independently; compare the same question with Luna and a deterministic baseline.
Keep all answers in shadow until missed useful turns, ambiguity, stale decisions,
source fidelity and decision latency are measured. Do not truncate history blindly
or treat a compact candidate menu as a substitute for novel plans and conversation.
