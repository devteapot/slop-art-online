# Combat and graded force

## Sub-features

- Threats produce percepts and trigger a threatened guard.
- Hurt stops without death; yield stops a beating.
- A wolf refuses a healthy adult among others.
- Seize refuses an unyielded healthy person.
- Seize should accept a yielded healthy person. The driver records `XFAIL KNOWN ISSUE` while the defect reproduces, and `XPASS` when fixed. See [Still open in LIVING_HANDOFF](../../../../docs/LIVING_HANDOFF.md#where-to-pick-up).
- Seize transfers an exact quantity from a badly hurt person and informs witnesses.
- Kill intent can kill someone who yielded.
- Starter skills under graphs (`scenes.py skirmish`, docs/COMBAT.md): two sides of 10 (`spawn_skirmish`) use strike, bow shot, block, dodge and heal; uses are recorded from acceptance with source `graph`; arrows strike bodies on their path; no actor's accepted uses of a skill come closer than its `skill_card` cooldown; fighters show a band; deaths go through the death rule and leave no `fighter` or `readiness` rows.
- The authority's own rules tests cover the geometry (`living_rules::combat`: sweeps, guard arcs, bands) and the starter skills' Rhai requirements and numbers (`script::tests::starter_combat_skills_follow_the_rules`).

## How to get to it (user POV)

Characters choose force through graphs or acts; players use the starter skills through `use_skill` (verify-player `combat.md`). Rules live in `living/scripts/skills.rhai:401,443,494`. Effects and witness evidence live in `living/authority/src/act.rs:913,917,1544`.

## Driving it with mechanics and scenes.py

Run mechanics, `seize` and `skirmish` from [SKILL.md](../SKILL.md) (`skirmish` on an island run: `$V launch --run core-<x> --seed island`, then `scenes.py skirmish --run core-<x>`). Mechanics covers threat, hurt, yield and wolf reluctance. The scene gives four stones to a victim. Initial seizure must fail without changing either inventory. The victim yields; keep the yielded-target XFAIL and unchanged inventories. Continue with a badly hurt victim, transfer two stones, check victim and witness percepts, then drive lethal intent against a fresh yield.

## Gotchas

- `living/authority/src/act.rs:238` populates `target.yielded_ago` only for attack. Seize wrongly sees no yield. Do not weaken the assertion or patch product code in this skill task.
- Hurt stops below 40% health; seize requires below 35%. A brief kill-intent attack may be needed to reach below 30% before stopping. Record that setup.
- Yield lasts 20 seconds. Re-yield before the lethal check.
- Chronicle coalesces repeated events. Compare `at_ms`, not row count, for repeated yields.
- Dense-battle performance is measured in docs/COMBAT.md, not by this skill. Throw and the older `shoot` remain unverified here.
- The skirmish scene is stochastic (who targets whom); it asserts kinds of outcomes, not counts.
