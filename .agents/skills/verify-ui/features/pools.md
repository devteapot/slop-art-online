# Pools on the bar, and the walk speed law

stamina-1 gave bodies pools in `my_vitals` (stamina for every bodily move, focus for fire bolt and heal; each with `*_from_ms` and a rate per second) and each bar skill a pool and a cost (`skill_card.pool`, `cost`). The bars are the world's `meters()`: health and stamina shown, focus shown under the world's word ("Mana") only while short (`while_short`), energy and hunger off the screen. A slot whose pool is short of its cost greys in the rules' own words (`short_of(pool)`: "not enough mana", "out of breath"); a grey is a hint, a press still goes. Settings › Play › Walk speed reads the world's `walk_base` law and, with a play scene's admin link, sets it (`set_world_law`).

## Sub-features

- `meters`: the shown meters in order; a `while_short` one only while its value is under its max.
- `refill`: a pool's bar moves between updates (per second from the later of `at_ms` and `<field>_from_ms`).
- `grey`: a slot of a short pool greys with `short_of`'s words; a slot of another pool does not; a cooldown shows first.
- `walk`: the row reads `walk_base`, writes 2.6 / 3.0 / 3.4 m/s through the admin link. Exactly those three chips, the current one selected (within 0.05 m/s: 2.5999 is 2.6); a value none of them is (set by another client or an admin) shows as one more chip, selected (`settings:walk:other`, not clickable). The dump's `extra.facing_sight.walk_chips` lists the chips shown (label, selected). Without the admin link there are no chips and the row reads "x.x m/s (read-only)"; with no `walk_base` law in the script it reads "not in this world's laws (walk_base)".

## Driving it with drive.py

- **Pools.** `sync:low` (admin `set_world_law|"focus_max"|"40"`), draw (`key:KeyX:tap`), a fire bolt (`key:KeyR:down` … `up` at `cursor:0.5,0.3`) → the dump's `me.meters` has `focus` short; `extra.slots["bar:Skill2"].off` "Not enough mana"; the bolt's slot greys once cooled down. `sync:back` restores 100.
- **Walk.** `drive.py --admin-link`; Menu › Settings → `extra.facing_sight.walk` 2.6; `click:@settings:walk:3.0` → 3.0 and an owner `law_change` row; back to 2.6. Admin `set_world_law` 2.8 → four chips, 2.8 selected; 2.5999 → three, 2.6 selected; 2.6 chosen again → three.
- Scenarios: `check.py --run $R pools` (6), `check.py --run $R walk-law` (10).

## Gotchas

- Heal is refused at full health (the rules' `heal_check`: "you are not hurt"): the scene spends focus with a fire bolt.
- A strike tapped with someone near the aim point goes to them (aim assist): `bar` taps with the cursor near the top of the view.
