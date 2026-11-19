# Rest and behaviour replacement

Spark, 2026-11-19. The laptop's sit-hips validation (`9b526a9b`) saw a resident remain seated 47 seconds after `wander` and 12 seconds after `goto home`. The authority scene below tests that transition with `wander`, with no mind service or client.

## What the authority does

- **Rest is an eight-second skill.** [`rest_duration`, `rest_spec` and `rest_shows`](../living/scripts/skills.rhai#L916) define the fixed duration, `latch: true`, and the `rest` look. [`act::perform`](../living/authority/src/act.rs#L1136) stops the body and sets the activity's end from the scripted duration. Bevy maps the rest look to ground sitting for eligible outdoor residents in dry weather. The client starts its roughly 1.54-second rise when the seat pose ends. [Town pose](../living/game/src/town.rs#L370), [rise](../living/game/src/live.rs#L874), [clip duration](../living/game/src/live.rs#L253).
- **The finishing-work latch applies inside a graph.** [`brain::eval`](../living/authority/src/brain.rs#L199) reads the active leaf for the current revision, and [`Node::If`](../living/authority/src/brain.rs#L644) keeps its then branch active if that leaf lies inside it. After a graph replacement the old activity is an orphan, outside the new graph's node range. [Finishing work](LIVING_CORE.md#behavior-graph).
- **A new graph can take over on its first evaluation.** The test reducer [`set_behavior`](../living/authority/src/lib.rs#L482) and a mind's [`install`](../living/authority/src/mind.rs#L523) call [`set_graph`](../living/authority/src/mind.rs#L315), which updates the graph and revision, orphans graph work and wakes the actor. [`act::begin`](../living/authority/src/act.rs#L781) can adopt a matching orphan without restarting its timer. When a different leaf can start, [it cancels the prior activity](../living/authority/src/act.rs#L1029), clearing the old `doing` and refreshing needs after rest. [`brain::after`](../living/authority/src/brain.rs#L2318) also cancels unowned work, with distinct exceptions for a held deliberate act or committed combat. Ordinary rest has neither exception. [Cancellation](../living/authority/src/act.rs#L1215).
- **The same graph path handles a player's rest or movement graph.** [`human_act`](../living/authority/src/lib.rs#L704) installs real-time commands as graphs. [`human_move`](../living/authority/src/lib.rs#L768) with nonzero input explicitly cancels current rest before setting movement intent, after the committed-combat check. These paths were read from source. The scene uses the admin entry point.
- **Iter-11 changes need rates.** `git diff b6abdb50^ b6abdb50` shows one production change, the `person_pace(0) = 0.3` multiplier for human hunger, energy, healing, starving, spent, wet and cold rates in Rhai. The remaining edits update tests and verification records. The eight-second timer, latch, graph installation and client pose code are identical across the merge. Rest recovers less energy per second, so a needs-driven graph can make different choices over time. [Rate multiplier](../living/scripts/skills.rhai#L755), [iteration 11](TRIALS.md#fast-iterations).

## Intended behaviour and recommendation

A resident can choose to stay seated because its current graph keeps choosing rest, for example while passing the evening at the square or sheltering from rain. The town notes describe both behaviours. The finishing-work rule lets a rest finish when its own guard falls away, while an explicit new graph that chooses viable movement can interrupt the rest. A 47-second hold after such a replacement would be a defect. [Town starting ways](TOWN_LIFE.md#starting-ways), [real-time graph and deliberate acts](LIVING_CORE.md#behavior-graph).

Carry the laptop's failed attempt into the next diagnosis with the reducer receipt and `brain.revision` immediately at `sync:up`. Sample `clock`, `activity`, `body` and `doing` for the same actor, then compare `seen_doing` and the drawn pose in the player's client. The first divergence determines the fix. The UI workaround at `8910d770` combines `place_at` with a second graph install (`wait`), so standing after that pair does not isolate either operation. In the authority, placement resets steering and writes a body frame. [Placement](../living/authority/src/motion.rs#L1394), [activity publication](../living/authority/src/town.rs#L142), [client lookup](../living/game/src/net.rs#L370).

Keep the current latch and orphan adoption while the reported authority failure remains unreproduced. If the trace shows a viable new leaf really waiting on an old graph's action, fix the ownership transition for all controllers. Keep in-graph completion and matching-action adoption, but allow an unrelated explicit goal to take over as soon as its checks pass. Use the existing commitment rules for actions that physically hold the body. If the authority already moved and cleared rest, fix the stale activity or pose at the first client boundary where it persists.

## Reproduce

Use the branch's [verify-core scene](../.agents/skills/verify-core/scripts/rest_latch.py) with each revision's verify harness. Run these commands from each revision's checkout on Spark, with the scene file copied into the same path for historical revisions. Use a private SpacetimeDB 2.14.1 container, bound to loopback with its own writable `/wasm` mount. Set `LIVING_STDB_CONTAINER` and `LIVING_STDB_URL` to that container and its published URL. Give each checkout a separate target subdirectory to avoid reusing generated seed data across revisions.

```bash
source ~/slop-sysroot/env.sh
export CARGO_TARGET_DIR=~/slop-restlatch-target/REVISION
run=core-rest-latch-REVISION    # use a lowercase label unique to the run
verify_cli=.agents/skills/verify/scripts/verify.py
~/slop-mq/build-slot python3 "$verify_cli" launch --run "$run"
python3 "$verify_cli" doctor --run "$run"
python3 .agents/skills/verify-core/scripts/rest_latch.py --run "$run"
python3 "$verify_cli" call --run "$run" set_paused '[true]' --as-admin
python3 "$verify_cli" cleanup --run "$run"
```

The scene selects the first living AI resident on the default seed, installs `rest`, waits until it has been stationary in the performing phase for at least 3.1 seconds of authority time, and installs `wander` with at least a second remaining on the original timer. It verifies the new revision and polls for the first changed `body.x/y` sample, for up to 47 seconds of wall time. `activity.started_ms` is the authority timestamp of the movement action, distinct from the first sampled position change. Doctor and the scene both check advancing time. Evidence is written under `.local/living/verify/<run>/`.

## Results

One fresh default-seed world per revision, resident #1, no model calls, no player or renderer. Spark used a private SpacetimeDB 2.14.1 container. Each doctor's four-second sample showed an advancing tick and each scene confirmed it again.

| Revision | Rest duration | Install to `wander` start (authority) | Install request to first changed stored `x/y` (wall) |
|---|---:|---:|---:|
| Main at start, `5ccbeacf` | 8.000 s | 1 ms | 0.126 s |
| Iter-11, `b6abdb50` | 8.000 s | 5 ms | 1.809 s |
| Parent, `e6b7e698` | 8.000 s | 4 ms | 0.580 s |

In each arm the first sample after replacement already had nonzero velocity and `wander` owned by the new revision. The stored position is the anchor of a movement segment, which may stay unchanged until the next segment or arrival. In the iter-11 arm the resident covered about 7.9 m on that first segment. These observations give no evidence of a 47-second authority hold or a latch regression at iter-11. The timings include sampling and depend on the actor's starting tile and steering. The laptop's specific `goto` run, client subscriptions and rendered pose were outside this comparison.

The first parent publish failed during species initialization after sharing a Cargo target with main. The clean per-revision retry succeeded. All three live worlds were paused before cleanup. The evidence archive `~/slop-evidence/rest-latch-2026-11-19.tar.zst` holds the launch, doctor, scene, pause and cleanup outputs, the raw samples and the failed publish log. `just living-check` passed on main's identical-input stamps.
