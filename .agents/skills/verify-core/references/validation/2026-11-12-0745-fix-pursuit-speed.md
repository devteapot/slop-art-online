# verify-core: fix-pursuit-speed

## 2026-11-12 fix-pursuit-speed: every pursuit keeps at least its target's speed (Spark)

Branch `fix-pursuit-speed` from origin/main `a07f5919` (origin/main `f7af6d49`, skills-layout, merged), the trial service `slop-trials-stdb` (2.14.1, port 3320), `scoped`, private `CARGO_TARGET_DIR`. Change: `motion::toward`'s floor (at least the speed the target draws away at, plus 0.3 m/s, up to the pursuer's own) for every pursuit, not only the movement intents.

- `chase` (extended: a fresh wolf each chase, `PURSUERS`, `MODES`, `blow_s`, prey going 55 m straight away). "Before" worlds were built from this tree with main's condition put back (the one line); "after" with the fix. Fresh-wolf runs: `core-pursuit-b2-073614` / `core-pursuit-a2-073651` (wolf and person, 5 each), `core-pursuit-b3-074802` / `core-pursuit-a3-074817` (wolf against a walker, 8 each). The first blow's start:
  - wolf against a walker: before 2 of 9 within 55 m (19.0, 19.4 s, both as the prey slowed to stop at its end); after 11 of 11, median 1.9 s (1.3–2.6);
  - wolf against a runner: before 3 of 5, median 13.4 s (13.2–14.2), all at the prey's end; after 5 of 5, median 4.4 s (4.1–4.6);
  - person (`attack`, `run: true`) against a walker: before 1 of 5 (24.2 s, at the end); after 5 of 5, median 2.9 s (2.7–3.6);
  - person against a runner: before 2 of 5 (14.1, 14.4 s, at the end); after 2 of 5 (7.2, 10.8 s), the other 3 slower than their runner;
  - closing to the catch distance (3.2 m wolf, 2 m person) unchanged: a wolf 0.2–1.3 s either way.
- Earlier attempts (`core-pursuit-before-070039`, `core-pursuit-after-070254`) reused wolves 3 s apart (winded and tired, about 4 m/s against 5.1), had prey turn back at the line's end into the pursuer, and set the prey's walk before the pursuer's attack (at night the prey could be out of sight at the start: pursuers that never moved). Kept as evidence only; the scene now avoids all three.
- `skirmish` 8/8 (`core-pursuit-isl-080837`, island). `wildlife` 14/14 (`core-pursuit-wl2-082256`, stage1-acts, the migration included); a first world (`core-pursuit-wl-081001`) stopped at grazing: its deer stood on grass "grazed bare" (a truthful refusal).
- `just living-check` passes on the merge.
