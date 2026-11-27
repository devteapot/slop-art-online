# Can, as perceived (`perceived_can_on`)

Perception parity phase 1 ([audit](../../../../docs/PERCEPTION_PARITY_AUDIT.md), the `can` and `dares` rows). The world law `perceived_can_on` (an ordinary law, off as shipped) splits what a character decides on from what its act is checked on:

- **Deciding** (`act::can`, a graph's `{"can": …}` condition): under the law, the skill's check runs on the context as the actor perceives it (`act::perceive`), the rule the game client's choices follow (`living/game/src/verbs.rs`):
  - another's health as it is shown to the actor (`perception::health_seen`: the band, exact while appraised; `living_rules::combat::perceived_hp`, shared with the client);
  - what another carries, or a store holds, assumed to be what is asked of it (`TargetFacts::perceived`, shared with the client); what it knows, its body's sex and when it was last hurt unknown;
  - a yield only when the actor saw it (its own `yield` lines, `living_rules::script::yielded_seen`; the client reads its `my_experience` lines the same way, under the law only);
  - whoever struck the actor counts as close (`hurt_by_near`) only while the actor sees them;
  - a store's food is "food" (`take food`), not the food it holds.
- **Acting** (`act::begin`) is unchanged: the check runs on the truth and refuses truthfully when the guess was wrong ("… does not have 1 arrow").
- **A predator's `dares`** (in `attack_check`, deciding and acting alike, since it is the predator's own judgment): under the law, the people it counts near its prey (`target.company`) are those it sees or smells, and its prey's `activity` is what it is visibly doing (`perception::visibly`: a sleep seen), not its private activity.

Off, every path is as before (one law read added per `can` and per predator check). Players' choices are the same rule; a structure's contents in `Filter.holds` targets are not covered (the audit's separate row).

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py perceived_can --run "$R" > ".local/living/verify/$R/perceived_can.txt" 2>&1
```

`scenes.py perceived_can` (any seed, about 3 minutes): W beside T, who carries 3 meat and lacks an arrow and yields in W's sight; W's probe asks `can seize` meat and the arrow (a walk 3 m north for yes, south for no). Law off: meat yes, arrow no (the leak). Law on: both yes; W's seize of the arrow is refused truthfully and T keeps its meat. Then U yields with W 13 m off (unseen) and W is brought beside U: law on no, law off yes (the private yield).

Evidence: `perceived_can-probe-*.json`, `perceived_can-t-after.json`, `perceived_can-cast.json`, `perceived_can-actions.jsonl`.

## Gotchas

- A body is not second-guessed for 45 s after it arrives; the scene sleeps until then.
- The unseen-yield probes must both finish inside the 20 s yield; the scene checks the time and fails otherwise.
- The probe reads a 3 m walk from `activity`, never a gesture (a cooldown refuses a second one silently) or a turn (one to where the body already faces is refused, and told only once).
- What T lacks is chosen when the probes start (residents gather berries meanwhile): an arrow, else salve, obsidian, hide or flint.
- T yields again before the law-on probes: the first yield has lapsed by then.
- The scene restores `perceived_can_on` in a `finally`.
