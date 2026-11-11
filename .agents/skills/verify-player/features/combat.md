# Combat skills (the skill bar)

A player's character uses the skills on the bar (the script's `skill_bar()`, `skill_card.slot`; the six starter skills and the jump, docs/COMBAT.md) through `use_skill(skill, target, x, y)` and lets go of a held guard with `release_skill(skill)`. Every attempt is recorded in `skill_use` (read through the player's `my_skill_uses` view); a refusal returns `Ok` and is told back as a `REFUSED` row in `my_combat`, so the record of the failed attempt survives.

## Sub-features

- An unknown skill is a reducer error ("not on the skill bar").
- Refusals are recorded and told: a strike with no target, a strike out of reach (no walking into reach), a heal when unhurt, a second fire bolt inside its windup or cooldown.
- A strike shows its windup (`fighter.act` equals the strike's `skill_card.code`), releases, deals damage, and the player perceives `RELEASE` and `HIT` with the amount; the target's band is public, its health is not.
- A blow does its full damage (no hurt or kill mode since 2026-11-09, docs/COMBAT.md "One damage rule"): scene `kill` strikes a resident past 40% and 10% of its health, and the strike that exceeds its health kills it (use outcome `killed <name> (<n>)`, `HIT` with the amount, `character.alive = false` with cause `killed by <the player as the victim knew them>`: the player's name only with an `acquaintance` row (an introduction), else `killed by a stranger`; a `chronicle` `killing` row with real names).
- A bow shot launches a missile that strikes the first body on its path (`LAUNCH`, `IMPACT`, damage); the arrow is spent.
- A fire bolt burns the creature it meets.
- A guard facing the blow blocks it (`BLOCKED`, reduced); facing away, the blow lands in full; letting go ends it.
- A dodge dashes about 2.6 m and the blow winding up misses or is dodged.
- A jump (the bar's seventh place, Space in the game) hops about 1.6 m like a dash but does not evade (`jump_combat()`'s `evades: false`): a blow winding up as you jump toward its striker lands or misses by reach, never `DODGED` (scene `jump`).
- Heal mends yourself.
- The seed's bold pack attacks a healthy adult player.
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
- The `kill` scene takes about ten strikes at 2 energy each; with `--scene all`, use `--fresh` so later scenes are not refused "too tired". The dummy resident is set to a wait graph, so it neither flees nor strikes back.
- Energy is a real requirement: a character worn out by earlier scenes is refused "too tired". Use `--fresh`.
- Place a dummy before setting its graph: a teleport drops an approach its graph already started.
- A missile strikes the first body on its line, which may be an earlier scene's dummy or a resident at its post: the arrival spot is inside a town, with a building and residents in fixed lines (the diagonal fire bolt struck a wall on 2026-11-10). The bow and bolt scenes place their dummy in the first direction whose line is clear of wall, rock and other bodies (terrain from the public `terrain_chunk` rows), aim at where it actually stands, and check the health of the body the impact names (a bystander who walked in counts; one the shot killed counts as burned).
- `my_combat` rows expire after 4 s; filter by `at_ms` per scene.
- SQL returns `Ready` rows positionally: `[skill, from_ms, at_ms]`.
- Presentation codes are `skill_card.code`, kept stable across script installs by the authority's private `skill_code` table; they are the world's codes, so read them from `skill_card`, never hard-code a number.
- How `use_skill` aims a skill comes from its script shape (`aim`: creature, self_or_ally, point, facing, dash), not its name; the refusal text "no one there to <skill>" names the skill.
