# Combat skills (the skill bar)

A player's character uses the skills on the bar (the script's `skill_bar()`, `skill_card.slot`; the six starter skills, docs/COMBAT.md) through `use_skill(skill, target, x, y)` and lets go of a held guard with `release_skill(skill)`. Every attempt is recorded in `skill_use` (read through the player's `my_skill_uses` view); a refusal returns `Ok` and is told back as a `REFUSED` row in `my_combat`, so the record of the failed attempt survives.

## Sub-features

- An unknown skill is a reducer error ("not on the skill bar").
- Refusals are recorded and told: a strike with no target, a strike out of reach (no walking into reach), a heal when unhurt, a second fire bolt inside its windup or cooldown.
- A strike shows its windup (`fighter.act` equals the strike's `skill_card.code`), releases, deals damage, and the player perceives `RELEASE` and `HIT` with the amount; the target's band is public, its health is not.
- A blow does its full damage (no hurt or kill mode since 2026-11-09, docs/COMBAT.md "One damage rule"): scene `kill` strikes a resident past 40% and 10% of its health, and the strike that exceeds its health kills it (use outcome `killed <name> (<n>)`, `HIT` with the amount, `character.alive = false` with cause `killed by <the player as the victim knew them>`: the player's name only with an `acquaintance` row (an introduction), else `killed by a stranger`; a `chronicle` `killing` row with real names).
- A bow shot launches a missile that strikes the first body on its path (`LAUNCH`, `IMPACT`, damage); the arrow is spent.
- A fire bolt burns the creature it meets.
- A guard facing the blow blocks it (`BLOCKED`, reduced); facing away, the blow lands in full; letting go ends it.
- A dodge dashes about 2.6 m and the blow winding up misses or is dodged.
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

- The block, dodge and heal scenes give the attacker 4 s to land its blow. On 2026-11-09 one full run on a host also running the mind suite and a headless game client failed all three with no blow at all; two reruns (and the scenes run alone) passed. Rerun on a quieter host before calling it a regression.
- The `kill` scene takes about ten strikes at 2 energy each; with `--scene all`, use `--fresh` so later scenes are not refused "too tired". The dummy resident is set to a wait graph, so it neither flees nor strikes back.
- Energy is a real requirement: a character worn out by earlier scenes is refused "too tired". Use `--fresh`.
- Place a dummy before setting its graph: a teleport drops an approach its graph already started.
- A missile strikes the first body on its line, which may be an earlier scene's dummy; aim off their lines.
- `my_combat` rows stay 1.5 s for the two involved (a refusal 4 s, an onlooker's 300 ms; the dead one's death and witnesses until it joins again); filter by `at_ms` per scene and read soon after the act.
- SQL returns `Ready` rows positionally: `[skill, from_ms, at_ms]`.
- Presentation codes are `skill_card.code`, kept stable across script installs by the authority's private `skill_code` table; they are the world's codes, so read them from `skill_card`, never hard-code a number.
- How `use_skill` aims a skill comes from its script shape (`aim`: creature, self_or_ally, point, facing, dash), not its name; the refusal text "no one there to <skill>" names the skill.
