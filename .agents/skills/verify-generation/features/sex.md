# Body sex in generated worlds

Since `sex-1` (2026-11-13; docs/LIVING_CORE.md "Body sex"). Genesis writes one private `sex` row per person (1 female, 2 male). A seeded resident gets the seed's `sex` and everyone else the world's pick. Looks follow it (docs/LOOK.md §10).

## Sub-features

- **Rows** (`check_sex`, with every seed of the worlds feature): every person has one, 1 or 2, and no animal has one.
- **The seed's sex.** Each seeded resident (by name, minded) has the seed's `sex`.
- **The world's pick.** Everyone else (households drawn by the world, bands without a member's `sex`, newcomers) has `living_rules::sex::pick(world seed, id, female_share)`, recomputed in the driver (`sex_pick`; `female_share()` 0.5, or the seed's laws' value).
- **Looks by sex** (`check_looks`):
  - each pool pick is `pool_pick(world seed, id, n)` over the `n` sorted pool entries of the person's sex (an entry's sex is the last word of its lines' `form`; `entry_sex_of`);
  - every person's look entry shows their sex (the island's Brackenford wore 7 of the other sex before).
- **The seed check** (Cargo):
  - an authored cast is a seed with `looks`, or one where any resident gives `sex`, and every one of its residents must give "f" or "m" (`seed_sex_is_checked_and_sheets_warned`, `authored_casts_give_every_resident_a_sex`);
  - a look entry whose lines show two sexes is refused, and so is a resident whose own entry shows the other sex (`look::check`);
  - the sheets' warning: another resident's sheet calling someone "wife" and "she" while the seed makes them male logs a warning, not a refusal (`sex::sheet_warnings`; none in any shipped cast).
- **The casts carried into the compiled seeds:** `python3 living/tools/cast_sex.py --check` (island, Cullet, aske-coast and its variants).

## Driving it

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-sex1-b --feature worlds --seeds island,plan-test,cullet,aske-coast,plan-test-floor,hamlet,authored-test
cargo test --manifest-path living/Cargo.toml -p living-authority --lib sex:: look::
```

Evidence: each seed's `checks.json` (the sex checks are named for it) and `sex.json`.
