# Needs over time

## Sub-features

- Idle hunger rises and energy falls.
- Rest recovers energy over time.
- Eating consumes food and lowers hunger.
- Night exposure reduces healing; a cloak removes the cold penalty.
- Visible infants look warm or cold, fed, hungry or starving, and hurt when injured. The cold predicate in `skills.rhai` is shared by `rates` and `body_state`.
- Shelter warmth reaches 2.5 tiles and campfire warmth 3.5 by default. A nearby caregiver adds no thermal protection. Carrying infants is not implemented.
- Rate changes include cloak ownership and winter; winter cold subtracts 5 hp/min rather than 2.

## How to get to it (user POV)

Characters need food, rest and warmth. Rates live in `living/scripts/skills.rhai:81`. The authority settles them at state changes in `living/authority/src/brain.rs:128`. `living/authority/src/common.rs:430` applies elapsed minutes to each anchor.

## Driving it with scenes.py

Run `needs` from [SKILL.md](../SKILL.md). Capture eight seconds idle and eight resting, consume one granted cooked meat, then wait for a real night. The exposed and cloaked `hp_rate` values must differ by 2, within 0.1.

## Gotchas

- Vitals are anchors, not continuously rewritten values. The driver saves the anchor, authority time and derived current needs together.
- Worlds start at 07:00. Night starts after 390 seconds. The driver waits up to a full day for the boundary.
- Genes vary rates. Compare the same actor before and after the cloak.
- Fire and shelter prevent exposure. The scene checks warmth bits before asserting cold.
- Cargo's `infant_appearance_agrees_with_cold_damage` crosses night, fire, shelter, cloak and season while holding hunger at 80 to isolate cold. `infant_appearance_reports_food_and_injury_separately` checks food and wounds. These test predicates, not live spatial placement.
- Infant night placement and cry cadence need a live scratch scene. Wait for real night with a still-living infant, two parents and witnesses. Hold food and energy constant, compare shelter-near and exposed `looks`, anchored rates and derived health, then keep one cause for over 120 seconds while answering only one parent's request. Keep scene, vitals, experience and deliberation snapshots. Move both parents out of hearing to check the nearest caring adult fallback.
- A cold infant can still heal if the positive healing rate exceeds the cold penalty. Compare the same infant's rates rather than assuming any cold appearance means net health loss.
- The live infant recipe, starvation, winter's extra cold, sleep recovery and long-term survival are not established by the adult `needs` scene.
