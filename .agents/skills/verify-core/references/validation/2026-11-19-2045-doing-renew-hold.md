# doing-renew, pacing-neutral: the row held until the next evaluation (verify-core)

This follows [2026-11-19-1915-doing-renew](2026-11-19-1915-doing-renew.md), which recorded the first design: a second graph pass that began the leaf again at once. At the coordinator's request that design is replaced, because it removed the idle second and so changed pacing (gather +12%).

Branch `doing-renew` at `67527f4c` (code), on main `440ca6a7`; main's authority is identical to `3df6e1f1`. Server: the worker's own `slop-doingrenew-stdb` (v2.14.1, 127.0.0.1:3441), no battle lock, no mind service, no model calls. Long runs were launched with `VERIFY_LEASE_SECONDS=2700`.

## The change

- **Hold.** `act::finish_as` → `town::hold`: a continuous act card (not `record`, `aside` or `turn`) that ends well, for an AI body no person plays, under the `renew_in_place` law, keeps its `doing` row as it was. Nothing is written. A `doing` row with no activity behind it is held.
- **Begin.** `act::begin` with nothing under way → `town::unhold`: the held row gives way, kept in the transaction's `ENDED`. The same activity shown again (`town::shown`, same skill, target, `indoors`, spot within 0.5 m) keeps its `since_ms`, and subscribers get one update. Anything else replaces it.
- **Settle.** `brain::evaluate` → `town::settle` at its end: with nothing under way, a held row is deleted. The exception is the evaluation that read that activity's end and came to `Ok` with nothing else (`read_end`; not a finished `seq` root, not a played body): it keeps the row, and the next evaluation decides.
- **Readers.** `perception::visibly` reads a held row as under way past its end; `perception::doing_of` names its skill in a mind's scene.
- **Timing.** The begin timing is main's: the brain's second pass is gone.

SpacetimeDB: as in the first record. A same-key delete and insert in one transaction is one update to subscribers (SDK 2.14.1 `derive_updates`; docs: one update per transaction, https://spacetimedb.com/docs/clients/subscriptions/semantics). No column and no table changed.

## Runs

- **`scenes.py doing_renew`, `core-hold2` (67527f4c): 12/12.**
  - Under a `desires` root, 34 s: 753 samples, 0 missing, 60 held. The next rest began 550, 1002 and 999 ms after the last ended (main 933–1001), with `since_ms` kept.
  - Under a `first` root: gaps 1001 and 999 ms.
  - Walk-off removed the row after 102 ms.
  - Law off: 52 samples missing, gaps 717 and 1000 ms.
  - `core-hold1` (the earlier commit that wrote `until_ms` 0 at the hold) passed too.
- **`scenes.py sleeper`, `core-sleep5`: 25/25.**
- **`town.py` (island), `core-town5`: 22/23.** The only failure is the known flake "a resident faces someone who comes up behind them". Main failed the same check in both of its runs today (`core-town0`, and `core-town3` at 22/23). Morning, work, evening and night checks all pass, including "they leave home" and "each person's new day begins once".
- **`just living-check` on 67527f4c:** ok in 518 s (authority, mind+viewer, game, game-tests, viewer-wasm, rules-tests, seed-laws, frame-tests, script-gate).

## Measurements

Realm-4 (default seed), 120 s of `doing_deltas.py` then three 20 s `bench.py` windows. One world at a time, alternating branch and main, host load 4–8.

| run | gather starts / gatherer-minute | blinks/s | owner inserts/deletes/updates per s | tick ms/s (3 windows) | `tick.wakes` ms/s |
|---|---|---|---|---|---|
| branch `core-pace-b3` | 14.35 (84 gatherers) | 3.64 | 10.31 / 10.40 / 13.84 | 22.22, 19.67, 21.66 | 3.72, 3.23, 3.80 |
| main `core-pace-m3` | 14.25 (85) | 14.88 | 23.25 / 23.30 / 1.62 | 23.39, 20.68, 18.34 | 4.15, 3.60, 2.83 |
| branch `core-pace-b4` | 14.29 (87) | 3.50 | 10.68 / 10.78 / 14.24 | 23.17, 12.12, 15.37 | 4.04, 2.18, 2.63 |
| main `core-pace-m4` | 14.29 (85) | 15.28 | 23.20 / 23.24 / 1.53 | 21.40, 19.97, 22.01 | 3.84, 3.20, 3.65 |

- **Pacing:** gather starts match main within noise (14.29–14.35 against 14.25–14.29).
- **Tick:** mean tick 19.0 ms/s on the branch against 21.0 on main; the window-to-window spread on this shared host is larger than the difference, so it has not risen.
- **Changes:** owner events per second fall from about 48 to about 35. Row operations on the wire are about equal (48.4 against 49.8), since an update travels as a delete and an insert.
- **Blinks left on the branch** are a different activity in between: a walk to the next bush, a turn.
- **Earlier commit:** the version that wrote the hold (`until_ms` 0, `core-pace-b1`) wrote one extra update for each finish followed by something else: owner events 53.4/s against main's 48.8. That is why the hold now writes nothing.

## Not covered

- `doing_cost`, `fights`, and the 216-character or battle profiles.
- Only the reducer's own tick time was measured, not the views and subscription work after it. verify-client's cue timing checks it from a client.

Evidence (worktree, not in git): `.local/living/verify/core-hold1/`, `core-hold2/`, `core-sleep5/`, `core-town5/`, `core-pace-b1..b4/`; main's `~/slop-doingrenew-target/main-wt/.local/living/verify/core-pace-m1..m4/`. All archived in `~/slop-evidence/doing-renew-hold-20261119.tar.zst`.
