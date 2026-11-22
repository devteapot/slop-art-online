# The two-sided melee's side asymmetry: id order or spawn position? (2026-11-23)

Branch `side-asymmetry` (Spark): origin/main `238d151f9` (fair-ties on main since `0877fe93a`) with `sides-mixed-defence` (`9077ff608`) merged in locally. A diagnostic record. Free: no mind, no model. No game rule changed, and nothing here is meant for merge.

## The question

**E5's real-mind recording** (docs/ATTENTION_E5.md §6 on `heed-e4`) lost Side B in all 4 runs. Its settings: heed on, capacity 32, `sides_mixed_defence` on, `sides_first` 0, Cullet, 120 minds. Survivors A/B: 35/7, 32/7, 34/5, 41/7.

**E4b** (docs/ATTENTION_E4.md §7.4, heed off, mixed defence) had already shrunk the asymmetry to 4 of 6 decided fights. That was before fair-ties.

**The general coordinator asked** for a swapped-sides check after fair-ties, to tell two causes apart: the **id order** (which side holds the lower ids) and the **spawn position** (which side stands where).

## Verdict

**Neither factor shows after fair-ties**, at E4b's size (60) or at E5's (120).
- Swapping the id order changes nothing measurable.
- Swapping which side gets which places changes nothing measurable either.
- Side A as such does no better or worse than Side B.

**What does decide much of a fight is the particular layout:** where each fighter of each side happens to stand in the random interleave.
- One layout can favour one half of its places by up to about 10 deaths of 30 per side (60 fighters) or about 20 of 60 (120 fighters).
- The fixture draws a new random layout for every world: `ctx.rng()` is seeded from the reducer's timestamp (`spacetimedb-2.14.1/src/rng.rs:50`, `StdbRng::seed_from_ts(self.timestamp)`). So the favoured half falls to Side A or B by chance in each run.
- Under that alone, the same side losing all of 4 runs has probability 2 × (1/2)^4 = **1/8**.

**E5's 4 of 4 is therefore not explained by id order or by a side-systematic spawn position.** It stays an open question for the real-mind arm (see "The real-mind difference"). E5 also ran a pre-fair-ties build.

## Spawn position in this fixture

`spawn_battle_sides` (`living/authority/src/lib.rs`) has no per-side spawn position.
- Each fighter's place is drawn uniformly in one 14 × 14 m box round a point 20 m from Cullet's arrival (`center ± 7`).
- Each draw is rejected if the tile is not free.
- The side goes by creation order (`made % sides`), so the sides are interleaved draw by draw.
- Nothing gives one side the near or far edge, terrain or cover, or an approach. Contact is immediate: the first landed blow comes at a median 0.75 s (range 0.37–1.82 s), 3.9–4.4 m from the centre.

"Position 1/2" can therefore only mean **which of a layout's places a side holds**. To make that a factor, the diagnostic reducer (`living/tools/side_swap_diag.patch`) does the following:
- It draws the places from a **fixed layout seed** (splitmix64).
- It deals them in pairs, with slot 0 of each pair to one side ("position 1") and slot 1 to the other.
- It chooses **independently** which side is made first in each pair, which is the side that holds the lower id of every pair.

Everything else is as on the branch: two communities with open `enemy` stances, spears, block and dodge alternating within each side, and the attack on the nearest enemy.

## Design

**Cells.** 2 × 2, built from two settings:
- `i0`: Side A is made first in each pair, so it holds the lower ids. `i1`: Side B is made first.
- `p0`: Side A holds slot 0, "position 1". `p1`: Side B does.

**Replicates.** Replicate *r* uses the same layout seed in all four cells.
- `i0p0` and `i1p1` are mirror images: the same places and the same id order, with the labels A and B swapped. So are `i0p1` and `i1p0`.
- This gives three contrasts, each within a layout:
  - **the id effect:** same places, ids swapped;
  - **the place effect:** same ids, places swapped;
  - **the label effect:** the mirrors.

**Replicate count.** In E4b's mixed heed-off melee, the end-of-run A−B dead difference had an SD of 9.6 over 16 runs.
- **60 fighters:** 10 replicates per cell (layouts 1001–1010), 40 runs. Each factor compares 20 runs with 20, a 95% CI of about ±6 deaths.
- **120 fighters:** 6 per cell (layouts 2001–2006), 24 runs.

**Runs.**
- Heed off, no model, no refills.
- Each run lasted until a side was at 20% of its fighters or fewer ("broke"), or for 6 minutes of world time.
- The `cullet` module was built from the branch plus the patch: wasm sha256 `3a046270…0dca`.
- All runs were on a private 2.14.1 container (`slop-sideasym-20261122`) pinned to CPUs 0–4 and 10–14, at nice 10, 5 worlds at a time (4 at 120 fighters).
- Every world held 59.0–59.97 ticks/s. These are outcome counts, not timing, so there was no `battle.lock`.

**Measures** (`living/tools/side_swap.py report`, all from 2-second samples):
- which side broke;
- the dead difference at 30, 60, 90, 120, 180 and 300 s and at the end;
- blows landed (`hit for N`, `killed … (N)`) and damage dealt, including blocked blows' "N got through", read from `skill_use` before its 24-per-character pruning;
- the first landed blow's time, side and place;
- spawn geometry per side.

CIs are bootstrap over runs, or over layouts where stated. Break shares carry Wilson 95% intervals.

## Results

### The 2×2, 60 fighters (10 per cell)

| Cell | Low ids | Position 1 | A broke | B broke | Neither | A−B dead at 60 s (95% CI) | A−B dead at the end | A−B blows landed |
|---|---|---|---|---|---|---|---|---|
| i0p0 | A | A | 1 | 3 | 6 | −0.1 (−3.7, 3.5) | −2.1 (−8.3, 4.0) | +12.6 (−45, 71) |
| i0p1 | A | B | 4 | 2 | 4 | 0.0 (−2.6, 2.4) | +2.8 (−3.2, 8.1) | −26.1 (−78, 29) |
| i1p0 | B | A | 3 | 0 | 7 | +2.0 (−0.4, 4.3) | +3.3 (−0.9, 7.5) | −21.6 (−58, 16) |
| i1p1 | B | B | 4 | 2 | 4 | +0.4 (−3.4, 4.1) | +3.7 (−2.6, 9.6) | −21.9 (−72, 28) |

### The 2×2, 120 fighters (6 per cell)

| Cell | Low ids | Position 1 | A broke | B broke | Neither | A−B dead at 60 s | A−B dead at the end | A−B blows landed |
|---|---|---|---|---|---|---|---|---|
| i0p0 | A | A | 4 | 1 | 1 | +5.2 (−3.0, 12.3) | +13.0 (−1.2, 24.5) | −93 (−200, 34) |
| i0p1 | A | B | 2 | 4 | 0 | −4.3 (−12.0, 3.3) | −7.5 (−23.2, 8.7) | +52 (−73, 175) |
| i1p0 | B | A | 1 | 1 | 4 | −0.5 (−10.3, 8.7) | −4.7 (−18.0, 8.3) | +44 (−65, 152) |
| i1p1 | B | B | 3 | 2 | 1 | −1.3 (−7.2, 4.5) | +2.0 (−11.5, 14.3) | −2 (−100, 113) |

### The factors

"Dead less" is that side's dead less the other side's; positive means that side died more. "Paired" pairs runs with the same layout and place deal and only the ids swapped.

| Factor | Fighters | Its side broke (decided) | Wilson 95% | Sign p | Dead less at 120 s | Dead less at the end | Paired, end: mean (sign-flip p), better / worse |
|---|---|---|---|---|---|---|---|
| **Low-id side** | 60 | 7 of 19 | 0.19–0.59 | 0.36 | −1.4 (−3.6, 0.8) | −1.6 (−4.4, 1.3) | −1.6 (p = 0.054), 14 / 4 |
| **Low-id side** | 120 | 9 of 18 | 0.29–0.71 | 1.0 | +1.0 (−5.0, 6.9) | +2.0 (−5.7, 9.3) | +2.0 (p = 0.60), 4 / 8 |
| **Position-1 side** | 60 | 8 of 19 | 0.23–0.64 | 0.65 | −0.5 (−2.8, 1.8) | −1.3 (−4.2, 1.6) | – |
| **Position-1 side** | 120 | 11 of 18 | 0.39–0.80 | 0.48 | +3.8 (−2.1, 9.6) | +3.5 (−4.1, 11.1) | – |
| Side A (the label) | 60 | 12 of 19 | 0.41–0.81 | 0.36 | +1.5 (−0.8, 3.7) | +1.9 (−1.0, 4.8) | – |
| Side A (the label) | 120 | 10 of 18 | 0.34–0.75 | 0.81 | −0.2 (−6.4, 5.8) | +0.7 (−7.0, 8.3) | – |

**Pooled over both sizes:**
- the low-id side broke 16 of 37 (43%, Wilson 29–59%);
- the position-1 side broke 19 of 37 (51%);
- Side A broke 22 of 37 (59%, Wilson 43–74%, sign p = 0.32).

**First landed blow:** by the low-id side in 23 of 40 runs (60 fighters) and 16 of 24 (120), and by the position-1 side in 25 of 40 and 12 of 24.

- **Id order.** At 60 fighters, the paired contrast hinted that the low-id side loses slightly fewer: −1.4 at 120 s (p = 0.027) and −2.1 at 180 s (p = 0.009). Four times were tested, though, and at 120 fighters the sign reverses (+2.0; better in 4 of 12 pairs). Taken together there is no id effect. Any effect left is a few percent of a side, against E5's gap of about 28 of 60 and E4b's one-defence-per-side gap of +15 of 30.
- **Place deal.** No main effect at either size, as expected: over random layouts, a layout's slot-0 and slot-1 places are exchangeable.
- **The layout itself** is the large source of variance.
  - The position-1 side's mean dead difference per layout ranged from −12 to +8 at 60 fighters (10 layouts; between-layout F(9,30) = 3.64, permutation p = 0.002).
  - At 120 fighters it ranged from −12.8 to +19.8 (6 layouts; F(5,18) = 2.18, p = 0.11).
  - The 120-fighter id × place interaction (+6.8, layout-bootstrap CI 1 to 13) is the same per-layout effect seen through 6 layouts. It is not a separate cause.
- **What about a layout favours a half** was not pinned down.
  - Spawn distance to the centre does not predict deaths: r = 0.00 per run at both sizes, and r = +0.09 and +0.24 per layout.
  - Having more of one's own side within 3 m at spawn goes with fewer deaths: r = −0.63 per layout (60, n = 10) and −0.36 (120, n = 6); per run, −0.29 (60) and −0.03 (120).
  - The likely mechanism is that a mixed cluster that starts locally outnumbered snowballs.

## Where id order and position enter the code (read-only, current main)

**Spawn** (`spawn_battle_sides`).
- **Places:** one uniform box, interleaved by creation order; no side-specific geometry (above).
- **Ids:** consecutive, A and B alternating. Id parity is therefore the side: Side A holds one parity in every world, the odd ids in E5 (65, 67, …).
- **Defence:** alternates within each side by index on the branch.

**The tick** (`living/authority/src/tick.rs`).
- **Motion and activity due lists** are sorted by `(due time, tie_draw(id, tick, salt))`, so an exact tie is a fair coin (fair-ties).
- **Wake rounds** run in the `wake` table's storage order. Windups that start in one tick tie by the coin, whoever is written first.
- **The combat cadence** (15 Hz) evaluates the class `id % 4` whose phase comes up this tick, and the classes' phases are re-drawn every second (`cadence_turn`).
  - Because id parity is the side, every cadence tick evaluates fighters of one side only.
  - Which side's classes come first is a fresh, symmetric draw every second.
  - The 1 Hz slots split the same way.
  - Symmetric in distribution, and no effect was measured.
- **Target choice** (`brain.rs`, `nearest`): the nearest seen person of `relation: enemy`, through `relation_ok` and the community stance. No id comparisons. Ties only at exactly equal distances.

**No code path gives the lower-id side or the position-1 side a standing advantage.** Before fair-ties, the cadence's fixed phases favoured one id of a pair by residue (docs/COMBAT.md, "The combat cadence's order turns every second"). With side = parity, every A residue was favoured against one B residue and disfavoured against the other, so even then there was no side-level bias. E4b's mixed heed-off result agrees: the low-id side broke 4 of 6, the other way from E5.

## The real-mind difference (open)

Read from E5's archived run directories (copied out of `~/slop-evidence/heed-e5-20261122.tar.zst`):

- **Mind service queue: ruled out.**
  - Over a whole run, B's mean queue wait is higher (2.9 against 2.2 s in r1, and so on).
  - That is composition only. B dies sooner, so fewer of its requests fall late, when the queue is empty.
  - Matched by time, the sides are equal. In the first 30 s: 8.0 against 8.0 s (r1), 7.7 against 7.7 (r2), 8.5 against 7.7 (r3), 7.3 against 7.6 (r4). Request counts per side were also equal: 141–171 each.
- **Spawn geometry:** a weak lead only.
  - Side A spawned nearer the centre in all 4 runs: 4.80/5.30, 5.30/5.48, 4.97/5.51 and 5.21/5.53 m. Combined, that is about z = 2 for random draws.
  - Side A had more friends within 3 m in 3 of 4.
  - In the no-model runs, distance to the centre does not predict the outcome; the friends-within-3 m relation does, weakly.
  - B was already behind at E5's first sample in 3 of 4 runs (A/B alive 46/42, 45/45, 48/46, 48/39). E5's warm-up deaths count before that sample.
- **Mind-written relations: not B-heavy.**
  - `relation_ok` (`brain.rs`) lets a personal `relation` row decide alone: a row with trust above −25 and no enemy word in its label **masks the community's `enemy` stance**, and that foe is no longer a target.
  - E5's minds wrote such masking rows about foes on both sides: A 24, 63, 27, 2; B 16, 32, 24, 9.
  - A's minds also wrote enemy-labelled rows about their own side (9, 15, 15, 3, against B's 0, 1, 1, 0). The final skill-use snapshots show no attacks on one's own side.
  - Still, a mind's wording can switch a fixture fighter's targets off. Worth knowing for any minded fight.
- **Prompts:** A7's and B7's first think prompts have the same sections. The only label-tied inputs a mind sees are the names (`A7`, `B7`) and the communities.

**So E5's 4 of 4 is compatible with per-layout chance (1/8) on a pre-fair-ties build. A real-mind side effect is not ruled out.**
- A free check would be E5's exact recording fixture on current main with the fake model: heed on, capacity 32, `sides_minded`, mixed defence.
- Run it with fixed layouts in both orientations (the diagnostic reducer's `layout`/`place`), so that each layout is cancelled by its mirror.
- A paid real-mind repeat needs the general coordinator's word.

## Proposed changes (fixture only; none made)

No engine fix is indicated: no factor shows, and no code path favours a side.

1. **Pair side comparisons by layout.** Any experiment that compares the sides (E4's capacity arms, E5's recording) should run each layout in both orientations, with the same places and the sides swapped. A layout alone swings a fight by up to a third of a side, more than the effects those arms measure.
   - **Change:** a fixed layout seed and a place deal in the shipped fixture.
   - **Safest route:** a new admin reducer beside `spawn_battle_sides`, as in the patch. Changing an existing reducer's arguments is not a safe module update. It needs bindings regenerated.
   - **Or:** two fixture laws (a script and `law_about` change, no columns).
   - **Risk:** fixture only, no game rule. Runs with a fixed seed are not comparable with E4b and E5's random-layout runs.
2. **Optionally decouple id parity from side:** alternate which side is made first from pair to pair (A,B,B,A,…).
   - Today every 15 Hz cadence class and every 1 Hz slot holds one side only. That is fair in distribution since fair-ties, but it couples two things a reader would not expect to be coupled.
   - **Risk:** fixture only. It changes `spawn_battle_sides`' output for any given world and draw, so old and new runs are not paired. Low priority, since no effect was measured.

## Not covered

- Heed on, minds, or the fake model. This check is the no-model, heed-off melee.
- Builds before fair-ties.
- Three or four sides.
- Other sites than Cullet's arrival box.
- What exactly makes a layout favour one half; the friends-within-3 m correlation is weak.

## Evidence

- **Run folders and reports:** `.local/side-asym/` (`runs60/`, `runs120/`, `report60.json`, `report120.json`, `pilot/`, series scripts, logs and load logs, `container.log`, `check.log`).
- **Archive:** `~/slop-evidence/side-asymmetry-20261123.tar.zst` (sha256 `502e90ef02140d1bc3d37c712450fd9db2493372ac18b9cb51950c0cfca62d9c`; this document as first written, before this line). It also holds the E5 analysis scripts and the diagnostic patch.
- **Tools:** `living/tools/side_swap.py` (run, report) and `living/tools/side_swap_diag.patch` (the diagnostic reducer).
- **Every world** (66, the pilot included) was paused, SQL-confirmed and deleted (`world_delete.py`; "deleted (SQL now 404)" for each).
- **Container:** `slop-sideasym-20261122` was stopped by SIGINT (exit 0, not forced; log clean: 0 errors, warnings only for long `init`/genesis calls) and removed with its volume by exact name.
