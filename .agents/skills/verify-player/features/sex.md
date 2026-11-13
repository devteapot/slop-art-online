# A player's body sex

Since `sex-1` (2026-11-13; docs/LIVING_CORE.md "Body sex").

## Sub-features

- **`join(name)` is unchanged:** the player's `sex` row is the world's pick for the world seed and its id (`living_rules::sex::pick`, recomputed in `sex.py`).
- **`join_as(name, sex)`, beside it:**
  - "f" and "M" (any case; "female" and "male" too) join with rows 1 and 2;
  - "x" and "" are refused with `sex must be "f" or "m"`, and nothing is made for that identity;
  - from someone who already plays, it is refused like a second `join`.
- **`my_sex`** (the player's own view) says "female" or "male" for its living character. SQL on the private `sex` table is refused to it.
- **With looks** (plan-test): every player's look entry shows its sex, and its own `seen_characters` row carries that line.

## Driving it

```bash
$V launch --run $R --seed plan-test --target-dir "$PWD/living/target/verify-seeded" && $V doctor --run $R
python3 .agents/skills/verify-player/scripts/sex.py --run $R
python3 .agents/skills/verify-player/scripts/look.py --run $R    # the pool pick among the entries of the player's sex
```

`sex.py` mints a fresh identity for each `join_as` player (`POST /v1/identity`). The run's own player joins with `join`. Evidence: `player_sex.json`.
