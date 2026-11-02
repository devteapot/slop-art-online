---
name: verify-player
description: Verify the human-player surface of the living core. A person's character joins, moves, acts and speaks through the player reducers with its own non-admin identity, and is refused what players may not do. Use when changing join, human_move, human_act, human_say, player permissions, or rules a player's commands run through.
---

# Verify the human player

A person outside the simulation controls one character through the public reducers `join`, `human_move`, `human_act` and `human_say`. The authority runs the same skills, physics and act path for that character as for AI characters. No first-party player client exists yet; the browser observer cannot control anyone. The reducer API over HTTP is the entry point a player client uses.

Read the [`verify` entry point](../verify/SKILL.md) first. It owns launch, doctor, cleanup, the safety rules and the evidence standard. This skill only adds the player recipes.

## Run

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-$(date +%m%d-%H%M%S)
$V launch --run $R && $V doctor --run $R
# drive the recipes in features/
$V cleanup --run $R
```

Every player action goes through `$V player`, which uses the run's own identity minted with `POST /v1/identity`. Refusals are proven with `$V call … --as-player --expect-refusal TEXT`, which keeps the token off the command line. Admin reducers set scenes only, through `$V call … --as-admin`: `place_near` to put the player beside someone, and `grant_items` to give the player something to hand over. Name them in the report, because they are not something a player can do.

## Feature map

[features/README.md](features/README.md) lists the player features. [references/validation.md](references/validation.md) records the last real run.

## What this skill does not prove

- What a connecting client receives over subscriptions: use `verify-client`.
- Whether the rule a command triggers is correct in general: use `verify-core`.
- How the player appears in the UI: use the future UI skill (not built; see `verify`).
