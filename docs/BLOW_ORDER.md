# Blow order: same-tick blows and id order

A free diagnosis made on 2026-11-22 for the general coordinator, branch `blow-order` (from `origin/main` `9ed12f51d`). It used no model calls. **The branch is a diagnostic record and is not for merging:** it adds a fixture reducer and unconditional `duel …` log lines in the tick's hot path. No engine fix was applied.

**Question.** When two blows complete in the same tick, does the lower id land first? If it did, that would be a fairness bug in every duel. (E4b's read-only list, `docs/ATTENTION_E4.md` §7.4 on `heed-e4`, item 1.)

**Answer.**
- **No id-order bias.** In forced same-tick ties, the lower id won 75 of 148 (50.7%, 95% CI 42.7–58.6).
- **The tie-break is write order.** The blow whose activity row was written first resolves first: 292 of 292 tied exchanges.
  - Write order comes from storage and evaluation history, not from the id.
  - It is deterministic and invisible to the fighters.
  - SpacetimeDB documents no order for equal keys.
- **A lethal tie is decided by that order alone.** The blow resolved first kills, and the other blow is deleted unlanded.
- **In natural duels this did not happen once:** 0 of 69 decided duels (95% CI 0–5.3%).
- **Fix proposed:** a seeded, per-tick fair tie-break (below). Whether simultaneous blows should instead trade (a double kill) is a design call for the owner.

## 1. The code path (origin/main `9ed12f51d`)

**Where completions run.** `tick` step 2, `living/authority/src/tick.rs:69-74`:

```rust
let due: Vec<u32> = ctx.db.activity().ends_ms().filter(..=now).map(|a| a.id).collect();
for id in due { if let Some(a) = ctx.db.activity().id().find(id).filter(|a| a.ends_ms <= now) { act::progress(ctx, a, now); } }
```

- **Key order.** Blows due in one tick resolve in `ends_ms` order, so an earlier-ending blow goes first. That is fair.
- **Exact ties.** Rows with the **same** `ends_ms` come back in the index's order for equal keys. The module imposes no order of its own.
- **When ties occur.** A windup ends at `now + duration` (`act.rs:1279`, `perform`). The spear attack's windup is a fixed 750 ms and the strike's is 350 ms (`skills.rhai:1481`, `:1949`). So two windups of one skill that start in the same tick (one `now`) end at the same millisecond.

**The tie-break (SpacetimeDB 2.14.1, versioned source).** In `crates/table/src/table_index/btree_index.rs` at `v2.14.1`, a non-unique B-tree index is a `BTreeMap<K, SameKeyEntry>`. The rows for one key are kept as follows (`same_key_entry.rs`):

- **Up to 512 rows** (4096 / 8-byte row pointers): a `SmallVec` in **push order**.
  - Every insert, and every update (a delete then an insert), pushes the row to the end.
  - A delete is a `swap_remove`, so the last row moves into the gap.
- **Over 512 rows:** a `HashSet` with `RandomState`, which "entails that the iteration order is not deterministic" (the source's own comment).

The [index documentation](https://spacetimedb.com/docs/tables/indexes/) (2.0.0) gives no order for equal keys or for range-scan results. **So the order is the order the rows were last written.** It is not their id order, and nothing guarantees it.

**What a landed blow does to the other's pending blow:**
- **Non-lethal hit:** no interrupt and no stagger. `damage` (`act.rs:2681`) changes health, perception and wakes. The victim's committed windup still completes in the same tick.
- **Lethal hit:**
  - `damage` calls `die_unseen` (`act.rs:2849`), which deletes the victim's activity (`act.rs:3076`).
  - The tick then finds nothing due for that id (`find(id)` is `None`).
  - Had the row survived, `progress` would drop it anyway, because its actor is dead (`act.rs:1675-1677`).
  - **The second blow never lands.**

**Who writes first in a tick.** Windups are written during evaluation, in that loop's order:
- **wakes:** the `wake` table scanned in storage order (`tick.rs:94`);
- **the combat cadence:** `mind_state.fast_until` index order, filtered by `(id + tick) % every` (`tick.rs:121`);
- **motion events:** `body.next_ms` index order (`tick.rs:52`).

None of these sorts by id; each follows earlier writes and free storage slots.

**Item 2 is a separate effect: the combat cadence.** A fighter is evaluated when `(id + tick) % 4 == 0` (15 Hz).
- **Same cadence class** (id difference ≡ 0 mod 4): two fighters ready in the same tick are evaluated together, and their windups tie.
- **Otherwise** they are evaluated 1, 2 or 3 ticks apart. The fighter evaluated first can lead every later exchange by that margin.
- This is reasoned from the code and seen in 2 forced-tie duels (§3). It was not measured.

## 2. The fixture and the runs

**`spawn_duel`** (admin reducer, `living/authority/src/lib.rs`, branch only) makes two identical spear duellists on an east–west line, each attacking the other by id.
- **Clone:** the second is the first's clone (sex, age, genes and ways, vitals and breath, items).
- **Arguments:**
  - `gap` sets the distance between them.
  - `between` sets the number of fillers made and killed between the two, so the ids differ by 1–4, one per cadence class.
  - `low_west` puts the lower id west.
  - `east_first` installs the east duellist's graph first.
  - `hp` sets both healths; 5 means one blow kills.
  - `defend` is none, `block` or `dodge` when threatened.
  - `hold_east` makes the east duellist wait until the driver installs its attack graph.
- **Logs:** the branch logs `duel windup|complete|blow|dodged|drop` in the order the tick resolves them (`act.rs`, `DUEL_LOG`).

**`living/tools/blow_order.py`** runs batches on a scratch world:
- It kills every character, then spawns up to 16 pairs 25 tiles apart, beyond the 11-tile sight.
- It waits until each pair has a death, or 150 s.
- It reads the module log and attributes events by the pair's two ids.
- **Lower id side:** alternated, independently of the install order.
- **Tie:** both attack windups end at the same millisecond.
- **Tie-decided duel:** the loser's last windup ended at the killing blow's time and never landed.

**Where it ran:**
- **Server:** a private `clockworklabs/spacetime:v2.14.1` container (`slop-blow-order-stdb`, pinned to CPUs 0-4,10-14), with the world `verify-bo-d` (seed `eco-a`, scoped build).
- **Clock:** the real clock. `det_clock` was not used: a spawn reducer takes the wall clock. Exact ties need only a shared start tick, so they reproduce under either clock.
- **Heed:** off (the law is not on main). There was no mind service and no fast lane.
- **No timing was measured.**

## 3. Results

| Arm | Duels | Decided | Decided by a same-tick tie | Lower id won | Other |
|---|---|---|---|---|---|
| **Forced tie**: in reach (gap 1.0–1.3), 5 hp, no defence; 2 replicates | 151 | 151 | **148 (98%)** | 77/151; **75/148 tie-decided (50.7%, 42.7–58.6)** | The second-installed won **149/151 (98.7%, 95.3–99.6)**. |
| **Natural**: walk in (gap 2.5–6), full health, no defence | 35 | 35 | 0 | 17/35 | 0 tied exchanges; the first-installed won 32/35. |
| **Natural**: the same, blocking when threatened | 34 | 34 | 0 | 15/34 | 0 tied exchanges; the first-installed won 20/34. |
| **Natural**: the same, dodging when threatened | 31 | 0 in 150 s | n/a | n/a | 141 tied exchanges, all dodged. |
| **Natural, all decided** | 69 | 69 | **0 (95% CI 0–5.3%)** | **32/69 (46.4%, 35.1–58.0)** | The first-installed won 52/69 (75%). |
| **Offset control**: forced tie, but the east graph installed 50–150 ms later | 70 | 70 | 0 | **33/70 (47.1%, 35.9–58.7)** | The earlier starter won **70/70**. |

**By id gap**, tie-decided duels (lower id won):
- id difference ≡ 0 mod 4: 19 of 36;
- ≡ 1: 20 of 40;
- ≡ 2: 20 of 40;
- ≡ 3: 16 of 32.

**Write order.** The first-written windup resolved first in **292 of 292** tied exchanges across all arms: 69 + 82 forced and 141 in dodge duels. 2 of the 292 shared their `ends_ms` key with another pair.

**Effect size of the lower id:**
- **Tie-decided:** 50.7%, +0.7 pp over even (95% CI −7.3 to +8.6).
- **Untied:** natural plus offset, 65 of 139 (46.8%, 38.7–55.0).
- **Tied minus untied:** +3.9 pp (−7.6 to +15.5).
- **No id effect** is detectable in either.

**Reading:**
- **In this fixture, the second-installed duellist won the ties.** Its windup was logged, and so written, first in the tick, so it resolved first. Both installs wake their duellist, and the wake round (`wake().iter()`, storage order) evaluated the second first. Why storage returns it first was not traced further.
- **In natural duels, the first-installed usually won.** In the logs read, the first to wind up was the first to land, and the blows then alternated. Health falls in lockstep, so the first to land is the first to kill.
- **Both are first-mover effects, not tie-breaks.** In the offset control, the earlier starter always won, whichever side held the lower id.
- **Two cadence cases.** Two forced-tie duels had a first exchange that was not lethal (weak duellists, 3.9 damage). In both, the next exchange was led by the lower id by one tick. Their id difference was 3, the cadence class in which the lower id's evaluation tick comes first in 3 of 4 phases.

## 4. Is it a fairness bug?

**Not an id-order bias.**

It is a small, real fairness defect in how simultaneous blows are handled:
- Two blows due at the same millisecond are resolved one after the other, in an order that comes from storage history.
- That order is not part of any rule, and no fighter can see or influence it.
- When both blows are lethal, it alone decides who lives. The other blow is deleted unlanded, and its attacker is told nothing of it.
- Above 512 rows sharing one `ends_ms`, the order becomes non-deterministic in 2.14.1. That breaks `det_clock` replay in a very large battle.

**How often it matters.**
- Exact ties need both windups to start in the same tick. Among AI fighters, that means a shared wake round, or the same cadence class becoming ready together.
- A player's windup starts in its own reducer call at wall-clock milliseconds. A player's blow ties another only in the same millisecond.
- In 69 natural decided duels, none was tie-decided. Ties occurred, but only where blows were dodged.
- Large battles have more same-tick windups and more fighters near death, so the share there is unmeasured.

## 5. Proposed fix (not applied)

**Recommended: a fair, seeded tie-break.**

Order the due list by `(ends_ms, mix(id, tick))` instead of index order:

```rust
let mut due: Vec<(u64, u32)> = ctx.db.activity().ends_ms().filter(..=now).map(|a| (a.ends_ms, a.id)).collect();
due.sort_unstable_by_key(|&(e, id)| (e, splitmix64(id as u64 ^ k_tick.rotate_left(32))));
```

- **Fairness:** each exact tie becomes a coin flip per tick, independent of id, write history and storage slots, the same idea as the bystander-wake rotation. Earlier ends still go first.
- **Determinism:** it is deterministic under `det_clock`, which seeds from the tick count. It also removes the 512-row non-determinism.
- **Cost:** one sort of the tick's due list (a handful of rows, already read). It needs no new table or column.
- **Risk: low.** It changes only who wins exact ties. `det_compare` against main will differ from the first tied tick (expected; state it as the change's signature). Run verify-core's combat scenes (duel, battle, pack) and verify-player's death scene.
- **Same treatment elsewhere:** `body.next_ms` (`tick.rs:52`) has the same equal-key order, and approach windups start there. A matching sort there makes who winds up first fair too.

**For the owner: simultaneous blows trade.**

A blow due at or before its attacker's death in the same tick still lands, so a double kill is possible.
- **Implementation:** keep the tick's due activity rows as a snapshot. Complete an attacker who died this tick at `died_ms >= ends_ms`, instead of dropping it. `die_unseen` deletes the row, so the snapshot is required.
- **Fairness:** this is the physically fair reading of equal times.
- **Risk: medium.** It touches the death path and `complete`/`apply` for a dead actor: practice, stamina spend, `skill_use` outcome, chronicle killings by the dead, a death record naming a dead killer, and a double kill as a new outcome for UI and minds. It changes the feel of combat, so it is the owner's decision. The seeded tie-break can ship first; this would supersede it.

**Item 2, the cadence lead:** its effect on duel outcomes is unmeasured here. If the coordinator wants it measured, a paired run on this fixture would do it. Hold the first exchange non-lethal (full health) and force a common ready tick, then compare id differences ≡ 1 and ≡ 3 mod 4. A per-tick rotation of the cadence phase would be the matching fix, like the wake rotation.

## 6. Evidence

- **Runs:** `.local/blow-order/{tie,tie2,natural,offset,smoke}/` holds `duels.json`, `pairs.json`, `summary.json` and the world's `duel` log lines (`module.log`). The check log is beside them.
- **Archive:** `~/slop-evidence/blow-order-20261122.tar.zst` (sha256 `7894507d0499ee5d1a62dc12db82a00969f5b4356b295fa453bf9898aa2dbf35`).
- **Reproduce:**
  1. `verify.py launch --run bo-d --seed eco-a` on a private server, from this branch.
  2. `python3 living/tools/blow_order.py run --db verify-bo-d --container <c> --url <u> --out <dir>`, with:
     - **tie:** `--gap 1.0,1.3 --hp 5 --defend none --vary-first --batches 10 --per-batch 16 --seed 11` (replicate `--batches 12 --seed 12`);
     - **natural:** `--gap 2.5,6 --defend none,block,dodge --vary-first --batches 16 --seed 21`;
     - **offset:** `--gap 1.0,1.3 --hp 5 --defend none --hold 100 --batches 10 --seed 13`.
