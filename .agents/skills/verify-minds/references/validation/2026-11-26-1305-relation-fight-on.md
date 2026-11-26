# relation-fight-on: the minds under the law on by default

This run is on branch `relation-fight-on`, commit `0f743d6ab`, on origin/main `9cbb8d50c`. It used a private SpacetimeDB 2.14.1 (`slop-rfon-20261126`) and the fake model, with no paid calls. The full record is verify-core's `2026-11-26-1305-relation-fight-on.md`.

- `verify_minds.py --case fight-field --case roundtrip --case conversation --no-unit-tests` (`minds-rfon-133753`): **all pass**.
- In `roundtrip` and `conversation` the law was left at its new default. The deliberation prompt and the consolidation prompt both carry the gloss "Whom your body counts as an enemy (relation: enemy)". The one consolidation request without it is the starting-identity prompt.
- `fight-field` still sets the law on explicitly before the service starts.
- living-mind cargo tests: 147 passed, 14 ignored. This includes `whom_one_fights_is_told_only_under_its_law`, which now checks that the shipped prompts carry the order and the `fight` field.
- Not covered: the rest of the suite, and real models.
