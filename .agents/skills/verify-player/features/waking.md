# Waking residents (town life layer 2)

Since 2026-11-09 (docs/TOWN_LIFE.md, "Layer 2"). On an island world (`rules.minds = false`) residents live on their behaviour graphs alone. A player who engages one wakes it into a mind, which it keeps. Which engagements wake is the `wakes` law, and the ring each resident keeps before it wakes is the `woken_ring` law, both in `living/scripts/skills.rhai`. The engine has one entry point, `woken::engage` (`living/authority/src/woken.rs`), called from `act::perform` (a skill aimed at someone as it starts), `perceive::speak` (an addressed listener), `act::damage` (`hurt`) and the store `take` effect (`theft`).

## Sub-features

- A fresh island has no `woken` row; rings (`prior`) are at most `woken_ring("slots")` rows per resident, keyed `resident << 8 | slot`.
- A resident who sees the player's character come into view keeps "A stranger came into view." in its ring (from the player's perceived-set sweep).
- `human_say` to a resident wakes it: a `woken` row (`why = speech`, `by` the player, `prior` counted, the places it knew), `ai` and controller the world admin, the line as an experience of its mind, a first deliberation pending ("… spoke to you.").
- A resident in earshot but not addressed keeps the line in its ring, worded as it perceives the speaker ("A stranger said to …"), and stays instinct only; residents out of earshot have nothing of it.
- `human_act` `wave`, `give`, `offer` and `teach` aimed at a resident wake it as the act starts (`why` is the skill's name).
- Residents greeting one another meanwhile wake nobody; woken residents stay minds; engaging a woken one again counts an engagement on its row.
- `woken`, `prior` and `prior_head` are refused to the player and to an anonymous client.

## Driving it

```bash
V=.agents/skills/verify/scripts/verify.py
$V launch --run player-wake-<n> --seed island --target-dir .local/living/target-wake-island
.agents/skills/verify-player/scripts/wake.py --run player-wake-<n>
$V cleanup --run player-wake-<n>
```

Admin scene calls: `place_at` (the player beside a resident at its post), `grant_items` (berries), `grant_know_how` (techniques to teach). The driver reads `hearing` and the ring's `slots` from `living/scripts/skills.rhai`. No mind service runs; the mind side is verify-minds' `wake` case. Evidence: `<run>/wake.json`, `actions.log`.

## Gotchas

- A lesson takes 15 s; waking happens as it starts, so the check does not wait for the lesson to land.
- On a world younger than a minute the rings may still be empty; the driver waits up to 60 s for the first rows.
- Run the scene on its own island run: a second player in the same world would itself be engaged and perceived.
