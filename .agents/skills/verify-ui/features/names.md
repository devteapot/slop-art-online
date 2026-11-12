# Names on screen: people and places as perceived

The authority names others as the player's character perceives them: a known name, "a stranger" (or "a child", "an old stranger", "a baby"), or "someone too far away to make out" (`seen_characters.label`, `perception.rs`; told lines since fix-kill-name). The client names a person in one way, `Looks` (`looks.rs`): the authority's name or label, a stranger's clothes colours drawn ("a stranger in green"), and for plates, hover, the target plate and far speakers' bubbles "someone in green" (`Looks::plate`). Act lists, the wheel, the grid, the act name under the F prompt, the talk target, windows, the Log, offer cards and the death screen all go through it. Things are named by their kind; a structure is "your house" when mine, "Bram's house" only when my character knows the owner by name (the private view `my_known_names`: itself, family, community, introductions, its community's remembered dead), else "house" (`looks::structure_name`; the authority's law `owner_shown(#{knows, shows, kind})`, shipped `knows || shows`, `shows` not yet on any kind). Nothing else names an owner: not `land.params` (scrubbed of names since owner-known: lots `l0…`, spots `s0…`, streets `r0…`), not the seed. The death screen says the cause's kind only (the death row's code, else the authority's own fixed cause words), never free cause text, which can carry real names.

## Sub-features

- `naming`: the dump's `naming` lists every person- or place-naming text on screen by where it shows (`plate`, `target`, `bubble`, `window`, `log`, `event`, `people`, `note`, `acts`, `wheel`, `grid`, `aim`, `talk`, `card`, `death`, `place`), with `known_names` (names the authority gave: `seen_characters.name`, mine) and `given_places` (`my_places`).
- `guard`: on a world from a named seed (Cullet), a fresh player names no one and nowhere by a seed name it was not given.
- `death`: an admin's cause naming someone shows "You died"; killed by a stranger, "Killed by a stranger in …".
- `shot`: an arrow on me is told as a shot (fix-missile-told): the weapon's note is the authority's line ("A stranger shot you with an arrow: hit for 7. Your weapon is drawn."; unseen: "An arrow struck you from somewhere you could not see: …"), never our "attacked" (after a move aimed at me the weapon draws at once and the note waits 1.5 s for that line, else "X is attacking you"); an unseen shooter (id 0 in the feed and the line) is named, targeted, plated and pointed at by nothing; the death screen names a killer only if my character saw them in the 2 s before it died, and a witness of id 0 is no one.
- `houses`: a resident's house reads "house" to a stranger, "{name}'s house" once they said their name, and the player's own "your house".

## How to get to it (user POV)

Arrive in Cullet as a newcomer; point at people, hold F, press Enter, open the Log, its People and a person's window. Die.

## Driving it with drive.py

- **Guard.** `check.py --run $R names` on a `--seed cullet` world: a fresh token (`--token`, a new file) as "Newcomer"; the four residents nearest the arrival point (`land.arrive_x/y`): `point:`, hold F (the wheel), Enter (the talk box), then Log, People, the first person's window, Events. Every dump's `naming` is checked against `living/seeds/<seed>.json`: residents' full and first names, buildings, plan lots and spots ("the " dropped), minus `known_names` and `given_places`.
- **Death.** `check.py --run $R death` (any seed): a fresh player killed by admin `kill(me, "killed by <a resident's real name>")` (code `other`) → `naming` `death` is exactly "You died", the name nowhere; then a fresh player struck dead by verify.py's player identity ("Striker", `$V player join`; the scene sets `dmg_strike` 40 and `cost_strike` 0 and restores 5 and 20) → "Killed by a stranger …", "Striker" nowhere.

- **Houses.** `check.py --run $R houses` (any seed): a resident held 3 m off the arrival with a house placed by them (admin `place_structure(near, "house")`: owned by `near`); a fresh player at the arrival, `pointat:` the house → `naming` `aim` "house"; admin `mind_say` "I'm {name}." to the player (an introduction) → `known_names` has them and the aim reads "{name}'s house"; `place_structure` by the player → "your house".

- **Shot.** `check.py --run $R shot` (island): verify.py's player identity ("Striker": a bow and 6 arrows by admin `grant_items`, held by `set_behavior`) shoots a fresh player at noon on open grass (300, 330) from 6 m (`player|use_skill|bowshot|{me}|(mx)|(my)`), then, after `weapon:sheathe`, from 16 m (beyond the 11 m one sees by day, within the bow's 22). Proof: the authority's `attacked` lines (owner SQL: subject the shooter, then 0), the notes, `extra.drawn`, `perceived` (the shooter in sight at 6 m, not at 16 m), `hurt_by` (owner SQL snapshots: the shooter, then 0), `targeted` and `hovered`, and the shooter's name in no `naming` text.

## Gotchas

- Proper names only: names with a capital letter, matched as written (a first name of three letters or more). Plain spot names ("bench by the door", "gate") describe what anyone sees and would match a thing's kind, so they are left out.
- The guard's coverage is what the drive puts on screen; the `names` check also requires plates and the talk box among the texts.
- A sync runs once per name: repeated strikes or shots each need their own (`hit0`…, `shoot1`, `shoot2`).
- The cursor's aim takes a body before a thing: keep people off a structure you point at.
- `drive.py`'s `player|` calls pass whole numbers as integers (a `u32` id) and other words bare (`player|use_skill|strike|{me}|(mx)|(my)`); admin calls take JSON-quoted strings.
