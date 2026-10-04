# Player character

A person outside the simulation joins the world as one character and controls it through the same rules as AI characters. Movement steers the body. A command either becomes a deliberate act or replaces the character's behavior. Speech is heard by people within earshot.

## Sub-features

- `player-join`: a new identity creates one living, non-AI person near (40, 60) whose plan is `waiting for you` (`living/authority/src/lib.rs:313-327`).
- `player-join-once`: a second `join` from the same identity is refused while its character lives (`lib.rs:318`).
- `player-move`: `human_move` steers the body at a walk or a run, stops it, and sets the plan to `moving yourself` (`lib.rs:356-375`).
- `player-act-deliberate`: `human_act` with a skill that is not real-time (give, offer, gather, teach, conceive…) goes through `acts::submit`, the path minds use (`lib.rs:337-349`, `living/authority/src/acts.rs:27`). The act runs, or fails with feedback in the player's `experience` rows.
- `player-act-graph`: `human_act` with a real-time skill (`wander`, `follow`, `wait`, `attack`…; `REAL_TIME` in `living/rules/src/acts.rs:16`) becomes the character's behavior, with plan `your command` and source `human`.
- `player-say`: `human_say` writes a `speech` chronicle line, and people within earshot get a `speech` experience (`living/authority/src/perceive.rs:122-170`).
- `player-authority`: a player identity cannot call admin reducers (`admin only`), cannot use the `mind_*` reducers on someone else's character (`not your character`), and cannot join twice.

## How to get to it (user POV)

- A client calls `join(name)`, then `human_move(dx, dy, run)`, `human_act(node)` and `human_say(text, to)` with its own identity.
- No first-party player client exists in `living/`, and the browser observer cannot control anyone. The HTTP reducer API is the entry point a client would use.

## Driving it with verify.py

Set `V=.agents/skills/verify/scripts/verify.py` and `R=player-$(date +%m%d-%H%M%S)`, then run `$V launch --run $R` and `$V doctor --run $R`.

```bash
# join, once
$V player --run $R join Verifier
ME=$($V sql --run $R "SELECT id FROM character WHERE name = 'Verifier'" | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
$V sql --run $R "SELECT id, name, ai, alive FROM character WHERE id = $ME" --save me                       # ai false, alive true
$V call --run $R join '["Again"]' --as-player --expect-refusal "you already have a living character"

# scene (admin): a neighbour, and something to give
X=$($V sql --run $R "SELECT id FROM character WHERE kind = 'person' AND ai = true AND alive = true" | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
$V call --run $R place_near "[$ME, $X]" --as-admin
$V call --run $R grant_items "[$ME, \"berries\", 3]" --as-admin

# deliberate act: a gift
$V player --run $R act "{\"do\":{\"skill\":\"give\",\"target\":{\"id\":$X},\"item\":\"berries\",\"qty\":1}}"; sleep 4
$V sql --run $R "SELECT owner, item, qty FROM inventory WHERE owner = $ME" --save inv-after-give               # berries 3 -> 2
$V sql --run $R "SELECT kind, a, b, text FROM chronicle WHERE a = $ME" --save chronicle-give                    # "Verifier gave 1 berries to <name>"

# deliberate act that fails: feedback reaches the player
$V player --run $R act "{\"do\":{\"skill\":\"give\",\"target\":{\"id\":$X},\"item\":\"berries\",\"qty\":99}}"; sleep 2
$V sql --run $R "SELECT kind, text FROM experience WHERE observer = $ME AND kind = 'act'" --save act-feedback    # "…did not work out…"

# graph branch: a real-time skill becomes the behavior
$V player --run $R act "{\"do\":{\"skill\":\"follow\",\"target\":{\"id\":$X}}}"; sleep 1
$V sql --run $R "SELECT id, plan, source FROM brain WHERE id = $ME" --save plan-follow                         # your command / human
$V sql --run $R "SELECT id, skill FROM activity WHERE id = $ME" --save activity-follow                         # follow

# movement: run, walk, stop
$V player --run $R move 1 0 --run-gait; sleep 1
$V sql --run $R "SELECT id, vx, vy, speed FROM body WHERE id = $ME" --save body-run                           # about 4.1
$V player --run $R move 1 0; sleep 1
$V sql --run $R "SELECT id, vx, vy, speed FROM body WHERE id = $ME" --save body-walk                          # about 2.5-2.7
$V player --run $R move 0 0; sleep 1
$V sql --run $R "SELECT id, vx, vy FROM body WHERE id = $ME" --save body-stopped                               # 0, 0
$V sql --run $R "SELECT id, plan FROM brain WHERE id = $ME" --save plan-moving                                 # moving yourself

# speech, heard by the neighbour
$V call --run $R place_near "[$ME, $X]" --as-admin
$V player --run $R say "Good morning." --to $X; sleep 1
$V sql --run $R "SELECT kind, a, text FROM chronicle WHERE a = $ME AND kind = 'speech'" --save speech
$V sql --run $R "SELECT observer, kind, text FROM experience WHERE observer = $X AND kind = 'speech'" --save heard # "Verifier said to you: …"

# what a player may not do
$V call --run $R set_paused '[true]' --as-player --expect-refusal "admin only"
$V call --run $R grant_items "[$ME, \"berries\", 50]" --as-player --expect-refusal "admin only"
$V call --run $R mind_skip "[$X, 0, {\"kind\":\"deliberate\",\"summary\":\"\",\"detail\":\"\",\"latency_ms\":0,\"tokens\":0,\"model\":\"\",\"reference\":\"\"}]" --as-player --expect-refusal "not your character"

$V cleanup --run $R
```

## Gotchas

- Item names are the authority's: `berries`, not `berry`. An act normalizes a near-miss name before checking it, but admin `grant_items` stores any string unchecked, so a mistyped grant leaves the player holding an item no skill uses.
- The receiver of a gift is an AI character still running its instincts, so its inventory can change on its own between snapshots. Prove a gift by the giver's count and the `chronicle` line.
- `body.x`/`body.y` are the start of the current movement segment, not the live position. The position at time `t` is the segment start plus velocity times `(t - t_ms)`, up to `next_ms`. Read velocity and speed to prove movement, at least one tick after the call.
- Movement input is rate-limited by `input_hz`/`input_burst` in `living/scripts/skills.rhai`. Rapid changes can be refused; repeating the current intent is free.
- `human_say` refuses lines less than 2 s apart (`speaking too fast`) for characters with a mind state. A line addressed to someone out of earshot gives the speaker a `silence` experience.
- `join` places the character near (40, 60), in the north-west corner of the default map, far from the towns. Use admin `place_near` to bring the player to someone.
- `experience` rows are readable anonymously today. That is a known privacy issue tracked by `verify-client`. The recipes read them because the authority does, not because a client should.
- The reducer argument JSON must match the signature exactly. A wrong arity returns HTTP 400 `invalid arguments`, which is not a permission refusal.
