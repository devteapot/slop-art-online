# Core validation record

## 2026-11-12 first-sight: maintenance pass, scoped to the first-sight change (Spark)

This follows `2026-11-12-1043-first-sight.md`. It is a `maintain-verification-skill` pass scoped to what `first-sight` changed on four surfaces, not a pass over every feature file. Outcome: **changed**, committed on branch `first-sight`, no PR.

**Features covered, each driven live this session:**
- verify-core `first_sight`: `core-fs1`, `core-fs2`, and `core-fs3-114436` after the move below, 22/22 each;
- verify-minds `first-sight` (`minds-fs3-112258`);
- verify-player `first_sight.py` (`player-fs1-112453`);
- verify-client, the full suite (`client-fs2-112552`, 43/43).

**Corrections made:**
- **Index hygiene:** the new rows are placed in alphabetical order in the core, minds and player feature maps.
- **Case registration:** the `first_sight` scene is defined after the `SCENES` dict and registers itself on the next line (`SCENES["first_sight"] = first_sight`), as `dodge_told` does. The minds case registers itself with `@case('first-sight')`. The player script stands alone.
- **Harness drift found on main:** verify-client `drive.py` `PRIVATE` lacked `far_handle` and `slumber`, which far-handle and fix-sleep-thinking added, so the suite stopped before its first check. Both are now listed, and the suite passes.
- **Descriptions:** no SKILL.md `description` changed. The new law is a row of each feature map.

**Not covered:** the other feature files of these four surfaces (no source wave over them). The first-sight law is off by default and touches only `noticed`'s first sights.
