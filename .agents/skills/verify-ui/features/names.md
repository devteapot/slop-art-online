# Names on screen: people and places as perceived

The authority names others as the player's character perceives them: a known name, "a stranger" (or "a child", "an old stranger", "a baby"), or "someone too far away to make out" (`seen_characters.label`, `perception.rs`; told lines since fix-kill-name). The client names a person in one way, `Looks` (`looks.rs`): the authority's name or label, a stranger's clothes colours drawn ("a stranger in green"), and for plates, hover, the target plate and far speakers' bubbles "someone in green" (`Looks::plate`). Act lists, the wheel, the grid, the act name under the F prompt, the talk target, windows, the Log, offer cards and the death screen all go through it. Things, houses and workplaces are named by their kind; an owner only ever from the authority's perceived label, never from `structure.owner`, `land.params` (plan lots' names) or the seed (`verbs.rs` `toward`). The death screen says the cause's kind only (the death row's code, else the authority's own fixed cause words), never free cause text, which can carry real names.

## Sub-features

- `naming`: the dump's `naming` lists every person- or place-naming text on screen by where it shows (`plate`, `target`, `bubble`, `window`, `log`, `event`, `people`, `note`, `acts`, `wheel`, `grid`, `aim`, `talk`, `card`, `death`, `place`), with `known_names` (names the authority gave: `seen_characters.name`, mine) and `given_places` (`my_places`).
- `guard`: on a world from a named seed (Cullet), a fresh player names no one and nowhere by a seed name it was not given.
- `death`: an admin's cause naming someone shows "You died"; killed by a stranger, "Killed by a stranger in …".

## How to get to it (user POV)

Arrive in Cullet as a newcomer; point at people, hold F, press Enter, open the Log, its People and a person's window. Die.

## Driving it with drive.py

- **Guard.** `check.py --run $R names` on a `--seed cullet` world: a fresh token (`--token`, a new file) as "Newcomer"; the four residents nearest the arrival point (`land.arrive_x/y`): `point:`, hold F (the wheel), Enter (the talk box), then Log, People, the first person's window, Events. Every dump's `naming` is checked against `living/seeds/<seed>.json`: residents' full and first names, buildings, plan lots and spots ("the " dropped), minus `known_names` and `given_places`.
- **Death.** `check.py --run $R death` (any seed): a fresh player killed by admin `kill(me, "killed by <a resident's real name>")` (code `other`) → `naming` `death` is exactly "You died", the name nowhere; then a fresh player struck dead by verify.py's player identity ("Striker", `$V player join`; the scene sets `dmg_strike` 40 and `cost_strike` 0 and restores 5 and 20) → "Killed by a stranger …", "Striker" nowhere.

## Gotchas

- Proper names only: names with a capital letter, matched as written (a first name of three letters or more). Plain spot names ("bench by the door", "gate") describe what anyone sees and would match a thing's kind, so they are left out.
- The guard's coverage is what the drive puts on screen; the `names` check also requires plates and the talk box among the texts.
- `drive.py`'s `player|` calls pass whole numbers as integers (a `u32` id) and other words bare (`player|use_skill|strike|{me}|(mx)|(my)`); admin calls take JSON-quoted strings.
