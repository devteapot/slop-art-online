# A long battle world's disk on SpacetimeDB 2.14.1 (design note, measured 2026-11-20)

How much a world holding a 216-viewer battle writes to its commitlog, what the server keeps on disk, what fills it, and how such a world stays within a disk budget. It extends [BATTLE_VIEWERS.md](BATTLE_VIEWERS.md) (rollout step 2's commitlog measurement), and its source reading corrects that one's.

**For the performance contract (proposed; the GC takes it to the owner with the battle decision).** A 216-viewer battle of 200 fighters, with `combat_feed_on` and every battle law off:
- **writes about 32 GB of commitlog per battle-hour** (raw);
- **keeps about 12 GB per battle-hour on the server's volume**: 2.14.1's own compression keeps about 0.34 of the log, plus about 0.8 GB of snapshots;
- **archives to about 3 GB per battle-hour** if the raw log is compressed as one zstd stream, or about 10 GB as `trial_archive.py` tars it now.

Proposed line: *"Disk: at most 35 GB written and 13 GB kept on the server per battle-hour at 216 viewers; a world's volume holds a stated number of battle-hours and is pruned offline at a maintenance window, archive first."* With `far_cap` 40 the battle writes about 30% less: 22.5 GB raw, about 8.5 GB kept.

The contract's 8-hour battle at today's rates is about 260 GB written and about 96 GB kept, unless the world is pruned during it.

## 1. What was measured

**Hardware and build.** The dev-box, `sg-stdb` (SpacetimeDB v2.14.1, alone on its volume), unpinned (rootless podman has no cpuset controller). Cullet module from `clog-long` `f7dc6fcea`, which is main `79cb4a42e` plus tools only.

**The fixture.** 216 viewers on the 26–32 m ring around a battle of 200 fighters.
- Keep-alive every 0.5 s.
- Paused placement, the battle after placing.
- Tiers and cues on.
- Both copy tables on (the defaults) with the viewers on them.
- `combat_feed_on` on, with the viewers on `combat_feed` (the coming default).
- L0: server metrics, no spans.

**Two parts:**
1. **The hour.** A 57-minute window (3,420 s) after a 20 s warm-up, about 59 minutes of world life, sampled every 30 s by `living/tools/clog_watch.py`: segments, compression, snapshots, RSS, WASM memory, rows per table.
   - The fight did not last. Skill uses went from 127/s in the first 5 minutes to about 6/s after 15 minutes, as fighters died (keep-alive heals the viewers, not the fighters).
   - So the hour is mostly **216 viewers in a crowd after a battle**, at 55 ticks/s.
   - Other load on the host: another session's `cargo test` raised the load above 8 from 15:41 to 15:45 UTC. Otherwise it stayed at 3–4.
2. **The battle.** Six 60 s windows at 216 viewers in the battle's first minutes, two per arm: laws off, `far_cap` 40, and the crowd cadence (`crowd_sweep_n` 30, `crowd_frame_max_ms` 250). These were 22–31 ticks/s with about 350 alive, 0 viewer deaths.

**How the bytes were attributed.** `living/tools/clog_read.py` decodes the log offline in 2.14.1's format (commits, transactions, BSATN rows by the module's schema, compressed segments through `zstd -dc`). It attributed every byte: 17,049,204,551 of 17,049,204,551 for the hour, and each battle window's range in full. One of the six windows (`off-r2`) has its total but not its split: its replica was removed with the volume before it was decoded.

## 2. How 2.14.1 keeps a world's history (versioned source, tag `v2.14.1`)

- **Every write is logged, whole.**
  - A transaction that changes rows is appended with its reducer's inputs and every inserted and deleted row, encoded whole: an update is a delete and an insert of the full row ([txdata.rs](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/commitlog/src/payload/txdata.rs#L503-L518)).
  - Event tables' inserts are logged ([committed_state.rs](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/datastore/src/locking_tx_datastore/committed_state.rs#L738-L744)).
  - Only views' (ephemeral) tables are left out ([traits.rs](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/datastore/src/traits.rs#L287-L303)).
- **When snapshots are taken.**
  - Segments rotate at 1 GiB ([`DEFAULT_MAX_SEGMENT_SIZE`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/commitlog/src/lib.rs#L110)).
  - **A snapshot is requested at every rotation** ([`on_new_segment`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/relational_db.rs#L1924-L1941)).
  - Snapshots are also taken every 1,000,000 transactions, at offsets 1, 1,000,001 and so on ([`SNAPSHOT_FREQUENCY`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/relational_db.rs#L128-L135), [`maybe_do_snapshot`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/relational_db.rs#L993-L1001)).
- **Compression after each snapshot.**
  - The standalone server ([`LocalPersistenceProvider`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/persistence.rs#L198-L250)) compresses the sealed segments older than the snapshot, in place, under the same name ([compressor](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/relational_db.rs#L1964-L2015), [fs repo](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/commitlog/src/repo/fs.rs#L371-L383)).
  - The format is zstd **seekable, frames of at most 4 KiB** ([`segment_compressor`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/commitlog/src/repo/mod.rs#L456-L465)). That keeps about 0.34 of the raw bytes, against about 0.09 for the same log as one zstd stream.
  - Older snapshots are compressed too ([`compress_snapshots`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/snapshot.rs#L330-L364)).
- **Nothing is deleted.** The only removal in the snapshot code is of snapshots marked invalid ([snapshot lib](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/snapshot/src/lib.rs#L1266-L1269)).
- **Settings.** The `[commitlog]` section of the server's `config.toml` sets the segment size, offset-index interval, preallocation and write buffer ([config.toml](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/standalone/config.toml#L60-L78), [`CommitlogConfig`](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/engine/src/persistence.rs#L25-L42)). None of them sets a retention, cap or snapshot interval.
- **The docs agree.** The [commitlog internals](https://spacetimedb.com/docs/reference/internals/commitlog/) say "the log is never compacted", and segments "may be compressed using the zstd seekable format". The [standalone configuration](https://spacetimedb.com/docs/cli-reference/standalone-config/) lists `max-segment-size` and `preallocate-segments`, with no retention option. The [performance](https://spacetimedb.com/docs/tables/performance/) page's growth advice is about table rows, not the log. The pages are labelled 2.0.0; the behaviour above is read from the 2.14.1 source.

## 3. What the hour kept

| Minute | Raw log written (cumulative) | On disk: compressed segments + raw tail + snapshots | Service RSS |
|---|---|---|---|
| 5 | 2.0 GB | 1.35 GB | 1.45 GB |
| 20 | 6.4 GB | 3.2 GB | 1.53 GB |
| 40 | 11.8 GB | 4.5 GB | 1.51 GB |
| 58 | 16.8 GB | 6.9 GB | 1.48 GB |

- **The log.**
  - 17.0 GB raw over the hour: 4.9 MB/s, 17.7 GB/h.
  - The clog directory grew 6.12 GB over the 3,420 s window (6.4 GB/h).
  - A segment rotated every 3–4 minutes. Its snapshot came within 30 s, and the segment was compressed within 30 s of that, at 0.28–0.36 (mean 0.345).
  - The raw part of the log never exceeded one segment.
- **The snapshots.** About 116 MB each, 17 in the hour. Each older one is compressed to about 25 MB: 0.46 GB on disk at the end.
- **Memory.**
  - The world was alone on the server. Service RSS went from 108 MB before it, to 1.17 GB after placement, to 1.45–1.53 GB from minute 5 on: flat, peak 1.55 GB.
  - WASM memory held at 185 MB all hour.
  - The service's footprint did not grow with the log.

## 4. What fills the log

Shares of the decoded bytes:

| | Battle window (laws off, 8.9 MB/s) | The hour (mostly crowd, 4.9 MB/s) |
|---|---|---|
| Character mirror (`projected` + `seen_character_copy`, written twice) | **35.7%** | 28.6% |
| Combat (`combat_seen`, `combat_feed`, `fight_seen`, `skill_use`) | 15.5% | 2.2% |
| Motion copies (`seen_body_copy`) | 13.8% | **26.5%** |
| Hearing (`heard`, `character_earshot`, `line_seen`) | 8.6% | 11.7% |
| Fighter tiers (`fighter_seen`, `fighter_near`) | 6.5% | 11.3% |
| Perception rows (`perceived`) | 6.1% | 5.2% |
| AI and mind state (`mind_state`, `experience`, `deliberation`, ...) | 5.2% | 1.0% |
| Cues (`seen_body_cue`, `seen_fighter_cue`) | 4.6% | 9.1% |
| Bodies and movement (`body`, `steer`, `vitals`, ...) | 2.1% | 2.4% |
| Auto-increment bookkeeping (`st_sequence`) | 0.4% | 0.8% |
| Inputs, framing, other tables | about 1.5% | 1.2% |

**Per-viewer perception state is 70–95% of the log.** Each change of a creature is written once per viewer that sees it, as a whole row, and again as a whole row when it is deleted or replaced. The AI's own state is a few percent. `st_sequence` (the server rewriting a sequence's allocation row, about 112 bytes, as auto-increment tables advance) is under 1%.

## 5. Keeping a long battle within a budget

### Offline prune at a maintenance window (measured)

Measured on the hour's world with `living/tools/clog_prune_trial.py --in-place --archive`, which is [TRIAL_DISK.md](TRIAL_DISK.md#offline-snapshot-and-commitlog-pruning)'s procedure applied to the volume itself. The steps: pause the world and read it back as paused; stop the server; archive the replica's log and snapshots off the volume (tested with `zstd -t`, sha256 sidecar); prune; start; recover; check.

| Phase | Time |
|---|---|
| Stop (SIGINT until exited) | 0.3 s |
| Archive: 6.4 GB of log and 0.46 GB of snapshots → 5.1 GB `.tar.zst` | 46 s |
| Prune: keep the latest snapshot (offset 714,772), its covering segment and newer; 15 segments and 15 snapshots removed | 1.7 s |
| Start and recover (the world answers SQL) | 9.7 s |

- **The result.** The replica went from 6.9 GB to 1.06 GB, with identity, counts and `paused` unchanged.
- **The window.** About a minute for an hour's battle world, nearly all of it the archive, which runs at about 150 MB/s of on-disk bytes. Recovery reads the latest snapshot plus at most one segment, so it does not grow with the world's age.
- **The prune is fast; the archive's size is the issue.**
  - `trial_archive.py` and this trial tar the segments as they are on disk. Segments the server has already compressed stay at about 0.30 of raw (5.1 GB for 17 GB).
  - Decompressing the segments and compressing the raw log as one stream would keep about 0.09, about 1.6 GB.
  - Worth changing in `trial_archive.py` before long trials. The archive is then a plain, uncompressed segment set that the reader and the server both accept.

### Cutting write volume (candidates, not built)

By the battle window's shares:
1. **The character mirror's double write (35.7%).** `projected` is the authority's working state, and `seen_character_copy` mirrors every write of it for the clients (Addendum 2: "a mirror, not a move"). The frame-paced band and health rewrites are most of both.
   - **The option.** A narrow `projected` row for the authority, with the frame-paced fields only in the mirror.
   - **Saving.** Up to about 18% of the log.
   - **Constraint.** The kill switch needs `projected` whole while the view path exists.
2. **`far_cap` (measured, below):** −30%.
3. **Narrow rows for what changes often.** An update logs two whole rows, and every per-viewer row carries the viewer's 32-byte identity, which RLS (`viewer = :sender`) needs. Splitting the often-changing fields of `seen_body_copy`, the mirror and `fighter_seen` into narrow rows cuts the bytes per change. Addendum 2's slim row did this once.
4. **Combat rows.** `combat_seen` is logged on insert and again on expiry (10%), and `combat_feed` repeats each row once more (4.9%). A shorter retention would keep the same number of rows: the row count is the cost.
5. **The motion copies' far updates.** `far_motion_tol_m` (a value-only prototype law) skips small far moves. It was not measured here. These copies are 26.5% of the crowd hour.

### What the battle laws save in log bytes (measured)

60 s windows at 216 viewers, two runs per arm (the split by table is from one `off` run and both runs of each law):

| Arm | Raw log, MB/s | GB/h raw | Ticks/s | Per tick |
|---|---|---|---|---|
| Laws off | 8.91 / 8.91 | 32.1 | 22.1 / 22.8 | 0.40 MB |
| (a) `far_cap` 40 | 6.32 / 6.20 | **22.5 (−30%)** | 29.8 / 30.9 | 0.21 MB (−48%) |
| (b) crowd cadence 30 / 250 ms | 8.62 / 8.92 | 31.6 (−2%) | 30.2 / 27.4 | 0.30 MB (−24%) |

- **(a) `far_cap` 40.** It halves what is written per viewer:
  - the mirror 3.18 → 1.49 MB/s;
  - motion copies 1.23 → 0.74;
  - perception rows 0.54 → 0.29;
  - fighter tiers 0.52 → 0.23.
  
  Combat, hearing and cues are unchanged. **It is the one lever measured that lowers the log per second, while ticks rise by about a third.**
- **(b) The crowd cadence.** It writes about 24% less per tick, but ticks rise by about as much, so bytes per second barely move.
- **Per second will rise as ticks do.** Both laws, and any other gain in tick rate toward the contract's 60 Hz, raise the writes per second of everything written per tick. The crowd hour at 55 ticks/s shows the scale. A budget in GB per battle-hour has to be measured again at the tick rate the game ships with.

### Online retention

2.14.1 has none: no setting, no reducer or CLI command, and nothing in the docs (§2). The levers it does give:
- **`[commitlog] max-segment-size`.** Smaller segments mean more frequent snapshots and compression, so a smaller raw tail. But each snapshot is about 116 MB before it is compressed and about 25 MB after, so smaller segments trade raw log for snapshots. It does not cap anything.
- **Fewer bytes written** (above).
- **The offline prune** (above).

A newer SpacetimeDB may add retention. Check it at the next version change, against that version's source.

## Not covered

- **A sustained battle for a whole hour.** `battle_viewers.py --keep-fighters 1` (the Spark's, on main since `f9b36cefa`) replaces each dead fighter. The battle-hour figures above are the 60 s windows' rate times an hour, and the hour's own snapshot and compression ratios.
- `far_motion_tol_m`, the combined laws, and a pinned host.
- A tick rate near 60 Hz in battle.
- Several worlds on one server: RSS was measured with this world alone.

## Evidence

- `~/archive/worktree-evidence-20261120/clog-long-local.tar.gz` on the dev-box. It holds the series log, every sample (`watch/samples.jsonl`), the schema, `analysis.json`, the decoded bytes (`read-all.json`, each window's `*-read.json`), each run's `battle-viewers.json` and metrics, the prune trial (`prune-trial.json`) and the host load.
- The hour's whole replica log and snapshots, as archived before the prune: `~/archive/worktree-evidence-20261120/clog-long-replica4000001.tar.zst` (5.1 GB, `.sha256` beside it).
- The tools: `living/tools/clog_watch.py`, `clog_read.py`, `clog_prune_trial.py`, and `battle_viewers.py --keep-world --clog`.
