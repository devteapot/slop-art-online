# Combat skills (the skill bar)

A player's character uses the six starter skills (docs/COMBAT.md) through `use_skill(skill, target, x, y)` and lets go of a held guard with `release_skill(skill)`. Every attempt is recorded in `skill_use` (read through the player's `my_skill_uses` view); a refusal returns `Ok` and is told back as a `REFUSED` row in `my_combat`, so the record of the failed attempt survives.

## Sub-features

- An unknown skill is a reducer error ("not on the skill bar").
- Refusals are recorded and told: a strike with no target, a strike out of reach (no walking into reach), a heal when unhurt, a second fire bolt inside its windup or cooldown.
- A strike shows its windup (`fighter.act`), releases, deals damage, and the player perceives `RELEASE` and `HIT` with the amount; the target's band is public, its health is not.
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
.agents/skills/verify-player/scripts/combat.py --run $R [--scene strike,bow] [--fresh]
$V cleanup --run $R
```

`combat.py` drives the player's own identity and checks the player's views and public rows. It sets scenes with admin test reducers, named here because they are not player abilities: `place_at` (put a body somewhere), `set_behavior` (a resident stands still or strikes the player), `kill` (`--fresh`, or when an earlier run left the character too tired) and `join` again. Results go to `<run>/combat.json` and `<run>/actions.log`.

## Gotchas

- Energy is a real requirement: a character worn out by earlier scenes is refused "too tired". Use `--fresh`.
- Place a dummy before setting its graph: a teleport drops an approach its graph already started.
- A missile strikes the first body on its line, which may be an earlier scene's dummy; aim off their lines.
- `my_combat` rows expire after 4 s; filter by `at_ms` per scene.
- SQL returns `Ready` rows positionally: `[skill, from_ms, at_ms]`.
