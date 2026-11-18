# Body sex

Since `sex-1` (2026-11-13; docs/LIVING_CORE.md "Body sex"). Every person's body is female or male, one private `sex` row (1 female, 2 male) written in the transaction that makes them and kept after death. The rules (`living_rules::sex`, `skills.rhai`) hold the world's pick (`female_share()`), the words (`sex_words()`), kin words by sex (`kin_terms()`) and `conceive_needs_pair()`.

## Sub-features

- **Rows.** Every person has one, and no animal does.
- **The seed's.** A band member's `sex` (`SeedMember.sex`) is honoured: the family seed gives the five grown members f, m, f, f, m.
- **The world's pick.** The young (none given) and newcomers (`spawn_crowd`) get `living_rules::sex::pick(world seed, id, female_share)`, recomputed in the driver (`sex_pick`): with `female_share()` 1.0 every newcomer is a woman, with 0.0 a man, and with the shipped 0.5 each matches the recomputed pick.
- **Kin words by sex.** A child's line to the room "Mother, …" names its female parent (she is told "naming you") and not its male parent. "Father, …" names the other way round, and "Ask a parent." names both.
- **`conceive_needs_pair()`.**
  - On (an installed overlay): two women are refused, told "a family is started by a woman and a man", while a woman and a man start a family (`expecting`).
  - Off (the shipped script): two women start one.
- **Births.** Each child born, from both couples, has a row equal to the world's pick for its id. The row is written before anything in its creation reads it.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py sex-seed   # writes .local/living/verify/sex-family.json
$V launch --run core-sex1-a --seed "$PWD/.local/living/verify/sex-family" --target-dir "$PWD/living/target/verify-seeded"
$V doctor --run core-sex1-a
python3 .agents/skills/verify-core/scripts/scenes.py sex --run core-sex1-a
```

The family seed is `stage1-acts`, one family at a compressed pace (a child is carried about 2.6 real minutes), with the grown members' sexes given. Evidence: `sex-results.json`, `sex-sex-rows.json`, `sex-sex-after.json`, `sex-expecting-*.json` and `sex-actions.jsonl`. Updated worlds (`backfill_sex`, then `relook`) are [updates.md](updates.md).

## Gotchas

- A conception needs both partners fed (hunger 60 or less). The scene gives each cooked meat and waits for it.
- The scene installs the shipped script again at the end, and on a failure too.
