# combat-switches: the fighter table and the combat feed on the game client (verify-ui)

- **Branch:** `combat-switches`, from `origin/main` `75e26fcab`, laptop.
- **Server:** the shared `sao-living_spacetimedb_1` (v2.14.1, 127.0.0.1:3300).
- **Client:** release build from this branch's working tree, in a private `CARGO_TARGET_DIR` (`~/.cache/combat-switches-target`), through `build-slot` with `BUILD_SLOTS=1`. No owner session was open.
- **Runs:**
  - `ui-cs-1120-1505` (island; `verify-ui-cs-1120-1505`, deleted): the switch, death, ui and regression scenarios;
  - `ui-cs2-1120-1638` (island; `verify-ui-cs2-1120-1638`, deleted): the cost run and a second `law-override`.
- **Evidence:** `.local/living/verify/<run>/ui/`, with copies of each batch's `checks.json` in this worktree's `.local/cs-evidence/`. No model call was made.

## Shape change and maintenance

The surface changed in four places:
- `net::Feed` gains `fighter_table` and `combat_feed`;
- `my_combat` moves from the base set into the perception set;
- the client's log lines gain `fighters … combat_feed …` and a fighters' `missing now`;
- the seen log gains `fighters`, `combat` and two `tables` keys, and the dump gains `death`.

`maintain-verification-skill` was scoped to this change: the coordinator read the changed sources itself, with no source-wave subagents. Updated:
- **Pages:** `features/combat-switches.md` (new), a `features/README.md` row and the `net.rs`/`combat.rs` source rows, `features/battle-views.md` (log formats, start state, `my_combat` in the set) and `SKILL.md` (the four scenarios).
- **`scripts/check.py`:** four `@scenario`s (`combat-switches`, `-death`, `-ui`, `-cost`) and `delivery_cost` (factored out of `battle-views-cost`, which now calls it). `DELIVERY_LAWS` grows to six, and `feed_of` returns five fields.

Harness fixes found on the way, each re-driven:
1. **`battle-views` was stale since `bv-defaults-on`.** Its first check wanted both table laws off, and from the new defaults its steps could reach only 7 of the 8 combinations. It now sets both off first. Its regexes were updated for the new `tables:` field and the third `missing now`.
2. **The frame checks counted a creature entering sight just before a call as missing.** This was in `battle-views`, `law-override` and the new scenario: the window started 300 ms before the call, but "kept" was taken at the call. The window now starts at the call.
3. **A re-run under the same run name matched the previous `client.log`.** The sync was written before `drive.py` cleared its `.go` files, so the walk ran before the client was ready. `fresh_log` now removes the old log before each long drive.
4. **`combat-switches` could kill a resident.** One resident took about 40 strikes over three runs and died on `ui-cs-1120-1505` (#2, Cuth Marrow, a scratch world). The scenario now holds the two healthiest residents, strikes the healthier, never one under 50 hp, and checks that both are alive.
5. **Smaller ones:**
   - the striker's token is read after it joins;
   - the opening strikes go on until the authority holds fighter copies for me (a refused strike also answers 200);
   - the death truth is snapshot while dead (`sync:truth`), since a join clears the feed;
   - the cost walker does not jump (see the authority gap below);
   - the client's token is read once a drive is on.

## Product fix found by the death check

On main's client, a reconnect while dead joined a new stranger at once: `Disconnected` reset `join_sent`. The death screen went, and the join cleared the dead character's feed (`combat::clear_feed`). Now `Net::died` is set when the played character dies and cleared by `rejoin`, and a reconnect does not join while it is set. Proven by `combat-switches-death`'s dumps `04` in both arms.

## Results

**`cargo test --release -p living-game`:** 204 passed, 0 failed, 1 ignored. The new and changed tests:
- in `net::cue_tests`:
  - every one of the 32 sets' queries;
  - all 64 law states read from a world's rows;
  - each table law, the fighter law and the feed law flipped in place, in every combination;
  - a reconnect choosing the tables first;
  - the fighter copy row and the `combat_feed` row mapping;
  - the fighter kill switch keeping rows;
  - the pending-feed bound;
- in `combat::feed_tests`:
  - the death screen equal from `my_combat`, from the feed and from both;
  - ids forgotten by time, not by the cache.

**`cargo test --release -p living-rules`:** 359 passed, 0 failed, 17 ignored, including the `ui::` skill-name guard (38 tests).

**`combat-switches` (`ui-cs-1120-1505`): 197 / 197** on the final run (`checks-cs4.json`).
- **The calls:** 24 steps. Every client switch took 18–36 ms, with nobody, no character and no fighter missing in the switch line or in any frame. Tick gaps were 111–120 ms, under the 150 ms bound (the quiet gap was similar).
- **Combinations:** fighters × feed in all 4 states under both tier states (8), with the copy tables off and on.
- **The fighter kill switch:** `seen_fighter_copy` empty after 42–51 ms, my copies private. Law on: my 2 copies public, none private.
- **Events:** the authority wrote 30 `combat_seen` rows for me (polled every ~60 ms) and the client took all 30: 16 through `my_combat`, 14 through `combat_feed`. 28 of them were around the combat-feed switches. 15 strikes, none skipped.
- **Reconnect** with both laws on: the first set was `tables: motion true characters true fighters true combat_feed true`, and `my_combat` was read once. A fresh client chose only that set. The laws and residents were restored.
- **Earlier runs, kept:**
  - Run 1 passed 193 / 196 (`combat-switches-run1.json`). Its fighter checks failed until fighters existed: the two opening strikes were refused, which drove fix 5.
  - Run 3 passed 197 / 198. Its one "missing" creature was #22, entering sight 27 ms before the call: fix 2.

**`combat-switches-death`: 12 / 12.** In both arms, `combat_feed_on` off (`my_combat`) and on (`combat_feed`):
- the death screen equals the authority's rows: killer 4134 and witnesses {1, 3, 39, 57, 75, 4134, 4135, 4137, 4139};
- it stays the same after the law flips while dead, back, and across a reconnect while dead;
- the death row came from the arm's own source;
- with the law on, the reconnect read `my_combat` once (10 rows).

Across the arms, the cause words ("Killed by a short young woman in a blue smock …"), the killer and all nine witnesses' names are equal.

**Regressions:**
- **`combat-switches-ui`** (both new laws on): 136 / 137. Camera 60/60, talk 22/22, far 11/11, death 5/5, bar 14/14, own 6/6, move-off 8/8 and committed 7/8. Every client read the fighter table and the feed.
  - `committed`'s one failure, "the walk follows once the windup ends", also fails with the laws off (`checks2-committed.json`), so it does not come from them.
  - The body did walk: drawn 4.3 m on at `a4`, and the next segment (`b0`) 4.8 m on. The check compares the authority row's `x, y`, which is the start of the motion segment, so a walk that starts as one long segment reads 0 m. This is a fragile check from before this change. It is not fixed here.
- **`battle-views`:** 144 / 144, with all 8 combinations, the kill switch at 40–43 ms and the reconnect and fresh client passing.
- **`battle-views-ui`:** 3 / 3, with camera, talk and far passing.
- **`law-override`:** 68 / 72 on both worlds, the same 4 failures each time, all in the cover laws.
  - `cover_sight_on`: the client reacted after 5.45 s, against a 1 s bound, and the tick stalled 829–936 ms.
  - `cover_brush_min_fill`: the client reacted after 2.44 s, and the tick stalled 194–202 ms.
  - The client laid each override over within 12 ms. The wait is for the authority's `cover_law` row, while the authority's tick fell to 25 a second: the cover mask is computed on the authority. Nothing in this change touches cover.
  - The 2026-11-19 record measured 13–40 ms for the same steps. This is reported as an authority-side observation, not attributed further. Every delivery step passed.

**`combat-switches-cost` (`ui-cs2-1120-1638`): 19 / 20.** Four drives (off, on, off, on) per law and place, through the byte relay; the walker 1.2 m away on an octagon. Each arm had 18 refusal rows and 1–2 fighters read.

| Law | Place | kB/s off → on | near p50 off → on | near p90 off → on | segments |
| --- | --- | --- | --- | --- | --- |
| `fighter_tables_on` | square | 1.98 → 2.62 | 21 → 20 | 33 → 31 | 139 / 169 |
| `fighter_tables_on` | open | 0.82 → 0.82 | 20 → 20 | 30 → 29 | 129 / 128 |
| `combat_feed_on` | square | 1.23 → 1.11 | 21 → 22 | 32 → 41 | 126 / 64 |
| `combat_feed_on` | open | 0.80 → 0.73 | 19 → 18 | 30 → 29 | 118 / 118 |

- **The failure:** the arm `combat_feed_on-square-1-on`. The walker was out of sight for part of it (27 segments, no fighter read), the same fixture weakness recorded for `battle-views-cost`. That arm also gives the square's on-arm p90 its 49 ms (its twin had 41).
- **Square kB/s with the fighter table:** +32%. Each fighter copy change reaches the client as a row with the viewer's identity and the copy's key. The arms vary ±0.5 kB/s on the square with the residents' movement, as `battle-views-cost`'s did.
- **First cost attempts, kept:**
  - Run 1: every arm failed its fighting check, because jumps put no rows in my feed.
  - Run 2: failed by the stale log, fix 3. During it the walker jumped while being placed, and that jump never ended (below).
  - Run 3 (`ui-cs-1120-1505`): the walker stayed stuck.

## Authority gap seen (not changed here)

On `ui-cs-1120-1505`, verify.py's player (#4134) used `use_skill jump` at a point while `drive.py` was also moving it with `place_at`. Its `activity` row then stayed as follows (`.local/cs-evidence/stuck-jump-activity.json`):
- `skill jump`, `phase 0`, `node 65533`;
- target point (415.2, 261.7), `started_ms 1795186522720`;
- `ends_ms` 18446744073709551615 (`u64::MAX`).

`combat::rooted_now` is true for a dash, so every later `human_move` was deferred, and the body never moved again. An admin `set_behavior` did not clear it. My explanation, likely but not proven: a teleport during a dash leaves the dash unfinishable. That world was deleted.

## Not covered

- Scale: one client. The battle-density privacy and cost are the authority's series.
- The commitlog growth with `combat_feed` (dev-box's measurement before its default flips).
- A real window.
- A connection that dies before a death and returns after it (the one read covers it, but it was not driven).
