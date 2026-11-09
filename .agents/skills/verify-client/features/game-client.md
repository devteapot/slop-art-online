# Game client on a land world

## Sub-features

- The game client (`living/game`) subscribes in stages (`living/game/src/net.rs`, module comment):
  1. `world`, `land` and `settlement` whole (1, 1 and about 6 rows).
  2. On a land world (a `land` row exists), only its own characters: `SELECT * FROM character WHERE controller = :sender`. On a tile world it subscribes `terrain_chunk` and `character` whole, as before.
  3. Its character's `body`, `vitals`, `experience` and `place` by id.
  4. Two chunk windows, each moved by subscribing the new one before dropping the old one:
     - near, re-centred after 2 chunks: `body` within ±5 chunks, the characters on those bodies through a join, and `terrain_chunk` within ±3 chunks;
     - far, re-centred after 5 chunks: `lot` within ±11 chunks.
- It regenerates the land from the `land` row and compares the three digests (`living/game/src/live.rs`, `land` and `regenerate`). It logs `digests match` or `DIGESTS DIFFER`.
- It joins with `join`. The newcomer arrives at `land.arrive_x/arrive_y`, and the client moves only through `human_move` and `human_act` (`goto`).
- It draws buildings from `lot` rows and characters from the bodies in the window. The HUD shows vitals, heard speech, death and rejoin (`living/game/src/ui/live.rs`).

## How to get to it (user POV)

A player starts the game client against a server that hosts a land seed (`LIVING_SERVER`, `LIVING_DB`). The client connects, joins, and shows the island around the arrival point.

## Driving it

### The real client, headless

Launch a land world with the shared harness (`$V launch --run client-<name> --seed island`, then `$V doctor`), and build the game with `cargo build --release --manifest-path living/Cargo.toml -p living-game`. `LIVING_GAME_LIVE=<dir>` runs a script with no window and writes photographs to `<dir>`. `LIVING_GAME_LIVE_PLAN` holds `;`-separated steps, documented on `Script` in `live.rs`:

```bash
LIVING_SERVER=http://127.0.0.1:3300 LIVING_DB=verify-$R LIVING_GAME_TOKEN=.local/living/verify/$R/game.token \
LIVING_GAME_LIVE=.local/living/verify/$R/shots \
LIVING_GAME_LIVE_PLAN="ready;wait:3;shot:join;goto:416,250;wait:50;shot:plaza;say:Good morning!;wait:1;shot:say;quit" \
living/target/release/living-game > .local/living/verify/$R/game.log 2>&1
```

Use a fresh `LIVING_GAME_TOKEN` path for each run. A reused token is an identity whose character may still be alive, so `join` is not sent. In the log, check these lines:

- `world kind: Land`;
- `land: regenerated in … s; digests match: tiles …, heights …, layout …`;
- `playing character #N`;
- every 10 s, `live: cache body … character … lot … terrain_chunk … (N tiles edited) …; drawn … characters, … lots; window moves …`.

`island perf` lines report frame times every 2 s. They are capped at 60 Hz unless `LIVING_GAME_FPS_CAP=0`. They describe the machine and its load; they are not protocol evidence.

To exercise speech, death and rejoin, combine the script with the harness. `$V call … place_near` puts the run's harness player beside the game's character, and `$V player … say … --to <id>` makes it speak. The client shows a bubble for about `3.5 + 0.06 × characters` seconds (`ui/model.rs`, `bubble_life`), so photograph within that time. `$V call … kill '[<id>, "cause"]' --as-admin` kills the character. The script's `dead`, `rejoin` and `joined` steps then drive the death screen and its "Arrive as a new stranger" button. `place_near` and `kill` are admin scene setup; name them in the report.

### Each query through the probe

`drive.py` sends the client's exact queries. The run name must start with `client-`. Chunk ids are `(cy << 16) | cx`:

```bash
D=.agents/skills/verify-client/scripts/drive.py
ranges() { local col=$1 q=""; for cy in $(seq $4 $5); do q="$q${q:+ OR }($col >= $(( (cy<<16) + $2 )) AND $col <= $(( (cy<<16) + $3 )))"; done; echo "$q"; }
$V player --run $R join ProbeJoin
$D --run $R --as-player --save sender --seconds 2 --query "SELECT * FROM character WHERE controller = :sender"
$D --run $R --save join --seconds 30 --query "SELECT character.* FROM character JOIN body ON character.id = body.id WHERE $(ranges body.chunk 21 31 10 20)"
$D --run $R --save body --seconds 30 --query "SELECT * FROM body WHERE $(ranges chunk 21 31 10 20)"
$D --run $R --save lots --seconds 3 --query "SELECT * FROM lot WHERE $(ranges chunk 15 37 4 26)"
```

`:sender` must return exactly the harness player's character. The join must return one character per body in the window.

### Volume

Bytes per query come from the server's `spacetime_num_bytes_sent_to_clients_total{db=<database identity>}`, split by `txn_type`:

- `Subscribe`: initial rows;
- `Unsubscribe`: rows dropped when a window moves;
- `Update`: live changes.

`spacetime_active_queries{database_identity=…}` counts the live queries. While one game client walks, it must stay flat (12 on 2026-11-09). If it grows, a moved window was never dropped. The database identity is `GET /v1/database/<name>` → `database_identity`. Sample with nothing else connected, or each client's bytes count toward the same total.

## Gotchas

- `:sender` is the subscribing identity, so an anonymous probe receives its own (empty) result.
- Join columns must be qualified (`body.chunk`), and both join columns need an index. `character.id` and `body.id` are primary keys.
- Subscription SQL in 2.14.1 has no `IN`.
- The client draws characters only after their `character` row arrives through the join. Animals don't wait for one.
- Body rows are the live cost. Each steering change sends the whole row, path included, at about 150 B. At the town square that was about 10 kB/s for 72 bodies.
- A failed act (for example `build wall` without masonry) is refused in the actor's `experience` rows, not by the reducer's HTTP status.

## Evidence

The script's photographs, `game.log`, the probe's `.jsonl` files, and a TSV of the metric samples. Name the commit and whether `living/` had uncommitted changes.
