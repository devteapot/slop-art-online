# Observer subscriptions

## Sub-features

- Connect with the database owner's token through the generated Rust SDK, as the observer does since 2026-11-09 (`living/viewer/src/clock.rs`, `owner_token`): most of what it reads is private developer audit truth (docs/PERCEPTION.md).
- Apply the viewer's exact 27-query base set and receive initial rows.
- The same base set from an anonymous client is refused, with an error naming a private table (`anonymous-base.json`).
- Receive later `body` and `stats` updates while the authority ticks.
- Apply the inspected-character experience filter, routine filter, and routine-stat join.
- Assert that returned experiences and routines belong to the selected actor and joined stats belong to those routines.

## How to get to it (user POV)

The observer connects with the owner's token (`LIVING_TOKEN`, `.local/living/token`, or `#token=…` in the browser page's fragment), then subscribes to the tables it wants (`living/viewer/src/net.rs`, `connect`). Its base query set is `QUERIES` at the top of `net.rs`. Inspecting a character adds the three queries in `watch_experiences`.

## Driving it with drive.py

With the shared run already launched, checked, and joined as `ClientPrimary`:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

Read `observer-base.json`. `status` must be `applied`, `initial.counts.world` must be 1, and `initial.counts.character` must be positive. After four seconds both update counters must be positive and `final.ticks` must exceed `initial.ticks`.

The driver selects a living adult AI person for `inspected-character.json` and subscribes as the owner. It sends exactly:

```sql
SELECT * FROM experience WHERE observer = <actor>
SELECT * FROM routine WHERE actor = <actor>
SELECT s.* FROM routine_stat s JOIN routine r ON s.id = r.id WHERE r.actor = <actor>
```

The recorded actor replaces `<actor>`. Experiences, routines, and joined stats must all be nonempty. No experience or routine from another actor may appear. Each stat id must match one of the received routines.

## Gotchas

- A successful connection is not an applied subscription. Wait for `on_applied` before reading initial rows.
- A row count is not proof of live changes. The probe registers update callbacks before subscription and records both counters.
- The driver stops if the viewer query set differs from its copy. Update the skill with the viewer.
- Owner subscriptions see everything; they prove the observer's path, not what a player may read. [perception.md](perception.md) and [visibility.md](visibility.md) cover players and anonymous clients.
- This checks the client cache and protocol, not browser presentation or scale.

## Land worlds: chunk windows

A land world (`--seed island`, see `docs/ISLAND_AUTHORITY.md`) adds the public `land`, `settlement` and `lot` tables. The probe reads and counts them like every other primary-key table (`probe/src/main.rs`, `primary_tables!` and `snapshot`; the perception views with primary keys are in the same macro); when the schema gains a table or view, add it there too, or ad-hoc queries on it record empty `tables` even though the server sends rows. Subscription SQL in 2.14.1 has no `IN`. Express a window as one `id` (or `chunk`) range per row of chunks, joined by `OR`. Chunk ids are `(cy << 16) | cx`, so a row of chunks is one contiguous range:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R" --seconds 3 --save lot-window \
  --query "SELECT * FROM lot WHERE (chunk >= 851991 AND chunk <= 851996) OR (chunk >= 917527 AND chunk <= 917532)"
```

The probe reports rows, not bytes. For volume, read the database's `spacetime_num_bytes_sent_to_clients_total` from `http://127.0.0.1:3300/v1/metrics` before and after. The 2026-11-09 measurements are in `docs/ISLAND_AUTHORITY.md`.

The game client's own queries are in [game-client.md](game-client.md): the perception and own-state views with no window and no join, and two chunk windows of public world data (`terrain_chunk`, `resource_node` and `structure` near; `lot` far).
