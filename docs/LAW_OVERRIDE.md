# Value-only law changes (`law_override`)

Branch `law-override` (Spark, 2026-11-19). It builds Option 1 of the law-reinstall design (`docs/LAW_REINSTALL.md` on branch `law-reinstall`, 25c28334) on the interface agreed with dev-box and the laptop. Measured results are in [Measurements](#measurements).

## The problem

Before this branch, every `set_world_law` ran `install_source` inside the reducer on the database thread. That meant a Rhai compile, full script validation and a second compile on the next read. On the island this took 963 ms, 819 ms of it validation. On Cullet it took 2.36 s. No tick ran meanwhile, so the whole world froze for that long on every law change, including flips of dev-box's delivery switches.

## What changed

### Storage

- **`law_override { name (primary key), value, revision }`** is a new **public** table. It holds every world-own law value: a seed's `rules`, every `set_world_law` and the rows migrated from `world_law`.
  - `value` is JSON text, as `set_world_law` takes it.
  - `revision` is the law revision that wrote the row.
  - The table is read-only to clients. Only reducers write tables, and `set_world_law` is admin-only.
  - Laws are not secret: the client already downloads the whole script.
- **`law_revision { id: 0, revision }`** is a new **private** single-row table. It holds the world's law revision, which goes up by one at each `law_override` write. The authority reads it once per transaction by primary key. It is the cache key of the laws in force, next to the script revision.
- **`world_law`** is the table before this branch. It is no longer written or read.
  - The first transaction that reads the laws on a module with `law_revision` copies a world's `world_law` rows into `law_override`, once (`common::law_rev`). That transaction is the tick, within a frame of the update.
  - The old rows are kept, so a downgrade still finds them.
- **Why new tables:** in 2.14.1, appending a column to an existing table rewrites it and disconnects every client (see `docs/LOOK.md` §7). Two new tables migrate automatically, with no rewrite.

### One override layer (`living_rules::script`)

Precedence is decided in one place, `Scripts::laws_map`:

1. the script's `laws()`;
2. then the values written at its end (`world_law_values()`, an install's);
3. then the overrides.

A name that is not a law of the script, or a value of another kind, is left out. Everything that reads a law reads that map: `laws()`, `laws_with`, `law_value`, Rhai's `law(name)` and the constants' words. Direct Rhai calls to `laws()` still return the script's own map, as before.

The layer's API:

- `Scripts::with_overrides(source, day_ms, &over)` compiles with the values laid over. Everything the compile derives from the laws is read under them.
- `Scripts::apply_overrides(&over) -> Result<Applied, String>` lays new values over a compiled script in place, keeping the AST and running no validation. Each law whose value in force changes must be value-only in this script; otherwise the call is refused and nothing changes. Then it refreshes what that law reaches:
  - for `gaze_on`, the gaze ceilings and the 24 band, light and torch samples, under the compile's operation limit (`COMPILE_OPERATIONS`), with the senses kept per state cleared;
  - for every change, the constants' words (`law_about`).

  If a derived check fails, such as a gaze ceiling out of bounds, everything is restored: the laws, the overrides, the ceilings and the words.
- `overrides_of(rows)` decodes `law_override` rows (name, JSON). The authority and clients decode them the same way with it.
- `VALUE_ONLY` lists the value-only laws and their classes. `Scripts::value_only(name)` adds the source guard.

### The value-only laws and what they reach

| Law | Class | Rust readers | Rhai readers (shipped) | Refreshed on a value edit |
| --- | --- | --- | --- | --- |
| `cue_transport_on`, `near_tier_on`, `motion_tables_on`, `characters_table_on` (battle-views) | delivery | `frame.rs` via `common::laws(ctx)` (each tick, `scene`, `engaged_tiers`) | `laws()`, `law_about` | nothing derived. The next tick reads the new value. |
| `cover_sight_on`, `cover_eye_height_m`, `cover_brush_on`, `cover_brush_min_fill`, `cover_cliff_step_m` | cover | `common::cover_mask`, `publish_cover_law`, the `cover_law` row (the game client's `sightfield.rs` reads that row) | `laws()`, `law_about` | the `cover_law` row in the reducer. The cached map's cover mask compiles again at its next read, only when the policy changed. Terrain and gates are kept. |
| `gaze_on` | gaze | `attention::set` (`laws(ctx).gaze_on`), `common::hot`/`sight` via `Scripts::gaze_enabled` | `laws()`, `law_about` | the ceilings and samples, and the senses memo (in `apply_overrides`). When gaze goes off, the reducer also deletes the owner projection (`applied_gaze`), as an install did. When it goes on, sweeps fill the projection. |

**The source guard.** A law in `VALUE_ONLY` is value-only for a given script only when the script names it nowhere but the constants' own functions: `laws`, `base_laws`, `law_about`, `laws_about` and `world_law_values`.

- Every whole-word occurrence counts against the function declared last before it. That covers a key, a field, a `law("…")` string and a comment.
- An overlay that reads `law("gaze_on")` in a function of its own therefore makes `gaze_on` an ordinary law for that world, changed by a full install (`value_only_in`).
- This is how the class grows safely: a law joins `VALUE_ONLY` only with what it reaches refreshed and tested.

**Not value-only.** Every other law stays on the full install, as do source edits (`install_script`). A full install is the full validation and a new script revision, as before. The design note names the hazards of growing the class: transitive helpers, branches a new value takes, and a law that changes a derived spec or a speech fixture.

### The authority (`common.rs`)

- **`laws(ctx)`** is the typed `Laws` of `scripts(ctx).laws()`, kept by (script revision, law revision).
- **`scripts(ctx)` / `try_scripts(ctx)`** keep the compiled script by the same pair:
  - same script revision, new law revision: `apply_overrides` with the committed rows, in place;
  - new script revision: compile with the overrides.

  A failed in-place lay-over falls back to the compile, which refuses the same values. Callers that key on the script's `Rc` keep their entries: `perception`'s regard and band caches and the kept projections. None of them reads a value-only law.
- **Within a transaction,** `laws(ctx)` and `scripts(ctx)` read one snapshot throughout. A tick sees a value edit at its start or not at all. This is the "stable within a tick" property `frame.rs` needs: it compares delivery laws tick to tick.
- **Rollback.** Module memory is disposable, and nothing is trusted across a revision number:
  - writing `law_override` (`set_law_override`) clears the law revision, the typed laws and the cover check, and marks the compiled script's law key unknown;
  - a transaction that rolls back leaves memory under a revision the database never committed. The next transaction reads the committed revision, finds the mismatch and lays the committed rows over again;
  - an edit that takes the same number again lays its own rows over again.
- **The cover mask** (`map`, `COVER_FOR`) is checked once per (script, law) revision against the policy in force (`cover_law_of`). Only a changed policy compiles the mask again; the terrain and gates are kept. Before, a cover change dropped the whole map. `publish_cover_law` no longer drops the map.
- **The hot per-creature answers** (`HOT`) are keyed by the law revision too.
- **Caches keyed by the script revision alone** read no value-only law, by the source guard: the alarm cells, the chunk warming and the graphs. A change of any other law moves the script revision, as before.

### `set_world_law`

1. `require_admin`, then the kind check (`laws_with`), then the cover geometry check.
2. **Value-only** (`Scripts::value_only(name)`): write the row and the next law revision, then `try_scripts` (the in-place lay-over and its derived checks), then the class's own rows:
   - cover: `publish_cover_law`;
   - gaze off: `attention::clear_projection`.

   The script row, script revision, takeover reschedule, look retime, cards and codes are untouched: none of them reads a value-only law.
3. **Otherwise:** write the row, then `install_source` with the values written at the end (full validation, new script revision), as before.
4. Both paths write `law_change` and a chronicle line `… (law revision N, value only|installed, script revision M)`. `law_change.revision` is the script revision in force after the change, so it is unchanged for a value-only law.

A refusal at any step rolls every row back.

- **Same-value requests** are still recorded (row, revision, audit), as before. A value-only one costs only the row writes.
- **`seen_ranges`** keeps its special case: changing it deletes the `last_look` rows.
- **Timing:** `set_world_law` and `set_world_law.value_only` are always-on timing spans, like `install.compile`. Law changes are rare admin calls.

### Clients

A client that computes from the script (the game client: `senses`, `move_speed`/`motion`, `_ui`, `meters`, the delivery laws) subscribes `SELECT * FROM law_override` and lays the rows over its compiled script with `overrides_of`:

- **On a script revision:** `Scripts::with_overrides(source, day_ms, &overrides_of(rows))`.
- **On any `law_override` change with the same script revision:** `scripts.apply_overrides(&overrides_of(rows))`.
  - If it succeeds, the client changes nothing else, and `Applied` names the class: delivery means switching the subscription sets; cover means the client's own cover projection, which already follows the `cover_law` row; gaze means the senses.
  - If it fails (a law not value-only in that script), recompile with `with_overrides`.
- **On a reconnect:** the first subscription result holds every row (proved by `law_override.py checks`), so the client lays them over before reading a law.
- **Until a client does this,** it reads values from the `script` row's written-in block. That block is current for every ordinary law, but not for a value-only law edited since the last install.

**The game client** does this since branch `law-override-client`:

- `law_override` is in its base set, beside `script`.
- `verbs::Rules` compiles the script with the rows, or lays them over in place. Its `laws_key` moves on either, and every cache of a law read keys on it.
- `verbs::refresh_rules` runs before `net::perception_law` chooses the perception set.

Measured on the island, through the verify-ui `law-override` scenario:

- the client takes a value-only edit 1–35 ms after the reducer's reply;
- a delivery switch applies in 17–35 ms, with no creature missing from any frame;
- the world's tick never stood still longer than the sampler's resolution (about 35 ms; 70 ms on a cover-policy change, the mask compile);
- a `turn_rate` install still froze the world for about 1.4 s.

See `.agents/skills/verify-ui/features/law-override.md`.

The mind service compiles the `script` row alone and reads only ordinary laws: `cues_on`, `cue_cooldown_s`, `cue_gap_s`, `speech_truth`, `stranger_by_name`, `think_framing` and `fast_lane_inflight`. The mind test `the_laws_minds_read_change_by_an_install` fails if one of them becomes value-only, or if the mind reads a new law.

## Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- | --- |
| Laws in force, per transaction | `law_revision` (point lookup), and on a new revision every `law_override` row | — | PK | — | once per transaction (the revision); the rows only after a change | — |
| Value-only `set_world_law` | the law's row, `law_revision`, `land` and the `cover_ground` row count (cover on: whether the geometry is complete; a land without it starts `cover_step`, docs/COVER_SIGHT.md "Cover geometry") | `law_override` (1 row), `law_revision`, `law_change`, `chronicle`; cover: `cover_law`; gaze off: `applied_gaze` deletes | PK | every `law_override` subscriber gets one row update; `cover_law` subscribers one row | per admin call | one `law_change` row per call (kept); `law_override` is bounded by the law names |
| Ordinary `set_world_law`, `install_script` | as before, plus `law_override` | as before, plus `law_override` | PK | as before | per admin call | as before |
| Migration | `world_law` (once) | `law_override`, `law_revision` | PK | `law_override` subscribers | once per world | — |

There is no whole-World read: the value-only path touches no character, body or appearance table. The cover mask compile on the next map read is a world-scale effect of a world-scale law (Cullet 13–16 ms, measured before; see the design note). The terrain is not reloaded.

## SpacetimeDB documentation consulted (2026-11-19)

The build is pinned to 2.14.1 (`living/Cargo.toml`, the `clockworklabs/spacetime:v2.14.1` image).

| Page | What it says | What follows here |
| --- | --- | --- |
| [Tables](https://spacetimedb.com/docs/tables/) | A table is public with `public` in `#[spacetimedb::table]`. Public tables are "exposed for client read access through subscriptions. Writes still occur only through reducers." Private tables are "visible only to reducers and the database owner". | `law_override` is public. It is read-only because only reducers write it, and its one writer, `set_world_law`, is admin-only. `law_revision` is private bookkeeping. |
| [Performance](https://spacetimedb.com/docs/tables/performance/) | "Generally prefer indexed lookups over full table scans." Private tables "don't consume client bandwidth". | The per-transaction read is a primary-key lookup on `law_revision`. The rows (tens) are read in full only when the revision moved. |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | "SpacetimeDB sends you the matching rows immediately and then pushes updates." The applied callback "runs once initial matching rows are present in the local cache". The page shows always-displayed data as a global, never-cancelled subscription. | A client subscribes the whole small table once per connection. The page does not say what a reconnect receives, so that was proved live: a fresh connection's first result holds every row with the value in force (`law_override.py checks`). |
| [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) | "Adding new tables" is a safe change. A column can be added only at the end, with a default. "SpacetimeDB can remove a table only if it has no rows." | Two new tables, and no column added to an existing one: 2.14.1 rewrites a table on a column append and disconnects clients, see `docs/LOOK.md` §7. `world_law` stays, because it has rows on existing worlds. |
| [Reducers](https://spacetimedb.com/docs/functions/reducers/) | A reducer runs as one transaction, and an error rolls it back. | A value refused after the rows were written rolls everything back. Module memory follows the committed revision (above). |

The docs pages show version 2.0.0. Nothing used here is newer than the 2.14.1 module and SDK already exercise: public and private tables, primary keys and full-table subscriptions.

## Measurements

Setup:

- **Server:** Spark, a private `clockworklabs/spacetime:v2.14.1` container (`slop-lawoverride-stdb`). There were no players, no observer and no model calls, and `set_profile` was on, so ticks were logged.
- **Driver:** `law_override.py time`. Each value-only law goes to its other value and back three times; `fire_warmth` (an ordinary law) is the full-install reference.
- **Before:** main 3df6e1f1 (frame-views), on a world launched from a clean worktree of that commit. Main has no `set_world_law` span, so its reducer time is the HTTP round trip less the HTTP overhead. The overhead is the after column's round trip less its reducer time: 2–40 ms here, depending on the Spark's load from other sessions.
- **After:** this branch, the build after the cover fix below. The reducer time is the module's own `set_world_law` span, which starts after `require_admin`. The first tick is the first `tick` span logged after the call.
- **Load:** other sessions' builds and benchmarks ran on the Spark throughout. The before runs and the island after run took the heavier share, so read the before figures as their order of magnitude.

Each cell is the median (minimum–maximum) of 6 samples, or 4 for `fire_warmth`.

**Island** (seed `island`; gaze and cover off as shipped, cover geometry present):

| Law | Before: round trip ms | Before: `install.validate` ms | After: reducer ms | After: round trip ms | After: first tick ms |
| --- | --- | --- | --- | --- | --- |
| `cue_transport_on` | 1070 (1023–1486) | 844 (832–851) | 0.77 (0.71–0.82) | 29 (19–40) | 1.73 (1.62–3.06) |
| `near_tier_on` | 994 (973–1067) | 813 (803–833) | 0.58 (0.52–0.85) | 29 (24–36) | 1.20 (0.89–1.95) |
| `gaze_on` | 1048 (994–1096) | 829 (817–861) | 1.40 (0.94–2.07) | 22 (19–40) | 1.05 (0.81–1.68) |
| `cover_brush_min_fill` | 1287 (1009–1518) | 848 (817–1223) | 0.51 (0.39–0.67) | 16 (9–35) | 1.17 (1.10–1.59) |
| `cover_sight_on` | 1788 (1155–2984) | 958 (848–1206) | 0.52 (0.42–0.67) | 3 (2–50) | 20 (1.4–42) |
| `fire_warmth` (full install) | 1097 (1015–1445) | 855 (837–1166) | 952 (937–965) | 971 (953–988) | 16 (14–20) |

**Cullet** (seed `cullet`; gaze, facing and cover on in its laws):

| Law | Before: round trip ms | Before: `install.validate` ms | After: reducer ms | After: round trip ms | After: first tick ms |
| --- | --- | --- | --- | --- | --- |
| `cue_transport_on` | 2718 (2497–3169) | 2473 (2285–2795) | 0.57 (0.46–0.77) | 2.4 (2.1–2.9) | 0.39 (0.24–0.57) |
| `near_tier_on` | 3005 (2536–4756) | 2791 (2296–4347) | 0.77 (0.44–0.90) | 2.2 (2.1–2.6) | 0.66 (0.30–1.01) |
| `gaze_on` | 2669 (2477–4316) | 2374 (2230–4025) | 1.81 (1.23–2.05) | 3.3 (2.7–3.7) | 0.38 (0.30–1.70) |
| `cover_brush_min_fill` | 3498 (2601–3809) | 3184 (2352–3511) | 0.79 (0.49–0.81) | 2.3 (2.2–2.5) | 26 (14–27) |
| `cover_sight_on` | 2920 (2451–3812) | 2665 (2242–3511) | 0.85 (0.80–0.97) | 2.7 (2.4–3.0) | 13.5 (0.7–27) |
| `fire_warmth` (full install) | 2453 (2435–4308) | 2201 (2198–4032) | 2409 (2399–2431) | 2419 (2412–2442) | 7.7 (7.0–9.3) |

**What the figures show:**

- **Reducer time:** every value-only edit is under the 5 ms target on both worlds, at 0.39–2.07 ms. `gaze_on` is the costliest, because its 24 senses samples run again (natively 0.29 ms, `law_override_check::value_only_edit_cost`).
- **The first tick after a delivery or gaze edit** is an ordinary tick. Cullet's ticks run at p50 0.39 ms, p90 0.70 ms and max 1.7 ms over 142 profiled ticks at rest.
- **A cover-policy change** compiles the cover mask at the next map read, on the next tick: 13–27 ms on Cullet, about 40 ms on the island when cover turns on there. Turning cover off compiles nothing. The terrain and gates are not reloaded (`map.rebuild` never appears; `law_override.py checks` counts both spans after each edit). This is the world-scale cost the design note budgeted at 15–20 ms on Cullet; on this loaded host it reached 27 ms.
- **An ordinary law** still costs the full install, as before (952 ms on the island, 2.41 s on Cullet).

**Two things fixed on the way, both caught by the checks:**

- **The constants' words** (`law_about` for every constant) were first read again eagerly on each edit. That made 4–7.4 ms of reducer time, over the target. They are now read only when asked: only an install's checks and tests ask.
- **The cover mask** was first compiled again on the tick after *every* law write, about 13 ms on Cullet, because the check had no memory of the policy the mask was built under. `law_override.py checks` failed 6 of 49 on that build, once for each delivery and gaze edit (`law-checks-before-cover-fix.txt`). The mask's policy is now kept apart from the revision last checked, and the fixed build passes 49/49.

The evidence is archived in `~/slop-evidence/law-override-2026-11-19.tar.zst` (with a `.sha256`).

## Not covered

- **Load:** no measurement under player load or active owner subscriptions: a gaze-off edit's `applied_gaze` deletes, the `law_override` fan-out to many subscribers, and frame-view subscribers during a delivery switch. Those last are covered functionally by verify-client `cues.py` and `near_tier.py`, not timed.
- **The game client's half:** built on branch `law-override-client` (above).
- **The view-side law read** suggested in `docs/TICK_RATE.md`: an untiered view reading `near_tier_on` by key. A view cannot run the script, so it would need the shipped default for a world with no row. Not built.
- **External preparation** (the design note's Option 2): not built.
