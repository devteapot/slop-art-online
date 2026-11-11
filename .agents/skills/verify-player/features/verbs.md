# Verbs from the game client

The game client offers a player every act the rules allow, from the rules' own data (`living/game/src/verbs.rs`, docs/GAME_BRIEF.md "Verbs"; since `rules-2` every skill comes from its `<skill>_spec()` in the installed script, docs/WORLD_RULES.md): gather, eat, craft, build, write, give, offer, teach, sleep and the rest. Every act it sends is a `human_act` on the same act path minds use (`acts::submit`), or a `human_say` for asking to be taught. This feature proves that path from the real client, not from HTTP calls.

## Sub-features

- **F on a thing:** a berry bush within reach is aimed at (`verbs::aim`); the hint names the likely act (`F gather`), F's list holds what the rules' checks allow there (`gather`, `face`), and the act is `{"do": "gather", "target": {"nearest": "berry_bush"}}`. The outcome is an `act` experience: "You did what you had decided: gather → berry_bush (+1 berries)."
- **C on myself:** eat, craft, build, write, drop, experiment, sleep, rest, …, with what the character carries and knows. `eat berries` and `craft spear` (once spear is known and 2 wood and 1 stone are carried) are accepted; `craft bow` without archery is refused by the authority with the rules' reason, shown as a red-edged note.
- **Words:** `write tablet` opens the text box (its check refuses an empty text); the act carries the words: "You did what you had decided: write tablet (wrote a tablet)."
- **F on a person:** give, offer, offer_terms, demand, accept, host, conceive, teach, tend, appraise, wave, nod, join, welcome, follow, and asking to be taught (a skill whose spec reads `want` offers one choice per thing to ask for, from what the character carries and the skill's `items`, such as `lodging`); `give berries` is accepted: "… gave 1 berries to a stranger" (the resident as the player perceives it).
- **Sleep** goes through `human_act` as before and becomes the character's behaviour (an ongoing skill is not an act).
- **Panels:** I lists `my_inventory` with the rules' `nutrition` and `carry_limit`; K lists `my_know_how` (technique and source) and every skill with its spec's description, takes and gives.
- **A skill the world adds:** on a scratch authority whose script defines a throwaway `polish` (its spec and rules; before `rules-2` also a catalog line), the unchanged client binary lists it on a boulder and in K, and the authority performs it. Cargo: `a_skill_the_rules_add_is_offered`.
- **What the rules tell me:** experiences of kind `record` (an agreement kept or broken, a demand on me) show as notes ([dealings](dealings.md)).

## How to get to it (user POV)

```bash
$V launch --run client-verbs-$S --seed island && $V doctor --run client-verbs-$S
# a private release build of living-game (CARGO_TARGET_DIR), copied before running
python3 drive_verbs.py client-verbs-$S .local/living/verify/client-verbs-$S/game "$(cat plan.txt)" --resident ID
```

`drive_verbs.py` (kept with the evidence of the 2026-11-10 run) runs the copy headless with `LIVING_GAME_LIVE`, answers the plan's `sync:granted` with admin `grant_know_how` (spear, writing) and `grant_items` (4 wood, 1 stone), and `sync:resident` with admin `set_behavior` (the resident holds still) and `place_near`; it snapshots `inventory`, `know_how` and `experience` of the character as the owner before and after. Name those admin calls in the report. The plan's steps are `act:`, `menu:`, `words:` and `panel:` ([verify-client game-client](../../verify-client/features/game-client.md)).

Check the character's `experience` rows of kind `act` (one per act, accepted or refused), the pack and know-how before and after, the log's `verbs: <label> → <node>` lines and the photographs (hint, lists, notes, panels).

## Gotchas

- Things are named to the authority by kind, nearest first: stand by the bush you mean, or the client turns the act into a walk to it and then the act (`{"seq": [goto, act]}`), which runs as behaviour and reports no `act` row.
- A scripted `act:` is sent whether or not the client's rules offered it (the log says which), so a refusal can be driven.
- A resident given an item asks its mind (every resident has one); without a mind service it stays put under `set_behavior`.
