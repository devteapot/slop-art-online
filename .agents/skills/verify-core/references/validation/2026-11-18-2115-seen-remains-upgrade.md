# Seen remains diagnostic and C2 upgrade, 2026-11-18

The final diagnostic compares the two stored answers before using the legacy row as a fallback. It distinguishes range retention from a legacy-only ID missing from the ranges.

- `core-seen-1118-211158`, **15/15** on the updated diagnostic. It recorded 210 range comparisons and 4,117 C2 skip checks, both with zero differences. It recorded 86 retentions. The law-off field and its migration still passed.
- `client-seen-upgrade-1118-211504`, **6/6**. Built C2 from `1cd32ab2` and staged three remains. The C2 authority wrote three per-body notices and three legacy familiarity rows. A real SDK subscriber attached to `structure`. Publishing the new module with `--keep-data` preserved the subscription and all three body IDs. The next look transferred all three IDs to the new table, removed each legacy row and left the notice count at three.

Evidence is under `.local/living/verify/core-seen-1118-211158/` and `.local/living/verify/client-seen-upgrade-1118-211504/`. The latter includes `subscriber.jsonl`, `upgrade-result.json` and before/after snapshots. Both scratch databases were paused and archived before deletion.

The final product changes passed `just living-check` with the stamped steps reused. The full earlier pass included 329 rules tests and 128 game tests. Separate suites passed 41 authority tests and 124 mind tests. The measured production configuration disables the diagnostic.
