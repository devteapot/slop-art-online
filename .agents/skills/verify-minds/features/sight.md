# A mind sees what its character sees

Since 2026-11-09 (docs/PERCEPTION.md, "Minds see what their character sees"). Every perception path for minds uses the players' rule: sight by light and a clear sight line (rock, walls and shut gates hide).

## Sub-features

- Three AI residents are placed by the admin on the world's own map: the eye, one at most 4 tiles away behind rock or wall, and one 3 tiles away in the open. The deliberation the eye is asked for (`deliberation.scene`) and the prompt the model is sent list the one in the open and not the hidden one (`sent-prompt.txt`).
- Drops and low tiles do not hide (they block only the foot): [drop.md](drop.md) proves a mind sees across them.
- Both others are killed (admin `kill`): the eye's experiences hold the death in the open and not the one behind the wall.

- `death-names` (since fix-death-labels, 2026-11-11): four spawned people. The victim founds a community and welcomes the mind's character (`mind_act` found/join/welcome); an authored relation (`set_background` sheet) makes the mind feel something for the victim. The mind is asked once while the victim lives (`prompt-alive.txt`), the victim yields and an outsider kills it with a spear, and the mind is asked again (`prompt-after-death.txt`). Asserted: one `acquaintance` row for the victim, the member's (`perception::remember_member` in `die`); the member's death experience begins with the victim's name; the killer's reads "was killed by you" and not its own name; a bystander reads "A stranger was killed by a stranger"; both prompts list the relation as `<victim> (#id)` (`known_as`), never `a stranger (#id)`, and the after-death prompt's experience line names the victim with its id tag (`<victim>=#id`). Texts in `death-names.json`.
- `health-seen` (since fix-health-leak, 2026-11-11): two spawned strangers fight; A is thought for by the real mind service (the fake model's plans keep A attacking B), B by an `attack` graph. Fight reports (`act::fight_report`, urgent reasons) reach A's prompts. Asserted: every report sent before the appraisal ends with the band's words ("they look scratched."), no number and no `%`; after A appraises B (`mind_act`), a report inside the 20 s reveal ends "they have N of M health." with M B's full health; no prompt carries the old "theirs looks about N%". Texts in `health-seen.json`.

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case sight
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case death-names
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case health-seen
```

## Gotchas

- `death-names` waits out the person's `think_min_s` (20 s, `living/seeds/species.json`) between its two asks; a sooner non-urgent ask is dropped by the authority.

- The geometry search reads `terrain_chunk` (public) for a thin rock or wall run with open ground on the eye's side; a map without one fails with "no wall geometry", a fixture failure.
- Players' side of the same rule is `verify-client`'s perception checks; the combat feed's is covered there and in `verify-core`.
- Someone too far away to make out (far-label, 2026-11-12, docs/STRANGERS.md §1): where the world's `perceived_of` law marks a person `far` (Cullet past 24 m), the scene a mind is sent lists them as `"who": "someone too far away to make out"` with their `id`, no `name` and no `community`, and no first sight of them is told until they can be made out. Driven in verify-core `stranger_filter` (the scene the authority writes for a mind) and verify-client `far_label.py` (the same label to a player); the mind service changes only how memory names them (verify-knowledge [strangers](../../verify-knowledge/features/strangers.md)). `roundtrip` and `conversation` were rerun on far-label (2026-11-12) and pass.
