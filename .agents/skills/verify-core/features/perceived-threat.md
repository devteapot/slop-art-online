# Threatened, as perceived (`perceived_threat_on`)

Perception parity phase 1 ([audit](../../../../docs/PERCEPTION_PARITY_AUDIT.md), the `threatened` rows). The world law `perceived_threat_on` (an ordinary law, off as shipped) decides what `threatened` reads, in all three places it is read:

- a graph's condition `{"threatened": true}` (`brain.rs` `Cond::Threatened`);
- a desire's weight `threatened` (`brain.rs` `desires`);
- heed's candidate field `threatening` (`heed.rs` `Field::candidate`, behind `heed_on`), which heed's `threatened`, `attacker` and `hurt_me` read.

**Off (as shipped):** any move aimed at the character (`activity.victim == me`, a hostile move in its windup or a menace), seen or not. The condition checks sight only while sight has a field (`fov_on`); the weight never checks it; heed asks only over creatures it sees.

**On:** `perception::threat_seen` over the creatures in the character's scene (`Ev::creatures`: sight, its line, its field; under heed, its individuals): a hostile move still winding up (phases `winding up` and `about to release`) aimed at the character, by its target or its drawn aim, as `seen_fighters` shows a player; or a menace (`threaten`, which has no `fighter` or `doing` row of its own and is told to its target) at the character by someone it sees. An attacker it does not see never makes it threatened. Two changes beyond sight: a point-aimed move (a bow shot at a spot) whose drawn aim faces the character counts, as it would for a player; and the weight now follows sight too.

Cost: on, one `fighter` and at most one `doing` and `activity` point lookup per creature in the scene, as the `doing` condition; the weight is asked only when a desire weighs `threatened`. Off, the reads are as before (one law read added).

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py perceived_threat --run "$R" > ".local/living/verify/$R/perceived_threat.txt" 2>&1
```

`scenes.py perceived_threat` (any seed, about 4 minutes): W faces east on an open line, A 2 m ahead, B 2 m behind, with sight on a field (`fov_on`, near ring 0.5 m), so B is unseen. W's routine dodges when `threatened`, as a condition or as a desire's weight. Law off: A's attack is dodged by both; B's attack from behind is not dodged by the condition (its fov gate) and is dodged by the weight (the leak). Law on: A's attack and A's threat are dodged by both, B's attack and B's threat by neither.

Evidence: `perceived_threat-uses-<off|on>-<cond|weight>-<skill>-<id>.json`, `perceived_threat-cast.json`, `perceived_threat-line.json`, `perceived_threat-actions.jsonl`.

## Gotchas

- A body is not second-guessed for 45 s after it arrives; the scene sleeps until then.
- The scene restores `fov_on`, `fov_near_m`, `fov_near_dark_m` and `perceived_threat_on` in a `finally`.
- Under heed (`heed_on`), the condition and weight see only the character's individuals, as before; the scene does not drive heed.
