# Heed for players after merging main (branch `heed-player`)

Follows 2026-11-26-1300-heed-player.md and 2026-11-26-1330-heed-player-combat.md. Branch `heed-player` with origin/main merged twice: `4854b6248` (growth-fix, S7) and `55c271265`/`bb1046074` (growth-fix-2: sight and the players' sweep) at `6bcc7f931`, then `e6aa9ee63` (relation-fight-on) at `f3e0dded6`. Bindings regenerated with the pinned image after each merge: identical to the merged ones. Private `hp-stdb` (SpacetimeDB 2.14.1). No change to this surface's shape.

Driven on the build at `6bcc7f931` (growth-fix-2 in; relation-fight-on changes only the script and the mind service's prompts, not the module):
- `player-heed2-154307`: `heed.py` **19/19**.

det_compare (docs/ATTENTION_BUDGET.md "Verification"): laws off **identical** to main `e6aa9ee63` with `relation_fight_on` on as main ships it (1,800 ticks, 113 tables, 45,459 rows; main against itself identical; the negative control differs from tick 2). Against `bb1046074` main differed from itself in `deliberation` alone (495 ticks from 1307), so that run is not evidence either way.

**Not covered:** what 1300's record lists; `combat.py` was not re-driven after the merges.
