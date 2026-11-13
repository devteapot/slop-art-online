# Look bands

Since `look-1-auth` (2026-11-12, docs/LOOK.md §4). A person's look band follows their life: infant (stage 0), child (stage 1 under the `look_bands()` law's `youth` years, shipped 12), youth (to under `adult` years, 18, at stage 1 or 2), adult, elder (stage 3) — `living_rules::look::look_band`. Each `look` row stores `next_ms`, the world time its band next changes (an age threshold or a stage end, `next_change`), and housekeeping reads only the due rows through the `look.due` index (`look.due().filter(..=now)`) after the second's stage changes. `grew` rewrites the look in the stage change's own transaction. A changed line is written to the `projected` rows of everyone who sees the person (the `projected.body` index). A script install (`install_source`) retimes every row once (the life and band laws may have changed); `relook` (admin) moves a world to its seed's looks. A death deletes the row. No scan of all people or looks is added to the per-second path.

## Sub-features

- At a lab pace, a child crosses 12 (child → youth) and then 18 (youth → adult): one rewrite each, both from the due read; its stage change at 16.1 years keeps the youth line.
- An adult's stage change to elder rewrites the look in `grew`, once; no poll sees the elder stage without the elder band or the reverse.
- The elder's death deletes his look row.
- In the source: housekeeping calls `look::due`, which reads the `look.due` index range; `look` rows are iterated only in `retime_all` (a script install) and `relook` (an admin's call).
- Cargo: `look::tests::` (bands, `next_change`, `pool_pick` vectors, `phrase`), `script::tests::look_laws_are_read_and_checked` and `cullet_check::tests::{composed_worlds_keep_the_shipped_look_bands, cullet_s_band_cases_hold, names_only_within_knowing_distance}` (the `look` of `perceived_of`).

## Driving it

```bash
R=core-look-$(date +%m%d-%H%M%S)
.agents/skills/verify-core/scripts/look_bands.py seed --run $R
$V launch --run $R --seed $PWD/.local/living/verify/$R/look-bands
.agents/skills/verify-core/scripts/look_bands.py drive --run $R     # about 2 minutes
```

The seed is plan-test's (its looks fixture) at `year_days` 1 and `life_pace` 0.01 (a year is 7.2 s on the 12-minute day), with Nell Hollis made 6 and Tom Hollis 52. The driver polls the private `look` and `character` rows as the owner every 0.5 s and reads the module log's `look: #id <band> -> <band> (<why>)` lines (one per band change; `due`, `grew`, `laws`). Evidence: `look-bands.json` (checks, what was observed, the log lines), `look-bands-samples.jsonl`, `look-bands-module.log`.

## Gotchas

- Launch takes 20–40 s after genesis: the first band change (Nell at 12) comes about 43 s in; the log lines are the proof, the polls only confirm.
- A poll reads `look` and `character` in two queries: a change between them would count as a mismatch (none seen).
