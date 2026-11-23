# NPC client service and (M) batching: what can leave the authority's thread

Status: **design and measurement**, 2026-11-23, dev-box. The measuring code is on branch `npc-measure` (`3f6768a28`), never for main. The owner's idea came through the general coordinator: NPCs "kind of like players … hosted on a different service", with the authority still computing who sees what. A second part splits a human player's character work into what the screen needs now (S) and what the character experiences and remembers (M).

## Recommendation

**Do not build the NPC body service on its own. Build it, if at all, as a consumer of the perception helper's sets, after the relay and the helper. Take (M) out of the tick first, by deriving witness lines outside it from what is delivered.**

- **The NPC service only pays when the authority stops computing each NPC's perceived set on its thread.**
  - Driving a fighter from outside frees 0.61 ms/s of its tick work. Its batched intents cost 0.27 back.
  - A perceived set computed the way a player's is costs about 1.0–1.4 ms/s per fighter. So the service alone makes a battle more expensive: 330 → about 470–550 ms/s for 200 fighters.
  - With the perception helper applying sets at 0.2 ms/s, it frees a little: about 330 → 307.
  - The big gain is for calm crowds: a 2,000-character world's graphs are about 800 of about 1,080 ms/s. That gain needs the helper, and calm NPCs' sets at about 1 Hz.
- **(M) is the cheaper lever.** Taking players' witness lines out of the tick (the upper bound) took the gate case's relay arm from 514 to 461 ms/s. Ticks/s went 59.5 → 59.8, and the server step p99 21/19 → 18 ms.
  - It does not reach the coordinator's line on the dev-box: arrival p99 24.5–24.8 ms, 0.78–0.86% over 25 ms.
  - Batching (M) at 1 Hz inside the tick saves little. Witness lines are already folded every 2 s, and what remains is a sight test per blow.
- **One service, not three.** Perception helper, relay and NPC service share one thing, the perceived sets. Run them as one process, with the minds' inference kept in the mind service.

## Bottom line

- **(i) The 216 gate case** (100 human fighters, 116 walkers): the NPC service frees almost nothing. All fighters are players; only the 64 residents' graphs move, about 20 ms/s. **(M) frees about 52 ms/s on the relay arm** (0.52 per human, upper bound), but the line is still missed.
- **(ii) A 200-fighter AI battle:**
  - service without the helper: worse, about +140 to +220 ms/s (estimate);
  - service with the helper: about −23 ms/s (estimate);
  - (M) for everyone: −27 ms/s (measured).
- **(iii) A 2,000-character world:** about −350 to −670 ms/s of about 1,080 (estimate), only with the helper and slow sets for calm NPCs. Without the helper, it is worse.
- **Latency:** a windup seen to a dodge sent costs a local service about **16–18 ms at the median** from the windup's start to the dodge's start (authority time). An in-tick AI is at 18–34 ms. The p99 is 335–700 ms for the service and 734 ms for the AI, mostly from fighters too busy to answer (§2.3).
- **The microsecond line** (59.9 ticks/s, arrival p99 within 17.5 ms, at most 0.5% over 25 ms) **was missed by every dev-box run here, including a world with no battle** (arrival p99 18.9 ms, at L1).

## 1. What was built and measured

**Branch `npc-measure`:** the relay prototype (`gate-remeasure`) with main `73e823313` merged (after `fair-ties`). The bindings were regenerated with the pinned v2.14.1 image.

**Laws.** Both are value-only and off by default. det_compare is **identical to main with both off** (16 players, 200 fighters, 1,800 ticks, 113 tables). The negative control (`memory_off=1`) differs in `experience`, `fight_seen` and `line_seen`.

- **`npc_external_on`.** Characters listed by `npc_external_set` (admin) in the private `npc_external` table are not evaluated by their graphs: `brain::evaluate` returns.
  - `npc_intents(batch: Vec<NpcIntent>)` applies one batch for many characters in one transaction.
  - Each intent goes through **the player's own input code**: `use_skill_as`, `release_skill_as` and `human_move_as`, which `use_skill`, `release_skill` and `human_move` now call. So the checks, rates, costs and effects are the same.
  - Attempts are recorded in `skill_use` with source `npc`, beside players' `player`.
- **`memory_off`.** The upper bound of deriving witness lines outside the tick.
  - 1: players are not judged onlookers of others' blows.
  - 2: no one is, and a fight's first landed blow is still tested for the bystanders it wakes.

**The stand-in service, gate-load `npc`.**
- It is one owner connection holding the battle's truth: bodies, fighters, characters, cards and readiness.
- It decides as `spawn_battle`'s graph does:
  - when a windup is aimed at it, it guards (odd ids) or dodges (even ids) at once;
  - otherwise it strikes the nearest person in reach, or walks up to them.
- It batches every 16 ms, and at once when a reflex is owed. It records every fighter row it receives, which is how reflexes are paired in both arms.

**Tools.**
- `living/tools/npc_measure/reflex.py` pairs reflexes; its known-answer self-test passes 5/5.
- `tables.py` builds the tables. It runs the Spark's `us_reread.py` (`gate216-x925` `5956bc2da`) unmodified, as a separate process.

**The prototype's limits** (needed for real use; not measured):
- **Identity.** The service calls as the world admin, not with a service identity of its own.
- **Rollback.** A player's failed call rolls back its own writes. In a batch, an intent refused after writing keeps what it wrote. SpacetimeDB 2.14.1 has one transaction per reducer call ([reducers](https://spacetimedb.com/docs/functions/reducers/): "Every reducer runs inside a database transaction"), so per-intent rollback needs validation before any write.
- **Sets.** It computes no perceived sets for NPCs. It reads the battle's truth as the owner. Per-NPC sets are inferred from the player path (§2.2), not measured with NPCs as viewers.

**Fixture.** Warm, `performance` governor, L0, two runs per arm, interleaved, on a private server (`npc-stdb`, v2.14.1). Runner listeners were sampled: `g-D-r2` passed the mark (a 10 s peak of 1.51 cores) and was redone as `g-D-r3`. All runs are post-fair-ties.

## 2. The NPC body service

### 2.1 Batched intents, measured

**The battle:** 200 fighters (`spawn_battle`, the dead replaced every second), no viewers. The service drives the fighters with `id % 4 < share`.

| Arm | DB thread, ms/s | Tick | `npc_intents` | Refills (`spawn_battle`) | Fallen/s | Ticks/s | Server step p99 (ms) |
|---|---:|---:|---:|---:|---:|---:|---|
| All AI | 329.6 (327.6–331.6) | 322.2 | – | 5.4 | 2.5 | 59.95 | 18, 18 |
| Service drives 50 | 336.8 (335.8–337.8) | 310.4 | 16.4 | 7.8 | 3.7 | 59.94 | 18, 18 |
| Service drives 100 | 311.5 (309.8–313.1) | 276.9 | 24.3 | 8.0 | 3.8 | 59.95 | 18, 18 |
| Service drives 200 | **266.8** (261.3–272.3) | **200.6** | **53.6** | 10.1 | 4.9 | 59.77 | 20, 21 |

**Per NPC, driving all 200:**
- **Tick freed:** −121.6 ms/s, **0.61 per NPC**. That is the graph evaluation, with the perception it asks for lazily (`nearest`, `sees`).
- **Batched intents:** +53.6, **0.27 per NPC**.
- **Net:** −63 ms/s, 0.31 per NPC.

**What a batch costs.** Fitted over the six runs (the window's calls only): about **0.18 ms per call plus 0.09 ms per intent**. A player's input call costs about 0.24 ms (the gate case: 72 ms/s for about 300 inputs a second). So a batched intent costs about half as much.
- The service sent 36–57 calls a second, with 2.7–8.6 intents each, and 2.4 intents a second per NPC when driving 200.
- Below about 100 NPCs the per-call part dominates: driving 50 cost more than it freed, net +7 ms/s.

**The fights differed.** Driven fighters fell faster (4.9/s against 2.5/s with all AI), so refills cost more (+4.7 ms/s).
- The stand-in answers every windup once. Its guards and dodges were often refused (busy, or out of breath).
- An AI's graph keeps trying on every evaluation. §2.3 has the answered shares.
- The DB comparison therefore carries some difference in workload.

### 2.2 Per-NPC perceived sets, inferred from the player path

**The owner wants the authority to keep computing who sees what.** For an NPC that means a set like a player's. These figures are inferred from human players, not measured with NPCs as viewers.

- **On the authority:**
  - a human fighter's perception sweep is **1.37 ms/s per s, 1.53 per tick**, at L2 ([HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md) §2.1);
  - a walker on the relay costs 0.81 in all;
  - with the perception helper, the authority only applies sets: **0.19–0.31 ms/s per viewer** ([PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md)).
- **Off the thread** (the relay, this series' gate runs):
  - relay process 49–50 ms/s for 216 clients, about **0.23 ms/s per client**;
  - about **1.1 KB/s and 15 frames/s per client**;
  - tick to client age p50 21 ms, p99 34–35 ms.

**So a fighter's set made the player's way (about 1.0–1.4) costs more than the graph work it replaces (0.61).** An AI's graph pays only for the perception it asks for. A player-grade set pays for everything in sight, every 200 ms.

### 2.3 Reflex latency: windup to answer, authority ms

Pairing: each windup aimed at a counted fighter, with its first dodge or block started between the windup's start and its release (`reflex.py`, the same for both arms).

| Arm | Windups | Answered | p50 | p90 | p99 |
|---|---:|---:|---:|---:|---:|
| All AI, every fighter | 6,225–6,366 | 62–64% | 33–34 ms | 584–597 ms | 734 ms |
| All AI, the ids a 50-NPC arm drives | 1,953–2,036 | 61–63% | 18–32 ms | 583–600 | 733 |
| Service drives 50 | 1,325–1,387 | 30–33% | 16 | 35–106 | 692–700 |
| Service drives 100 | 2,599–2,703 | 37–39% | 16 | 28–31 | 634–650 |
| Service drives 200 | 6,291–6,307 | 39–40% | **17–18** | **29–30** | **335–345** |

- **The service, step by step** (driving 200):
  - a windup reached it **17.4–17.7 ms (p50)** after the windup started (p99 108–115 ms; 418–632 ms with fewer driven);
  - it decided in 0.02 ms;
  - the next tick applied the intent.
- **An in-tick AI** waits for its combat evaluation (15 Hz, every 4th tick): 18 or 33 ms at the median, by phase.
- **The tails come from being busy.** An AI keeps evaluating until it can answer (p90 about 0.6 s); the stand-in tries once. A real service would retry the same way, and its answered share would rise.
- **Over a real network** the service's p50 grows by the network's round trip. A local service is as quick as the tick, or quicker.

### 2.4 What it frees, with the arithmetic

dev-box measured or estimated; X925 is scaled by the same-code ratio 0.86–0.92 ([BATTLE_CONTRACT_CASES.md](BATTLE_CONTRACT_CASES.md) §3). The dev-box is the harder case.

| Case | Today, ms/s (dev-box) | Service alone | Service with the helper | X925, with the helper |
|---|---:|---:|---:|---:|
| (i) The 216 gate case, relay | 514 | about −20 (the residents' graphs) | about −20 | about −17 to −18 |
| (ii) 200-fighter AI battle | 330 | **worse: about 470–550** (−63 + 200 × 1.0–1.4) | **about 307** (−63 + 200 × 0.2) | about 264–282 |
| (iii) 2,000-character world | about 1,080 | worse | **about 410–730** | about 350–670 |

**The arithmetic for (iii):**
- A calm resident costs about 0.54 ms/s at L0 (64 residents, 34.6 ms/s). 2,000 of them make about 1,080 ms/s, already beyond one thread.
- In this series' calm world (L1, two runs), graph evaluation is **74% of the tick**: the slots 31.4, wakes 3.7 and combat 0.4 of 48 ms/s. That is about **800 ms/s** for 2,000.
- **Intents:** calm characters act rarely. At an assumed 0.2 a second each: 2,000 × 0.2 × 0.09 plus about 60 calls × 0.18, about **47 ms/s**.
- **Sets:**
  - the player's way, about 0.5 each: about **1,000 ms/s, worse than today**;
  - applied from the helper at 5 Hz: about 400;
  - at 1 Hz for calm NPCs: about 80.
- **Result:** 1,080 − 800 + 47 + 80…400 = **about 410–730**.
- **Assumptions:** linear scaling from 64 to 2,000 residents, and the intent rate. Neither is measured.

### 2.5 Determinism, replays, "same rules for players and minds"

- **The same rules.** Intents enter through the player's input code: the same checks, rates (`input_hz`), costs, refusals and outcome rows. An NPC's attempt is recorded like a player's (`skill_use`, source `npc`), so intention, attempt, refusal and outcome stay distinct, as AGENTS.md asks.
- **What leaves the authority is the graph's evaluation, not the rules.** But the graphs (instincts, routines, minds' plans) are part of the world's laws today, evaluated by `brain.rs` against the authority's own tables.
  - A service that evaluates them must run **the same graph code**: `brain.rs`'s evaluator, moved into a shared crate that both the authority and the service use. Otherwise it is the "second approximate simulator" AGENTS.md forbids.
  - That is the largest piece of work in this design. `brain.rs` reads about 20 tables directly.
- **Determinism.** The authority stays deterministic given its inputs. The NPCs' decisions become inputs, so they arrive in network order.
  - A commitlog replay restores the same rows: the batches' effects are in it.
  - A rerun from a seed (det_compare's runs) no longer reproduces the NPCs' decisions, as it does not reproduce players'. To compare runs, the intents would have to be recorded and fed back.
  - det_compare with `npc_external_on` off is unchanged (above).
- **External inference stays in the mind service** (`living/mind`). The NPC service would evaluate graphs only, never a model.

### 2.6 Failure

- **The service lags.** Its NPCs act late, like a lagging player. Reflexes lose their 16–18 ms edge, and blows land.
- **The service dies.** Its NPCs stand idle and defenceless.
- **The fallback** needs a lease: a batch at least every N ms, or the authority unlists the service's NPCs, and their graphs run in the tick again. This is cheap to build, since the evaluator stays on the authority. But **the authority must still carry the whole in-tick load while the service is down.** So the service raises normal-time headroom, not the worst-case limit.
- **A slower fallback:** NPCs hold or retreat while the service is gone. It costs less, but it is a visible change of behaviour.

### 2.7 One service or three

- **The perception helper** computes the sets: who sees whom, for players and NPCs alike.
- **The relay** delivers sets to player clients.
- **The NPC service** consumes sets and sends intents.

**All three hold the same per-character sets and the same world truth.** One process with three roles avoids a second copy of the truth and a relay hop between helper and NPCs. The minds stay a separate service: inference, not physics or perception.

## 3. (M): what a character experiences and remembers

### 3.1 The split of a human fighter's premium

From [HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md)'s L2 runs (B0 → B50). Per human per second; per tick at 60 Hz in brackets.

| Part | Kind | ms/s per human |
|---|---|---:|
| Perception sweep (heed, sight, projections) | S: the perceived set | 1.37 (1.53) |
| Delivery in the tick (`tick.frames`: copies, earshot, scenes) | S | 0.51 (0.58) |
| Frame cues (`tick.cues`) | S | 0.12 (0.13) |
| Input (`use_skill`, `human_move`, `release_skill`, `join`) | S | about 0.4 (0.44) |
| Finding a blow's onlookers by sight (`fold.blow`) | **M** | **0.22 (0.29)** |
| Folding and writing witness lines (`fold.flush`: labels 0.17, writes 0.05) | **M** | **0.24 (0.30)** |
| Per-blow percepts (`perceive.*`) | **M** | **about 0.1** |
| Lines delivered (`frame.lines`) | **M** | **0.07** |
| Damage, deaths and outcomes (`act.damage`, `act.die`, outside `fold.blow`) | S: own outcome, and workload | about 0.2 |

**So (M) is about 0.6–0.75 of the 3.1–3.7 premium (about 20%).**
- `combat_seen` (`my_combat`) is the screen's feed of blows seen: S. A client that draws hits from the relay would not need it.
- First sights and familiarity are an AI's (`brain.noticed`). A player's character does not run them in the tick.

### 3.2 What reads (M) in real time

**No graph condition reads witness lines.** The conditions (`brain.rs` `cond`) read live state: vitals, activity, sight, threat, `heard_ms`, beliefs, judgments.

**These do read (M) rows at once, and would change behaviour if those rows were batched:**

| Reader | Reads | If batched |
|---|---|---|
| A mind's "watch for" request (`mind.rs`, cue validation) | familiarity | "you have never seen #id" for someone first seen within the batch window: **a real change** |
| The fight report a mind is asked to think about (`act.rs`) | its own `attacked`/`combat` lines | own outcomes, S: keep them at once |
| A plan's say nodes (`line_overtaken`, `heard_first`) | heard speech in `experience` | speech is not (M) here: keep it at once |
| A fight's first landed blow (`fold::blow`, `wake_bystander`) | the sight test at the blow | **wakes bystanders: real time.** `memory_off=2` keeps this test |

### 3.3 1 Hz inside the tick, or derived outside it

- **1 Hz in the tick saves little.** Witness lines are already one folded line every 2 s (`witness_fold_ms`, "Grim attacked Ada: 3 blows (2 landed, 1 blocked)").
  - What remains is the sight test per blow, against the onlookers near it.
  - Testing once a second per (onlooker, fighter) pair costs about the same: each fighter is in fewer than one blow a second.
  - Using the last sweep's sets for players (lever (b), [HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md) §7) saved about 5 ms/s, inside the spread.
- **Derived outside the tick, from what the relay already delivers** (each player's set and the fighters' moves), (M) leaves the thread. `memory_off` measures that upper bound (§3.4). The lines would then be built by the service, not the authority.
- **The same cadence for everyone** is possible if the NPC and mind side derives its characters' lines the same way. `memory_off=2` on the AI battle: **329.6 → 302.4 ms/s (−27, 0.14 per AI fighter)**, with bystanders still woken by first blows.

### 3.4 The gate case with players' (M) out of the tick

100 human fighters and 116 walkers, `experience_copy`, after fair-ties. Two runs each.

| Arm | DB thread, ms/s | Ticks/s | Server step p99 (ms) | Server steps over 25 ms | Arrival p99 (ms, µs) | Arrival over 25 ms | Line |
|---|---:|---:|---|---:|---|---:|---|
| Relay | 513.6 (505.6–521.6) | 59.53 | 21, 19 | 0.62–0.95% | 26.0–27.9 | 1.37–3.17% | fail |
| **Relay, `memory_off=1`** | **461.1** (449.6–472.6) | **59.83** | **18, 18** | **0.25–0.31%** | 24.5–24.8 | 0.78–0.86% | fail |
| Direct | 596.8 | 58.29 | 33, 33 | 2.39–3.45% | 30.0–31.1 | 3.2–6.1% | fail |
| Direct, `memory_off=1` | 566.1 (563.1–569.1) | 58.75 | 33, 33 | 1.84–2.39% | 28.9–30.0 | 2.7–3.3% | fail |

- **(M) out of the tick saves 52 ms/s on the relay arm (0.52 per human) and 31 direct.** The server's step p99 reaches 18 ms on the relay arm.
- **On X925**, scaled 0.86–0.92: the relay arm with (M) out is about **397–424 ms/s**. The Spark measured X925's relay base at 59.92 ticks/s and a server p99 of 18 ms, so (M) out would very likely bring it within the slot by server steps. That is an estimate; X925's arrival µs is not measured with (M) out.
- **On the dev-box the arrival line is out of reach as measured.** Even with no battle (64 residents, L1), the arrival p99 is 18.9 ms. The 200-fighter AI battle reads 22.2–23.9 ms at 300–330 ms/s.
  - The watching client shares the host with the server, the driven clients and the relay ([HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md) §8).
  - Whether the reference server meets 17.5 ms on arrival is a hardware and placement question as much as a tick question.

### 3.5 With the perception helper (estimate)

On the dev-box, the relay arm with (M) out (461) and players' sets applied at 0.2 instead of swept at about 1.0–1.4 is **about 340–380 ms/s**. That is below the about 390 ms/s where strict server steps held ([HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md) §4).

## 4. Not measured

- **NPCs as relay viewers.** Their sets are inferred from the player path.
- **A service identity, per-intent rollback, a lease and fallback.**
- **The graph evaluator in a shared crate,** and its cost outside the authority.
- **Calm NPCs' intent rate, and the 2,000-character world.** Both are extrapolated from 64 residents.
- **(M) derived outside:** only its removal is measured, not building the lines elsewhere.
- **X925:** scaled, not measured, except where the Spark's figures are quoted.

## Evidence

- **Code:** branch `npc-measure`:
  - `1b007f62f`: the laws, the reducers, the stand-in and `battle_viewers --npc-share`;
  - `fc750162f`: the skill codes at ready;
  - `3c1c5b31c`: `reflex.py` and its self-test;
  - `3f6768a28`: `tables.py`.
  - Module `npc-cullet` `89a2025cad08`.
- **Runs:** dev-box, worktree `t3-b749c655`, `.local/npc/`:
  - `runs/`: the series and the redo, `series.log`, `tables.json`, `runners.log`, `flagged.txt` (`g-D-r2`);
  - `det-off/`, `det-negative/`: det_compare;
  - `smoke/`.
- **Archived** to `~/archive/worktree-evidence-20261123/npc-service.tar.zst` on the dev-box (sha256 beside it).
- **SpacetimeDB** (docs; the pinned 2.14.1 behaves as quoted where used here):
  - [reducers](https://spacetimedb.com/docs/functions/reducers/): one transaction per call, rolled back on error;
  - [schedule tables](https://spacetimedb.com/docs/tables/schedule-tables): an interval's missed ticks are skipped;
  - [subscription semantics](https://spacetimedb.com/docs/clients/subscriptions/semantics): one update per transaction, in commit order;
  - [access permissions](https://spacetimedb.com/docs/tables/access-permissions/): "Clients cannot query, subscribe to, or see private tables".
  - The owner connections here, and the relay's, subscribe private tables as the database owner, as [RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md) does.
- **Related:**
  - [HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md);
  - [PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md);
  - [RELAY_PROTOTYPE.md](RELAY_PROTOTYPE.md);
  - [BATTLE_CONTRACT_CASES.md](BATTLE_CONTRACT_CASES.md);
  - [BATTLE_SCALE.md](BATTLE_SCALE.md) (fix 4, the folded lines);
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md).
