# Player character

A person outside the simulation joins the world as one character and controls it through the same rules as AI characters. Movement steers the body. A command either becomes a deliberate act or replaces the character's behavior. Speech is heard by people within earshot.

## Sub-features

- `player-join`: a new identity creates one living, non-AI person near (40, 60) whose plan is `waiting for you` (`living/authority/src/lib.rs:313-327`).
- `player-join-once`: a second `join` from the same identity is refused while its character lives (`lib.rs:318`).
- `player-move`: `human_move` steers the body at a walk or a run, stops it, and sets the plan to `moving yourself` (`lib.rs:356-375`).
- `player-act-deliberate`: `human_act` with a skill that is not real-time (give, offer, gather, teach, conceive…) goes through `acts::submit`, the path minds use (`lib.rs:337-349`, `living/authority/src/acts.rs:27`). The act runs, or fails with feedback in the player's `experience` rows.
- `player-act-graph`: `human_act` with a real-time skill (`wander`, `follow`, `wait`, `attack`…; `Shapes::real_time` in `living/rules/src/combat.rs`: `MOVES` and each combat skill's `real_time` trait in `living/scripts/skills.rhai`) becomes the character's behavior, with plan `your command` and source `human`. It runs once: when its root ends, done or failed, the character waits for its person again (plan `waiting for you`, `command_done` in `lib.rs`, called from `brain::evaluate`). Before 2026-11-10 it was installed as `{"seq":[node,{"wait":60}]}`, and a root `seq` starts over, so `{"wait":4}` lasted 64 s and repeated. A new graph adopts the activity in progress only when skill, target, item and amount all match, so a 4 s wait does not carry on the 30 s wait of `waiting for you`.
- `player-told`: when a graph action of the played character fails, refused as it starts (`act::refused`) or failing after it started (`act::report`), the player is told as an AI character is told: the same words ("You failed to <action>: <why>"), one `own` line in its own log, which the client reads through `my_experience`, once per `repeat_failure_s` (120 s) for the same action and reason (`act::tell` in `living/authority/src/act.rs`, since 2026-11-11; before, only AI characters were told, so a failed command went silently back to waiting). Notable successes ("You finished: …") stay for minds only; a character with no mind and no person (an admin benchmark crowd: `ai = false`, no `presence` row) is told nothing. Taking the controls during a command breaks it off with "you moved", which the player is now told too ("You failed to follow → person: you moved"). A player's own skill-bar move (`use_skill`) is reported through `skill_use`/`my_combat` instead, and a deliberate act through its `act` line, as before.
- `player-walk-far`: click-to-move (`human_act` with `{"do":"goto","target":{"at":[x,y]}}`, a deliberate act) reaches another settlement anywhere on the island, leg by leg, and lasts as long as the walk takes; a short click round a building row or a pond reaches it too. A click more than 12 m into water is refused ("destination unreachable"), and a place that cannot be reached at all is refused ("no path there") (`living/authority/src/motion.rs` `start`, `living/rules/src/nav.rs`, `acts::overdue`; docs/PATHS.md).
- `player-say`: `human_say(text, to)` is the `say` way, and `human_speak(text, to, way)` speaks in any way the rules list in the public `speech_card` ("" is `say`; since `speech-1`, 2026-11-11, docs/COMMUNICATION.md). Both go through the one speech primitive (`living/authority/src/speech.rs`, `speak`) that minds and graphs use. A line writes a `speech` chronicle line, and every person within the way's carry gets a row of the way's kind (`speech` for `say`). The player's own character perceives its words as a `said` experience ("You said to <name>: “…”", salience 0.5; since 2026-11-09, for player memory, docs/PLAYER_MEMORY.md), like any speaker's. Who heard each line, the receivers the speaker saw, is the player's `my_heard` view (`line` = the `said` row's id, `way`, `hearers`, `at_ms`). A refused line comes back as the reducer's error and writes nothing: "no way of speaking called `X`", "speaking too fast", and a way's own refusals ("a <way> needs someone to <way> to", "too far to <way>: step closer", "too soon to <way> again: wait N s", "you don't know <technique>"). `scripts/speak.py --run $R` drives them all, from the card.
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

- A client calls `join(name)`, then `human_move(dx, dy, run)`, `human_act(node)` and `human_say(text, to)` or `human_speak(text, to, way)` with its own identity.
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

# a command runs once (4 s here), then the character waits for you; it does not start over
python3 .agents/skills/verify-player/scripts/command.py --run $R > .local/living/verify/$R/command.txt   # writes command.json

# a failed command is told as an AI is told: {do:graze} refused at start ("only grazing animals graze", before `laws-2` "only deer graze"; sent twice,
# one line), a gift whose receiver is moved 6 m away while it is handed over ("they moved away"); an AI
# character runs the same graphs for the text to compare (default seed: it needs ai = true people)
python3 .agents/skills/verify-player/scripts/told.py --run $R > .local/living/verify/$R/told.txt     # writes told.json

# movement: run, walk, stop
$V player --run $R move 1 0 --run-gait; sleep 1
$V sql --run $R "SELECT id, vx, vy, speed FROM body WHERE id = $ME" --save body-run                           # about 4.1
$V player --run $R move 1 0; sleep 1
$V sql --run $R "SELECT id, vx, vy, speed FROM body WHERE id = $ME" --save body-walk                          # about 2.5-2.7
$V player --run $R move 0 0; sleep 1
$V sql --run $R "SELECT id, vx, vy FROM body WHERE id = $ME" --save body-stopped                               # 0, 0
$V sql --run $R "SELECT id, plan FROM brain WHERE id = $ME" --save plan-moving                                 # moving yourself
$V sql --run $R "SELECT kind, text FROM my_experience" --as-player --save own-after-move                     # own: "You failed to follow → person: you moved"

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
- `human_say` and `human_speak` refuse lines less than 2 s apart (`speaking too fast`) for characters with a mind state. A line addressed to someone out of earshot gives the speaker a `silence` experience.
- The game client addresses its lines since 2026-11-11 (`living/game/src/talk.rs`): `to` is the person under the cursor, else the nearest within the rules' hearing, else 0. It shows `silence` rows as a refused note. The authority accepts any `to`; the addressee hears it at salience 0.9 whatever `address_m`.
- `join` places the character near (40, 60), in the north-west corner of the default map, far from the towns. Use admin `place_near` to bring the player to someone.
- On a land world (`--seed island`), `join` places the character at the `land` row's `arrive_x`/`arrive_y`, on the first town's square among its residents (`living_rules::host::arrival`, since 2026-11-10; before, outside its first gate). Residents there run without minds (`rules.minds = false`): they are `ai = false` and write no `experience` rows. Pick a neighbour with `kind = 'person' AND alive = true AND stage = 2 AND id != $ME` instead of `ai = true`, and prove speech by the `chronicle` line. A gift may fail because the resident walks away on its own routine.
- `$V sql` reads as the database owner, so these recipes read `experience`, `brain`, `chronicle` and the rest as developer truth; that says nothing of what a client may read. A player reads its own through the views (`SELECT * FROM my_experience` with `--as-player`), and in a `LIVING_PERCEPTION=scoped` build the tables themselves refuse it (docs/PERCEPTION.md, `verify-client`).
- A failure only reaches the player's log while the target stays in sight. A `follow` whose target leaves sight, or a gift whose receiver is moved 40 m, is dropped by the evaluator without a report, for an AI character as well; `told.py` therefore moves the receiver 6 m (out of reach, in sight).
- The reducer argument JSON must match the signature exactly. A wrong arity returns HTTP 400 `invalid arguments`, which is not a permission refusal.
