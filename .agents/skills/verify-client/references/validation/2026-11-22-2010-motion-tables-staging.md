# verify-client: motion_tables' switch checks and a passer-by (dev-box coordinator)

## 2026-11-22: a staging fragility, not a flake

**What failed.** The scene gate of `experience-incremental`, attempt 2 (batch 55, gate `gate-1122193749-a7f28a`, dev-box, `performance` governor), failed `motion_tables` on its first run (328 s) and passed it alone (47 s). Under the gate's rule since `flake-scope` it blocked the merge. Attempt 1 of the same branch had passed it.

**What happened.** Three switch checks failed: "law off: A's views still show the same creatures", "law on again: A's rows return within a second", and "law off: the mirror is empty ... A's seen_characters view is unchanged". The run's record: A's `seen_bodies` with the laws off read `[165, 308, 310]`, and the mirror coming back `[165, 307, 308, 310]`. Creature 165 is not one of the scene's actors (A 307, B 308, C 309, F 310); a resident of the default world walked into A's sight between the samples. The checks compared everything A could see before and after the switch, so a passer-by fails them for a reason that is not the switch. The long first run gave one time to arrive. The other switch checks on the scene's own actors passed.

**The fix (`motion-tables-staging`).** The switch checks compare the scene's own actors (`{a, b, c, f}`). The private-table count is compared with A's view sampled at the same moment, not with the view before the switch.

## 2026-11-23: the mirror's return, the check the first fix missed

**What failed.** The scene gate of `clearing-flake` (batch 61, gate `gate-1122235743-762299`) failed `motion_tables` on its first run and passed it alone (47 s): "law on again: A's mirror returns within a second, on its view's rows". The first fix had kept the switch-off checks to the scene's actors, but this one still compared A's whole `seen_characters` view after the switch with the mirror's rows, read by a second query.

**What the record shows.** The mirror came back on `[307, 308, 310]` (A, B, F; C is 389 m off). A's whole view at that moment was not kept. A's subscription stream for the run (`motion-tables-a.jsonl`) holds creatures 77, 88 and 90, none of them scene actors: residents passed through A's sight during the run. That supports the passer-by cause but does not prove it was the moment of this check.

**The fix (`motion-tables-staging-2`).** The mirror's return compares the scene's actors as the other switch checks do, and the record now keeps A's whole view and the whole mirror after the switch (`mirror.view_back`, `mirror.back_all`), so a future failure shows its cause.
