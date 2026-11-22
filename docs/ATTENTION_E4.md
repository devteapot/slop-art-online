# E4: does heed capacity matter in a fight?

Status: **built behind `heed_on` (off by default) and measured on the pack arena (fake model) and the two-sided melee (no minds), free.** 2026-11-22, branch `heed-e4` (Spark), from `origin/attention-exp` `0aba82f2`, with attention-exp `67a68abd7` (the smoothed selector) and main `aa41242c5` (`sides-battle-fix`) merged. It is the Spark's E4 of docs/ATTENTION_BUDGET.md §8.2 (v2 with the v2.1 amendments). **Nothing merges to main until the owner decides on the law.** The player side (heed replacing `far_cap`'s trim in `sweep_one`, throng rows to clients) is not built: players keep today's perception even with the law on.

## In short

- **Off is the base, byte for byte.** With `heed_on` off the branch's final head runs a Cullet battle of 200 and the E4 pack arena tick for tick and row for row as its base (attention-exp `67a68abd7` + main `aa41242c5`): 3,600 and 7,200 ticks, 113 tables, 43,232 and 105,029 rows identical (§2).
- **Pack arena (fake model, 6 wolves v 6 spear-carrying people, 108 valid runs): capacity from 4 to 32 does not matter there.** At 4, 8, 16, 32 and both formulas, no first blow came from an unheeded attacker in any run (0 of 413 first blows logged in those arms, day and night), every windup aimed at a subject was heeded when it began, no person died, and rear blows, encirclement, the subjects' own blows and the casualties stay within the capacity-16 arm's range, except for scattered differences in both directions (§3.3). By `pack_arena.py`'s rule the answer is **no**: capacity 4 and 8 do not differ from 16 in the direction of more unheeded blows, more rear blows or more deaths.
- **Why:** the heed instinct's first rule takes any windup aimed at the character in the tick it begins (the event pass displaces the lowest place), so a capacity of even 4 sees every attack coming when at most 2–3 wolves attack one person. Capacity starts to bind only at 1 and 2 (exploratory arms): 3 first blows from an unheeded attacker in 12 runs (at most 0.035 a subject-minute; 17% of one run's first blows), a few windups unheeded (95–97% heeded), and at night more health lost (185 against 95). Not a fight-changing effect even there.
- **Repeated invisible blows: 0 by construction, asserted:** no blow in any run came from an attacker that had made contact within `heed_contact_s` yet was not an individual at its windup, and no `heed invariant` line was logged. Later blows from an unheeded attacker after the window lapsed: 0.
- **No wound spiral:** on the formula, capacity fell by a median 0–5% (at most 21%) while health fell by a median 6–31%; nobody's capacity collapsed, because nobody was hurt below a quarter for long, and no one died.
- **Reactions are not measurable on this fixture:** the people's own starting behaviour (their seeded "stay safe" routine) never blocks or dodges, so blocks and dodges per windup are 0 in every arm, heed off included. The melee (§3.4) has fighters who block and dodge.
- **The 60-person two-sided melee (no minds, 54 runs): capacity does matter there.** Side A at capacity 1, 2 or 4 lost all 18 fights and at 8 lost 4 of the 5 decided, killing a median 1–4.5 enemies against 15 at capacity 16 and 22.5 at 32. Unheeded first blows explain 1 and 2 only (24% and 6% of first blows); at 4–8 the cause is that the instinct's "who is close" rule fills a small capacity with one's own side, so enemies not yet striking stay in the throng and are not attacked. By the strict §5.5 rule only 1 and 2 differ from 16 (the melee's spread is wide); the direction at 4 and 8 is consistent in all 12 runs (§3.4).
- **AI tick cost at 200 fighters:** heed on adds about 76 ms/s of tick (501 → 577, +15%); its passes cost about 85 ms/s, about 7.5 µs per creature in sight per pass, independent of how many are heeded (§4).

**Validity.** Every pack run ran from a quiet start (merge lock free, load under 4) under `battle.lock`, the trial server pinned to the X925 cores, the load sampled every 10 s; a run whose window passed load 8 was left out and redone (14 of 122 measured runs, mostly from 6 arenas in parallel; later replicates ran 3 at a time). The first 6 day arenas of replicate 1 ran on the old selector (`0aba82f2`) and were stopped and not counted when the selector moved; replicate 1 of the restarted series was redone whole (my own det_compares had run beside it). All counted runs are on the smoothed selector with holds on (`aa3d4d9e2` as merged at `631b496ac`), module `trial-island-d04f5129` built from `631b496ac`.

## 1. The authority side (behind `heed_on`)

`living/authority/src/heed.rs`. A character the authority runs (no person plays it: `combat::human` is none) perceives through heed when the world's `heed_on` law is on.

- **The set.** Per character, in module memory: the selector's picks (`living_rules::heed::select`, the code E3's replay runs), each pick's last time on merit (for its rule's `hold_s`), how long each has been heeded and in sight, and the last pass's field. The policy is the species' instinct (`living/seeds/heed.json`): no mind writes one in E4 (`mind_update` has no `heed` field).
- **The full pass** runs at most once a second per character, from its behaviour evaluation, or from any reader that finds the set missing or older than 3 s. Its candidates are built from what the body perceives (`perception::Sensing`): kind, distance, closing speed, made out or far, family by parentage (and friend, enemy, stranger, community only when the policy reads them), windups aimed at it, what it visibly does (`perception::visibly`), who hurt it and when, who spoke or waved to it, whom it acts on, contact, cue matches, heeded and in-sight times. Loud and lit are not filled (the instinct's `loud` weight is 1 and never fires; listed below).
- **The event pass** (`living_rules::heed::admit`) runs in the tick for a windup aimed at the character (`act::begin`, before the fast lane counts it), a creature coming into a full scene, a cue's match, and words to it.
- **Forced, outside the capacity, whatever the policy:** whoever the character acts on (its activity's or move's target) and whoever made contact within `heed_contact_s` (a blow that reached it: landed, blocked or dodged; `act::damage` and a dodge by evasion). Both are worked out when a reader asks, so they are never stale.
- **Capacity:** the world's `heed_capacity(a)` over the character's own facts (`act::facts`, its practice and genes), clamped by `heed_ceiling` (`Scripts::heed_capacity`), at each full pass.
- **Diagnostic law `heed_trace`** (value-only, off in play): logs, for characters with a mind, each pass (`heed pass id cap health in_sight picked forced`), each windup aimed at one (`heed windup … seen heeded contact`) and each blow that reaches one (`heed blow … first repeat_in_window seen_at_windup heeded_at_windup`). An invisible repeated blow (contact within the window before the windup, yet not an individual then) is logged as `heed invariant` whether or not tracing is on.

**Module memory and rollback.** The SpacetimeDB reducers page (read 2026-11-22, version 2.0.0, [reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior"): "Relying on global variables, static variables, or module-level state to persist across reducer calls is undefined behavior"; "SpacetimeDB may run each reducer in a fresh WASM or JS instance"; "If you modify global state and then roll back the transaction, the modified value may remain for subsequent transactions". The 2.14.1 source reading in docs/PERCEPTION.md ("Module memory and rollback") holds: one instance, a trap or publish starts a fresh one. The heed set is therefore a cache of a selection, never a record: a fresh instance has none and every reader asks for a pass; a pass or a contact a rolled-back transaction left in memory is re-derived by the next pass or lapses within `heed_contact_s`. Nothing is written to a table: no table, column, reducer, view or subscription changes, so no migration and no bindings.

### What each `Sensing` reader does under `heed_on`

| Reader | Under heed (AI characters) | Where |
| --- | --- | --- |
| graph `sees`, the `nearest`, `id`, `attacker`, `speaker`, `hailer`, `parent`, `partner`, `named` targets | individuals only (`first_seen` filters, `seen_by_id` refuses a throng member; a refused act says "no #id in sight") | `brain.rs` |
| graph `count`; the crowd alert ("among a crowd of about N") | individuals and throng: a throng's numbers are perceived | `brain.rs` |
| graph `doing` | individuals only | `brain.rs` |
| graph `threatened`; the `threatened` desire signal | only a windup by an individual (one from the throng is not seen coming); the instinct's first rule admits a windup aimed at one in the tick | `brain.rs`, `heed::windup` |
| cues | matched against everyone in sight; a throng member that matches is `cued` and takes the event pass, the cue fires only if it becomes an individual | `brain.rs` `cues` |
| first sights, `familiar` rows, "a wolf is close" | individuals only | `brain.rs` `noticed` |
| a mind's scene (`scene_json`) | the individuals in full (the hidden 14-nearest cap is gone with the law on); the rest as `throngs` lines (`dir`, `dist` band, `about` count, `across` spread, `moving` relative to one, `visibly` fighting, `kinds`), never among `creatures`; `visibly.at` and `doing → whom` name only individuals | `perceive.rs` |
| earshot in a mind's scene | **reads sight** (speech consent): throng hearers are counted, named "someone in the throng to the …" | `perceive.rs` |
| a mind's on-stage detection | a player in the throng is counted in the scene's `_stage.throng_players`; `watched` treats it as a player present; `prompts::model_scene` strips `_stage` from every prompt | `perceive.rs`, `mind/src/mind.rs`, `prompts.rs` |
| witness lines, missile lines, fight folds | a throng member is "someone in the throng to the …", subject or object 0 | `perceive.rs`, `fold.rs` |
| speech heard | a speaker in the throng: "Someone in the throng to the … says: …", subject 0, no introduction; words to the hearer are an event (`addressing`) first | `speech.rs`, `heed::addressed` |
| `mind_reach` (talk frame) | a throng member is not perceived as them | `mind.rs` |
| the fast lane's "move seen again" | a move by a throng member is not counted | `fast.rs` |
| **unchanged** | players (sweeps, copies, combat feed, `my_earshot`: no throng exists for them yet); steering's hold on a target (it is acted on, so forced); smell; heard-not-seen; the `apart` push | |

## 2. Off is the base, byte for byte

`living/tools/det_compare.py run --scripts BASE,CAND` (each copy installs its own build's shipped script; the base is `attention-exp` `0aba82f2` exported with `git archive`, built in its own target dir):

| Run | Base | Candidate | Ticks | Tables | Rows at the stop | Result |
|---|---|---|---|---|---|---|
| Cullet battle of 200 (`spawn_battle`), final head | attention-exp `67a68abd7` + main `aa41242c5` (merge tree `0b1571aac`), its own `skills.rhai` with Cullet's laws | `heed-e4` `596942111` | 3,600 | 113 | 43,232 | **identical** |
| E4 pack arena (`prepare --arena pack`: 6 bold wolves, 6 spear people on the fighters' graph, island, no minds), final head | the same base | `596942111` | 7,200 | 113 | 105,029 | **identical** |
| Cullet battle of 200, after the selector merge | attention-exp `67a68abd7` | `631b496ac` | 3,600 | 113 | 47,773 | identical on the rerun; the first try differed from tick 2,707 in `last_look.max_structure`, `seen_structures.ranges` and `deliberation` only (base copy's structure ids at 4,096+, the candidate's at 230: SpacetimeDB 2.14.1's random sequence skip, the known artifact of docs/COMBAT_PHASE.md's det runs; kept as `det2-cullet-off-try1`) |
| Cullet battle of 200 and pack arena, first build | attention-exp `0aba82f2` | `b5d2e48a0` | 3,600 / 7,200 | 113 | 47,400 / 104,869 | identical |

**The comparison can see heed:** the same pack template with `--candidate-law heed_on=true` on the candidate alone differs at every tick: in the law's own rows from the first, and in the world's state from 8 ticks in (`experience`, `familiar`, `sex_seen`: first sights of throng members not told), 36 tables at the stop.

`prepare --arena pack` is new (`det_compare.py`): it stages the arena on a paused island world the way the trial places it. The people run the fighters' graph there, because no mind runs in a det copy. Each run installs each build's own script (`--scripts`), so the candidate's added laws (`heed_closing_s`, `heed_trace`) are in its copy.

## 3. E4 fixture

### 3.1 The pack arena

`living/tools/heed_e4_trials.py` writes `living/trials/heed-e4-{day,night}.json`, the variants (`heed-e4-variants.json`) and the fake script (`fake/heed-e4.json`). It is docs/PACK_MIND.md §5's arena, spread start, with these choices made before the first counted run:

- **The people:** 6 adult people of Brackenford, each given a spear, on **their own starting behaviour**: the graph they had (desires over their seeded routines; "stay safe": strike back at whoever hurt one, attack the nearest wolf when one is within 6 m with others near, flee or yield when badly hurt). Their minds run on the fake model, and every deliberation keeps the graph (`"graph": "keep"`) and says nothing. So no reaction is prescribed by the fixture, the heed policy is the instinct, and only capacity varies.
  - Found in the smokes: the fake model's default deliberation installs `{"wait": 2}` (people stand and are eaten), and clearing their routines leaves their desires with nothing to run. Both were fixed before the first counted run.
- **The wolves:** 6 bold wolves on the shipped bold instinct, 15–35 m off. The island's other wolves and its deer moved far away and kept still.
- **Arms (variants):** heed off; heed on with the shipped formula (person 10, wolf 8); the formula with a person's base at **14** (added at the general coordinator's request: heed-town found 10 tracked 2 of 14 named people beyond the 8 nearest, 16 tracked 13); and the people's capacity fixed at **4, 8, 16, 32** (the design's arms) and **1, 2** (exploratory), the wolves on the formula. Ceiling 32. `heed_trace` on in every heed arm.
- **Runs:** 5 minutes each, day and night (start hour 21: sight 6 m), 6 valid replicates per arm and time, interleaved, through `trials.py run --fake --keep-db`, then `heed_e4.py collect` (the module log's heed lines) and `trials.py clean` (each world paused, confirmed, deleted).
- **Measured with** `living/tools/heed_e4.py report --loads … --control …/heed-cap16`: `pack_arena.py`'s M2 (rear blows, encirclement), M5 and M6, the subjects' blows (uses), and from the heed lines: first blows by attacker per engagement (20 s) and whether that attacker was an individual to the subject when its windup began, windups heeded, repeated invisible blows, capacity per pass. The decision rule is docs/PACK_MIND.md §5.5's against the capacity-16 arm of the same time of day.

### 3.2 Evidence

Batches `he4nr2`, `he4nr3`, `he4pr4`–`he4pr6`, `he4xr1` (the redone replicate 1) and the top-ups `he4ta`–`he4td`, under `.local/living/trials/` in this worktree (git-ignored), with each batch's load log and the reports in `.local/heed-e4/` (`report-day.json`, `report-night.json`, `series/series.log`). The stopped runs are kept as `.local/heed-e4/aborted-*`. All of it (`.local/heed-e4/`, the trial batches, the verify runs `core-heed*`, `minds-heed*`, `minds-bdh*`, and the modules' sha256 in `wasm.sha256`) is archived as `~/slop-evidence/heed-e4-20261122.tar.zst` (sha256 `e000e7d7f3d3b756876624110e3b7fa21b99303861851ac2e9c9f278de925116`, beside it). The private servers and their volumes were removed afterwards.

### 3.3 Results (median, range over 6 replicates; ◆ differs from capacity 16 by the §5.5 rule; * exploratory)

### Day

| Measure | off | formula (10) | formula, base 14 | 1 * | 2 * | 4 | 8 | **16** (control) | 32 |
|---|---|---|---|---|---|---|---|---|---|
| First blows from an unheeded attacker, per subject-minute | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0.035) | 0 (0–0.034) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Share of first blows from an unheeded attacker | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0.167) | 0 (0–0.091) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Windups at a subject heeded when they began | – | 1 (1–1) | 1 (1–1) | 1 (0.974–1) | 1 (0.949–1) | 1 (1–1) | 1 (1–1) | 1 (1–1) | 1 (1–1) |
| Rear-blow share | 0.599 (0.429–0.895) | 0.556 (0.469–0.846) | 0.542 (0.407–0.7) | 0.467 (0.238–0.545) | 0.539 (0.4–0.615) | 0.494 (0.333–0.571) | 0.564 (0.5–0.688) | 0.589 (0.4–0.75) | 0.543 (0.5–0.667) |
| Encircled share (k ≥ 3) | 0.0715 (0–0.143) | 0 (0–0.043) | 0.097 (0–0.377) | 0.0185 (0–0.05) | 0 (0–0.261) | 0 (0–0.107) | 0.342 (0.184–0.5) ◆ | 0.041 (0–0.082) | 0.075 (0–0.281) |
| Wolf windups at subjects | 24.5 (11–37) | 21.5 (0–58) | 42 (9–52) | 46.5 (38–67) ◆ | 40 (24–63) | 27 (7–86) | 27.5 (8–39) | 24 (15–43) | 32.5 (12–45) |
| Subjects' blows begun | 22.5 (18–38) | 31 (0–40) | 32 (19–45) | 26.5 (21–31) | 34 (24–40) | 34.5 (9–43) | 27 (19–46) | 28 (20–44) | 35 (28–41) |
| Subjects' blows landed | 17.5 (12–28) | 24.5 (0–25) | 25.5 (14–30) | 24.5 (18–31) | 26.5 (17–34) | 24.5 (9–36) | 23.5 (16–31) | 22 (16–30) | 27.5 (21–34) |
| People dead | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Wolves dead | 0.5 (0–2) | 1 (0–2) | 0 (0–1) | 0 (0–1) | 0 (0–1) | 1 (0–2) | 1 (0–2) | 1 (0–1) | 0.5 (0–2) |
| People's health lost | 121 (65–160) | 125 (0–240) | 226 (52–265) | 250 (183–295) | 191 (151–325) | 162 (39–381) | 150 (49–194) | 116 (85–269) | 162 (85–221) |
| Start to first blow, s | 5.55 (0.9–15.9) | 7.1 (5.3–13.5) | 3.15 (2–7.6) | 5.85 (0.9–11.7) | 3.3 (2.1–12) | 5.65 (1.9–20.1) | 4.55 (1.6–17) | 5.25 (1.5–16.3) | 6.6 (4.7–14.1) |
| Fight, s | 113 (65.6–212) | 121 (80–293) | 162 (52.3–220) ◆ | 136 (111–300) | 252 (115–298) ◆ | 63.7 (40.7–295) ◆ | 76.2 (55.8–219) | 101 (74.2–145) | 116 (93.7–242) |
| Share of passes at capacity (more in sight than places) | – | 0 (0–0) | 0 (0–0) | 0.337 (0.209–0.427) ◆ | 0.193 (0.143–0.305) ◆ | 0.095 (0.0756–0.13) ◆ | 0 (0–0.0035) | 0 (0–0) | 0 (0–0) |
| Capacity lost (formula: the wound spiral) | – | 0 (0–0.1) | 0.0535 (0–0.214) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Health lost (lowest) | – | 0.152 (0–0.318) | 0.314 (0.0775–0.489) | 0.544 (0.384–0.643) | 0.27 (0.209–0.598) | 0.236 (0.037–0.648) | 0.235 (0.0365–0.354) | 0.166 (0.042–0.603) | 0.249 (0.149–0.322) |

### Night

| Measure | off | formula (10) | formula, base 14 | 1 * | 2 * | 4 | 8 | **16** (control) | 32 |
|---|---|---|---|---|---|---|---|---|---|
| First blows from an unheeded attacker, per subject-minute | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0.037) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Share of first blows from an unheeded attacker | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0.2) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Windups at a subject heeded when they began | – | 1 (1–1) | 1 (1–1) | 1 (0.95–1) | 1 (1–1) | 1 (1–1) | 1 (1–1) | 1 (1–1) | 1 (1–1) |
| Rear-blow share | 0.578 (0.412–0.812) | 0.5 (0.333–1) | 0.53 (0.333–0.786) | 0.517 (0.346–0.684) | 0.331 (0–0.833) | 0.4 (0–0.545) | 0.667 (0.25–0.75) | 0.571 (0.188–0.688) | 0.5 (0.4–0.8) |
| Encircled share (k ≥ 3) | 0.159 (0–0.465) ◆ | 0 (0–0) ◆ | 0.043 (0.043–0.043) ◆ | 0.217 (0.053–0.238) ◆ | – | – | – | 0.182 (0.182–0.182) | – |
| Wolf windups at subjects | 15.5 (0–41) | 11.5 (0–45) | 13.5 (0–23) | 30.5 (20–39) ◆ | 7 (0–18) | 13 (5–21) | 5 (0–11) | 15 (0–27) | 5 (0–15) |
| Subjects' blows begun | 16.5 (0–44) | 23 (0–38) | 28.5 (0–36) | 22.5 (16–30) | 8.5 (0–25) | 17 (0–28) | 12.5 (0–26) | 22 (0–32) | 6.5 (0–32) |
| Subjects' blows landed | 13.5 (0–33) | 15.5 (0–28) | 21.5 (0–27) | 20 (16–24) | 6 (0–14) | 12 (0–23) | 9 (0–20) | 16 (0–23) | 4.5 (0–17) |
| People dead | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Wolves dead | 0 (0–1) | 0 (0–2) | 1 (0–1) | 0 (0–1) | 0 (0–0) | 0 (0–1) | 1 (0–2) | 1 (0–2) | 0 (0–1) |
| People's health lost | 92.5 (0–274) | 59.5 (0–229) | 84 (0–120) | 186 (140–256) ◆ | 52.5 (0–133) | 65 (0–144) | 29 (0–77) | 95.5 (0–135) | 14 (0–108) |
| Start to first blow, s | 3.3 (0.5–4.3) | 4.3 (2.9–19) | 3.9 (3.1–19.1) | 3.85 (1.7–34.1) | 10.8 (7.5–53) ◆ | 5.8 (2.9–9.4) | 7 (2.3–15.2) | 3.7 (1.7–5.4) | 7.45 (5.4–11.5) ◆ |
| Fight, s | 42.1 (33.8–82.7) | 67.2 (14.1–181) | 55.6 (51.9–56.7) | 56.2 (36.2–209) | 44.2 (32.7–61.7) | 42.2 (24.4–136) | 28.9 (26–45.2) | 49.3 (29–142) | 58.8 (27.1–138) |
| Share of passes at capacity (more in sight than places) | – | 0.0408 (0.0339–0.0596) ◆ | 0 (0–0.0053) | 0.633 (0.599–0.913) ◆ | 0.364 (0.286–0.444) ◆ | 0.221 (0.194–0.261) ◆ | 0.0552 (0.0405–0.0619) ◆ | 0 (0–0) | 0 (0–0) |
| Capacity lost (formula: the wound spiral) | – | 0 (0–0.2) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Health lost (lowest) | – | 0.059 (0–0.411) | 0.0745 (0–0.185) | 0.231 (0.075–0.47) | 0 (0–0.161) | 0.0168 (0–0.161) | 0 (0–0.0375) | 0.121 (0–0.256) | 0 (0–0.189) |

- **Unheeded first blows:** day 2 of 406 first blows, night 1 of 165, all three at capacity 1 or 2. Capacity 4 and up, and both formulas: none.
- **The flagged differences are scattered and run both ways:** fight length (formula 14 and capacity 2 longer, capacity 4 shorter by day), encirclement at capacity 8 by day, time to the first blow at capacity 2 and 32 by night. None lines up with capacity, and none is a direction the question asks about. At night several arms had engagements in only 4–5 of 6 runs (the wolves did not reach the people), which leaves encirclement undefined there.
- **Places are full only at 1–4** (by day 10–34% of passes with more in sight than places; at night 22–63%), and from 8 up almost never: 6 wolves and 5 companions rarely exceed 8 in sight.

### 3.4 The two-sided melee

`living/tools/heed_e4_melee.py` on my private server (pinned to the X925 cores, under `battle.lock`, quiet start, load at most 2.8 through the series): Cullet's module from `bd35001de` (main's `sides-battle-fix` merged), `spawn_battle_sides(60, 2)`, no refills, no minds: two sides of 30 spear fighters on the arrival plaza, each blocking or dodging when `threatened`, else attacking the nearest enemy. **Side A's capacity is fixed** (1, 2, 4, 8, 16, 32; `heed_capacity` returns N for Side A's ids), **Side B stays on the formula**; the formula arms put both sides on it (base 10 or 14); heed off is the control of the fixture. A run ends when a side is down to 20% (6 alive) or after 5 minutes. 6 replicates per arm, interleaved, 2 at a time. **Casualties confirmed first** (smoke, heed off): the first fighter fell at 19 s, 4 within 30 s, 10 within 61 s.

| Measure | off | formula (10) | formula, base 14 | 1 * | 2 * | 4 | 8 | **16** (control) | 32 |
|---|---|---|---|---|---|---|---|---|---|
| Side A dead (of 30) | 15 (8–24) | 24 (11–26) | 24 (3–24) | 24 (24–25) | 24 (24–25) | 24 (24–25) | 24 (9–25) | 23.5 (16–24) | 14 (8–24) |
| Side B dead | 24 (6–24) | 8.5 (4–22) | 13.5 (9–24) | 1 (0–5) | 1.5 (0–3) | 4 (2–17) | 4.5 (1–24) | 15 (1–24) | 22.5 (5–24) |
| A dead less B dead | -9 (-16–18) | 15.5 (-11–22) | 10.5 (-21–15) | 23 (19–25) | 23 (21–24) | 20.5 (7–22) | 20 (-13–23) | 8.5 (-8–23) | -8.5 (-16–19) |
| Fight, s (a side down to 20%, or 5 min) | 167 (93.5–196) | 136 (67.1–302) | 188 (116–249) | 75.2 (61–101) ◆ | 84.3 (57.1–106) | 127 (75.1–255) | 107 (73–302) | 169 (85–301) | 162 (108–302) |
| First blows on A from an unheeded attacker, per A fighter-minute | 0 (0–0) | 0 (0–0) | 0 (0–0) | 2.05 (1.54–2.6) ◆ | 0.493 (0.305–0.716) ◆ | 0 (0–0.0736) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| Windups at A heeded when they began | 1 (1–1) | 1 (1–1) | 1 (1–1) | 0.885 (0.865–0.906) ◆ | 0.974 (0.966–0.98) ◆ | 1 (0.997–1) | 1 (1–1) | 1 (1–1) | 1 (1–1) |
| Blocks and dodges per blow reaching A | 0.765 (0.664–0.779) | 0.749 (0.629–0.817) | 0.755 (0.736–0.781) | 0.658 (0.634–0.681) | 0.682 (0.669–0.72) | 0.73 (0.695–0.787) | 0.718 (0.679–0.768) | 0.729 (0.641–0.791) | 0.751 (0.706–0.772) |
| A's blows landed | 262 (172–280) | 195 (113–273) | 230 (201–278) | 90.5 (72–137) ◆ | 94.5 (59–123) ◆ | 154 (104–236) | 163 (126–268) | 228 (118–267) | 260 (184–277) |
| A's passes at capacity | – | 0.938 (0.675–1) | 0.825 (0.722–0.985) | 1 (1–1) | 1 (1–1) | 1 (0.938–1) | 0.967 (0.577–1) | 0.835 (0.629–1) | 0.532 (0.5–0.634) ◆ |
| A's capacity lost (wound spiral) | – | 0.4 (0.2–0.4) ◆ | 0.429 (0.214–0.429) ◆ | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) | 0 (0–0) |
| A's health lost (lowest) | – | 0.805 (0.653–0.922) | 0.855 (0.489–0.888) | 0.784 (0.733–0.857) | 0.798 (0.747–0.838) | 0.847 (0.697–0.934) | 0.857 (0.554–0.883) | 0.763 (0.723–0.893) | 0.783 (0.537–0.877) |
| Which side broke (A, B, none) | 2 / 4 / 0 | 4 / 0 / 2 | 5 / 1 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 4 / 1 / 1 | 3 / 2 / 1 | 2 / 3 / 1 |
| First blows on A, of them unheeded (all runs) | 1602, 0 | 1740, 0 | 1808, 0 | 1401, 333 | 1390, 82 | 1650, 2 | 1628, 0 | 1739, 0 | 1633, 0 |

- **Here capacity matters, and the mechanism is not ambush.** Below 16, Side A lost every fight at 1, 2 and 4 (18 of 18) and 4 of the 5 decided at 8, while killing a median 1–4.5 of Side B against 15 at 16 and 22.5 at 32. Its own landed blows rise with capacity: 90, 95, 154, 163, 228, 260 (heed off: 262).
- **Unheeded first blows** appear only at 1 and 2 (333 of 1,401 first blows at 1, 82 of 1,390 at 2; 2 at capacity 4; none from 8 up), so they explain the losses at 1–2 but not at 4–8. What does: the person instinct's "who is close" rule takes the nearest **regardless of side**. In a mixed melee a small capacity fills with one's own side, and enemies a step farther stay in the throng, where `nearest enemy` cannot pick them until they strike (contact) or wind up at one. Fighters at low capacity start fewer blows against enemies that are not yet attacking them.
- **By the strict §5.5 rule** (median outside the capacity-16 range, ≥ 2/3 of runs) only capacities 1 and 2 differ (unheeded first blows, windups heeded, blows landed, fight length at 1). Capacity 4 and 8 do not pass it on deaths, because a melee snowballs and the 16-arm's own range is wide (B dead 1–24); the direction is consistent across all 12 runs at 4 and 8, but 6 replicates and this rule do not call it.
- **The wound spiral is mild:** on the formula a fighter's capacity fell a median 40% (10 → 6) while its health fell about 80%; capacity drops after health, never ahead of it.
- **A fixture asymmetry to check:** with heed off Side A lands more blows (1,427 against 829 hits over 6 runs) and B broke 4 times of 6; with both sides on the same formula A broke 4 of 6 (formula) and 5 of 6 (formula 14). Side A is created first (lower ids). The capped arms are compared with the capacity-16 arm, which shares it, but the symmetric arms suggest a side or id-order effect under heed that this series cannot separate from chance (9 of 10 decided symmetric heed runs went against A).

Evidence: `.local/heed-e4/melee/` (per run `roles.json`, `summary.json`, `characters.json`, `heed.log`; `melee-report.json`); every world deleted after it was read (paused, confirmed).

## 4. AI tick cost

`living/tools/battle_diag.py --battle 200 --walkers 0 --no-mind` on the island: 200 minded fighters (`spawn_crowd`, strike; dodge or block when threatened; refilled), no mind service, 5 minutes, profiled 30 s windows each minute, the first window left out as warm-up. Heed off, and on with the shipped formula (capacity 10, ceiling 16), interleaved off, on, off, on, on my private server pinned to the X925 cores (5–9, 15–19), the driver on the A725 cores, under `battle.lock` from a quiet start (load 1.9–3.5 at start, at most 5.1 in any window). `heed_trace` off. Build `596942111`.

| Run | Fighters alive (windows 2–5) | Ticks/s | `tick` ms/s | `heed.pass` ms/s | passes/s | in sight per pass | heeded per pass (forced included) | `perceive.scene_json` ms/s | `brain.noticed` ms/s |
|---|---|---|---|---|---|---|---|---|---|
| off 1 | 123 → 77 (refills fell behind) | 59.5–60 | 293 | – | – | – | – | 14.9 | 16.3 |
| off 2 | 171–176 | 56.8–57.5 | **501** | – | – | – | – | 26.6 | 36.6 |
| on 1 | 165–180 | 48.7–52.4 | **578** | **85.7** | 323 | 36 | 5.1 | 47.2 | 89.9 |
| on 2 | 160–177 | 48.2–54.1 | **577** | **84.9** | 316 | 35 | 5.1 | 47.7 | 89.4 |

- **Off 1 is not comparable:** its battle shrank to 77 fighters (the refill fell behind the deaths), so it is left out. Off 2 against the two on runs, at 160–180 fighters each: **heed adds about 76 ms/s of tick** (501 → 577, +15%), and the tick rate falls from about 57 to 48–54 a second on this fixture.
- **Where it goes.** `heed.pass` is 85 ms/s: about 320 full passes a second (a little under 2 a fighter: the 1 Hz pass from the evaluation, and a pass afresh when a reader finds the set older than 3 s), each about 0.27 ms over about 36 creatures in sight, about **7.5 µs per creature in sight per pass**. It runs inside the evaluation (`brain.noticed`, +53 ms/s, is where the scene is first split). `perceive.scene_json` grows by 21 ms/s: a deliberation's scene now lists all its individuals with no 14-cap and builds its throng lines.
- **It does not depend on how many are heeded.** The policy reads every candidate in sight; the rules' places (5.1 a pass here, the instinct's) cost little beside building each candidate (its `visibly`, closing, family and made-out reads). So dev-box's split by who is heeded (about 190 µs/s each for the first 8, about 67 beyond; docs/ATTENTION_E2_COST.md) is a player-delivery cost; for AI characters the cost is per creature in sight, and a lower capacity saves nothing here. What would cut it: fewer passes (only the 1 Hz slot, never a stale-read pass), candidates built only for what the policy reads (as `Reads` does for relations), and sharing a creature's visible features across observers within a tick.
- **Event passes are rare:** 5.8 a second at 200 fighters (windups aimed at one, words, cues), as E2 recommends (only aim and contact; no re-rank on movement or on coming into sight since `ee7a4b92f`).

## 5. Checks

- `just living-check`: passed on `596942111` (authority wasm, mind, viewers, game client and tests, authority unit tests, rules tests, script gate), and on `19a58f8a1` before.
- **verify-core** (own server `slop-heede4-stdb`, default seed):
  - the new `heed` scene (`scenes.py heed`, features/heed.md): 17 of 17 on `596942111`, `631b496ac` and `eac8b3880`. Off (the control) and on side by side: O sees S by id and counts 8 off; on with capacity 2, S is throng and O still counts 8; the scene lists at most 2 creatures, the rest as `throngs`, no throng member's id; with capacity 0 the first strike from the throng lands unforeseen, its contact makes the second seen and blocked (module log `heeded_at_windup=0` then `=1`); W's heard and fight lines name no one in its throng. A first version failed its control at night (W at 8 m, beyond night sight); everyone now stands within 5 m.
  - touched scenes with the law off, all passing: on `596942111` `tick`, `sight`, `crowd_sight`, `cues`, `witness_fold`, `seen_again`, `fov`, `sides_battle`; on `eac8b3880` also `senses`, `stranger_filter`, `scene_lazy`, `doing_seen`, `skirmish`. Evidence `.local/living/verify/core-heed*/`.
- **verify-minds** `roundtrip`, `acts`, `lod` with the law off: pass (`.local/living/verify/minds-heed-042915-*`). `prompts::tests::a_scenes_stage_mark_never_reaches_a_model` passes.
- **Rules:** `cargo test -p living-rules heed` (15) after the selector merge.
- **Not covered:** a player in a mind's throng (no player-side heed exists to put one there; the `_stage` path is covered by the unit test only); a mind-written heed policy (no `heed` reply field yet); verify-client and verify-player (no table, view, reducer or player path changed); paid tiers (none run).

## 6. Open questions

1. **The fixture decides the answer.** Against wolves (attackers only) capacity 4 suffices: the instinct ranks a windup at oneself first and the event pass gives it a place at once. In a mixed melee capacity 4–8 loses, because the instinct's "who is close" rule spends places on one's own side. Should the starting instinct weigh side (enemy, or `acting_on_heeded`) above plain nearness, or is that the mind's to write? And should the melee get more replicates (or a paired design: swap which side is capped) so 4 and 8 can pass the §5.5 rule, and to settle the side asymmetry of §3.4?
2. **AI cost.** 7.5 µs per creature in sight per pass, about 0.27 ms a pass, +15% tick at 200 fighters. Before default-on, the pass should run only at the 1 Hz slot (not again for a stale read), and candidates should read only what the policy reads; worth a measured follow-up.
3. **The combat feed** is human-only today (`combat::show`), so it reaches no AI or mind; its recipients by heed (dev-box's E2: 128,711 rows in one 16-viewer run) belong to the player side, not built here.
4. **`loud` and `lit`** are not filled for AI candidates (the instinct's `loud` weight never fires). Hearing a call or seeing a torch at night are perceptible and should feed them.
5. **Earshot words for a throng** list each throng hearer as "someone in the throng to the …", which repeats in a crowd; a count ("and 5 in the throng") would read better.
6. **`threatened` desire signal and the throng.** It now counts only windups by individuals, like the `threatened` condition; before heed it counted every windup aimed at one, seen or not (a pre-existing leak with `fov_on`).
7. Owner: whether the law goes on per world after the player side and E2's ceiling. The person base (10 or 14) is not separated by these fights: the formula and formula-14 arms differ from 16, and from each other, on no fight measure in either fixture.
