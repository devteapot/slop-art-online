# Life course

## Sub-features

- Two fed adults near a shelter mutually conceive.
- The laws of starting a family in `skills.rhai` (`conceive_roof`, `conceive_food`; shipped false and 0): under an overlay, two adults are refused in the open ("not under a roof"), then by a shelter with no food ("not enough food put by … carry 0, a family needs 6"), and start a family carrying 3 berries each.
- The longing for a child is felt after `longing_after_min` real minutes (shortened by nurture) and only while carrying `longing_food` food (laws(); shipped 20 and 0, a seed's `rules` may set them): with 0.1 and 3, an adult carrying 4 berries feels "You long for…" by day and one carrying nothing does not, until `longing_food` is 0.
- Housekeeping consumes pregnancy and creates a new living infant with both parents.
- Birth writes a chronicle line and starts rearing.
- A seeded infant ages into a child.
- Death clears bodily rows while retaining an expecting parent's inheritance until birth.
- Infant cries retain cause enums and per-carer prompt times in private `infant_cry`. Cold, starvation and injury cry even when the infant's installed behavior does not signal.
- Nearby adult parents receive cry deliberations. With no parent nearby, only the nearest adult sibling or adult with positive affinity does. Other listeners receive experiences.
- Same-cause pending requests are left unchanged. Completed requests get a reminder after 120 seconds; new causes can merge immediately, with cold, starvation and injury bypassing the normal think interval.
- Leaving infancy or dying deletes the infant's cry state.

## How to get to it (user POV)

Characters start families, grow and die. `living/rules/src/life.rs:91` applies pace to species life fractions. Stages and births run through `living/authority/src/tick.rs:213,249,357`.

## Driving it with scenes.py and mechanics

Run the fresh `stage1-acts` lifecycle and `family_laws` recipes in [SKILL.md](../SKILL.md). Lifecycle grants food, places a shelter and submits conception through `mind_act`. Compare the new child's id against all initial ids. Keep expecting, born, rearing, birth chronicle and aging snapshots. Mechanics' final check proves death cleanup and temporary inheritance retention. Cargo covers authored ages and stages at different paces, the longing wait (`longing_wait_ms`) and the laws' world values (`laws_with`).

`family_laws` spawns four adults (`spawn_crowd`) on an open row more than 10 m from every structure, installs overlays, and installs the shipped script again at the end, also when a check fails. Its evidence: `family_laws-*.json` snapshots (structures, expecting, longing experiences) and the action log.

## Gotchas

- The seeded parents already have children. Matching parent ids alone does not prove a new birth.
- `lab-lifecycle` has `year_days: 2` and `life_pace: 0.1`, but no explicit infant. `stage1-acts` supplies one.
- Gestation uses species `Life.gestation` and pace in `living/authority/src/act.rs:1299`. `laws.gestation_days` does not compress it.
- No mind connects. Persona generation and memory isolation require neighbouring skills.
- Adult-to-elder transitions and natural old-age deaths are not asserted. The trial tool `living/tools/births_report.py` compares each seeded person's death of old age with `Life::deathline` (its port is pinned by a `life.rs` test), but that is a trial measure, not a scene.
- The longing is a rising-edge alert (bit 128 in `mind_state.alerts`): it fires once when it becomes true and again only after it has been false. It needs day, an adult that is calm (hunger under 60, energy over 35, health over 60), `ai`, and neither expecting nor raising young. A world whose script lacks the two laws keeps the defaults (20, 0) in `Laws`.
- Authority `perceive::tests` covers carer selection, pending merging, cause escalation and reminders with one parent pending and the other completed. The live recipe is in [needs.md](needs.md). Lifecycle's current driver does not assert `infant_cry` cleanup or cry fan-out.
