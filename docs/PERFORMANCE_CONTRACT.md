# Game performance contract

Agreed with the user on 2026-09-07. These are product acceptance requirements,
not measured capabilities. This contract supersedes the old 20 Hz whole-world
checkpoint and the intermediate 30 Hz combat proposal. Change these requirements
through an explicit product decision, not to accommodate a benchmark result.

## Player experience

The target is responsive action-RPG movement and combat in a persistent living
world. LoL, VALORANT, CS2 and SUPERVIVE are references for the desired feel, not
claims that their server architectures or capacity transfer to this game.

| Area | Locked requirement |
| --- | --- |
| Active movement and combat | Sustained **60 Hz** authoritative simulation, including the 200-character battle workload. The nominal step interval is 16.667 ms. |
| Local response | Movement and attack feedback begins within **50 ms at p95**, using prediction where appropriate. Predicted feedback does not establish an authoritative hit or effect. |
| Server response | Server receipt to committed action outcome: **≤50 ms p95, ≤100 ms p99**, excluding declared intentional cast times/cooldowns. |
| Networked confirmation | Client input to authoritative outcome received: **≤150 ms p95, ≤250 ms p99**, at **80 ms round-trip latency**. |
| Client baseline | Stable **60 FPS** on the defined minimum supported client hardware, including combat; **99% of frames within approximately 16.7 ms**. Report missed frames and stutters separately. |
| Higher refresh rates | Support **120/144/165/240 FPS and higher** when hardware permits, with configurable caps. Camera, animation and local input presentation benefit from the additional frames. |
| Slow world systems | Hunger, damage, growth, infrastructure and similar systems execute at their gameplay deadlines. Settle due effects before dependent actions; slow maintenance must not block timely combat. |
| AI controllers | Installed behavior continues responsively while model interpretation and policy revision run asynchronously. Model latency must not gate physical simulation. |

Rendering and input presentation are independent of server ticks. Higher client
FPS must not change movement speed, cooldowns, costs or physical rules. Remote
movement should remain smooth between received updates; prediction corrections
should be infrequent and unobtrusive. These experience properties require actual
client playtests in addition to timing metrics.

60 Hz is the selected target. 64 Hz would shorten each interval by only about
1.04 ms and is not a separate quality goal; 128 Hz is not currently required.
Neither a configured timer nor mixed action/maintenance transaction counts prove
that active movement and combat actually meet the cadence requirement.

The current Bevy behavior-lab client remains temporary. These requirements apply
to the eventual gameplay client; they do not reopen deferred client-polish work.
Full product acceptance will still require client verification.

## Population, duration and resource envelope

The full target is **2,000 simultaneously active characters in one persistent
world**, including **200 interacting combatants in one locality**, sustained for
**8 hours**. Human- and AI-controlled characters have the same physical rules and
count equally toward character population. All real connections, controller
processing and delivery costs must be included; character count alone is not a
connection-capacity result. Other characters continue ordinary world activities
while combat runs.

The initial total backend reference budget is **16 vCPUs and 64 GB RAM**, covering
authority, controller and relay services. External model inference and load
generators are excluded and reported separately. This is a combined resource
budget, not a requirement for a particular deployment topology. Record the CPU
model, allocation, storage, software versions and network configuration; a vCPU
count alone does not make two machines equivalent.

Queues and timing debt must not accumulate, and active memory must reach a
bounded operating range. Retained audit history may grow: report storage growth,
archive backlog and retention separately from active memory. Do not obtain a pass
by restarting services, deleting original evidence, losing subscriptions or
letting the active population shrink. Preserve permanent death and ordinary
population-renewal rules rather than adding benchmark-only respawns or immunity.

## Acceptance workload and measurement

Use the actual shared simulation and authority. Include normal client
subscriptions, human input, an observer, persistence and audit maintenance.
Exercise movement, attacks, projectiles, dodges and interruptions as the mechanics
become available. Missing mechanics remain an acceptance gap; a transport fixture
or rest/move loop cannot stand in for full combat.

Before an acceptance run, freeze a manifest specifying:

- Population and controller mix, connection counts, ordinary activity rates,
  combat density, battle duration/duty cycle and effect/projectile load.
- Skill/law versions, resource supply and how the workload sustains its declared
  active population without bypassing gameplay rules.
- Subscription recipients, observer/inspector scope, export load and model-call
  concurrency/rate. Real inference and recorded/synthetic responses are labeled
  separately; model failures remain visible.
- Exact backend and client hardware/settings, reference client build, network
  RTT plus jitter/loss profile, warm-up, duration and resource limits.

The specific minimum client hardware and representative workload parameters are
not yet selected. They must be fixed before claiming acceptance, rather than
chosen after seeing results. The locked requirements above are not provisional
because those benchmark details remain to be specified.

Measure timestamps for input, server receipt, execution, commit and scoped
delivery. A reducer acknowledgement, accepted request, attempted action and
physical outcome are different milestones. Correlate them by request/action ID.
Report designed cast/cooldown delay separately; it must not conceal queueing or
late execution. Use a common monotonic clock for each interval where possible;
cross-machine intervals require documented clock synchronization/error bounds.

Report p50/p95/p99, maxima and missing outcomes, with time-window and workload
breakdowns so aggregate averages cannot hide a bad battle or a late-run collapse.
Record combat step intervals and deadline lateness separately from slow-system
transactions. Measure client frame pacing, subscription traffic, reducer/queue
time, controller/relay CPU, WASM and allocator memory, table growth and retained
WAL. Scoped privacy, shared physical rules, causal evidence and reconnect recovery
remain correctness gates at every load.

## Development gates and current evidence

1. **Immediate gate:** 216 active characters for **30 minutes**, meeting the same
   cadence, latency and applicable client requirements, with the declared crowded
   combat workload. Raw authority checks can progress first but are only partial
   evidence while client/combat coverage is missing.
2. **Scale gate:** increase population toward 2,000 without relaxing the response
   limits; verify the 200-character local battle alongside ordinary world work.
3. **Sustained product gate:** the complete 2,000-character workload meets this
   contract for 8 hours within the reference resource budget.

None of these gates is currently accepted. The latest 216-character diagnostic
is the [short baseline (25)](PERFORMANCE_BASELINE_25.md), which excludes long soaks
and records failed latency, admission and combat-startup checks. The earlier run
at a configured 33 ms interval delivered about 24.86 action-only transactions/s.
Its 107 automated inputs had p95 reducer-completion latency of 164.8 ms and p95
execution-notice latency of 331 ms. Those measurements are not the newly specified
server-only or 80 ms RTT outcome intervals and do not establish compliance.
See [retained performance evidence](REALTIME_PERFORMANCE.md#independent-physical-clocks-24)
and the [independent clock implementation](INDEPENDENT_PHYSICAL_CLOCK.md).

Future performance work should name the failing requirement, hypothesized cause,
measured result and remaining gap. Average world updates/s is a diagnostic, not
the completion criterion. Preserve original failed outcomes and historical targets.

## Reference evidence

These sources informed the comparison; our requirements are the agreed product
choice rather than requirements imposed by these games:

- [Riot's League infrastructure presentation, slide 43](https://reinvent.awsevents.com/content/dam/reinvent/2024/slides/gam/GAM307_Effortless-game-launches-How-League-of-Legends-runs-at-scale-on-AWS.pdf#page=43): 30 simulation updates/s.
- [Riot's VALORANT server engineering report](https://www.riotgames.com/en/news/valorants-128-tick-servers): 128 Hz and its execution budget.
- [Valve's Source 2 telemetry documentation](https://help.steampowered.com/en/faqs/view/5E6F-5B36-5485-F6B9): CS2 at 64 Hz and Deadlock at 60 Hz.
- [Valve's CS2 explanation](https://www.counter-strike.net/cs2): sub-tick input timing.
- [Riot's netcode explanation](https://www.riotgames.com/en/news/peeking-valorants-netcode): prediction, network delay and rendering independently of fixed simulation steps.

SUPERVIVE remains a feel reference; its authoritative rate was not reliably
verified. No official rationale for Valve choosing precisely 64 instead of 60 Hz
was established. Exact binary representation of 1/64 is a mathematical property,
not evidence of Valve's design rationale or a requirement for accurate game timing.
