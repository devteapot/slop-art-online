# Combat and force

## Sub-features

- Threats produce percepts and trigger a threatened guard.
- A blow does its full damage and the one that exceeds health kills (no hurt or kill mode since 2026-11-09, docs/COMBAT.md "One damage rule"); a yield only stops the yielder striking back.
- A wolf refuses a healthy adult among others.
- Seize refuses an unyielded healthy person.
- Seize accepts a yielded healthy person (the rules weigh the target's yield for every skill whose `<skill>_combat()` says `dares`: attack, strike, seize).
- Seize transfers an exact quantity from a badly hurt person and informs witnesses.
- A blow can kill someone who yielded; the first blow after the yield is chronicled "struck X, though X had yielded" and the death is "killed by X, after yielding", with X as the victim knew the killer (`perceived_of`: a name only when known, else "a stranger" or "a wolf"); the chronicle keeps real names.
- Starter skills under graphs (`scenes.py skirmish`, docs/COMBAT.md): two sides of 10 (`spawn_skirmish`) use strike, bow shot, block, dodge and heal; uses are recorded from acceptance with source `graph`; arrows strike bodies on their path; no actor's accepted uses of a skill come closer than its `skill_card` cooldown; fighters show a band; deaths go through the death rule and leave no `fighter` or `readiness` rows.
- **Outcomes reach their maker** (`force_outcomes` law, docs/COMBAT.md "The outcome of one's own blow or shot"): a mind-held character is told how its strike, shot or bolt came out (`act.rs` `report` for a force skill without a missile; `act::missile_told` from `combat::missiles` when a missile strikes, is dodged, hits a wall or nothing, or flies out of the shooter's sight). `scenes.py outcomes` on an island run: the archer's "struck …: hit for N", the striker's "hit for N", an arrow at an empty point told as coming to nothing, and none told with the law off (`set_world_law`).
- **Another's health as perceived** (`scenes.py health_seen`, any seed, about 2 min; docs/PERCEPTION.md): two strangers fight and the scene skips each pending `deliberation` as a mind would, so fight reports (`act::fight_report`, a reason to think; AI people only) keep coming. Without an appraisal a report ends "Your health 61; they look scratched." (the band's words, no number); inside A's 20 s `appraise` reveal A's report ends "they have 70 of 100 health." while B's stays banded; after the reveal ends A's is banded again. A graph's `health_of` reads the same perception (`perception::health_seen`): the band's middle without an appraisal, exact during one (a threshold between the two tells which; XFAIL when they are under 4 points apart). Until 2026-11-11 reports read "theirs looks about 70%" and `health_of` read the target's `vitals`. The rules test `combat::tests::fight_reports_show_the_band_unless_appraised` covers the text.
- **Stable codes:** `scripts/codes.py RUN` on a fresh `verify-core-*` world installs scripts that add and remove a combat and a shown skill and checks that `skill_card`/`act_card` codes never change or get reused (the private `skill_code` table, `living/authority/src/codes.rs`). Passed 10/10 on 2026-11-09 (`verify-codes-1`).
- The authority's own rules tests cover the geometry (`living_rules::combat`: sweeps, guard arcs, bands, codes), the starter skills' Rhai requirements and numbers (`script::tests::starter_combat_skills_follow_the_rules`), that the script's shapes classify the existing skills exactly as the name lists they replaced (`combat_shapes_classify_the_existing_skills_as_before`), and that a new skill works from the script alone (`a_new_skill_needs_only_the_script`).

## How to get to it (user POV)

Characters choose force through graphs or acts; players use the starter skills through `use_skill` (verify-player `combat.md`). Rules live in `living/scripts/skills.rhai:453,481,494` (attack, threaten, seize checks) and the combat shapes at `living/scripts/skills.rhai:735-771` (`<skill>_combat()`, `skill_bar()`; docs/COMBAT.md "Where combat rules live"). The authority selects its primitives by those traits: `living/authority/src/act.rs:252` (facts by `force`/`dares`), `:384` (`begin`: aim, melee, hostile victim; drops a force word a stored graph still carries), `:1712` (`damage`: a dash that evades dodges, as the dodge does and the jump doesn't (the shape's `evades`, on for a dash unless `evades: false`), a facing guard takes its `takes`, the rest lands in full).

## Driving it with mechanics and scenes.py

Run mechanics, `seize` and `skirmish` from [SKILL.md](../SKILL.md) (`skirmish` on an island run: `$V launch --run core-<x> --seed island`, then `scenes.py skirmish --run core-<x>`). Mechanics covers a threat, a blow that kills, blows landing on the yielded (with the news) and wolf reluctance. The scene gives four stones to a victim. Initial seizure must fail without changing either inventory. The victim yields; the yielded seizure then succeeds. Continue with a badly hurt victim, transfer two stones, check victim and witness percepts, then attack after a fresh yield until death.

## Gotchas

- Seize requires below 35% health without a yield. The fallback path attacks until the victim is below 30%, then replaces the attacker's graph to stop; blows no longer stop by themselves. Record that setup.
- Yield lasts 20 seconds. Re-yield before the lethal check.
- Chronicle coalesces repeated events. Compare `at_ms`, not row count, for repeated yields.
- Dense-battle performance is measured in docs/COMBAT.md, not by this skill. Throw and the older `shoot` remain unverified here.
- The skirmish scene is stochastic (who targets whom); it asserts kinds of outcomes, not counts.
