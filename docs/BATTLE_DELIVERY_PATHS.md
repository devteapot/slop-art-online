# Battle delivery paths: what could bring a dense battle to 216 viewers at 60 Hz

Status: **design study**, 2026-11-22, dev-box. Nothing is built. Its ground is [VIEWER_FLOOR.md](VIEWER_FLOOR.md): measured per-viewer parts, measured on dev-box, plus the SpacetimeDB 2.14.1 source. It also reads the versioned source of every release since 2.14.1 (§4). Where a number is not measured, it says so.

## Recommendation

**Build our own delivery relay, in two stages. Make the AI's 10 Hz combat cadence the owner's decision that goes with it.**

- **Stage 1: a delivery relay.**
  - **What it is:** a Rust service we own, like the mind service.
  - **What stays on the authority:** sight, the attended choice (`heed`), each viewer's perceived and attended set, projections, every reducer and all knowledge.
  - **What the relay does:**
    - subscribes, as one privileged connection, to the truth tables the frames read today;
    - fans out to each player only what that player's authority-written set allows: motion, fighter and doing copies, cues, the fight feed and hearing.
  - **What it costs the authority:** per viewer, about **1.2 ms/s** at the contract's density (estimate, from VIEWER_FLOOR's measured parts; §2.4), against 2.41 today with every plausible cut. The relay's own feed is a per-battle cost, not a per-viewer one, **measured at about 2 ms/s of subscription evaluation for the whole battle** (§2.4).
  - **What fits at 60 Hz:**
    - about **185 viewers** on dev-box with today's 15 Hz fighters;
    - about **230–240** with 10 Hz fighters, on dev-box or the Spark's X925 cores.
  - **So 216 fits with the relay and the 10 Hz cadence together,** and with neither alone.
- **Stage 2, only if stage 1's measurement falls short: perception compute beside the authority.** Sight and the attended choice, computed by the same rules crate from the same truth, would run beside the authority. The authority commits the result as trusted input and stays the only writer of the perceived set. This would cut the authority's per-viewer cost to about 0.65 ms/s (about 340 viewers), but it moves rule evaluation out of the reducer thread. That is close to the principle that rules stay authoritative in the authority, so it is **the owner's call**, not a default.

**Why the others lose:**

| Path | What it gives | Why it loses |
|---|---|---|
| A battle split across databases (zones) | nothing for one battle's viewers | every viewer is in the same locality, and every blow crosses a seam (§3) |
| Delivery databases fed by inter-database calls | the relay's gain, built from SpacetimeDB parts | adds commitlog-durability latency to every delivered change, and outbox rows that cannot be deleted grow without bound (§3.2) |
| A newer SpacetimeDB (2.15.0–2.16.1, and master to 2026-11-21) | nothing for this problem | no incremental views, no multi-threaded execution, no cheaper row-level-security fan-out (§4) |
| Cuts within 2.14.1 alone | about 140–185 viewers | tops out below 216 even with the owner's hearing buckets and 10 Hz fighters (§5) |

## 1. The target, the budget and what stays fixed

- **Requirement:** a dense 200-fighter battle with 216 player viewers at 60 Hz. Latency:
  - server receipt to committed outcome ≤50 ms p95;
  - client input to outcome received ≤150 ms p95 at 80 ms round trip ([PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md)).
  - All delivery costs count, including any process we add, within the reference envelope of 16 vCPUs and 64 GB.
- **Budget:** the whole tick at most 600 ms/s of the database thread (docs/COMBAT_PHASE.md "Budget"). The battle without viewers takes R = 377.6 ms/s on dev-box and about 338 on X925 (VIEWER_FLOOR §6). Per viewer at 216 that leaves:
  - **1.03 ms/s** on dev-box;
  - **1.33** with 10 Hz fighters (estimate);
  - **1.05 and 1.27** in dev-box terms on X925.
- **Today, measured** (VIEWER_FLOOR §7, contract density, uninstrumented): **2.41 ms/s** a viewer with every plausible cut, attention at 16 and the game's own views. About 92 viewers fit.
- **Fixed by AGENTS.md and docs/PERCEPTION.md:**
  - **Perception is enforced by the authority.** A spatial subscription is not a permission boundary.
  - **Three separate paths:** current perception, remembered knowledge (`my_experience`, places, know-how) and audit truth (private tables, read by the owner: the mind service, the observer).
  - **Rules stay authoritative in the authority,** with no second approximate simulator.
  - **External inference stays in the mind service.**
  - **We build our own tools,** not an outside service.

### 1.1 What a viewer costs today, by where the work could go

Contract density, uninstrumented, ms/s per viewer. The split is VIEWER_FLOOR's: set d's totals with the 216-viewer L1 shares. Each part is sorted by whether it has to stay on the authority.

| Part | ms/s | Must stay on the authority? |
|---|---:|---|
| Sight (the one sight rule over the gathered candidates) | ≈0.2 | **Yes.** Sight decides what the character perceives, learns and may act on. Delivery may not decide it. |
| The attended choice (`heed`: features and rules over those in sight, 5 Hz) | ≈0.25–0.4 | **Yes.** Attention is perception. The choice could run off the thread only as trusted compute whose result the authority commits (stage 2). |
| Writing the perceived and attended set (inserts and deletes as the set changes) | ≈0.05–0.1 | **Yes.** This is the permission record the relay reads. |
| Projections (names and labels as the viewer knows them) | ≈0.05–0.1 | **Yes.** They depend on the viewer's knowledge. Written on change only. |
| Hearing (rows per heard creature) | ≈0.1 at 1 Hz | No: who is out of sight is decided by the sight set. The bearing, band and counts can be worked out from positions. |
| Frames: motion, fighter and doing copies; cues; the copies' subscription evaluation | ≈0.5–1.1 (most of the attended's 1.07) | No: pure fan-out of truth rows within the set |
| The fight feed (`combat::show` and its rows) | ≈0.2–0.7 | No: fan-out of fight events, filtered by the set |
| `my_experience` and `heard_sounds` views | ≈0.1–0.2 | Lines are knowledge and are written by the authority. Their delivery could move. |
| The viewer as a character (its fold lines, evaluations, body, acts) | ≈0.42 | **Yes.** It is the AI tick's per-character cost. |
| Its own input (`human_move` at about 0.2–0.3 ms each) | ≈0.15 at the harness rate | **Yes.** Reducers are the authority. |

## 2. Path 1: delivery off the database thread (our own relay)

### 2.1 The shape

```
  player client ──(reducers: moves, skills, talk; own rows: my_vitals, my_body, lines)──> authority (SpacetimeDB)
       ▲                                                                                     │
       │ per-viewer stream (websocket, BSATN):                                               │ one privileged subscription:
       │ copies, cues, feed, hearing, tagged with the authority's tx offset                  │ truth tables + perceived/attended sets
       └─────────────────────────── living-relay (Rust, ours) <──────────────────────────────┘
```

- **The relay's one feed.** The relay connects with an identity the authority allow-lists (as the mind service is). It subscribes once to:
  - the truth delivery tables: `body` (motion segments), `fighter`, `doing`, health bands, and a world-level fight-event stream;
  - each viewer's authority-written **perceived and attended set** (today's `perceived`, with the tier and the attended flag), its projections, and E2's crowd rows if crowds are kept.
- **The relay's job.** It keeps that state in memory and runs today's frame logic for each viewer, in Rust:
  - the near and far tiers;
  - the cue rules;
  - the frame interval by scene size;
  - the fight feed;
  - hearing.

  It sends each player only the rows of creatures in that player's set.
- **What the authority stops doing** (behind a law, off by default, so it can be measured and switched back):
  - writing per-viewer copies, cues and the feed;
  - working out hearing rows;
  - re-running `heard_sounds`.

  It keeps sweeping sight, choosing the attended set, writing that set and projections, and everything else.

### 2.2 Perception stays enforced by the authority

- **The permission is the authority's row.** The relay sends viewer V a fact about creature C only while (V, C) is in V's authority-written set, as of the authority transaction the fact comes from.
- **Order is the subscription's order.** In 2.14.1 a client's subscription updates arrive per committed transaction, in commit order (one connection, one stream). So the relay applies the set and the state changes of each transaction together, and a fact from transaction t is never sent under a set from transaction t′ < t. When C leaves V's set, its "gone" is sent in the same relay frame that would have carried C's next change.
- **The relay is trusted like the mind service, and no further.** It reads private truth tables, which audit truth already is for the owner's services (docs/PERCEPTION.md).
  - It never writes game state.
  - It never decides perception.
  - It holds no remembered knowledge: lines stay the authority's `line_seen` and `experience`, read by the client from the authority.
- **The privacy proof moves with the work.** verify-client's privacy checks today prove that a copy or cue reaches only its viewer (`cues.py`, `copy_privacy`). A relay needs the same proofs against the relay's stream: another player, an anonymous connection and a forged identity receive nothing. That would be a new verification surface, `verify-relay`.
- **Authentication.** The relay accepts a client's SpacetimeDB token and verifies it as the authority does: the host's signing key, with the identity derived from `iss` and `sub`. That identity is one per host (docs/FLOORS.md, "Identities and tokens", verified in 2.14.1 source). The relay then maps it to the viewer's character through the authority's `player` table, which it subscribes to.

### 2.3 Latency, failure, reconnect and ordering

- **Latency.**
  - Today an update reaches a client after the tick commits, through subscription evaluation and the send worker.
  - With the relay it takes one more hop on the same host: the relay receives the update (sub-millisecond on loopback, plus decoding), runs its frame or cue step and sends.
  - **Estimate:** +1–3 ms at p50 and +5–10 ms at p99, with cues sent at once and frames on their interval as today.
  - Against the contract's 150 ms input-to-outcome budget at 80 ms round trip, that is small. Measured: nothing yet. The first prototype must measure it (§2.6).
- **The relay lags.** The relay stamps every frame with the authority transaction offset it reflects. If it falls behind (offset lag above, say, 100 ms), it coalesces: it skips frames for far tiers, keeps cues and attended creatures, and reports the lag. It never sends a fact outside the set it has applied, whatever its lag.
- **The relay dies.**
  - The authority is unaffected: it does not wait on the relay.
  - Clients keep their authority connection (inputs, own rows, lines) and lose others' motion until a relay is back. The client then shows its last state frozen and greyed, as on a dropped connection today.
  - A relay restarts from the authority's subscription snapshot (the initial update), so it holds no durable state of its own.
  - Two relays can run (half the viewers each, or a standby). Neither needs coordination: each reads the same authority.
- **Reconnect.** A client that reconnects to a relay gets a full frame of its set, as a first frame does today (`v.full`).
- **Ordering against the client's own rows.**
  - The client gets its own rows from the authority and others' from the relay. Both carry the authority's transaction offset: SpacetimeDB's transaction updates do, and the relay copies the offset.
  - The client applies relay frames no older than the authority offset it has already seen for its own state. Where they interleave (a blow on me and the attacker's windup), it shows the later.
  - **Where order matters for play:** the attacker's windup reaches the target from the relay; the target's own hurt comes from the authority. Today both come from the authority in one transaction update. With the relay they can arrive out of order by the relay's hop. The client must tolerate a windup arriving a few ms after the hurt. It already tolerates extrapolation and cue staleness.
- **How the client consumes it.**
  - A second connection, to the relay's websocket, with a stream format we own: BSATN rows of today's copy and cue types, so the client's `Scene` code keeps its shape.
  - Today's `seen_*` copies and cues become relay messages.
  - The client's subscription to the authority shrinks to its own state, lines, static tables and windows.

### 2.4 What it costs, with the arithmetic

**The authority, per viewer** (contract density; ms/s; estimates built from VIEWER_FLOOR's measured parts):

| Stays on the authority | ms/s |
|---|---:|
| Sight, setup and gather | 0.20–0.35 |
| The attended choice (`heed` at 5 Hz over about 70 in sight; E2: 0.39 ms/s over 119 at L2) | 0.25–0.40 |
| Writing the set and its projections (about 10 set writes a viewer-second at the probe's 6–14 µs a row) | 0.05–0.10 |
| The viewer as a character | 0.42 |
| Its input (harness rate) | 0.15 |
| **Total** | **≈1.1–1.4, central 1.2** |

**The relay's feed, a per-battle cost on the authority:** **measured.** One privileged subscriber held `body`, `fighter`, `doing`, `vitals`, `character`, `fight_seen` and `skill_use` through the 200-fighter battle, with 0 viewers, uninstrumented, 2 runs against 2 without it (`battle_viewers.py --relay-sub`, `series-r.sh`).
- It received about **2,525 rows a second (210 kB/s)**.
- It cost **1.9 ms/s** of subscription evaluation on the database thread (`txn_type="Update"`: 2.37–2.46 against 0.47–0.48).
- The send threads took about +5 ms/s.
- The database thread's total moved +6.5 ms/s (372.8–376.1 against 376.3–385.6), within the 0-viewer arm's run-to-run spread.

So the feed is about 2–7 ms/s for the battle, independent of the viewer count. The fight-event stream the relay would also need (a world-level table in place of `fight_seen`) is not in this figure.

**Viewers that fit:** N = (B − feed) / f, with f = 1.2 (1.1–1.4):

| Host | B | N (central) | N (range) |
|---|---:|---:|---:|
| dev-box, 15 Hz fighters | 222 | **≈185** | 160–200 |
| dev-box, 10 Hz fighters (estimate) | ≈287 | **≈235** | 205–260 |
| X925, 15 Hz (×1.16 per viewer) | 262 | ≈188 | 160–205 |
| X925, 10 Hz (measured R 283) | 317 | **≈228** | 195–250 |

**The relay itself.** It runs today's delivery work outside the database thread: about 1.2–2 ms/s a viewer of CPU in Rust, likely less than in WASM. At 216 viewers that is 260–430 ms/s, under half a core. The work splits by viewer across threads. Bandwidth is unchanged from today: the same rows to the same clients.

### 2.5 Build size, risks, and what changes for players and minds

- **Build size: large.**
  - The relay service (subscription client, per-viewer state, the frame and cue scheduler moved from `frame.rs`, the feed and hearing, a websocket server, token verification): a few thousand lines.
  - The authority: a law to stop per-viewer copies, cues and feed, and a world-level fight-event table.
  - The game client: a second connection, and its scene fed from it.
  - Tools: gate-load and `battle_viewers.py` learn the relay.
  - A new verification surface, `verify-relay`.
- **Risks:**
  - **Privacy.** A relay bug leaks. That is why the set-and-state ordering rule (§2.2) and the `verify-relay` privacy proofs are first-class.
  - **A second process per world** to run, watch and restart.
  - **The cross-stream order** of windups and hurts.
  - **The 1.2 ms/s is an estimate.** The authority's remaining per-viewer work (sight, `heed`, the character) is the measured floor's least-understood part at contract density.
- **For players:** nothing in what they perceive or may do, if built right; one more connection; possibly a few ms of latency.
- **For minds:** nothing. Minds read scenes from the authority (`Sensing`, `scene_json`) and never use frames.

### 2.6 The first measurement before committing to the build

A prototype behind a law, on the attention-e2 or viewer-floor line, never for main:
- the authority skips copies, cues and the feed;
- a small relay subscribes and counts, without sending to clients.

Run it on VIEWER_FLOOR's set d fixture, 64 viewers, L0. That measures the authority's remaining per-viewer cost (the 1.2 above) and the relay's feed (§2.4) directly, before any client work.

## 3. Path 2: a battle split across databases

### 3.1 Zones within a floor (docs/FLOORS.md, "Zones within a floor")

- **The design:** the same module, one database per zone. Bodies are owned by one zone. A neighbour holds read-only ghosts in an overlap band, sent by inter-database calls (IDC: SpacetimeDB 2.14.1's outbox tables, exactly once, delivered after the sending transaction is durable). Actions on a ghost are routed to its owner. Crossing a border is a ticketed handoff.
- **What it would give:** each zone's tick on its own executor, in parallel (verified in 2.14.1: `module_host.rs`, one executor per database).
- **Why it does not help this battle.** A dense battle is one locality.
  - **All its viewers stand round it.** Splitting by position puts nearly all 216 viewers, and all 200 fighters, in the zone that holds the fight. The others are idle.
  - **Splitting the fight itself** puts every blow across the seam: an IDC call, resolved a few ms later by the owner zone, with a conflict rule for dodges.
  - **Every ghost must be delivered** to the viewers of both zones.
  - FLOORS itself concludes the 200-character battle "should stay inside one zone".
- **What breaks.**
  - Two-party transactions such as trades need a two-phase protocol.
  - Records and knowledge span two commit logs, and causal evidence needs ticket ids across them.
  - Minds need a connection to every zone.
  - Verification needs a two-zone surface.
- **Confidence: design reading.** No IDC latency has been measured on this project (asked of the Spark).

### 3.2 Splitting viewers, not the battle: delivery databases

- **The shape.** The battle stays one authority database. K delivery databases, each serving about 216/K viewers, get each tick's changes from the authority by IDC and run today's frame logic for their viewers. The authority still decides each viewer's set and sends it along. This is the relay of §2, built from SpacetimeDB parts.
- **What it gives:**
  - the same authority saving as the relay, about 1.2 ms/s a viewer;
  - delivery spread over K executors;
  - clients keep using the SDK, with a second connection to their delivery database.
- **Why it loses to the relay:**
  - **Latency.** IDC calls the receiver only after the sending transaction is durable (2.14.1 source, `idc_actor.rs`, read for FLOORS). Every delivered change waits for a commit-log flush, which is not measured here. FLOORS estimates 1–5 ms each way on one host.
  - **Growth.** An outbox row cannot be updated or deleted (2.14.1, FLOORS). A battle sending one batch row per delivery database per tick writes 60 × K rows a second that stay: about 240 a second at K = 4, every row carrying a tick's changes. That is unbounded table and log growth, which the performance contract's retention rules forbid without a pruning answer 2.14.1 does not give.
  - **Every IDC call** runs the receiver's `client_connected` and `client_disconnected` around it (FLOORS).
  - **Each delivery database keeps its own copy of the battle's state.** That is K times the write traffic of the authority's body changes.
- **Confidence: design reading** of the 2.14.1 IDC limits; costs not measured.

## 4. Path 3: a newer SpacetimeDB

Read in versioned source, not announcements: every commit from `v2.14.1` (2026-11-02) through `v2.15.0` (11-06), `v2.16.0` (11-18), `v2.16.1` (11-19) and master to `c0f3122f5` (11-21; 2.16.2 bumped, unreleased). That is 52 commits to v2.16.1 and 11 more on master.

| What we would want | In 2.15.0–2.16.1 and master | Evidence |
|---|---|---|
| Incremental views | **No.** Procedural views are still re-run whole. Query-builder (`RawSql`) views record a whole-table read for every table they read, so they re-run on any change to those tables. The source says so: "TODO(jsdt): This means we will rerun the view and query for any change to these tables, so we should optimize this asap" (`module_host_actor.rs:232` at v2.16.1 and master). The docs' "can be updated incrementally" (views page, also at v2.16.1) is not what the code does. | source at each tag |
| Multi-threaded execution of one database | **No.** One executor per database. Subscription evaluation is still `eval_updates_sequential` ("we removed rayon and switched to a single-threaded execution"). | `module_subscription_manager.rs` at v2.16.1 |
| Cheaper row-level-security fan-out | **No change.** It is already pruned by search arguments in 2.14.1 (VIEWER_FLOOR §5). The subscription code changed by 14 and 13 lines (`module_subscription_manager.rs`, `tx.rs`). | `git diff v2.14.1 v2.16.1` |
| What did change | tiered storage (#6304, #6305: pages and blobs to S3-like tiers); an `outbox!` macro for IDC (#6460, ergonomics only); Nagle disabled in the Rust SDK (#6552, may lower small-message latency for clients); procedures interrupted on pause (#6537); the Rust receiver bindings' root renamed to `mod.rs` (#6593); a TypeScript cache speed-up (#6416, #6614). | commit log |

**What an upgrade would buy for this problem:** nothing. Its migration risk is real, though bounded:
- module API and bindings layout (#6593: our generated bindings and `just living-generate` change);
- the pinned image (`clockworklabs/spacetime:v2.14.1` in compose, every scratch-server script and `det_compare`);
- wasm identity and fuel across builds (docs/WASM_XARCH.md: never compare across dependency changes);
- the scene gate's red-on-main list.

**Separately worth a look:** the Rust SDK's Nagle fix (#6552), for the game client's small input messages. That is a client-latency question, not this one.

## 5. Path 4: cheaper delivery within 2.14.1

From 2.41 ms/s a viewer (contract density, plausible cuts, attention 16, game views), each step's effect and its confidence:

| Step | Effect, ms/s a viewer | Confidence | Changes for players or minds |
|---|---:|---|---|
| The fight feed trimmed to the attended and to blows on the viewer (its bound is measured: feed off) | in the plausible cuts already; a trimmed feed costs a little more than off | bounded | onlookers see fights only among those they attend; the crowd's fights come through crowd rows |
| Lines as a keyed table with a `viewer = :sender` rule, in place of the `my_experience` view (about 5 writes a viewer-second at 6–14 µs) | −0.05 to −0.08 (contract density), −0.35 (dense) | bounded (probe and set e) | none |
| **Hearing as buckets per bearing and band** (counts by kind, written on change; `heard_sounds` goes) — **the owner's call** | −0.1 to −0.15 (contract density), −0.4 to −0.6 (dense) | bounded (VIEWER_FLOOR §4) | an unseen creature becomes a count in a direction, not an individual with a key |
| The attended cost halved (v2's planned per-individual work: fewer rows per attended, cues only for the engaged) | −0.5 | estimate (E2: the first 8 attended cost about 190 µs/s each, later ones about 65) | none intended |
| Frames' per-tick bookkeeping only when a viewer's scene changed | −0.05 to −0.1 | estimate | none |
| The keep-alive (harness) | −0.16 | measured; real input costs about the same at 0.5–1 move a second | – |
| **Result** | **≈1.5–1.6** | estimate | |
| **Viewers at 60 Hz** | dev-box ≈140; dev-box with 10 Hz fighters ≈180; X925 with 10 Hz fighters ≈175 | | |

**Even with every step, including the owner's hearing buckets and 10 Hz fighters, about 180 is the reach.** That falls short of 216 because 1.1–1.2 ms/s a viewer of irreducible authority work remains: sight, `heed`, the character, input. On one thread, that alone allows about 185 (dev-box) to 240 (10 Hz). Every step here is still worth doing, inside or under the relay: the relay inherits the cheaper feed, lines and hearing.

## 6. Questions sent to the Spark (through the coordinator)

1. X925 at L0 on a recent build: the 0-viewer sustained battle, and per viewer at 16 viewers.
2. Floors and zones: anything built since FLOORS.md, IDC latency measured, outbox growth met.
3. Minds and attention: whether the attention design expects minds' attended sets in authority tables (the relay leaves minds as they are).
4. Any SpacetimeDB release after 2.14.1 tried, and breakage met.

**Answers: pending** when this note was written. Nothing above depends on them. The X925 figures are VIEWER_FLOOR's scaling, and §3's IDC limits are FLOORS' readings of the 2.14.1 source.

## 7. What this study did not do

- **No relay, delivery database or zone was built.** The relay's authority cost (1.2 ms/s a viewer) is an estimate from measured parts. §2.6 gives the measurement that would replace it.
- **No IDC latency or throughput** was measured.
- **The 10 Hz fighters' effect on dev-box** is X925's measured −17% applied to dev-box's reference. Their behavioural cost (docs/COMBAT_PHASE.md, Part B) is an owner's decision.
- **Stage 2 (perception compute beside the authority)** is sketched, not designed.

## Evidence

- **Per-viewer parts and budgets:** [VIEWER_FLOOR.md](VIEWER_FLOOR.md), branch `viewer-floor`, evidence `~/archive/worktree-evidence-20261122/viewer-floor.tar.zst` on the dev-box.
- **SpacetimeDB source:** a blobless clone of `clockworklabs/SpacetimeDB`; tags `v2.14.1`, `v2.15.0`, `v2.16.0`, `v2.16.1` and master `c0f3122f5`; read only.
- **FLOORS (2.14.1 IDC, executors, identities):** [FLOORS.md](FLOORS.md).
- **Contract:** [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md).
- **Perception and privacy:** [PERCEPTION.md](PERCEPTION.md).
- **The relay-feed measurement:**
  - run directories `.local/vf/runs/r0-L0-rel-base-r{1,2}` and `r0-L0-relay-r{1,2}` on the dev-box worktree `t3-b749c655`;
  - module `vf-cullet` `0b1d6e741f80`;
  - `battle_viewers.py --relay-sub` on branch `viewer-floor` (`60c473e46`);
  - archived at `~/archive/worktree-evidence-20261122/battle-delivery.tar.zst` on the dev-box (sha256 `75c9df2a64cfa12a…`).
