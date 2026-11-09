# Game client on a land world

**Perception (docs/PERCEPTION.md).** The client reads only what its character perceives: the per-sender `seen_*` views for others and the `my_*` views for its own state, which a default (`scoped`) build makes the only way in. The other subscriptions are public world data by chunk window. The former `docs/perception-client.patch` landed on 2026-11-09 and was deleted.

## Sub-features

- The game client (`living/game`) subscribes in stages (`living/game/src/net.rs`, module comment):
  1. `world`, `land` and `settlement` whole (1, 1 and about 8 rows).
  2. For the connection's lifetime, 15 queries with no window and no join (`PERCEIVED`): `seen_bodies`, `seen_characters`, `seen_fighters`, `seen_doing`, `my_characters`, `my_vitals`, `my_experience`, `my_places`, `my_inventory`, `my_know_how`, `my_combat`, `my_readiness`, `skill_card`, `act_card` and `weather`. The views follow the character on the authority, so walking changes none of them. A tile world also subscribes `terrain_chunk` whole.
  3. On a land world, two chunk windows of public world data, each moved by subscribing the new one before dropping the old one:
     - near, re-centred after 2 chunks: `terrain_chunk` within ±3 chunks;
     - far, re-centred after 5 chunks: `lot` within ±11 chunks.
- `seen_bodies` rows are `Motion` (52 B: no path, chunk or kind). `net::body_of` rebuilds a `Body` for the drawing code: the kind from `seen_characters`, an empty path, the chunk from `living_rules::map::chunk_of`.
- It regenerates the land from the `land` row and compares the three digests (`living/game/src/live.rs`, `land` and `regenerate`). It logs `digests match` or `DIGESTS DIFFER`.
- It joins with `join`. The newcomer arrives at `land.arrive_x/arrive_y`, and the client moves only through `human_move` and `human_act` (`goto`). `find_me` reads `my_characters` (alive, not AI).
- It draws buildings from `lot` rows and every body in `seen_bodies`: what the authority says the character perceives, within sight and with a clear sight line. A death takes the body out of `seen_bodies`; the corpse stays drawn from the death's `my_combat` row.
- What it shows of others is the projection (`seen_characters`): the `label` (the name when the character knows it, else `a stranger`, `a wolf`, …) on nameplates, speech bubbles, the log, the target panel and the death screen; build and dress from `folk` and `style`; health as the `seen_fighters` band, or exactly (`hp`/`max_hp`) while an appraisal holds, with a small `hp / max` under the nameplate (`ui/live.rs`, `ui/overhead.rs`). The death screen names the killer and witnesses by the labels the character last perceived, not from `character.cause`.
- The HUD shows vitals (`my_vitals`), heard speech (`my_experience`), death and rejoin (`living/game/src/ui/live.rs`).
- Town life (`living/game/src/town.rs`): `doing.code` from `seen_doing` is named through `act_card` and drawn as a clip on the standing body (work, gather, eat, play, sitting, wave, nod; appraise plays `idle_look`); a sleeper, or a resting body whose `doing` row says `indoors` (the authority decides it from the home it no longer sends), is hidden. A standing body's facing follows its own segment (`heading` + `turn` × elapsed, up to `turn_s`), so turns at zero speed turn in place. Rain follows the `weather` row. The keys G, B and V send `human_act` wave, nod and appraise ([verify-player gestures](../../verify-player/features/gestures.md), [perception](../../verify-player/features/perception.md)); appraise goes to any creature within 6 m, people or animals.

## How to get to it (user POV)

A player starts the game client against a server that hosts a land seed (`LIVING_SERVER`, `LIVING_DB`). The client connects, joins, and shows the island around the arrival point.

## Driving it

### The real client, headless

Launch a land world with the shared harness (`$V launch --run client-<name> --seed island`, then `$V doctor`), and build the game with `cargo build --release --manifest-path living/Cargo.toml -p living-game` in a private `CARGO_TARGET_DIR` (other sessions overwrite `living/target`). `LIVING_GAME_LIVE=<dir>` runs a script with no window and writes photographs to `<dir>`. `LIVING_GAME_LIVE_PLAN` holds `;`-separated steps, documented on `Script` in `live.rs`:

```bash
LIVING_SERVER=http://127.0.0.1:3300 LIVING_DB=verify-$R LIVING_GAME_TOKEN=.local/living/verify/$R/game.token \
LIVING_GAME_LIVE=.local/living/verify/$R/shots \
LIVING_GAME_LIVE_PLAN="ready;wait:3;shot:join;goto:416,250;wait:50;shot:plaza;say:Good morning!;wait:1;shot:say;quit" \
"$CARGO_TARGET_DIR"/release/living-game > .local/living/verify/$R/game.log 2>&1
```

Use a fresh `LIVING_GAME_TOKEN` path for each run. A reused token is an identity whose character may still be alive, so `join` is not sent. In the log, check these lines:

- `world kind: Land`;
- `land: regenerated in … s; digests match: tiles …, heights …, layout …`;
- `playing character #N`;
- every 10 s, `live: cache body … character … doing … act_card … weather dry|rain|none lot … terrain_chunk … (N tiles edited) …; drawn … characters, … lots; window moves …` (`act_card` 18 and `weather` `dry` or `rain` on the island seed). The `body`, `character` and `doing` counts are the views' rows (`seen_bodies`, `seen_characters`, `seen_doing`) and `experience` is `my_experience`: what is in sight, so `body` equals `character` and is small away from crowds (1 alone at the arrival, 13–18 in a town square).

Script steps for town life: `gesture:wave|nod|appraise[:ID]` (the G, B and V keys' path) and `sync:NAME` (waits for `<dir>/NAME.go`, so an outside driver can set a scene with admin reducers first; a number in the file sets the view's yaw). Since 2026-11-09 also `hold:DEG[:run]` (walk or run toward a heading until the next step) and `stop`, used by the animation probes.

`island perf` lines report frame times every 2 s. They are capped at 60 Hz unless `LIVING_GAME_FPS_CAP=0`. They describe the machine and its load; they are not protocol evidence.

To photograph what the projection shows (a stranger's label until they say their name, an appraisal's exact health and its end, someone behind a wall not drawn), set the scene with admin `set_behavior` (a resident's graph `{"seq": [{"say": {"text": "Well met. I'm NAME.", "to": {"id": ME}}}, {"wait": 900}]}`; `{"wait": 900}` holds a resident still) and `place_at`, then photograph from the script. Read the game's own views beside each photograph as the game's identity: its token is the `LIVING_GAME_TOKEN` file, sent to `/v1/database/verify-$R/sql` (`verify.py`'s `http` helper) with `SELECT * FROM seen_characters`. A wave at a resident frozen this way gets no answer, so its nameplate does not show; the bubble and the log carry the label.

To exercise speech, death and rejoin, combine the script with the harness. `$V call … place_near` puts the run's harness player beside the game's character, and `$V player … say … --to <id>` makes it speak. The client shows a bubble for about `3.5 + 0.06 × characters` seconds (`ui/model.rs`, `bubble_life`), so photograph within that time. `$V call … kill '[<id>, "cause"]' --as-admin` kills the character. The script's `dead`, `rejoin` and `joined` steps then drive the death screen and its "Arrive as a new stranger" button. `place_near` and `kill` are admin scene setup; name them in the report.

### Each query through the probe

`drive.py` sends the client's exact queries. The run name must start with `client-`. Chunk ids are `(cy << 16) | cx`:

```bash
D=.agents/skills/verify-client/scripts/drive.py
ranges() { local col=$1 q=""; for cy in $(seq $4 $5); do q="$q${q:+ OR }($col >= $(( (cy<<16) + $2 )) AND $col <= $(( (cy<<16) + $3 )))"; done; echo "$q"; }
$V player --run $R join ProbeJoin
$D --run $R --as-player --save mine --seconds 2 --query "SELECT * FROM my_characters"
$D --run $R --as-player --save seen --seconds 30 --query "SELECT * FROM seen_bodies"
$D --run $R --as-player --save seenc --seconds 30 --query "SELECT * FROM seen_characters"
$D --run $R --as-player --save doing --seconds 30 --query "SELECT * FROM seen_doing"
$D --run $R --save terrain --seconds 3 --query "SELECT * FROM terrain_chunk WHERE $(ranges id 23 29 12 18)"
$D --run $R --save lots --seconds 3 --query "SELECT * FROM lot WHERE $(ranges chunk 15 37 4 26)"
$D --run $R --save acts --seconds 2 --query "SELECT * FROM act_card"
$D --run $R --save weather --seconds 2 --query "SELECT * FROM weather"
$D --run $R --as-player --save body-refused --seconds 2 --query "SELECT * FROM body"   # refused in a scoped build
```

`my_characters` must return exactly the harness player's character. `seen_bodies` rows carry the 11 `Motion` columns; `seen_characters` the projection (`label`, `hp` -1 except for the player's own character or while an appraisal holds); `seen_doing` at most one row per perceived body. The perception checks of the fixed suite ([perception.md](perception.md)) prove what is in and out of sight.

### Volume

Bytes per query come from the server's `spacetime_num_bytes_sent_to_clients_total{db=<database identity>}`, split by `txn_type`:

- `Subscribe`: initial rows;
- `Unsubscribe`: rows dropped when a window moves;
- `Update`: live changes.

`spacetime_active_queries{database_identity=…}` counts the live queries. While one game client walks, it must stay flat: 20 on a land world (3 static, the 15 perception and own-state queries, the near and the far window), 21 for a moment while a window moves (the new one is subscribed before the old one is dropped). It was 21 before the perception views (6 base, 6 by id, 5 in the near window, 1 far). If it grows, a moved window was never dropped. The database identity is `GET /v1/database/<name>` → `database_identity`. Sample with nothing else connected, or each client's bytes count toward the same total.

## Gotchas

- The views are per sender: an anonymous probe receives empty `seen_*` and `my_*` results, and the player's must use `--as-player`.
- Subscription SQL in 2.14.1 has no `IN`.
- The client draws a person only after their `seen_characters` row arrives (folk, stage, dress); animals don't wait for one. A body whose kind is not yet known draws as an empty kind for that frame.
- Body rows are the live cost. `seen_bodies` sends the 52 B `Motion` row of each body in sight on each steering change, and a view refresh re-sends the viewer's rows that changed. `spacetime_num_bytes_sent_to_clients_total` counts a shared query's bytes once however many clients hold it (docs/PERCEPTION.md), so measure one client's bytes with a proxy (living/tools/perception_bench.py's `Proxy`).
- A failed act (for example `build wall` without masonry) is refused in the actor's `my_experience` rows, not by the reducer's HTTP status.
- `character.cause` on my own `my_characters` row carries the killer's real name (authority text); the death screen does not show it, but the row reaches the client.

## Evidence

The script's photographs, `game.log`, the probe's `.jsonl` files, and a TSV of the metric samples. Name the commit and whether `living/` had uncommitted changes.
