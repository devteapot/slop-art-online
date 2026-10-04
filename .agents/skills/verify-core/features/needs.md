# Needs over time

## Sub-features

- Idle hunger rises and energy falls.
- Rest recovers energy over time.
- Eating consumes food and lowers hunger.
- Night exposure reduces healing; a cloak removes the cold penalty.

## How to get to it (user POV)

Characters need food, rest and warmth. Rates live in `living/scripts/skills.rhai:81`. The authority settles them at state changes in `living/authority/src/brain.rs:128`. `living/authority/src/common.rs:430` applies elapsed minutes to each anchor.

## Driving it with scenes.py

Run `needs` from [SKILL.md](../SKILL.md). Capture eight seconds idle and eight resting, consume one granted cooked meat, then wait for a real night. The exposed and cloaked `hp_rate` values must differ by 2, within 0.1.

## Gotchas

- Vitals are anchors, not continuously rewritten values. The driver saves the anchor, authority time and derived current needs together.
- Worlds start at 07:00. Night starts after 390 seconds. The driver waits up to a full day for the boundary.
- Genes vary rates. Compare the same actor before and after the cloak.
- Fire and shelter prevent exposure. The scene checks warmth bits before asserting cold.
- Starvation, winter's extra cold, sleep recovery and long-term survival are not established.
