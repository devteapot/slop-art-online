# Combat skills (the skill bar)

A player's character uses the skills on the bar (the script's `skill_bar()`, `skill_card.slot`; the six starter skills and the jump, docs/COMBAT.md) through `use_skill(skill, target, x, y)` and lets go of a held guard with `release_skill(skill)`. Every attempt is recorded in `skill_use` (read through the player's `my_skill_uses` view); a refusal returns `Ok` and is told back as a `REFUSED` row in `my_combat`, so the record of the failed attempt survives.

## Sub-features

- An unknown skill is a reducer error ("not on the skill bar").
- Refusals are recorded and told: a strike with no target, a strike out of reach (no walking into reach), a heal when unhurt, a second fire bolt inside its windup or cooldown.
- A strike shows its windup (`fighter.act` equals the strike's `skill_card.code`), releases, deals damage, and the player perceives `RELEASE` and `HIT` with the amount; the target's band is public, its health is not.
- A blow does its full damage (no hurt or kill mode since 2026-11-09, docs/COMBAT.md "One damage rule"): scene `kill` strikes a resident past 40% and 10% of its health, and the strike that exceeds its health kills it (use outcome `killed <name> (<n>)`, `HIT` with the amount, `character.alive = false` with cause `killed by <the player as the victim knew them>`: the player's name only with an `acquaintance` row (an introduction), else `killed by a stranger`; a `chronicle` `killing` row with real names).
- A bow shot launches a missile that strikes the first body on its path (`LAUNCH`, `IMPACT`, damage); the arrow is spent.
- **The outcome of one's own move, as a mind is told it** (the `force_outcomes` law, docs/COMBAT.md "The outcome of one's own blow or shot"; since 2026-11-11, branch `mind-act-outcome-far`): after scene `strike` the player's `my_experience` holds "You finished: strike → … hit for N" with its `my_act_outcomes` row (kind `own`, skill `strike`, ok, code `done`); after scene `bow`, "You finished: bowshot → … struck …: hit for N" with its row. Read as the admin, every such line in `experience` and every such row in `act_outcome` belongs to the player's character only (`told` in `combat.py`).
- A fire bolt burns the creature it meets.
- A guard facing the blow blocks it (`BLOCKED`, reduced); facing away, the blow lands in full; letting go ends it.
- A dodge dashes about 2.6 m and the blow winding up misses or is dodged.
- A jump (the bar's seventh place, Space in the game) hops about 1.6 m like a dash but does not evade (`jump_combat()`'s `evades: false`): a blow winding up as you jump toward its striker lands or misses by reach, never `DODGED` (scene `jump`).
- Heal mends yourself.
- Breath (since `stamina-1`, docs/STAMINA.md; scene `breath`), read through the player's own `my_vitals`:
  - **A run.** `human_move` with run goes the `run_share` law times the walk and drains 4 breath a second. The row's rate comes from its anchor, and a held run writes no further row. Letting go writes the refill from a second later at 25 a second. Standing, breath comes back with no row written.
  - **Costs.** A dodge takes 20 and a jump 10.
  - **Refusal.** Dodging on without a pause is refused "out of breath", in the use's outcome and as a `my_combat` REFUSED row.
- The seed's bold pack attacks a healthy adult player.
- In the game client (since 2026-11-11), a left tap on a person who is not hostile to the player sends no `use_skill`; it opens the text box to them (and a `face` act). A held press, and a tap on an animal or a hostile person, strike as before. The reducers are unchanged, so `combat.py` still drives `use_skill` directly.
- The character dies through the vitals and death rules ("killed by …"), the dead player is told of the death and who saw it, and `join` makes a new character with only the newcomer's kit.

## Driving it

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-combat-$(date +%m%d-%H%M%S)
$V launch --run $R --seed island && $V doctor --run $R
$V player --run $R join Tester
.agents/skills/verify-player/scripts/combat.py --run $R [--scene strike,kill,bow] [--fresh]
$V cleanup --run $R
```

`combat.py` drives the player's own identity and checks the player's views (its characters through `my_characters`, its feed, uses and cooldowns) and, as the database owner, the world's rows (bodies, vitals, fighters, the chronicle), so it runs on both perception builds (docs/PERCEPTION.md). It sets scenes with admin test reducers, named here because they are not player abilities: `place_at` (put a body somewhere), `set_behavior` (a resident stands still or strikes the player), the admin reducer `kill` (`--fresh`, or when an earlier run left the character too tired; not the `kill` scene) and `join` again. Results go to `<run>/combat.json` and `<run>/actions.log`.

## Gotchas

- A dummy is an adult (`stage` 2 or more). Until 2026-11-10 it was the first living person with half its health, on the island resident 17, a child, whose strike the rules refuse ("too young to fight"): the block, dodge and heal scenes then saw no blow at all (5 of 25 failing on `origin/main` too). Since then a refusal at the start is told (`You failed to strike → …: too young to fight` in the attacker's `experience`), so look there first when an attacker never strikes.
- The block scene places the attacker first, reads where it stands, and raises the guard toward it (or away from it); a guard aimed at a fixed point east met a blow from the side when `place_at` put the attacker on the next walkable tile.
- The block, dodge and heal scenes give the attacker 4 s to land its blow. On 2026-11-09 one full run on a host also running the mind suite and a headless game client failed all three with no blow at all; two reruns (and the scenes run alone) passed. Rerun on a quieter host before calling it a regression.
- The `kill` scene takes about ten strikes at 10 breath each (since `stamina-1` combat spends breath, not energy): a strike refused "out of breath" waits 3 s for it to come back and goes on. The dummy resident is set to a wait graph, so it neither flees nor strikes back.
- Breath is a real requirement, and comes back by itself within seconds; energy no longer refuses a move. `--fresh` still starts a new character (an energy below 70 does it anyway).
- Since `fix-place-free` (2026-11-11) `place_at` puts a body on the nearest walkable tile no other body stands on (within 6 m), so near the busy arrival spot a dummy asked for 1.2 m east could land 2.2 m away, out of a strike's reach (1.6 m plus the 0.6 m lunge): 16 to 19 of 26 checks failed with "out of reach", and the jump found "no room to jump". `dummy()` now stages on a tile `free_spots()` finds free (walkable, no body on it, the offset's distance within 0.6 m, and for the jump 2 m of open ground beyond) and reads the body back. `living/tools/combat_scene.py` uses the same helper.
- The jump scene waits 1 s after the hop for the attacker's blow; one of six runs on 2026-11-11 saw no blow in that window (windup and hop fine). Rerun before calling it a regression.
- Place a dummy before setting its graph: a teleport drops an approach its graph already started.
- A missile strikes the first body on its line, which may be an earlier scene's dummy or a resident at its post: the arrival spot is inside a town, with a building and residents in fixed lines (the diagonal fire bolt struck a wall on 2026-11-10). The bow and bolt scenes place their dummy in the first direction whose line is clear of wall, rock and other bodies (terrain from the public `terrain_chunk` rows), aim at where it actually stands, and check the health of the body the impact names (a bystander who walked in counts; one the shot killed counts as burned).
- `my_combat` rows stay 4 s for the two involved and for a refusal (an onlooker's 300 ms; the dead one's death and witnesses until it joins again); filter by `at_ms` per scene and read soon after the act.
- SQL returns `Ready` rows positionally: `[skill, from_ms, at_ms]`.
- Presentation codes are `skill_card.code`, kept stable across script installs by the authority's private `skill_code` table; they are the world's codes, so read them from `skill_card`, never hard-code a number.
- How `use_skill` aims a skill comes from its script shape (`aim`: creature, self_or_ally, point, facing, dash), not its name; the refusal text "no one there to <skill>" names the skill.

Since 2026-11-11 (branch `rules-senses-outcomes`) the death scene also checks the death in codes: the player's `my_act_outcomes` has a `death` row with code `killed` (or `killed_yielding`) and the killer's id in `other`, and its line in `my_experience` reads "You were killed by …", the killer as the dead knew them ([outcomes.md](outcomes.md)).
