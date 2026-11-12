# A mind sees what its character sees

Since 2026-11-09 (docs/PERCEPTION.md, "Minds see what their character sees"). Every perception path for minds uses the players' rule: sight by light and a clear sight line (rock, walls and shut gates hide).

## Sub-features

- Three AI residents are placed by the admin on the world's own map: the eye, one at most 4 tiles away behind rock or wall, and one 3 tiles away in the open. The deliberation the eye is asked for (`deliberation.scene`) and the prompt the model is sent list the one in the open and not the hidden one (`sent-prompt.txt`).
- Drops and low tiles do not hide (they block only the foot): [drop.md](drop.md) proves a mind sees across them.
- Both others are killed (admin `kill`): the eye's experiences hold the death in the open and not the one behind the wall.

- `death-names` (since fix-death-labels, 2026-11-11): four spawned people. The victim founds a community and welcomes the mind's character (`mind_act` found/join/welcome); an authored relation (`set_background` sheet) makes the mind feel something for the victim. The mind is asked once while the victim lives (`prompt-alive.txt`), the victim yields and an outsider kills it with a spear, and the mind is asked again (`prompt-after-death.txt`). Asserted: one `acquaintance` row for the victim, the member's (`perception::remember_member` in `die`); the member's death experience begins with the victim's name; the killer's reads "was killed by you" and not its own name; a bystander reads "A stranger was killed by a stranger"; both prompts list the relation as `<victim> (#id)` (`known_as`), never `a stranger (#id)`, and the after-death prompt's experience line names the victim with its id tag (`<victim>=#id`). Texts in `death-names.json`.
- `health-seen` (since fix-health-leak, 2026-11-11): two spawned strangers fight; A is thought for by the real mind service (the fake model's plans keep A attacking B), B by an `attack` graph. Fight reports (`act::fight_report`, urgent reasons) reach A's prompts. Asserted: every report sent before the appraisal ends with the band's words ("they look scratched."), no number and no `%`; after A appraises B (`mind_act`), a report inside the 20 s reveal ends "they have N of M health." with M B's full health; no prompt carries the old "theirs looks about N%". Texts in `health-seen.json`.

## What someone is visibly doing

Since `doing-percept` (2026-11-12; docs/PERCEPTION.md, "What someone is visibly doing"). `perceive::scene_json` gives each creature in sight a `visibly` entry read from the rows a player's client draws (`perception::visibly`: its `fighter` move by its timing, else its `doing` row): `is` (the skill), `phase` (`living_rules::doing::Phase`), `at` (`you`, or the id of a target in sight). The graph grammar in `living/mind/src/prompts.rs` documents the `doing` condition beside `health_of`.

- `doing`: a resident faces another 3 m east who holds up a guard (`block`, held, a `fighter` row with `act`). The pending request's scene lists the other with `visibly` `{is: block, phase: holding}`, with `at: you` only when the other's guard happens to face the eye (a guard has no target; its drawn aim decides); the think prompt the fake model is sent carries it; the deliberate prompt's grammar carries `{"doing": {"who": "person", "is": "hostile", "phase": "winding up"` (a kind word since fix-dodge-told, not a skill the reader may never face) and `about to release`. Evidence: `scene.json`, `sent-prompts.txt`, `result.json`.
- What the routine does with it on the tick, the field, the far label and beyond sight are verify-core's ([doing](../../verify-core/features/doing.md)).

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case doing
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case sight
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case death-names
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case health-seen
```

## Gotchas

- `death-names` waits out the person's `think_min_s` (20 s, `living/seeds/species.json`) between its two asks; a sooner non-urgent ask is dropped by the authority.

- The geometry search reads `terrain_chunk` (public) for a thin rock or wall run with open ground on the eye's side; a map without one fails with "no wall geometry", a fixture failure.
- Players' side of the same rule is `verify-client`'s perception checks; the combat feed's is covered there and in `verify-core`.
- Someone too far away to make out (far-label, 2026-11-12, docs/STRANGERS.md §1): where the world's `perceived_of` law marks a person `far` (Cullet past 24 m), the scene a mind is sent lists them as `"who": "someone too far away to make out"` with their `id`, no `name` and no `community`, and no first sight of them is told until they can be made out. Driven in verify-core `stranger_filter` (the scene the authority writes for a mind) and verify-client `far_label.py` (the same label to a player); the mind service changes only how memory names them (verify-knowledge [strangers](../../verify-knowledge/features/strangers.md)). `roundtrip` and `conversation` were rerun on far-label (2026-11-12) and pass.
- `far-figure` (far-handle, 2026-11-12, docs/STRANGERS.md "Far handles"): two spawned people. M (thought for) founds a community and welcomes F, and an authored relation puts F in M's relations ("F (#id): neighbour"). An overlay of `perceived_of` makes everyone past 4 m `far` (`install_script.py`). F stands 5 m off and says a line (`mind_say`, admin). M's next prompt (`prompt-far.txt`) is checked:
  - the scene lists a figure too far away to make out under a handle (≥ 1000000000), and no entry with F's id;
  - the relations list names F;
  - F's line is tagged with the handle, not F's id or name;
  - no prompt line holds both the handle and F's name or id.
  M's `mind_act` wave at the handle reaches F (`skill_use.target`). F is placed 2 m off: a `made_out` experience joins the handle to F's id, and the next prompt names F. The shipped script is installed again at the end. Evidence: `far-figure.json`, `prompt-far.txt`, `prompt-near.txt`.

## A first sight asks a thought

Since `first-sight` (2026-11-12; docs/FIRST_SIGHT.md). Under the world's `first_sight_thinks` law, a first sight of someone the character cannot place asks its mind for one thought, and the reason is the first-sight line itself.

- `first-sight`: M's mind runs on the fake model. The case sets `first_sight_thinks` true and `first_sight_gap_s` 0 with `set_world_law`, because M's opening thought may itself be a first sight of someone else in view. It waits 30 s (past `think_min_s`), then places U, a stranger to M, 2 m away. The first think request sent after that carries U's first-sight line ("For the first time you see a stranger, 2 tiles east, wait.") as a line of "# Why you are thinking now", word for word, with no "newcomer", "visitor", "new to you", "near your home" or "worth". Evidence `first-sight.json`, `prompt-first-sight.txt`. The laws are restored.
- Without the gap at 0, U's sight can fall inside the 300 s gap that M's opening first sight started, and nothing is asked. That is the gap working, not a failure (the first attempt `minds-fs1` showed it).
- The throttle, the gap, far and named figures, sleepers and cues are verify-core's ([first-sight](../../verify-core/features/first-sight.md)).

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case first-sight
```

## A dodge told truthfully (fix-dodge-told)

- `dodge-told`: the mind service runs throughout. The eye stands two tiles short of a wall, the other (a spear) beside it; the eye's graph dodges toward the wall on `doing` attack "winding up": the dash is over before the blow lands, and the eye is told "You failed to dodge: it was over before the blow came" (its `skill_use` says so). After the mind has answered the attack, a graph restarting a dodge every tick for 4 s is refused while not ready: at most one "not ready yet" line per cooldown. The prompt of a thought asked afterwards (`Run.request`, marker `dodge-told`) carries the first line, and no more "not ready yet" lines than dodges made plus one. Evidence: `eye-told.json`, `eye-told-streak.json`, `uses-early.json`, `sent-prompts.txt`, `result.json`.
