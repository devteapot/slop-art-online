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

Run `needs` and the dedicated `infant` fixture from [SKILL.md](../SKILL.md). `needs` captures eight seconds idle and eight resting, consumes one granted cooked meat, then waits for a real night. The exposed and cloaked `hp_rate` values must differ by 2, within 0.1.

`infant` uses four adult family members and their infant, plus a caring witness and a remote shelter anchor. It waits for the second real night with infant hunger at least 70, which suppresses positive healing without modifying vitals, rules, species or the clock. A parent sees `warm, hungry` inside shelter range with HP rate 0, and another parent sees `cold, hungry` outside shelter range with HP rate -2. Eight seconds of exposure must lower derived HP by more than 0.15.

After feeding the adults to prevent unrelated starvation/injury requests, a cloak and berry meal reset the episode. Hunger returns above 55 through real authority rates and remains the sole cry cause. The graph alternates a cry with a six-second wait for 250 seconds, emitting about every seven seconds including the signal's duration. The driver answers one parent's requests through `mind_skip`, leaves the other's pending, counts created/merged crying requests by cry-specific authority timestamps, and keeps request, experience, body and private cry-state snapshots. At 60 seconds, a one-shot `think` graph creates an unrelated pending request for the answered parent, then the graph returns to rest. The due reminder must merge the cry into that same request while preserving the unrelated reason. `infant-unrelated-pending.json` retains the pre-merge row, and the prompt events retain the resulting row. It then parks parents and witness beyond the species cry's 12-tile hearing range and places two caring adults at different nearby distances.

## Gotchas

- Vitals are anchors, not continuously rewritten values. The driver saves the anchor, authority time and derived current needs together.
- Worlds start at 07:00. Night starts after 390 seconds. The driver waits up to a full day for the boundary.
- Genes vary rates. Compare the same actor before and after the cloak.
- Fire and shelter prevent exposure. The scene checks warmth bits before asserting cold.
- Cargo's `infant_appearance_agrees_with_cold_damage` crosses night, fire, shelter, cloak and season while holding hunger at 80 to isolate cold. `infant_appearance_reports_food_and_injury_separately` checks food and wounds. These test predicates, not live spatial placement.
- The infant fixture holds food/energy thresholds and the cry cause stable; values still change through the real authority. Hunger stays below starvation during the measured interval. Reminder timing begins at the last prompt, not its completion. A pending request already carrying this infant's cry receives no same-cause refresh; an unrelated pending request receives the cry when the reminder is due. The witness has positive affinity, so parent-only routing is checked against an otherwise eligible caring adult. Dawn, personal drives and reflection may independently update requests; the counter excludes those updates rather than treating every request row change as a cry.
- A cold infant can still heal if the positive healing rate exceeds the cold penalty. Compare the same infant's rates rather than assuming any cold appearance means net health loss.
- Starvation, winter's extra cold, infant campfire placement, sleep recovery and long-term survival are not established by these live scenes. Winter and campfire remain covered by the rules tests. Authentic mind responses and paid calls belong to other surfaces.
