# Authoritative timing contract

Implemented in rules `m1-7-time.1`, September 5, 2026. This supersedes the development client's former 2500 ms update interval. It does not change the retired legacy gameplay reducers.

## Native SpacetimeDB integration

SpacetimeDB owns scheduling, transactions, authenticated reducer inputs and subscription delivery. The application installs one `ScheduleAt::Interval` row per bounded run, default **50 ms (20 Hz target)**. The scheduled Rust reducer invokes the shared simulation kernel and its embedded Rhai definitions in the same transaction. Neither the browser nor the model bridge drives this clock. Initial model reasoning receives no warmup pause.

This follows the official [movement tutorial](https://spacetimedb.com/docs/tutorials/unity/part-4/): input reducers record intentions and an interval reducer advances the world. [Schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) also support one-shot deadlines; we do not implement a competing host timer service. The current small world evaluates due action continuations in its native interval reducer. Individual schedule rows for long-lived, sparse events remain available when a mechanic needs them.

The [Rust scheduling reference](https://docs.rs/spacetimedb/latest/spacetimedb/attr.reducer.html) describes best-effort execution. A configured interval is not a throughput guarantee. Our elapsed-time accounting is an application choice: derive elapsed milliseconds from the deterministic `ctx.timestamp` input and `SimRun.last_advanced_at`, retain submillisecond remainder, and pass that duration into the kernel. Regular pulses do not rewrite the schedule row. Only clock configuration/control changes its schedule or paused state. The pinned runtime/module is SpacetimeDB 2.1.0; current documentation is checked against compiled local APIs.

## Simulation and gameplay time

| Value | Meaning |
|---|---|
| `timing.time_ms` | Elapsed authoritative simulation time, excluding explicit pauses. |
| `timing.updates` | Count of committed simulation updates, independent of time units. |
| `tick`, `expires_tick`, `max_ticks` | Existing protocol compatibility units: one unit is **2500 ms**, not one scheduler invocation. |
| Script `time_ms` | Current simulation time. |
| Script `delta_ms` | Elapsed time since this invocation's previous evaluation; initial evaluation includes the current update. |
| Script `ready_at_ms` | Effective next evaluation time: maximum of continuation wakeup and lane cooldown. |
| Script result `wake_at_ms` | Continuation deadline, persisted with the running invocation; cancellation releases it. |
| Script result `cooldown_until_ms` | Earliest next effect on the actor lane, preserved across replacement so input spam cannot bypass costs. |

Participant context publishes milliseconds, update count and `clock_unit_ms`. Existing duration arguments for rest/wait count 2500 ms units. Legacy expiry fields remain quantized to that unit; they must not be interpreted as 20 Hz update counts. New mechanics should express deadlines explicitly in milliseconds. The browser displays elapsed seconds.

Bundled Rhai policy sets movement to one cell per 250 ms, gather/eat/speech cooldowns to 1000 ms, attack to 750 ms, and rest/wait units to 2500 ms. Needs and hazards pulse every 2500 ms. These are editable gameplay defaults. Rust owns validated time input, evaluation and persistence, not these balance values. An intention may start on the next authority update when its lane is ready; slow actions retain their own duration. Discrete grid movement remains the current mechanic; 20 Hz authority alone does not add continuous physics or client prediction.

Behavior and dialogue have independent readiness state. A continuation wakeup is distinct from a committed cooldown: cancelling rest permits another intention on the next update; replacing movement does not erase its 250 ms cooldown. Completed rest/wait adds no extra duration. A slow or failed speech invocation cannot impose a movement cooldown. Failed actions use an active-law retry delay. Applicable perceptions wake behavior guards; skill effects still respect the lane's deadline. Script changes activate at the next **update**, even when the legacy tick remains unchanged. Running skills keep their pinned definition while subsequent evaluations use active laws.

## Delays, pause and reproducibility

Cooldowns and periodic counters consume elapsed time rather than counting callbacks. Slight scheduler jitter is handled by persisted deadlines and remainders. There is at most one behavior traversal/action opportunity per actor per update; a long delay does not replay every missed action or collision. This is not a claim of identical outcomes for arbitrary coarse timesteps. Headless `World::step()` and the historical operator `sim_step` are explicit coarse 2500 ms experiment advances; live reducers use `advance_ms`, and the browser's single-step control advances 50 ms.

An elapsed gap above 60 seconds pauses the run with `clock_recovery_required` evidence rather than silently simulating an outage or dropping elapsed time. Recovery/offline progression is a future explicit product decision. Operator configuration/resume establishes a new timestamp baseline. Model latency never changes the clock configuration. Script transaction failures retain failure evidence rather than partial effects; they are observable faults, not permission to slow the world for reasoning.

Audit events carry simulation milliseconds and update count alongside the historical tick. Serialized continuations include evaluation time and lane deadlines. Saved worlds require the current rules version; old runs stay inspectable without silently acquiring new timing semantics.

## Measurement and remaining limits

[Timing tests](../simulation/src/timing_tests.rs) compare actual core execution at 50/100/125 ms, check save/reload, next-update activation and rejected outage jumps. [The authority experiment](../scripts/verify_simulation_timing.py) measures native updates against wall time, needs progression, pause/resume and clock authorization. Pilot observations also retain elapsed time and update count for measurements while clients and models are connected.

The current authority still rewrites one serialized world row per run. That is a bounded experiment adapter, not evidence of large-world scaling. SpacetimeDB's entity tables, indexes and selective subscriptions are the natural path when replacing it. Observer history decoding is limited to the most recent 180 events; the retained audit remains complete. Profile real reducer and subscription work before increasing population, not by reducing game speed to accommodate inference.

Final verification for `m1-7-time.1`: 84 relevant tests passed; release module, native host/MCP/participant runtime and Bevy WASM built successfully. `output/timing-contract-final-20260905/report.json` records 18.953 updates/sec, a simulation/wall-time ratio of 1.0002, pause/resume and authorization checks, and an authenticated move observed within 150 ms after cancelling rest. The earlier debug-module failure (15.898 Hz) and initial release/pilot evidence are retained separately. These checks establish bounded correctness; they do not establish sustained 20 Hz with the observer connected.
