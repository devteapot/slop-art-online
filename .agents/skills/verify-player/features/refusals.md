# Truthful refusals for a player

Since `truthful-refusals` (2026-11-22, [docs/TRUTHFUL_REFUSALS.md](../../../../docs/TRUTHFUL_REFUSALS.md)). A player's `human_act` runs the act path a mind's act runs; a target that does not resolve is refused with the why the authority works out (`brain.rs` `Ev::unresolved`) and its code in `my_act_outcomes` (`unknown`, `unseen`, `refused`). verify-core `scenes.py truthful_refusals` drives every kind through a mind's act and graph leaves.

## Recipe

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-refusals-$(date +%m%d-%H%M%S)
$V launch --run $R && $V doctor --run $R
.agents/skills/verify-player/scripts/refusals.py --run $R
$V cleanup --run $R
```

The default seed (residents). Admin calls set the scene only: `set_behavior` (the resident waits), `place_near`, `kill`. About 20 s. Writes `RUN/refusals.json`. Run it on a fresh run or first: it joins the run's player.

## What it checks

1. `goto {"place": "verify nowhere"}`: code `unknown`, `why` "you know no place called "verify nowhere"", the same words in its `act` line, which says nothing of sight.
2. `wave → attacker` with nobody hurting it: `unknown`, "nobody has hurt you in the last minute".
3. `wave → {"id": far}` (a resident over 60 m off): `unseen`, `"<label> is not in sight"` (known name, else `"a stranger"` / `"someone"`, no raw `#N`).
4. Control: `wave` at the resident beside it: ok, `done`.
5. Control: `goto {"place": "home"}` with no "home" place row: a `goto` starts, nothing refused, its `steer` goal the character's own `home_x`/`home_y`.
6. The resident beside it killed (`kill`): `refused`, `"<Label> is dead: their remains lie in sight"`.

## Not covered

- Non-acts: `human_act` makes a non-act node the character's command graph, and an unreadable node is a reducer error; the named non-act refusals are a mind's (`scenes.py truthful_refusals`).
- The other roles (`speaker`, `hailer`, `suitor`, `partner`, `parent`) and bare resources through `human_act`: the same function, driven for a mind in verify-core.
