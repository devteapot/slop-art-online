# Battle scale: familiarity, novelty, bystanders' wakes, folded fight lines

What lets a dense battle of minded characters keep its tick (docs/BATTLE_SCALE.md: fixes 1–3, `battle-scale`; fix 4, `battle-fold`). For fixes 1–3, nothing a character sees or is told changes, only when the work is done. Fix 4 changes how onlookers are told: one folded line a window holding every blow they saw, more than the fight's first blow they were told before.

## What it does (user POV)

- **Familiarity forgets by age only, never what is in view** (fix 1; `brain.rs`):
  - The limit is the `familiar_limit` law (familiar-cap, value-only; 2,048 rows a character as shipped, not 256). Over it, `prune_familiar` removes the oldest rows by `last_ms`.
  - It never removes a row touched within `FAMILIAR_KEEP_MS` (60 s), nor one whose thing is in the character's seen set within `SEEN_MS` (90 s).
  - The check runs every `familiar_limit / 32` new rows of that character (8 to 64; 64 as shipped).
  - With the `familiar_regard` law (off as shipped): unnamed strangers go first, the oldest first, then places and things; never someone the character knows by name (family, community, an introduction) or has a `relation` or `relation_fight` row about. Their `sex_seen` pairs go with them. A forgotten stranger seen again is a first sight again; a cue on one is refused "you do not remember seeing #N" (law off: "you have never seen #N"). A dead creature's `familiar` rows go for everyone when its remains are gone, by the index on `familiar.thing` (at its death when it leaves none). `scenes.py familiar_regard` (default seed, about 5 min).
  - What a minded observer remembers of a person's body (`sex_seen`) goes with the remains (growth-fix-2): `scenes.py sex_seen_bound` (default seed, about 3 min).
  - The recently-seen fast path is a per-character set (`SEEN`, thread-local) sized to what it saw. It used to be a 96-entry list on `mind_state`, which thrashed and was rewritten at every evaluation; the row's `seen` stays empty now.
- **Novelty once a second** (fix 2): `noticed()` runs at most once per `NOTICE_MS` (900 ms, a little under the 1 Hz slot) per character, not at every woken or combat-cadence evaluation. Cues keep their own interval (`cue_check_s`). A crowd's first sights are told a few to a line (`FIRST_SIGHTS_PER_LINE`) at each look.
- **Bystanders' wakes** (fix 3; the `witness_wake_ms` law, default 500; 0 means woken by each sight, as before):
  - A witnessed event's percept is written at once and in full to every onlooker (`perceive::witnessed`, `witnessed_shot` → `percept_seen`).
  - A party to it (its subject, or the one it was done to or aimed at) is woken at once.
  - A bystander is woken at most once per `witness_wake_ms` (`common::wake_bystander`). A wake held back is delivered when its window ends (`due_bystander_wakes`, each tick before the wakes).
  - A remains noticed is a bystander's sight too.
- **Folded fight lines** (fix 4; `fold.rs`, `living_rules::fold`; the `witness_fold_ms` law, default 2,000; 0 means each fight's first blow told at once on its own line, as before):
  - Each blow (landed, blocked, dodged, missed) is written once to a private `fight_seen` row with everyone who could see it under `witnessed`'s sight test (facing and walls included), the two in it excepted.
  - Each onlooker gets one `fight` line per window, ending at its own phase: who struck whom in the order each pair was first seen, how many blows and how each ended, and who fell ("A stranger (#412) attacked Grim: 3 blows (2 landed, 1 blocked), and Grim fell."). A mind's line anchors each one it cannot name by its scene id (a far figure by its handle); a player's reads as the screen shows it.
  - A blow at or by the onlooker is not folded: its own lines come at once, as before. A death is still told at once on its own line too.
  - A fight's first landed blow wakes its onlookers as bystanders when it lands (as its line did); the folded line wakes no one.
  - Pending blows are rows, not module memory (SpacetimeDB keeps no module state between calls); a row goes once every onlooker's window holding it is told.
- **The fighters' cheaper paths** (battle-cheap; docs/BATTLE_SCALE.md "The cheaper paths as built"):
  - **A move's check before it starts** is given only the fields its plan reads (`check_ctx_plan`; `act::checked`, `Reads`). The roll is drawn either way.
  - **The body's alarms** are kept per character until a fact `status_of` reads can change (`alarm_cells`; `brain::alarm_statuses`, `BodyFacts::next_change_ms`). The law's shared memo is keyed by those facts alone (`Scripts::status_reads`).
  - **Warmth** visits only what warms or shelters, in place (`common::chunk_warming`).
  - Each has a diagnostic `_check` law that also works the answer out the old way and counts differences.
- **The body's statuses by their parts** (status-parts; the `status_parts` law, on; `status_parts_check` a diagnostic; docs/STATUS_PARTS.md):
  - The shipped `status_of` is the join of eight parts (`status_parts()`: hunger, energy, health, cold, combat, breath, slowed, mending). `Scripts::status_of` keeps each part's answer on what that part reads and runs a part only when its inputs are new (`living_rules::script::body`, `Part`, `Parts`), giving the same joined `Rc` for the same answers.
  - An alarm cell holds the way it was asked (`AlarmCell::way`), and expires on the active way's reads (`Scripts::status_reads_as`).
  - `status_parts_check` asks the whole law with the whole body at every ask by the parts and counts `status_parts:checked`, `status_parts:differed` and, while profiling, `status_parts:has:<status>` (the statuses the compared asks gave). Off, `status_parts` asks the law whole (`eval:status_run`, `eval:status_memo`); on, `eval:status_parts_asked`, `eval:status_parts_joined`, `eval:status_part_memo`, `eval:status_part_run` and `eval:status_part_run:<i>` by the part's place.
- **The lazy scene** (scene-lazy; the `scene_lazy` law, on; `scene_lazy_check` a diagnostic):
  - A graph's scene is what the body senses (`perception::Sensing`): every creature within gathering range, nearest first, each tested for sight only when a reader comes to it.
  - The nearest pick (`Ev::first_seen`) and a creature looked up by id (`Ev::seen_by_id`: `visible_creature`, the `threatened` condition by facing) test only as far as their answer needs. Readers of the whole list (`Ev::creatures`: desires, `count`, `doing`, cues, noticing, the stranger filter) test every one.
  - Resources and the heard list are gathered when first asked for. The nearest pick reads the list in place, not a copy.
  - Since ai-trims (docs/COMBAT_PHASE.md, "Step 3 results"), the candidates are put in order only as far as a reader goes: a min-heap on `common::nearest_key` (the distance as `f32::total_cmp` orders it, then the gathered place), which pops exactly the stable sort's order. `perception::sensed` (the `scene_lazy_check` reference) still sorts all at once through `common::creatures_near` (`Sensing::sorted`).
- **The AI trims** (ai-trims; docs/COMBAT_PHASE.md, "Step 3 results"), each exact, none behind a law of its own:
  - A move's check before it starts builds only the target fields its plan reads (what the target knows and carries, its body sex, its distance, what it does, its stage), with one read of the actor's body (`act::target_facts_reading`, `facts_at`); a move's start does the same for its check and windup (`Reads::of_start`; a paced skill's genes and practice too), compared with the whole context under `check_ctx_check`.
  - A needs recompute gives the `rates` law the fields it reads, and the genes its answer is finished with (`act::rates_facts`).
  - A graph leaf reads the body's activity once and hands it to `act::begin_with`; the end of an evaluation reads it once for `town::settle_with` and `perceive::slept_with`, which reads the character only when the body woke. The nearest pick reads the chosen character once.
  - A bystander's held-back wakes are delivered in id order (`due_bystander_wakes`): the map's own order is the hasher's, which on wasm32 comes from memory addresses and differed between builds.
  - Since battle-laws (docs/COMBAT_PHASE.md, "Wake order"), the delivery starts at the tick count modulo the number due and wraps round, so the lowest ids are not always evaluated first. The start depends on the tick alone. Under `det_clock` each tick with wakes due logs `det wakes tick=N due=[…] start=k`, and `det_compare.py` reports the due sets of both builds (`wakes`). A build compiled with `LIVING_DET_NOROTATE` starts at 0, the control.
- **Fighters' scheduling laws** (battle-laws, docs/COMBAT_PHASE.md "Part B", docs/BATTLE_LAWS.md §4; measured options for the owner, value-only (`ValueOnly::Delivery`: a row edit read at the next tick), at today's value as shipped):
  - `fighter_bystander_wakes` (on, as before; dev-box's (c) in docs/BATTLE_LAWS.md): off, a creature on the combat cadence (`mind_state.fast_until` at least one cadence ahead, `common::on_cadence`) is not woken as a bystander, neither at once nor when a held-back wake falls due; its next cadence evaluation sees what happened. Counted as `wake:fighter_left_to_cadence` while profiling. A party to an act is woken at once either way.
  - `combat_eval_hz` (15): creatures in a fight are evaluated every `round(60 / combat_eval_hz)` ticks, staggered by id (`Laws::combat_every_ticks`; 15 is every 4th tick, as before). Since fair-ties the class `id % every` holds a phase that a permutation drawn from the second (`tick / 60`) assigns (`tick::cadence_turn`), so no id difference leads the cadence; `LIVING_DET_NOCADENCETURN` at compile time keeps the fixed phases, the control (docs/COMBAT.md, "The combat cadence's order turns every second").
  - Both apply to every character on the cadence. A player's character in a fight runs its command or waiting graph on the same cadence; its skills (`use_skill`) start at once either way.
- **The sweep's memory across ticks** (battle-laws, the `sweep_keep_memory` and `sweep_keep_check` laws, diagnostics, off in play; `perception::HEARD_KEPT`, `VITALS_KEPT`): a player's sweep takes its `heard` rows and the creatures' vitals from module memory instead of the table. Cleared as `KEPT` is (a skipped or repeated tick, `sweep_now`, `forget`); heard rows read afresh every 150 sweeps, a vitals row after 60 ticks or when `health_moved` marks it. `sweep_keep_check` compares each kept value with the table and logs `sweep keep: heard_kept=… heard_differed=… health_kept=… health_differed=… health_band_differed=…` once a second.
- **The exact comparison across builds** (ai-trims; the `det_clock` and `det_stop` laws, diagnostics, off in play; `living/authority/src/det.rs`, `living/tools/det_compare.py`): under `det_clock` a tick's clock is the last tick's plus 1/60 s, its draws come from a generator seeded by the tick, housekeeping runs inside every 60th tick, and every tick logs a hash of each table (auto-increment ids by rank, since 2.14.1 skips sequences ahead at random per database load). `det_compare.py prepare` makes a paused battle world and copies the server's volume as a template; `run` copies it twice, publishes one build on each copy, runs both to `det_stop` and compares every tick's hashes and every table at the stop. Its control: a build with `LIVING_DET_PERTURB=<n>` (compile time) moves every hash map's keys and must still compare identical with itself.
- **Remains in sight** (`brain.rs`): a scene's structures are gathered only when an evaluation reads one (`Ev::structures`), so a fighter's 15 Hz evaluation does not copy every remains in sight; noticing checks durable ranges by block and copies structure details only when something is new.

## Driving it

On a launched default-seed run (`scenes.py <case> --run "$R"`):

- **`familiar_dense`** (about 5 minutes):
  - O stands among about 360 people (well over the old cap), placed within 7 m and standing still, for 150 s.
  - Checks: more than 256 familiarity rows; one row per person; each told as a first sight exactly once (no row forgotten while in view and made again).
- **`notice_rate`** (about 30 s):
  - Two fights among ten minded people.
  - Checks: during a 12 s profiled window, the noticing passes a second (the `diag:` counts) stay at most one per 0.9 s for each minded character, while evaluations run at least 1.3 times as often.
- **`witness_wake`** (about 1 minute):
  - B stands beside V and has appraised V; B's graph waves at V once V is hurt; V's graph waves once hurt.
  - Five decoy fights start in B's sight, then A strikes V.
  - Checks:
    - every fight is told to B at once, its line about A and V in the same transaction as V's hurt;
    - wakes were held back (`wake:deferred`);
    - B waves within `witness_wake_ms` plus 100 ms of the blow;
    - V, a party, within 100 ms.

- **`witness_fold`** (about 1.5 minutes):
  - O stands between two fights: A, with a spear, strikes V until V falls; C strikes D, who blocks.
  - Checks:
    - the blows O's lines count lie between the `fight_seen` rows naming O (read by polling, a lower bound) and the strikes the rules resolved (`skill_use` outcomes). When O is among every row read, they equal the strikes, landed and blocked;
    - V's fall is in O's lines once;
    - fewer lines than blows, at most one a window, the first within `witness_fold_ms` plus 100 ms of the first blow;
    - O is among most rows' onlookers, and neither of the two in a blow is;
    - D's own lines come at each blow, not folded;
    - with `witness_fold_ms` 0, O is told a first blow at once on its own line.
- **`cheap_check_ctx`, `cheap_alarms`, `cheap_warmth`** (about 1.5 minutes each; battle-cheap, the `check_ctx_plan` and `alarm_cells` laws, warmth in place):
  - 12 fighters on an open line, a campfire, a shelter and three dead among them, for 60 s, with the diagnostic laws `check_ctx_check`, `alarm_cells_check` and `warmth_check` on.
  - Each case asserts its own path from the `diag:` counts of its own window: many comparisons, none different. For the alarms, more answers kept than asked.
  - The counts are read from the server log's lines stamped after the case began.
- **`status_parts`** (about 2.5 minutes; run it last on its world: it moves the world's clock to its night and leaves the fixtures' bodies):
  - 8 minded fighters on an open line (strike, dodge or block, heal) and 8 bodies beside them set by admin fixtures (`admin_set_vitals` for health, owner SQL `UPDATE vitals` for hunger and energy): starving, very hungry and exhausted, hungry and spent, peckish and tired, fed and hurt, well rested and badly hurt, barely alive, hungry and tired. The world's clock is moved to its night (`verify.py sql`, which records the epoch) and rain set (`set_weather`), so those out in it are freezing and wasting.
  - 75 s with `status_parts_check` on, then 25 s with `status_parts` off.
  - Checks: at least 500 asks compared, none differed, no `status_parts of` error line; every one of the law's 23 statuses among the compared answers; part memo hits above part runs; with the law off, no ask by the parts and every ask answered whole.
  - Evidence: `status_parts-status-parts.json` (both windows' counts, the statuses met, the window stamps), `status_parts-fixtures.json`, `status_parts-after.json`.
- **`scene_lazy`** (about 2.5 minutes):
  - 12 fighters on an open line with `scene_lazy_check` on: 40 s with sight all round, 40 s by facing (`fov_on`), then 20 s with `scene_lazy` off.
  - Checks:
    - in both lazy windows a battle went on, and every lazy answer equalled the whole scene's (at least 200 compared, none differed);
    - by facing, creatures were looked up by id;
    - with the law off there were no lazy answers, and the battle went on.
  - Counts come from `diag:` lines stamped 2 s after profiling restarts (counts made while it was off are reported then).
- **The chronicle's repeat check read newest first** (battle-exact-2 E; the `chronicle_recent` law, on; `chronicle_recent_check` a diagnostic):
  - `common::chronicle` folds a line said again into its entry ("(×n)") when it is among the newest 40 entries of the last two minutes. It reads the last 1 s, 4 s, 16 s, then the whole two minutes, and stops at the first window holding 40 entries from before this tick.
  - Only entries before this tick count: a range read inside the tick's transaction gives this tick's rows apart from the committed ones (SpacetimeDB 2.14.1), so a narrow read short of 40 committed rows could pick one of them where the full read picks an older committed row. The first scene runs found exactly that (one of 68, then one of 460).
- **`chronicle_recent`** (about 2.5 minutes):
  - 16 people on an open line, each saying one of two short lines in turn; their graphs are reinstalled every 2 s (a say node speaks at most once per 45 s, an install clears it). `chronicle_recent_check` on: 60 s, then 30 s with `chronicle_recent` off.
  - Checks: lines were written and repeats folded; every newest-first read equalled the full read (at least 60 compared, none differed, no difference logged); both the narrow and the whole read were used; with the law off neither was, and lines were still written.
  - A difference's log line is saved beside the case's evidence (`<case>-differs.txt`).
- **Noticing read in place** (battle-exact-2 C1; the `notice_inplace` law, on; `notice_inplace_check` a diagnostic):
  - A look walks the chunks' structure lists in place (`common::for_structures_near`): those seen lately are re-marked, the rest marked and asked about nearest first, as the full pass does; the copied, sorted list is built only when something is new.
- **`notice_inplace`** (about 2 minutes):
  - 8 people walk back and forth along an open line while a builder puts up a shelter or a storage beside it every 3 s (each spot once: a tile beside a familiar one of its kind and owner is part of it and rightly not told). `notice_inplace_check` on: 45 s, then 20 s with `notice_inplace` off.
  - Checks: structures were put up and noticed; every in-place split equalled the full list's (at least 100 compared, none differed); the full list was built only for looks that found something new; with the law off there was no in-place look and new structures were still noticed.
- **A look checks only what is new since the last** (C2; the `notice_delta` law, on; `notice_delta_check` a diagnostic):
  - Each character a mind runs has a private `last_look` row: where its last look stood, its radius, the highest structure id in sight, when. A structure no newer than that and within that disc, seen again within 45 s, is passed over; every other is checked as `notice_inplace` checks it. Pruning spares structures within the last look's disc.
- **`notice_delta`** (about 2 minutes):
  - 8 people walk an open line among structures and four people's remains while a builder puts up a new one every 3 s; one walker is taken 120 m away for 50 s and brought back. `notice_delta_check` on: 50 s, then 20 s with `notice_delta` off.
  - Checks: structures put up and the remains noticed; looks incremental, passing over more structures than looks; every structure passed over familiar (at least 1,000 checked, none not); every walker has its `last_look` row; with the law off, nothing passed over and new structures still noticed.
  - A look comes about once a second, so a last look older than 45 s (a whole look) is a first look or one after a gap; the scene does not force one.
- `witness_wake` checks B's folded line holding the blow on V within `witness_fold_ms`; the `sight`, `fov` and facing duel scenes check who is told a fight (walls, facing) through the folded lines.

- **`seen_remains`** (fresh default-seed run):
  - Two observers learn the names of two of the 20 people before leaving the field. The bodies are staged while the observers are away.
  - With `seen_ranges_check` on, the first observer receives two named lines and one line counting 18 strangers. The counted experience has zero subject and object, salience 0.8, and the nearest body's position.
  - Leaving and returning produces no new lines. One new body and a new shelter each produce one line. Death removes the observer's private block rows.
  - With `seen_ranges` off, the second observer receives the same three lines and keeps 20 legacy familiarity rows. Turning it back on transfers those IDs to ranges without repeating the lines.
- **`seen_remains_gaze`** (fresh `--seed cullet` run, by day; cover, facing sight and gaze on as Cullet ships them):
  - Structures are taken within the observer's sight radius (`senses(a).sight`), which the gaze band scales: Near 0.6, Middle 1.0 of Cullet's 48 m by day, Far 1.3. Cover traces people only; it does not hide a structure from noticing, the scene or a player's public `structure` rows.
  - An observer in Near arrives at eleven strangers' bodies, six about 14 m away and five about 38 m away. It is told one counted line for the six. Changing to Middle brings the five within reach: one more counted line, counting only those five.
  - Near, Middle and Far again repeat no remains line, and the observer's `seen_structures` rows exist.

- **`det_compare.py`** (about 8 minutes a run on the slow cores; its own private server, never a shared one):
  - `prepare --container C --url U --volume V --wasm-dir D --template T --meta T.json --base BASE.wasm --ticks 3600`: a fresh Cullet battle (`spawn_battle` 200) paused with `det_clock` on, the volume copied to `T`.
  - `run --template T --meta T.json --wasm-dir D --base BASE.wasm --candidate CAND.wasm --ports P1,P2 [--tag x] [--stop N] --out DIR`: passes (exit 0, `"identical": true`) when every tick's hashes of 113 tables and every row at the stop agree. On ai-trims: the same build on both copies, the base against itself with moved hash keys, and each batch of trims against the base, 3,600 ticks each, all identical; two builds before the wake-order fix differed from the 76th tick (residents woken in another order).

The rules tests `attention_cues_are_the_world_s_laws` (the laws' defaults and descriptions), `alarm_cells_give_the_law_s_answer_at_every_moment` (a cell's answer is the law's at every millisecond of five fighters' rows) and `fold::tests` (the line's words, counts and order) and the authority's `fold::tests` (each blow in exactly one window per onlooker) cover the rest offline. `profile_detail` (a diagnostic law) times the parts of each evaluation while profiling. The scale evidence is `living/tools/battle_diag.py` (docs/BATTLE_SCALE.md).

Not covered here: a scripted scene for `fighter_bystander_wakes` off, `combat_eval_hz` or `sweep_keep_memory` (their exactness off is det_compare's, their effect on is in docs/COMBAT_PHASE.md "Part B" and "Next"), a missile's folded line (unit test only), a held-back wake delivered late in the scene (B's window may be free when A strikes; the bound holds either way), remains noticed once each in a long battle (`battle_diag.py`), and players' views (unchanged; verify-player `combat.py`).

## The sides battle fixture

`spawn_battle_sides(n, sides)` (an admin fixture, no game rule; docs/BATTLE_LAWS.md §1) packs `n` spear fighters near the arrival point in 2-4 sides. Each side is a community (`Side A`, `Side B`, …; names `A12`, `B7`). An open `stance` record each way between every two sides says `enemy`, due never (`u64::MAX`). Each fighter's graph blocks or dodges when threatened, else `attack`s the nearest person of `relation: enemy`, which a person of no side (a resident) never is. Block and dodge alternate by the fighter's index in its own side, so each side has both, within one (sides-mixed-defence, 2026-11-22). Before, the defence went by id parity while the side went by creation order: with consecutive ids one whole side blocked and the other dodged, and in the E4b melee the low-id, blocking side broke 14 of 19 (docs/BATTLE_LAWS.md §1). `spawn_battle` (no sides) still goes by id parity.

Until sides-battle-fix (2026-11-22) the fixture wrote those records due at 0. Record housekeeping (1 Hz) drops every record with `due_ms <= now`, so the stances were gone within a second. The fighters then found no enemy in sight after their first blows and nobody fell.

**`sides_battle`** (`--seed cullet`, a fresh world: the scene counts every living person not spawned by it as a resident; about 70 s after the launch):
- 60 fighters in 2 sides on Cullet's arrival plaza, watched for 60 s of authority time from their `born_ms`.
- `skill_use` (the last 24 uses of each actor, outcomes kept after death) and `character` are read over HTTP each second, so every use is seen. A full set of 24 unseen rows after earlier ones were seen would be a gap, which fails the check `every use was seen`.
- Checks: each side has both defences, block and dodge counts within one (read from each fighter's `brain` graph right after the spawn; the run folder's `sides_battle-defence.json` lists side and defence per fighter); the two stance records exist, open and never due, 3 s after the spawn; fighters fall within 30 s; fighters aim uses at someone; no use targets a resident, the fighter's own side or anyone outside the battle; no resident dies in the 60 s.
- Evidence in the run folder: `sides_battle-summary.json` (fighters, sides, residents, uses, accepted, aimed, fallen by 30 s and 60 s, residents dead), `sides_battle-uses.json` (every use seen), `sides_battle-dead.json`, `sides_battle-spawned.json`.
- On main before the fix it fails: the stances are gone at 3 s, 78 uses in all, 0 fallen in 60 s. With the fix: 2,276 and 2,432 uses, 4 and 6 fallen by 30 s (first at 5.7 s and 18.3 s), 14 and 16 by 60 s, no resident dead (validation record 2026-11-22, sides-battle-fix).
- Stochastic: who falls when varies; it asserts at least one fallen by 30 s, never a count.
- The scene gate runs it (`sides_battle`, a Cullet world) when a merge touches `SIDES_BATTLE_PATHS` in `living/tools/scene_gate.py`.

### Fixed layouts

`spawn_battle_sides_layout(n, sides, layout_seed, deal)` (sides-layout-seed, 2026-11-23; docs/BATTLE_LAWS.md §1) is the same fixture on a fixed layout. `n` must be a positive multiple of `sides` (2-4), else it is refused. The places come from a splitmix64 stream seeded `layout_seed` in the same 14 × 14 m box, skipping tiles that are not free, and are dealt in groups of `sides`: slot `k` of group `j` goes to side `(k + deal) % sides`. Within a group the sides are made in order, so the ids follow the side, and fighter `j` of each side has the defence of index `j` (dodge when even). With two sides, deal 1 is deal 0's mirror. `spawn_battle_sides` itself is unchanged: its layouts are random per world and not comparable with these.

**`sides_layout`** (after `sides_battle` on its Cullet world; about 20 s; the world stays paused):
- Spawns 60 fighters in 2 sides five times: seed 1001 deal 0, deal 1, deal 0 again, seed 1002 deal 0, and 61 fighters (refused).
- Checks: each spawn makes 60 placed, armed fighters of the side their name says; deal 1 puts `A<j>` on deal 0's `B<j>` place and `B<j>` on `A<j>`'s, for every `j`; the same defence on each place in both deals; each side 15 block and 15 dodge; the same seed and deal give the same places; seed 1002 shares no place with 1001; the 60 places are distinct; the odd `n` is refused ("multiple"); the open, never-due `enemy` stance records each way.
- Evidence in the run folder: `sides_layout-<seed>-<deal>.json` (each fighter's id, place, side and defence by name) and the printed `sides_layout:` line (pairs mirrored, and A1's and B1's places in both deals).
- The scene gate runs it after `sides_battle` on the same world, on the same paths.
