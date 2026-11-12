# A player's sleeping character

A player's character sleeps through its own command (`human_act` with `sleep`). While it sleeps it is woken by the same rule as anyone (`perceive::wakes`, `living/authority/src/perceive.rs`): a sound at least the `wake_loudness` law loud, by its spec's `loudness` (a way of speaking, a species signal, a skill's blow), within `wake_reach` metres. A line whose words reach it and that does not wake it is not in its log (`my_experience`) while it sleeps; it waits in the private `heard_asleep` table and is told on waking as "While you slept, you heard: …" (`perceive::heard_on_waking`). What woke it is told as "You woke up: …". Players get no deliberations.

## Sub-features

- A quiet line (`say`, loudness 1) does not wake it and is not in its log; a called name (`call`, loudness `call_carry()`, 2.5) wakes it, and the quiet line follows in its log as heard while asleep.
- Someone else's baby crying (the `cry` signal, loudness 2.5 in `species.json`) about 3 m away wakes it.
- A fight (a blow from a skill with `loudness: 2.0`) about 12 m away does not wake it; the same fight about 3 m away does ("You woke up: the noise of a fight, …").
- Struck by a resident, its own `human_act` sleep is refused: its log gets "You failed to sleep: you cannot sleep: you were struck moments ago" (the rules' `sleep_check`, laws `alert_after_hit_s` and `alert_while_attacker_near`; verify-core's [needs.md](../../verify-core/features/needs.md#sleep-in-a-fight)).
- With both alert laws off (`set_world_law`, restored after), a sleeping player is woken by a fight's second blow as well as its first (`perceive::wake_struck`).

## Driving it

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-sleep-$(date +%m%d-%H%M%S)
$V launch --run $R --seed $PWD/.agents/skills/verify-core/scripts/infant
.agents/skills/verify-player/scripts/sleep.py --run $R
$V cleanup --run $R
```

Admin calls set the scene only: `place_at`, `set_behavior`, `mind_say` for the residents' lines (as their minds would say them), and `set_world_law` for the alert laws. The player's command is a run of sleeps (`{"seq": [{"do": "sleep"}, ...]}`), since a rested body's single sleep lasts only 5 s.

## Gotchas

- A woken player's run of sleeps goes on to its next sleep: the check is what its log says woke it, not that it stays awake.
- Distances are read back after `place_at`, which takes the nearest free walkable tile.
