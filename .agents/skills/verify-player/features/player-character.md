# Player character

A person outside the simulation joins the world as one character and controls it through the same rules as AI characters. Movement steers the body. A command either becomes a deliberate act or replaces the character's behavior. Speech is heard by people within earshot.

## Sub-features

- `player-join`: a new identity creates one living, non-AI person near (40, 60) whose plan is `waiting for you` (`living/authority/src/lib.rs:313-327`).
- `player-join-once`: a second `join` from the same identity is refused while its character lives (`lib.rs:318`).
- `player-move`: `human_move` steers the body at a walk or a run, stops it, and sets the plan to `moving yourself` (`lib.rs:356-375`).
- `player-act-deliberate`: `human_act` with a skill that is not real-time (give, offer, gather, teach, conceive…) goes through `acts::submit`, the path minds use (`lib.rs:337-349`, `living/authority/src/acts.rs:27`). The act runs, or fails with feedback in the player's `experience` rows.
- `player-act-graph`: `human_act` with a real-time skill (`wander`, `follow`, `wait`, `attack`…; `Shapes::real_time` in `living/rules/src/combat.rs`: `MOVES` and each combat skill's `real_time` trait in `living/scripts/skills.rhai`) becomes the character's behavior, with plan `your command` and source `human`.
- `player-walk-far`: click-to-move (`human_act` with `{"do":"goto","target":{"at":[x,y]}}`, a deliberate act) reaches another settlement anywhere on the island, leg by leg, and lasts as long as the walk takes; a short click round a building row or a pond reaches it too. A click more than 12 m into water is refused ("destination unreachable"), and a place that cannot be reached at all is refused ("no path there") (`living/authority/src/motion.rs` `start`, `living/rules/src/nav.rs`, `acts::overdue`; docs/PATHS.md).
- `player-say`: `human_say` writes a `speech` chronicle line, and people within earshot get a `speech` experience (`living/authority/src/perceive.rs`, `speak`). The player's own character perceives its words as a `said` experience ("You said to <name>: “…”", salience 0.5; since 2026-11-09, for player memory, docs/PLAYER_MEMORY.md); AI speakers get none.
- `player-authority`: a player identity cannot call admin reducers (`admin only`), cannot use the `mind_*` reducers on someone else's character (`not your character`), and cannot join twice.

## Walking far (island seed)

`living/tools/walk_times.py` drives it with one fresh identity per walker, all at once: each joins, clicks on the `--from` settlement, then on its own target settlement (`--to all`: every other one), and `--clicks N` adds a walker making N clicks 30–60 m away in random directions. It records each outcome (the `act` experience row), the seconds to arrival, the walked length from `body` samples and the distance left. Each poll is a call as the walker, so its person stays present (no takeover). Use the run's own server variables, as for `$V`.

```bash
$V launch --run $R --seed island && $V doctor --run $R
python3 living/tools/walk_times.py --db verify-$R --clicks 40 --out .local/living/verify/$R/walks.jsonl \
  2> .local/living/verify/$R/walks.stderr   # 16 journeys from Brackenford and 40 clicks; about 25 min
```

Expect "You did what you had decided: goto → (x,y)." for every journey and click, `left_m` 0.0, and walk times close to the road or straight-line length at 2.6 m/s walking (1.4× on roads). Compare with docs/PATHS.md.

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
- On a land world (`--seed island`), `join` places the character at the `land` row's `arrive_x`/`arrive_y`, outside the town's first gate. Residents there run without minds (`rules.minds = false`): they are `ai = false` and write no `experience` rows. Pick a neighbour with `kind = 'person' AND alive = true AND stage = 2 AND id != $ME` instead of `ai = true`, and prove speech by the `chronicle` line. A gift may fail because the resident walks away on its own routine.
- `$V sql` reads as the database owner, so these recipes read `experience`, `brain`, `chronicle` and the rest as developer truth; that says nothing of what a client may read. A player reads its own through the views (`SELECT * FROM my_experience` with `--as-player`), and in a `LIVING_PERCEPTION=scoped` build the tables themselves refuse it (docs/PERCEPTION.md, `verify-client`).
- The reducer argument JSON must match the signature exactly. A wrong arity returns HTTP 400 `invalid arguments`, which is not a permission refusal.
