# A mind sees what its character sees

Since 2026-11-09 (docs/PERCEPTION.md, "Minds see what their character sees"). Every perception path for minds uses the players' rule: sight by light and a clear sight line (rock, walls and shut gates hide).

## Sub-features

- Three AI residents are placed by the admin on the world's own map: the eye, one at most 4 tiles away behind rock or wall, and one 3 tiles away in the open. The deliberation the eye is asked for (`deliberation.scene`) and the prompt the model is sent list the one in the open and not the hidden one (`sent-prompt.txt`).
- Drops and low tiles do not hide (they block only the foot): [drop.md](drop.md) proves a mind sees across them.
- Both others are killed (admin `kill`): the eye's experiences hold the death in the open and not the one behind the wall.

- `death-names` (since fix-death-labels, 2026-11-11): four spawned people. The victim founds a community and welcomes the mind's character (`mind_act` found/join/welcome); an authored relation (`set_background` sheet) makes the mind feel something for the victim. The mind is asked once while the victim lives (`prompt-alive.txt`), the victim yields and an outsider kills it with a spear, and the mind is asked again (`prompt-after-death.txt`). Asserted: one `acquaintance` row for the victim, the member's (`perception::remember_member` in `die`); the member's death experience begins with the victim's name; the killer's reads "was killed by you" and not its own name; a bystander reads "A stranger was killed by a stranger"; both prompts list the relation as `<victim> (#id)` (`known_as`; since sex-1 `<victim> (#id, a man)` with their body), never `a stranger (#id…)`, and the after-death prompt's experience line names the victim with its id tag (`<victim>=#id`). Texts in `death-names.json`.
- `watch-fight` (since battle-fold, 2026-11-12; docs/BATTLE_SCALE.md fix 4, the `witness_fold_ms` law): five spawned strangers. The mind's character W stands between two fights it is not party to: A, with a spear, strikes V until V falls; C strikes D, who blocks when threatened (graphs). W's onlooker lines are folded, one `fight` line per window. Asserted: the blows W's lines count lie between the `fight_seen` rows naming W (read by polling, a lower bound) and the strikes the rules resolved, equal to the strikes when W is among every row read, in fewer lines than blows. Rows and lines are both read while the fights go on: consolidation takes integrated lines out of the inbox; a line has A's blows on V landing and C's on D blocked, each stranger anchored as `a stranger (#id)` by the id W's scene knows them by; V's fall is told once (`… (#V) fell.`); the think prompt asked afterwards (`prompt-watched.txt`) carries those lines. Texts in `watch-fight.json`.
- `health-seen` (since fix-health-leak, 2026-11-11): two spawned strangers fight; A is thought for by the real mind service (the fake model's plans keep A attacking B), B by an `attack` graph. Fight reports (`act::fight_report`, urgent reasons) reach A's prompts. Asserted: every report sent before the appraisal ends with the band's words ("they look scratched."), no number and no `%`; after A appraises B (`mind_act`), a report inside the 20 s reveal ends "they have N of M health." with M B's full health; no prompt carries the old "theirs looks about N%". Texts in `health-seen.json`.

## What someone is visibly doing

Since `doing-percept` (2026-11-12; docs/PERCEPTION.md, "What someone is visibly doing"). `perceive::scene_json` gives each creature in sight a `visibly` entry read from the rows a player's client draws (`perception::visibly`: its `fighter` move by its timing, else its `doing` row): `is` (the skill), `phase` (`living_rules::doing::Phase`), `at` (`you`, or the id of a target in sight). The graph grammar in `living/mind/src/prompts.rs` documents the `doing` condition beside `health_of`.

- `doing`: a resident faces another 3 m east who holds up a guard (`block`, held, a `fighter` row with `act`). The pending request's scene lists the other with `visibly` `{is: block, phase: holding}`, with `at: you` only when the other's guard happens to face the eye (a guard has no target; its drawn aim decides); the think prompt the fake model is sent carries it; the deliberate prompt's grammar carries `{"doing": {"who": "person", "is": "hostile", "phase": "winding up"` (a kind word since fix-dodge-told, not a skill the reader may never face) and `about to release`. Evidence: `scene.json`, `sent-prompts.txt`, `result.json`.
- What the routine does with it on the tick, the field, the far label and beyond sight are verify-core's ([doing](../../verify-core/features/doing.md)).

## Who would hear you now

Since `earshot` (2026-11-12; docs/COMMUNICATION.md §17), behind the world's `earshot` law (off as shipped). A person's deliberation scene says whom a line said now would reach, at each way, among the people it lists: `"who would hear you now": "Within earshot if you say it: Walker2 (#269); a whisper would reach no one; a call would also reach: a stranger (#270)."` (`perceive::scene_json`, `earshot::reach` and `words`; the key is `living_rules::script::speech::EARSHOT`). Each person is named as the mind knows them, with the id the scene shows them under (a far figure's handle). Someone the scene does not list is never named, though a line may reach them.

- `earshot`: on a quiet open line (`open_line`, a copy of verify-core's `quiet_line`), H (thought for) stands with A 3 m east, B 10 m east and C 15 m west; A and C tell H their names first. With the law off, H's think prompt has no such key (`prompt-earshot-off.txt`). The admin turns it on (`set_world_law earshot true`), and H's next think prompt (`prompt-earshot.txt`) lists A by name at say, B as a stranger added by a call (by day; sight 11 m), and never C (15 m, beyond sight). H then says a line to the room and calls one (admin `mind_say`). Among A, B and C, those who receive each are exactly the list at that way, and C receives the call unlisted. By night (sight 6 m) B is out of sight too, and the case expects "a call would reach no one more". Evidence: `earshot.json`.

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case doing
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case sight
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case death-names
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case watch-fight
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case health-seen
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case earshot
```

## Gotchas

- `death-names` and `watch-fight` wait out the person's `think_min_s` (20 s, `living/seeds/species.json`) between its two asks; a sooner non-urgent ask is dropped by the authority.

- The geometry search reads `terrain_chunk` (public) for a thin rock or wall run with open ground on the eye's side; a map without one fails with "no wall geometry", a fixture failure.
- Players' side of the same rule is `verify-client`'s perception checks; the combat feed's is covered there and in `verify-core`.
- Someone too far away to make out (far-label, 2026-11-12, docs/STRANGERS.md §1): where the world's `perceived_of` law marks a person `far` (Cullet past 24 m), the scene a mind is sent lists them as `"who": "someone too far away to make out"` with their `id`, no `name` and no `community`, and no first sight of them is told until they can be made out. Driven in verify-core `stranger_filter` (the scene the authority writes for a mind) and verify-client `far_label.py` (the same label to a player); the mind service changes only how memory names them (verify-knowledge [strangers](../../verify-knowledge/features/strangers.md)). `roundtrip` and `conversation` were rerun on far-label (2026-11-12) and pass.
- `far-figure` (far-handle, 2026-11-12, docs/STRANGERS.md "Far handles"): two spawned people. M (thought for) founds a community and welcomes F, and an authored relation puts F in M's relations ("F (#id): neighbour", since sex-1 "F (#id, a woman): neighbour"). An overlay of `perceived_of` makes everyone past 4 m `far` (`install_script.py`). F stands 5 m off and says a line (`mind_say`, admin). M's next prompt (`prompt-far.txt`) is checked:
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

## The think prompt's framing (`think_framing`)

Since `think-framing` (2026-11-12; docs/FRAMING.md). The world's `think_framing` law chooses the think prompt's framing: off, today's; on, the neutral one (N2).

- `think-framing`: M's mind runs on the fake model.
  - **Off:** with `set_world_law think_framing false`, M is asked to think (`Run.request`). The think request carries today's sentence ("Start from why you are thinking now: …") once, and the section "# Why you are thinking now".
  - **On:** after `set_world_law think_framing true`, the next think request's system prompt equals the off one with that sentence replaced by the neutral one. Its user prompt has the same sections in the same order, the reason's renamed "# What just happened".
  - **Evidence:** `prompt-off.json`, `prompt-on.json`, `think-framing.json`. The law is restored.

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case think-framing
```

## A dodge told truthfully (fix-dodge-told)

- `dodge-told`: the mind service runs throughout. The eye stands two tiles short of a wall, the other (a spear) beside it; the eye's graph dodges toward the wall on `doing` attack "winding up": the dash is over before the blow lands, and the eye is told "You failed to dodge: it was over before the blow came" (its `skill_use` says so). After the mind has answered the attack, a graph restarting a dodge every tick for 4 s is refused while not ready: at most one "not ready yet" line per cooldown. The prompt of a thought asked afterwards (`Run.request`, marker `dodge-told`) carries the first line, and no more "not ready yet" lines than dodges made plus one. Evidence: `eye-told.json`, `eye-told-streak.json`, `uses-early.json`, `sent-prompts.txt`, `result.json`.

## Whose a house is (house-owner-label)

Since 2026-11-12 (docs/PERCEPTION.md "Whose a thing is"). `house-owner`: three spawned people. M founds a community and welcomes F (`mind_act`); X stays a stranger to M. An overlay of the shipped script makes anyone past 4 m too far away to make out (as Cullet's `perceived_of` past 24 m) and gives the `storage` kind `shows_owner`. With M 40 m off, F puts up a house and X a house and a storage (`place_structure`); F and X go 30 m off and M is brought beside the houses; the real mind with the fake model is asked once (`Run.request`, marker `house`).

- Asserted from the think prompt (`prompt-house.txt`): F's house carries `home_of` and `by` with F's name; X's house carries neither; X's storage carries `by` with X's name; no structure entry carries "someone too far away to make out".
- Asserted from every request the model was sent (the mind integrates its experience rows, so the experience table is empty by then): "You notice a house built by F … {F=#id}" and "You notice a storage built by X … {X=#id}", tagged by id; X's house noticed with no tag; no notice line tagged by a far handle. Before the fix the lines named the owner by the far label, and after the label fix alone, the far handle still tagged a line that named the owner (`percept_owned`).
- Evidence: `house-owner.json` (entries, noticed lines, checks), `prompt-house.txt`, `fake-requests.jsonl`, `house-overlay.rhai`. The shipped script is installed again at the end.
