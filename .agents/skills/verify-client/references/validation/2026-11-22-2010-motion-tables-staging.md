# verify-client: motion_tables' switch checks and a passer-by (dev-box coordinator)

## 2026-11-22: a staging fragility, not a flake

**What failed.** The scene gate of `experience-incremental`, attempt 2 (batch 55, gate `gate-1122193749-a7f28a`, dev-box, `performance` governor), failed `motion_tables` on its first run (328 s) and passed it alone (47 s). Under the gate's rule since `flake-scope` it blocked the merge. Attempt 1 of the same branch had passed it.

**What happened.** Three switch checks failed: "law off: A's views still show the same creatures", "law on again: A's rows return within a second", and "law off: the mirror is empty ... A's seen_characters view is unchanged". The run's record: A's `seen_bodies` with the laws off read `[165, 308, 310]`, and the mirror coming back `[165, 307, 308, 310]`. Creature 165 is not one of the scene's actors (A 307, B 308, C 309, F 310); a resident of the default world walked into A's sight between the samples. The checks compared everything A could see before and after the switch, so a passer-by fails them for a reason that is not the switch. The long first run gave one time to arrive. The other switch checks on the scene's own actors passed.

**The fix (`motion-tables-staging`).** The switch checks compare the scene's own actors (`{a, b, c, f}`). The private-table count is compared with A's view sampled at the same moment, not with the view before the switch.
