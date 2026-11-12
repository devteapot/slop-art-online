# Needs over time

## Sub-features

- Idle hunger rises and energy falls, at the rules' pace: every person rate is scaled by `person_pace` (0.3 since iter-11: hunger 1.2 a minute), and the needs and infant scenes read the law and scale their thresholds and hunger waits by it. Since `rules-1` the shipped rates are written per game hour (`per: "hour"`, the old per-minute numbers halved) and the engine doubles them on the 12-minute day, so the scenes' real-minute expectations (cold tiring 1.5 × `person_pace` a minute) are unchanged; `person_pace` now scales game-hour rates. A world with another day is [laws.md](laws.md).
- Rest recovers energy over time.
- Eating consumes food and lowers hunger.
- "food" is whatever the rules give nutrition (`nutrition(item)` in `skills.rhai`): `has food`, and eat, give, store and take of `food`, all read it. `eat food` takes the most nourishing food held.
- Night exposure reduces healing; a cloak removes the cold penalty.
- Visible infants look warm or cold, fed, hungry or starving, and hurt when injured. The cold predicate in `skills.rhai` is shared by `rates` and `body_state`.
- Shelter warmth reaches 2.5 tiles and campfire warmth 3.5 by default. A nearby caregiver adds no thermal protection. Carrying infants is not implemented.
- Rate changes include cloak ownership and winter; winter cold subtracts 5 hp/min rather than 2.

## How to get to it (user POV)

Characters need food, rest and warmth. Rates live in `living/scripts/skills.rhai:121`. Since 2026-11-09 `rates(a)` returns the state's rates and parameters: the thresholds, the genes and exposure. The engine finishes them per body (`NeedLaw::rates`, `living/rules/src/script.rs:409`). One answer is kept per state (kind, stage, activity, warmth, cloak, night, rain, season) and shared by every body in it. The authority settles rates at state changes in `living/authority/src/brain.rs:133`, profiled as the `needs.rates` span. `living/authority/src/common.rs:517` applies elapsed minutes to each anchor.

## Driving it with scenes.py

Run `needs` and the dedicated `infant` fixture from [SKILL.md](../SKILL.md). `needs` captures eight seconds idle and eight resting, consumes one granted cooked meat, then waits for a real night. The exposed and cloaked `hp_rate` values must differ by 2, within 0.1.

`food` gives a fresh person (who carries berries) two smoked fish: `eat food` eats one and feeds, `give food` hands the other to a neighbour, and with smoked fish and cooked meat added `eat food` eats the cooked meat. Before 2026-11-10 `best_food` listed five foods and missed smoked ones, so `has food` held while eat, give, store and take of food failed.

`infant` uses four adult family members and their infant, plus a caring witness and a remote shelter anchor. It waits for the second real night with infant hunger at least 70, which suppresses positive healing without modifying vitals, rules, species or the clock. A parent sees `warm, hungry` inside shelter range with HP rate 0, and another parent sees `cold, hungry` outside shelter range with HP rate -2. Eight seconds of exposure must lower derived HP by more than 0.15.

After feeding the adults to prevent unrelated starvation/injury requests, a cloak and berry meal reset the episode. Hunger returns above 55 through real authority rates and remains the sole cry cause. The graph alternates a cry with a six-second wait for 250 seconds, emitting about every seven seconds including the signal's duration. The driver answers one parent's requests through `mind_skip`, leaves the other's pending, counts created/merged crying requests by cry-specific authority timestamps, and keeps request, experience, body and private cry-state snapshots. At 60 seconds, a one-shot `think` graph creates an unrelated pending request for the answered parent, then the graph returns to rest. The due reminder must merge the cry into that same request while preserving the unrelated reason. `infant-unrelated-pending.json` retains the pre-merge row, and the prompt events retain the resulting row. It then parks parents and witness beyond the species cry's 12-tile hearing range and places two caring adults at different nearby distances.

## Gotchas

- Vitals are anchors, not continuously rewritten values. The driver saves the anchor, authority time and derived current needs together.
- Worlds start at 07:00. Night starts after 390 seconds. The driver waits up to a full day for the boundary.
- Genes vary rates. Compare the same actor before and after the cloak.
- Fire and shelter prevent exposure. The scene checks warmth bits before asserting cold.
- Cargo's `need_rates_match_the_whole_script_computation` compares the parameter rates with the script computing them whole, as before 2026-11-09, bit for bit over 24,576 states (kind, stage, activity, hunger and energy around each threshold, warmth, cloak, night, rain, season, two gene sets).
- Cargo's `infant_appearance_agrees_with_cold_damage` crosses night, fire, shelter, cloak and season while holding hunger at 80 to isolate cold. `infant_appearance_reports_food_and_injury_separately` checks food and wounds. These test predicates, not live spatial placement.
- The infant fixture holds food/energy thresholds and the cry cause stable; values still change through the real authority. Hunger stays below starvation during the measured interval. Reminder timing begins at the last prompt, not its completion. A pending request already carrying this infant's cry receives no same-cause refresh; an unrelated pending request receives the cry when the reminder is due. The witness has positive affinity, so parent-only routing is checked against an otherwise eligible caring adult. Dawn, personal drives and reflection may independently update requests; the counter excludes those updates rather than treating every request row change as a cry.
- A cold infant can still heal if the positive healing rate exceeds the cold penalty. Compare the same infant's rates rather than assuming any cold appearance means net health loss.
- Starvation, winter's extra cold, infant campfire placement, sleep recovery and long-term survival are not established by these live scenes. Winter and campfire remain covered by the rules tests. Authentic mind responses and paid calls belong to other surfaces.

## Since `laws-2` (2026-11-11)

- Warmth by structure is the script's `structures()` traits (`warms`, `roof`; `structure_traits()` before 2026-11-11), at the laws' `fire_warmth` and `shelter_warmth`; the values and the result are unchanged (docs/WORLD_RULES.md, "Traits instead of lists"). A fire that eats fuel (`burns`) warms within its own radius only while lit (`structure.lit_until_ms`); the `goods` scene covers it ([goods.md](goods.md)).
- The need-rate key compares hunger and energy with the thresholds the `rates` law last gave that body (`NeedLaw::cuts`), not copies of them in `brain.rs`: a world whose law moves `starving_at` or `fed_below` recomputes at its own levels. `scenes.py needs` and `food` drive the shipped values.
- A new body's hunger and energy are the laws `spawn_hunger` (25) and `spawn_energy` (85). Food kept in a structure spoils at `kept_spoil(kind)` (1/3).

## Meters and statuses

Since 2026-11-11 (branch `rules-senses-outcomes`; docs/WORLD_RULES.md "The body: meters and statuses"). How a body is, for the players' screens, the minds' body words and the bodily alarms, is one law: `status_of(a)`, over the bars `meters()` names (fields of `my_vitals`). The authority's alarms (`brain.rs` `alerts`, bodies the minds hold) are the statuses' `alarm`s; each is told once per episode (a bit among the top 16 of `mind_state.alerts`, by its words), asks the mind to think when its `think` says so, and quotes the routine of its `routine` want.

- `scenes.py alarms` (any seed, about 1 min): an overlay adds a status with an alarm to every body. A spawned person is told it once (a `body` line) over 6 s while it lasts, its deliberation request carries "Your body: …"; the shipped script installed again ends the episode, and the overlay again tells it a second time. A meter naming `stamina`, which the vitals row lacks, is refused at install ("not a my_vitals field"). The shipped script is installed again at the end.
- Cargo (`living-rules`, `script::body::tests`): the shipped meters and their fields; one set of thresholds (the old alarms at their thresholds, badly hurt and barely alive one episode, the body words); the body moving along its rates within its meters; a world adding `stamina` with a meters row only; bad meters and statuses refused at install; one answer per state; Cullet composing with the law.

## Sleepers' thoughts

A sleeping body's mind is asked to think only on what wakes it (`perceive::Wake`, `living/authority/src/perceive.rs`): being attacked, an alarm of its own body that asks for a thought (`brain.rs`, `alerts`), its infant's cry of distress (cold, starving, hurt), and an attention cue under the `cues_on` law once that lands (`Wake::Cue`, a hook: nothing fires one on main). Every other request waits in the private `slumber` table (one row per sleeper: `since_ms`, `until_ms` the current sleep's end, the reasons and their arrival times as `deliberation` keeps them). A sleep ends unrested every 150 s at most and the graph sleeps again, so a body counts as asleep from its first sleep act until it is in another act, its sleep was broken off, or `SLEEP_GAP_MS` (3 s) passed after a sleep ended with no next one (`perceive::slept`, at the end of `brain::evaluate`). On waking it is told "You woke up." (a `body` percept) and, if reasons waited, its mind is asked with "You woke up." first. A waking reason breaks the sleep off for any controller (a player's character too), is told as "You woke up: …", and leads the request with what waited after it. Players get no deliberations; a player's sleeping character is woken by the same causes.

`scenes.py sleeper` (any seed, about 4 min): a `think` between two short sleeps waits in `slumber`, not in `deliberation`; the body sleeps on through the gap; a new graph wakes it and the request reads "You woke up." then the waited reason; asleep again, another adult's graph attack wakes it with "You woke up: … is attacking you!" as the request's first line and the waited reason after it, and the percept says so.
