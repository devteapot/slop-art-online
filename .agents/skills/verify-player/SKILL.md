---
name: verify-player
description: Verify the human-player surface of the living core. A person's character joins, moves, acts, gestures (wave, nod, face), speaks and fights (use_skill, release_skill) through the player reducers with its own non-admin identity, turns to look (human_face), perceives by facing when the world's fov_on law is on (heard_sounds), and is refused what players may not do (set_world_law among them). Use when changing join, human_move, human_face, human_act, human_say, use_skill, release_skill, player permissions, or rules a player's commands run through.
---

# Verify the human player

A person outside the simulation controls one character through the public reducers `join`, `human_move`, `human_act`, `human_say`, `use_skill` and `release_skill`. The authority runs the same skills, physics and act path for that character as for AI characters. The game client (`living/game`) plays through these reducers; the browser observer cannot control anyone. The reducer API over HTTP is the entry point a player client uses.

Read the [`verify` entry point](../verify/SKILL.md) first. It owns launch, doctor, cleanup, the safety rules and the evidence standard. This skill only adds the player recipes.

## Run

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-$(date +%m%d-%H%M%S)
$V launch --run $R && $V doctor --run $R
# drive the recipes in features/
$V cleanup --run $R
```

Every player action goes through `$V player`, which uses the run's own identity minted with `POST /v1/identity`. Refusals are proven with `$V call … --as-player --expect-refusal TEXT`, which keeps the token off the command line. Admin reducers set scenes only, through `$V call … --as-admin`: `place_near` to put the player beside someone, `grant_items` to give the player something to hand over, and for combat `place_at`, `set_behavior` and `kill` (see [features/combat.md](features/combat.md); `scripts/combat.py` drives them). Gestures on an island run: `scripts/gesture.py --run $R` ([features/gestures.md](features/gestures.md)), with `place_at`. What a player perceives of others (`appraise`, names, a bystander): `scripts/appraise.py --run $R` ([features/perception.md](features/perception.md)), with `place_at` and `set_behavior`. What others perceive of a walking player: `scripts/approach.py --run $R` (same file), with `place_at` and `set_behavior` (a `think` leaf). What a player perceives by facing, with the admin's `set_world_law fov_on` (heard and not seen, the field's edge, the `face` act turning the body): `scripts/fov.py --run $R` ([features/fov.md](features/fov.md)), with `place_at`, `set_behavior` and `set_world_law`. The player's look, `human_face` (standing, walking within the walking limit, release, the input bucket): `scripts/face.py --run $R` ([features/fov.md](features/fov.md#the-players-look)), with `place_at`, `set_behavior` and `set_world_law`. Making glass at a furnace that burns fuel (refused out and short of fuel, made once fed, seen at work): `scripts/workplace.py --run $R` on a `--seed cullet-laws` run ([features/workplace.md](features/workplace.md)), with `grant_know_how`, `grant_items` and `place_structure`. Across a drop (sight, no stepping off, an arrow over it): `scripts/drop.py --run $R` on a `--seed plan-test` run ([features/drop.md](features/drop.md)), with `place_at`. Trade offers (a resident's offer in `my_offers`, a second player's outgoing one, `accept` refused then accepted): `scripts/offers.py --run $R` ([features/offers.md](features/offers.md)), with `spawn_crowd`, `set_behavior`, `place_near`, `grant_items` and the walker's `mind_act`. Dealings (an agreement through the verbs' node, told outcomes, `my_records`, a demand on the player): `scripts/deal.py --run $R` ([features/dealings.md](features/dealings.md)), with `spawn_crowd`, `place_near`, `grant_items`, `set_behavior` and the walker's `mind_act`. A skill added only in the script, used by the player, a graph and a mind's act: `scripts/new_skill.py --run $R` ([features/verbs.md](features/verbs.md)), with `install_script` (it reinstalls the tree's script at the end). A failed command told to the player as an AI is told: `scripts/told.py --run $R` ([features/player-character.md](features/player-character.md)), with `place_near`, `place_at`, `set_behavior` and `grant_items`. Name them in the report, because they are not something a player can do.

## Feature map

[features/README.md](features/README.md) lists the player features. [references/validation.md](references/validation.md) records the last real run.

## What this skill does not prove

- What a connecting client receives over subscriptions: use `verify-client`.
- Whether the rule a command triggers is correct in general: use `verify-core`.
- How the player appears in the UI: use the future UI skill (not built; see `verify`).
