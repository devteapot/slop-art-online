# A world still being made (staged genesis)

A freshly published world is made by scheduled steps after the publish returns: the island takes about 17–22 s and Cullet about 11 s (docs/STAGED_GENESIS.md). Until its public `genesis` row (`id` 0) says `done`, the authority refuses `join`, `join_as`, the `human_*` reducers, `use_skill` and `release_skill` with `world_preparing: the world is still being made (step i of n: label)`.

## What the player sees

- **The first-load cover** says **"Preparing the world…"**, with a line `step i of n · label` and a thin bar (`loading.rs`, `CoverBar`).
  - `steps` grows once a land's wards are known, for example from 16 of 24 to 17 of 40. The line shows the steps as they are; the bar keeps the most done so far, so it never runs back.
  - The cover stays up while the world is being made, past its usual 30 s cap.
- **Nothing is shown as a failure.** A `world_preparing` refusal never reaches the errors list (the F1 panel's red line), the notes or a warning in the log.
- **When `done` turns true,** the client subscribes the base set and joins. On the island, the drives measured 0.66 s and 1.94 s from the authority's `done` to `playing character`.
- **After a reconnect into a world being made,** the link line says "Preparing the world… step i of n · label" instead of "Reconnecting…".
- **After 120 s** (`genesis::TIMEOUT_S`), the line adds that it is taking longer than usual and keeps waiting: the cover has no buttons. A stopped chain (a label `stopped: …`) shows "The world could not be made" at once.

## How it works (`living/game/src/genesis.rs`, `net.rs`)

- **On connect,** the client subscribes `SELECT * FROM genesis` as a subscription of its own, beside the static set.
  - It is its own subscription because a module from before staged genesis has no such table. Only that subscription fails (`genesis: no genesis table on this world … it counts as ready`), and the world counts as ready.
  - A row that is absent or `done` also counts as ready.
- **The base set waits for ready, and `join` with it** (`Net::watch_genesis`). A half-made world has no `land` row yet, so the world's kind would be guessed as tiles, and its chunks are still being written.
- **A call refused with `world_preparing` all the same** (`Net::on_reply`, prefix match `genesis::is_preparing`) is held quietly.
  - For `join` and `join_as`, `Wait::refused` takes the progress from the error text when no row is in.
  - It sends `join` again when the row it saw preparing turns `done`, or after a backoff of 1, 2, 4, then 5 s.
  - A refusal while the row already says ready waits for the backoff, so it can never loop.
- **Unit tests:** `cargo test --release -p living-game genesis` covers the prefix parse, the gate's moves, the retry on `done`, the backoff, quiet holds of other calls, the bar that never runs back, and the long-wait and stopped lines.

## Client log lines

- `genesis: preparing step i of n · label`, once per new step;
- `genesis: the world is ready after S s preparing`;
- `genesis: joined S s after the world was ready`;
- `genesis: the world is being made: …`, only when a refusal came first;
- `genesis: joining again (…)`.

## UI dump

Each `dump:` has a top-level `genesis` block:

- `gate` (`Unknown`, `Preparing` or `Ready`) and `status`;
- `progress`: `step`, `steps`, `label`, `line` and `share`;
- `since`;
- `cover`: `title`, `detail` and `bar` while the first-load cover is up;
- `link`;
- `errors`: the last 12 refusals and failures the connection holds.

## Live script

`preparing[:S]` waits until the client shows the world as being made, at most S s (default 60).

## Recipe: `check.py --run ui-<new> preparing`

The scenario is explicit and launches its own world, so give it a run name with no world yet. It refuses a run that was already launched.

1. **Launch.** It starts `verify.py launch --run R --seed island --target-dir T` in the background.
   - `T` is `VERIFY_UI_TARGET_DIR`, else `.local/living/verify/R/target`. A target dir that already holds the module makes the publish start at once.
   - `VERIFY_UI_PREPARING_SEED` picks another seed.
   - Launch itself waits for genesis through `genesis_wait.py`, then installs the script.
2. **Drive.** As soon as `state.json` records `publish_attempted`, it starts `drive.py --preparing`, which skips the start's tick check.
   - The plan is `preparing:180;wait:0.5;shot:01_preparing;dump:01;wait:3;shot:02_preparing;dump:02;ready;wait:1;shot:03_joined;dump:03;quit`.
   - The client cannot reach the world for a moment and retries every 3 s.
3. **Sample the authority.** Meanwhile it reads the `genesis` row as the owner, every 0.25 s, into `genesis.json`. Once, while the world is not done, it calls `join` as verify.py's player identity (`$V player join Probe`) to record the authority's refusal (HTTP 530, `world_preparing: …`).
4. **Checks:**
   - the world was made and the client joined;
   - the probe was refused with the stable text;
   - dump 01 is `Preparing`, and its cover says "Preparing the world…" with `step i of n` and a bar;
   - the line moved between 01 and 02;
   - the client joined after "the world is ready", and dump 03 is `Ready` with no cover;
   - no `world_preparing` in the errors, the notes or a warning, and no `join refused`;
   - the client was playing within 10 s of the first owner read that saw `done`.
5. **Timing.** `timing.json` keeps the time from done to join, as the client saw it and from the authority's `done`.
   - The authority's time is the first owner read of `done`, not `genesis.updated_ms`. The last step stamps that field when it starts, and on the island populate then runs about 4 s more.
6. **Cleanup.** `$V cleanup --run R` afterwards.

**Evidence:** `.local/living/verify/R/ui/preparing/` holds `01_preparing.png`, `02_preparing.png`, `03_joined.png`, the dumps, `client.log`, `genesis.json`, `timing.json` and `launch.log`.

**Not covered:**

- The join-refusal path end to end in the client. The client holds `join` until ready, so a live drive never sends a refused `join`. Its logic is in the unit tests, and the authority's refusal text is recorded by the probe.
- The 120 s message, live.
- A reconnect into a world being made.
- Cullet's timing.
