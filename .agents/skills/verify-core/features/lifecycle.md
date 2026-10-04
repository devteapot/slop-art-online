# Life course

## Sub-features

- Two fed adults near a shelter mutually conceive.
- Housekeeping consumes pregnancy and creates a new living infant with both parents.
- Birth writes a chronicle line and starts rearing.
- A seeded infant ages into a child.
- Death clears bodily rows while retaining an expecting parent's inheritance until birth.

## How to get to it (user POV)

Characters start families, grow and die. `living/rules/src/life.rs:91` applies pace to species life fractions. Stages and births run through `living/authority/src/tick.rs:213,249,357`.

## Driving it with scenes.py and mechanics

Run the fresh `stage1-acts` lifecycle recipe in [SKILL.md](../SKILL.md). It grants food, places a shelter and submits conception through `mind_act`. Compare the new child's id against all initial ids. Keep expecting, born, rearing, birth chronicle and aging snapshots. Mechanics' final check proves death cleanup and temporary inheritance retention. Cargo covers authored ages and stages at different paces.

## Gotchas

- The seeded parents already have children. Matching parent ids alone does not prove a new birth.
- `lab-lifecycle` has `year_days: 2` and `life_pace: 0.1`, but no explicit infant. `stage1-acts` supplies one.
- Gestation uses species `Life.gestation` and pace in `living/authority/src/act.rs:1299`. `laws.gestation_days` does not compress it.
- No mind connects. Persona generation and memory isolation require neighbouring skills.
- Adult-to-elder transitions and natural old-age deaths are not asserted.
