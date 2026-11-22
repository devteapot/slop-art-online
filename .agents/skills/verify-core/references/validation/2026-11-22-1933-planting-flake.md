# verify-core: the planting check's bush across a river (Spark, branch `planting-flake`)

## 2026-11-22: a staging race in the fixture, not a flake

**What failed.** sides-mixed-defence's scene gate on the Spark (2026-11-22 ~18:49, `gate-1122184906-8bd028-a-mechanics`, module `36189df3d`, 15-minute load about 8.9) failed `mechanics` on its first run with only `planting` false, and passed on its rerun. The story shows other characters planting, which the check (since `mechanics-flake-2`) does not count: it waits for a new bush within 3 m of A's own target. dev-box saw planting fail together with consensual conception in wolf-drift's gate (2026-11-21 ~17:52), both passing on rerun.

**What happened.** The driver's failure line: A at (309.3, 155.0), target bush at (83.5, 206.5), A started at (92.8, 217.7), A's activity `goto` phase 0, its feedback a string of "You come to a place new to you" further and further east. `plant` needs grass or dirt underfoot, so the driver sent A to the nearest berry bush by straight-line distance. Here that bush was across a river: A stood in forest on the east bank, the bush 14.5 m away on the west bank. `goto` routes round the river to a crossing far to the east; after the 90 s wait A was 220 m on its way. The route is right; the target was wrong for a 90 s check.

**Conception with it.** After the wait the driver places B beside A, the shelter beside B, and then installs the conceive sequence; A is still walking all the while (A–B 3.70 m at the conception setup in the Spark run). Under a gate's call latency A gets out of reach before it is told to conceive: dev-box's pair.

**Repro** (private server `slop-plantflake-20261122`, SpacetimeDB 2.14.1, pinned to CPUs 0-4,10-14; module `cc590da77` = origin/main; default seed; evidence `.local/living/verify/pf-probe/` and `gate-pf-*-mechanics/`):

- A walker placed at (92.8, 217.7) and sent to (83.5, 206.5) walks east: 84 m in 39 s (`probe/walk.py`). Deterministic: the seed's terrain is fixed.
- 2,000 random walkable spawns on that map (`probe/odds.py`, `spawn_crowd`'s rule): 120 (6.0%) have the nearest bush behind water, rock or wall. Twelve of them walked for real (`probe/arrive.py`, unloaded): 4 not there after 95 s (50–216 m off; up to 222 m from the start), 8 arrived in 4–37 s. About 2% of worlds, whatever the load; the gate's load only coincided.
- The full driver with one added line placing A at the failing start before step 5 (`drivers/forced_old.py`), under the load below: **main's driver failed planting 2 of 2** (`gate-pf-r1-1`, `r1-3`: 22/23, A at (325.3, 151.8) and (301.6, 156.5) still on `goto`, A–B 5.85 and 3.04 m at the conception setup). The fixed driver passed 23/23 2 of 2 (`r1-2`, `r1-4`, A–B 1.00 m).

**The fix** (`living/tools/verify_mechanics.py`, test-only). `plant_spot` reads the `terrain_chunk` rows around A and picks the centre of the nearest grass or dirt tile within 20 m whose straight line from A crosses only walkable tiles; A walks there and plants, and the check waits for a new bush within 3 m of that spot. With none (36 of the 2,000 spawns, mostly deep forest), A is placed on a plantable tile at the nearest bush (`place_at`) and the driver says so. After the wait A is set idle before B is placed beside it. The driver prints where A walks. From the twelve blocked starts the new spots were reached in 0–7 s.

**Proof.** Fresh `verify-gate-pf-*-mechanics` worlds launched by `verify.py launch` and driven with `--gate-world` as the gate does, 4 drivers at a time, with six `python3` busy loops pinned to CPUs 0-4,10-14 (the server's cores; host 1-minute load 9–13 at the round ends):

| Round | Driver | Results |
|---|---|---|
| r1 | forced start: 2 main, 2 fixed | main 22/23 ×2 (planting); fixed 23/23 ×2 |
| r2, r3, r4 | fixed, random spawns | 23/23 ×12 |
| r5 | final driver: forced start, a fallback probe (A at (329.8, 214.0); snapped to a tile centre it found a spot 20.0 m off), 2 random | 23/23 ×4 |
| r6 | final, random | 23/23 ×4 |
| r7 | final, random | 23/23 ×2; 22/23 ×2: "force: blows land on the yielded, and striking them is news" |
| r8 | final: a fallback probe (A at (352.5, 206.5): no spot, placed at (375.5, 209.5)), 3 random | 23/23 ×4 |

Planting passed in all 30 fixed-driver runs (25 random spawns), and consensual conception with it. r2–r4 ran the fix before two small changes (the "walks … m" line, and the fallback placing A on a plantable tile by the bush instead of at the bush); r5–r8 ran the committed driver.

**Not this change: r7's two failures.** `gate-pf-r7-1` and `r7-2` failed only the yielded-blows check: J yielded (story "Walker10 yielded to Walker9 (×2)") and felt nine blows "though you had yielded", but the story has no "struck …, though … had yielded" entry, so the news wait ran out. The planting change does not touch I, J or the chronicle. In `act.rs` the news is written only when `!struck_since_yield`, which is `v.hurt_ms >= <the yield mark's at_ms>`; a yield made in the same tick as the blow that provoked it carries the same millisecond, so every later blow may count as already struck since the yield. That is a hypothesis about a rules race, not shown here; it needs its own investigation before any rules change.

**Not covered.** Other drivers and scenes; dev-box's conception failure itself (its evidence is on dev-box; the mechanism is shown here by the A–B gaps); the steering driver.
