# Relay prototype: what delivery off the database thread actually saves

Status: **measurement**, 2026-11-22, dev-box. The prototype lives on branch `relay-proto` (from `viewer-floor`) and never goes to main. This note is the §2.6 measurement that [BATTLE_DELIVERY_PATHS.md](BATTLE_DELIVERY_PATHS.md) asked for before anyone commits to building a relay.

## Measured, and the recommendation updated

**The relay works, and it is safe, but it does not hold up as the way to 216 viewers.** The measurement is at the contract's density: the 26–32 m ring, about 49 in sight, heed with holds at 16, uninstrumented. Every arm ran on an equally warm host (§2.3).

| | Direct: today's path with the plausible cuts | Relay |
|---|---:|---:|
| Authority cost per viewer, 64 viewers | **2.78 ms/s** (2.77–2.78) | **2.30 ms/s** (2.24–2.36) |
| Authority cost per viewer, 128 viewers | – (saturates) | 2.04 ms/s (53.7 ticks/s: over budget) |
| Viewers that fit 60 Hz on dev-box (warm budget 266 ms/s) | about 96 | about **116** |
| With fighters at 10 Hz (estimate: X925's −17% applied) | about 116 | about 140 |

**The details:**
- **The relay's feed** (its one trusted subscription) costs **1.0–1.3 ms/s** of subscription evaluation for the whole battle. That confirms the 1.9 ms/s figure from the design study's command-line subscriber.
- **Latency the relay adds** (its receipt to a client's receipt), p50 / p99:
  - 0.09 / 0.2–0.5 ms at 16 viewers;
  - 0.14 / 0.65 ms at 64;
  - 0.20 / 1.2 ms at 128;
  - 0.35 / 2.1 ms at 216.

  Against the contract's 150 ms input-to-outcome budget, that is negligible.
- **The relay's own cost:** 21, 34 and 48 ms/s of CPU and 22, 29 and 40 MB of memory at 16, 64 and 128 viewers; 58 ms/s and 53 MB at 216. That is about 13 ms/s plus 0.2 ms/s per viewer, and about 15 MB plus 0.17 MB per viewer: under 6% of one core at 216.
- **Privacy** (corrected 2026-11-22, §3.4): no viewer received a row outside its authority-written set. The claim was re-proved with a fixed probe (`26c71b96e`), because the original probe's transaction names collided once a second.
  - **The known answer:** the deliberately broken relay was caught first, with 143 violations in 23,350 rows.
  - **The re-proof:** 0 violations in 1,094,943 rows at 16, 64 and 128 viewers, with the relay alone, including set changes in the same transaction.
  - **With off-thread perception** ([PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md)): another 1,368,310 rows at those counts, 0 violations.

**Why the relay saves less than the estimate.** It removes 0.5–0.7 ms/s per viewer: copies, cues, the fight feed, hearing, and their subscription evaluation. The estimate of about 1.2 ms/s left on the authority did not survive measurement. Of the relay arm's 2.3 ms/s (L1 shares, §3):
- **perception, 0.92:** sight, heed, the perceived set, projections and crowd rows;
- **the viewer as a character, about 0.83:** its witness lines, wakes, acts, combat cadence and body. An AI character in its place pays the same;
- **input, 0.14:** the keep-alive's moves;
- **the rest, about 0.3:** views, the frames' remaining bookkeeping, subscription evaluation.

**216 viewers need about 1.23 ms/s each.** With the relay, only two levers remain:
- **Perception off the thread.** This is the design study's stage 2, perception compute beside the authority: sight and heed by the same rules crate, with the authority committing the result as trusted input. The owner decides, because rule evaluation leaves the reducer thread.
- **A cheaper character.** The AI tick's per-character work, such as the 10 Hz combat cadence (an owner's decision) and the fold.

Estimate with both: about 0.83 + 0.14 + 0.15 ≈ 1.1 ms/s per viewer, about 240 viewers on dev-box. That passes 216 on paper, at two owner's calls and a large build.

**Updated recommendation:**
- **Do not build the relay alone for this gate.** It buys about 20% more viewers (96 → 116).
- **Before any build, measure stage 2's premise:** the authority with sight and heed taken out (a switch), on the same fixture. If that measured per-viewer cost is at or below about 1.2, build the relay and perception compute together, after the owner's call on stage 2. If not, the 216-viewer battle needs the character's own cost cut, or a contract decision on viewer count.
- **A correction to VIEWER_FLOOR, found here (§2.3):** its per-viewer figures were about 18% low, because of host power states. That note now carries the correction.

## 1. What was built (branch `relay-proto`)

**On the authority**, one value-only law, `relay_on`, off by default.
- **With it on, the authority stops:**
  - writing players' copies, cues and the fight feed;
  - working out `heard` rows.
- **It writes each fight event once** to a private event table, `relay_event` (kind, actor, target, skill, position, amount, time).
- **It keeps:**
  - sight and heed;
  - each viewer's perceived set in `perceived` (the authority-written permission record; its writes stay in the measured cost, as the Spark asked);
  - projections, crowd rows, lines, views and every reducer;
  - the frames' engagement map, which heed reads.
- **Code:** commits `d2ce734f2`, `53535251a` and `fc1af9d77`.
  - `fc1af9d77` fixed the first version, which also skipped the engagement map. That left heed choosing from stale targets, and those runs were set aside (§2.4).
- **Bindings:** regenerated; the only change is `relay_event`.

**The relay** (`living/tools/relay_proto`, about 550 lines of Rust; SDK 2.14.1, tokio, tokio-tungstenite). One binary, three modes:
- **`relay`.** One owner connection subscribing `body`, `fighter`, `doing`, `perceived`, `player`, `relay_event` and `clock`.
  - Each server message is one transaction. The relay buffers its callbacks, then, after `advance_one_message` returns, applies the transaction's set changes first and its state second. A fact from transaction T therefore goes out only under T's sets.
  - Viewers connect by WebSocket and name themselves. Each gets:
    - the whole state of its set on connecting;
    - every change of a creature in its set;
    - "gone" when one leaves it;
    - fight events whose actor or target is in it, or that involve the viewer's own character;
    - 1 Hz hearing buckets: counts by 8 bearings and 3 bands of creatures within 9 m outside its set.
  - Frames are compact binary items (body 33 B, fighter 19, doing 18, event 22, gone 5, hearing bucket 4) under a 28-byte header: tick, transaction index, relay receipt time and the tick's time.
- **`clients`.** One WebSocket per viewer. It times each frame's hop from the relay's receipt and its age from the authority's tick, and logs every item.
- **`checker`.** An independent owner connection with the same subscriptions. It logs each viewer's set changes and the players' characters, by transaction.

Transactions are named (tick, index): the latest `clock` tick, and the number of messages since it. A transaction starts a new tick only when the `clock` row's tick number moves. Housekeeping (1 Hz) and a script install rewrite the row without moving it. The first probe counted any `clock` change, so once a second two transactions shared a name. That was fixed in `26c71b96e`, on branch `perc-offthread` (§3.4). Two connections with the same subscriptions get the same transactions in the same order (one server message per transaction in 2.14.1), so the relay's and the checker's names agree. `.local/rp/privacy.py` replays the checker's set history and fails any received item outside its viewer's set at that transaction.

**Off is off.** Main `a6375a70e` (the branch's base) against `rp-cullet` with every switch off, in `det_compare`'s player mode (16 players, 200 fighters, 1,800 ticks, every table every tick): **identical** (113 tables, 46,272 rows), checked again after `fc1af9d77`. The negative control, `relay_on=true`, differs from tick 2 in the law tables, then from tick 3 in copies, cues and senses.

**The harness.**
- `battle_viewers.py --relay BIN` starts the relay and the checker with the world, and one relay client per viewer once the viewers are ready.
- It reads the relay process's CPU and memory at the measured window's edges, stops everything after the window, and records the relay clients' identities.

### What a production relay would need that this one skips

- **Token verification.** The prototype trusts a viewer's self-declared identity.
- **Real clients.** The game client would need a relay connection and its scene fed from it.
- **Today's frame policy:** the near and far tiers, frame intervals by scene size, cue rules and budgets. The prototype sends every change of an attended creature at once, which is the cue path for everyone.
- **Lag handling, coalescing and back-pressure,** and their metrics.
- **Several relays,** standby or sharded by viewer, and restart from the authority snapshot.
- **The engagement-first ordering** of cues.
- **Earshot and crowd rows.** In relay mode the authority skips earshot (it reads the scene the relay now holds). Crowd rows stay on the authority.
- **Hearing by the sight set.** The prototype's hearing counts everyone outside the attended set within 9 m, including seen but unattended creatures. Production hearing would need the authority's sight set, or a decision on what is heard.
- **A `verify-relay` surface:** privacy probes against the relay's stream, and the scripted and real-client tiers.

## 2. Method

### 2.1 The fixture

VIEWER_FLOOR's set d:
- the 200-fighter sustained Cullet battle (`--keep-fighters 1`);
- viewers kept alive on the 26–32 m ring (`--keep-alive 0.5`);
- heed with holds at a ceiling of 16, crowd rows on;
- module memory for the sweep, lines every 1 s;
- L0 (no profiling) for the headline numbers, L1 for shares (series s), 20 s warm-up, 60 s window.

**The two arms:**
- **direct:** today's path with VIEWER_FLOOR's plausible cuts (hearing at 1 Hz, feed off);
- **relay:** `relay_on`, with the relay doing hearing and the feed.

Each viewer arm is measured against the 0-viewer arm in the same state: the battle alone for direct arms, the battle with the relay connected for relay arms.

**Server and host:** scratch server `rp-stdb` on dev-box, SpacetimeDB 2.14.1, started through `systemd-run --user --scope`. Replicas were cleared between runs, and each run waited for load under 4. No gate ran during any series.

### 2.2 The series

| Series | Runs | What |
|---|---:|---|
| smoke, broken | 2 | 16 viewers, 30 s: the real relay (0 violations) and the broken one (137) |
| m | 15 | the first full series; its relay arms are set aside (§2.4), its direct arms ran cold |
| m2 | 11 | relay arms rerun after the fix (cold) |
| z, z2 | 8 | the 0-viewer offset traced (§2.3) |
| **w** | **16** | **every arm warm: the headline numbers** |
| s | 4 | L1 shares at 64 viewers, warm |

### 2.3 Host power state: a finding that corrects VIEWER_FLOOR

The relay's 0-viewer arm ran about 50 ms/s below the battle alone: 327–340 against 375–399, the gap inside the module's own tick time. Three checks traced it:
- **Not the law:** a no-op law override, or `relay_on` with no relay process running, both match the plain battle (368–384).
- **Not the subscription:** VIEWER_FLOOR's command-line subscriber added +6.5 ms/s.
- **It is any neighbour process waking often.** A do-nothing Python loop sleeping 200 µs, with no connection to the server, lowers the battle alone from 370–378 to **328–330 ms/s (−12%)** (series z2).

The dev-box runs the `powersave` governor (`balance_performance`). A host kept out of deep idle runs the bursty 60 Hz tick faster.

**Consequence.** A viewer arm's own client processes warm the host, so subtracting a quiet 0-viewer reference **understates** per-viewer cost. Series w ran every arm with the waking loop on throughout. At 64 viewers, against VIEWER_FLOOR's set d:

| Arm | Cold (VIEWER_FLOOR) | Warm (here) |
|---|---:|---:|
| Floor | 1.78 | **2.10** (2.02–2.19) |
| Plausible cuts plus heed 16 | 2.36 | **2.78** (2.77–2.78) |

So VIEWER_FLOOR's per-viewer costs were about 18% low, and its viewer counts about 18% high. The warm 0-viewer battle is 333.8 ms/s, so the warm budget at 216 is 266 ms/s, or 1.23 ms/s per viewer. The relay's own polling made its arms and its reference equally warm, which is why the cold relay arms (series m2) already agreed with the warm ones: 2.26 against 2.30 at 64.

**For future measurements:** run every arm warm, or pin a performance governor. The governor is a host setting and the owner's decision on a shared host.

### 2.4 Set aside

- **Series m's relay arms.** The first `relay_on` also skipped the engagement map, so heed chose from stale targets. They are kept in `.local/rp/superseded/`.
- **Series m's direct arms** ran cold. They are kept, but not used for the headline.

## 3. Results

### 3.1 Per viewer, all warm (series w; L0; 2 runs per arm)

| Arm | Viewers | Ticks/s | Database thread, ms/s | Per viewer, ms/s | Subscription evaluation, ms/s | Views, ms/s |
|---|---:|---:|---:|---:|---:|---:|
| Battle alone | 0 | 60.0 | 333.8 (328.5–339.1) | – | 0.29 | – |
| Battle, relay connected | 0 | 60.0 | 326.9 (322.6–331.1) | – | 1.28 | – |
| Direct | 16 | 60.0 | 368.4 | 2.16 (2.12–2.20) | 2.64 | 2.01 |
| Relay | 16 | 60.0 | 366.1 | 2.46 (1.92–3.00) | 2.21 | 1.97 |
| Direct | 64 | 59.3 | 511.6 | **2.78** (2.77–2.78) | 9.65 | 8.61 |
| Relay | 64 | 59.4 | 474.0 | **2.30** (2.24–2.36) | 4.06 | 7.21 |
| Floor (attention 0, as today) | 64 | 59.1 | 468.5 | 2.10 (2.02–2.19) | 4.19 | 13.56 |
| Relay | 128 | 53.7 | 588.5 | 2.04 (2.02–2.07) | 6.04 | 16.39 |
| Relay (series m2, cold, 1 run) | 216 | 32.0 | 698.8 | – (saturated) | 7.74 | 23.80 |

- At 16 viewers the per-viewer figure carries the 0-viewer arm's ±5 ms/s spread divided by 16, so it does not separate the arms. 64 is the clean comparison.
- At 128 the relay arm misses 60 Hz (53.7 ticks/s at 588 ms/s): the tick's spikes, not its mean, hit the 16.7 ms slot.

### 3.2 Where the relay arm's cost goes (series s, L1, 64 viewers, warm, 1 run each; shares)

| Part, ms/s per viewer | Direct | Relay |
|---|---:|---:|
| Sweep: sight, heed, perceived set, projections, crowd rows (`tick.perception`) | 1.06 | **0.92** |
| Frames: copies, the near tier, lines, senses (`tick.frames`) | 0.42 | 0.13 |
| Cues | 0.03 | 0.01 |
| Combat, including feed work in the tick | 0.39 | 0.13 |
| The viewer as a character: fold, activity, wakes, slots, motion | 0.54 | **0.70** |
| Subscription evaluation | 0.14 | 0.04 |
| Views | 0.14 | 0.11 |
| Input (the keep-alive's moves) | 0.13 | 0.14 |
| **Total** (L1) | **3.04** | **2.33** |

- About 49 in sight and about 10.6 heeded per sweep in both arms.
- The viewer-as-a-character parts vary by ±0.1–0.2 between single runs; they are not touched by `relay_on`.

### 3.3 Latency (series w; m2 for 216)

| Viewers | Relay hop p50 / p95 / p99 (µs) | Tick start → client p50 / p99 (ms) |
|---:|---|---|
| 16 | 90–93 / 162–178 / 206–457 | 16.2–16.7 / 26.2–26.5 |
| 64 | 134–142 / 360–384 / 640–661 | 19.1–19.5 / 31.6–31.8 |
| 128 | 199 / 552–557 / 1,185–1,194 | 23.2–23.4 / 40.5–43.0 |
| 216 | 350 / 983 / 2,140 | 35.4 / 59.4 (the host saturated at 32 ticks/s) |

- **"Tick start → client"** runs from the tick's own clock time (`clock.last_ms`) to the client's receipt. It covers the tick body, its commit, the confirmed-read wait, subscription evaluation to the relay, the relay's step and the hop. A direct subscriber's latency is that minus the hop.
- **So the relay adds its hop:** under 0.7 ms at p99 up to 64 viewers, 1.2 ms at 128, 2.1 ms at 216.

### 3.4 Privacy

> **Correction (2026-11-22).** The figures first given here are superseded. They were measured with a probe whose transaction names collided once a second.
>
> - **The defect.** Housekeeping writes the `clock` row without moving its tick, and the relay and the checker counted that write as a new tick. Two transactions then shared a name, so the checker could misorder a set change against a row.
> - **How it showed.** In [PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md) §1.4, 6 rows were flagged, and the labels, not the relay, were out of order.
> - **The fix.** `26c71b96e` (branch `perc-offthread`): a new tick only when the tick number moves.
> - **What it means for the old figures.** The old 0 stands as observed. But the collision could in principle also have hidden a real violation at those boundaries, so the claim was re-proved.
>
> The re-proof ran on the `performance` governor, in the same battle at contract density, with the checker riding along in every relay arm and in its 0-viewer reference. The known answer ran first.

| Run set (fixed probe `26c71b96e`) | Viewers | Rows checked | Outside the set |
|---|---:|---:|---:|
| Broken relay (state before set removals), 30 s | 16 | 23,350 | **143**, each at the transaction where the creature left the set |
| Real relay (30 s and 60 s) | 16 | 58,089 | **0** |
| Real relay (4 runs: 15 Hz and 10 Hz fighters) | 64 | 680,526 | **0** |
| Real relay | 128 | 356,328 | **0** |
| **Relay alone, all** | 16–128 | **1,094,943** | **0** |
| Relay plus off-thread perception ([PERCEPTION_OFF_THREAD.md](PERCEPTION_OFF_THREAD.md); 2 runs at each count) | 16, 64, 128 | 1,368,310 | **0** |

**Superseded, first probe:**
- the broken relay: 137 violations in 18,925 rows;
- every real relay run (series smoke, m, m2, w; 16–216 viewers): 0 in about 1.83 million rows.

The re-proof did not cover 216 viewers.

## 4. SpacetimeDB 2.14.1: what the relay rests on

Docs (version 2.0.0 on the site) and the pinned source:
- **[Rust client SDK](https://spacetimedb.com/docs/clients/rust/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/).** Row callbacks fire per transaction update. In the 2.14.1 SDK source:
  - other clients' transactions arrive as `Event::Transaction`, with no timestamp or offset (`spacetimedb-sdk-2.14.1/src/event.rs`);
  - `advance_one_message` processes one server message and fires all its callbacks before returning (`db_connection.rs`).

  The relay's set-then-state rule rests on this, and so does naming transactions by the `clock` row.
- **Confirmed reads.** `with_confirmed_reads` (`db_connection.rs`): the server sends results only once they are durable, at the server's default when unset, as here. This is part of the "tick start → client" age above.
- **The owner reads private tables.** `owner_permissions` (docs/PERCEPTION.md), so the relay's trusted subscription needs no new visibility.
- **[Event tables](https://spacetimedb.com/docs/tables/event-tables/).** `relay_event` rows exist only for their transaction and are still logged. Subscribers get inserts. Event tables cannot be read by views (not needed here).
- **One executor and single-threaded subscription evaluation per database** (VIEWER_FLOOR §5, BATTLE_DELIVERY_PATHS §4). That is why delivery off the thread was worth measuring at all.

## 5. The Spark's answers (BATTLE_DELIVERY_PATHS §6)

1. **X925 at L0** on current main (0 and 16 viewers, three runs each, pinned): being measured by the Spark, behind its heed-e4 arenas. Not yet in.
2. **Floors and zones:** nothing new since FLOORS.md on the multi-database side. No tower or transit database exists, IDC latency has never been measured, and nobody has met the outbox limit. So BATTLE_DELIVERY_PATHS' "IDC delivery databases lose" rests on its reading of the 2.14.1 source alone.
3. **Minds and heed:** each character's attended set lives in module memory, rebuilt from rows (the heed tables `heed_policy`, `attend_pick`, `attend_effect`, `seen_throng`). Minds get it through the scene the authority writes. Leaving minds as they are fits the relay. The relay needs players' sets as an authority-written table (here `perceived`), whose writes belong in the authority's cost; they are in it.
4. **SpacetimeDB after 2.14.1:** not tried on the Spark.

## 6. What was not measured

- **Stage 2** (sight and heed off the authority). Its 1.1 ms/s per viewer is an estimate from §3.2's shares. It is the next measurement (the recommendation above).
- **A real game client on the relay.** The relay clients here are load clients.
- **Today's frame policy in the relay** (tiers, intervals, budgets). The prototype sends every attended change at once, so its bytes and CPU are an upper end for a policy that coalesces.
- **X925.** The 10 Hz figures apply X925's measured −17% (COMBAT_PHASE Part B) to dev-box.
- **The host power-state effect on E2's numbers** (ATTENTION_E2_COST). Its 16-viewer per-viewer figures share VIEWER_FLOOR's bias. Its saturated 216 arms were reported per tick and labelled as such.
- **Memory growth over hours.** Runs are 80 s windows.

## Evidence

- **Code:** branch `relay-proto` (`fc1af9d77` and the harness commits after it): the authority switch, `relay_event`, `living/tools/relay_proto`, `battle_viewers.py --relay`.
  - Module `rp-cullet` `707591346519` (series m2 onward; `1b13084395cf` before the fix).
  - Main's module for the off-equals-main check: `cde8d300c340` (`a6375a70e`).
- **Runs:** dev-box, worktree `t3-b749c655`, `.local/rp/`:
  - `runs/` holds every run: `battle-viewers.json`, `v<n>/metrics.json`, `threads.json`, `relay.json`, `clients.json`, `clients.json.items`, `checker.log`, `relay-ids.json`, `procs-*.txt`;
  - `runs/series.log` holds module hash, commit, dirty count and load per run;
  - `superseded/` holds series m's relay arms;
  - `tables.json` (`rp_tables.py`) and `privacy.py`;
  - the series scripts (`series-*.sh`), `poller.py` and `det.sh`, with `det-off/` and `det-negative/`.
- **Archived** to `~/archive/worktree-evidence-20261122/relay-proto.tar.zst` on the dev-box (63 MB, sha256 `7d69a94fce788b50…`, in full in the `.sha256` beside it; the build tree left out).
- **Related:**
  - [BATTLE_DELIVERY_PATHS.md](BATTLE_DELIVERY_PATHS.md) (the design this tests; its §6 now points here);
  - [VIEWER_FLOOR.md](VIEWER_FLOOR.md) (now carries the §2.3 correction);
  - [PERCEPTION.md](PERCEPTION.md);
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md).
