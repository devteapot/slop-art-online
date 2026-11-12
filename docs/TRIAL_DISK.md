# The trial server's disk: deleted databases, their commitlogs, and a plan

Status: **plan for the owner, nothing removed** (2026-11-12, branch `trials-records`). Everything below was read, not changed. The code changes on this branch are written but not yet run: they wait for the end of the battle quiet window.

## What is on disk (read 2026-11-12, `slop-trials-stdb`, SpacetimeDB 2.14.1)

| Part | Size |
|---|---:|
| Data directory `/home/spacetime/.local/share/spacetime/data` | **262 GB** |
| `replicas/` (1,771 directories) | 243.6 GB |
| `cache/` (wasmtime's compiled modules; regenerated on demand) | 11 GB |
| `program-bytes/` (229 module binaries, by hash) | 7.0 GB |
| `logs/` | 1.1 GB |
| `control-db/` | 3.1 MB |

The host disk is 93% full: 67 GB free of 917 GB.

**Live databases: 6, all listed.** `spacetime list` and `GET /v1/identity/<owner>/databases` agree. The owner is the container CLI's identity `c200cb3b…`, which also publishes every trial database. Each live database was mapped to its replica directory by its module log:

| Database | Replica | Size | State |
|---|---|---:|---|
| `verify-trial-bi1-hamlet-default-r1` | 4002239 | 407 MB | paused (kept evidence) |
| `verify-trial-bi1-hamlet-spaced-default-r1` | 4002245 | 1.0 GB | paused (kept evidence) |
| `verify-trial-bi1-hamlet-provided-default-r1` | 4002247 | 1.0 GB | paused (kept evidence) |
| `verify-trial-bi1-hamlet-longing-default-r1` | 4002249 | 969 MB | paused (kept evidence) |
| `verify-core-mainbs-192010` | 6001371 | 66 MB | ticking (another session's scratch) |
| `verify-minds-way6-11121809-speech` | 6001373 | – | ticking (another session's scratch) |

- **b3f is no longer hosted.** Its name answers 404, and its last action was `set_paused`.
- **The other 1,766 directories (240.2 GB) are deleted databases.** Their replica directories stayed on disk.

## Why deleted databases stay on disk

- **Known in SpacetimeDB's own source, with no supported cleanup.** At tag `v2.14.1`, `crates/standalone/src/lib.rs`:
  - `delete_database` drops the control-DB rows and calls `delete_replica`;
  - `on_delete_replica` says, verbatim: "This will just drop them from memory, but will not remove them from disk. We need some kind of database lifecycle manager long term." It then exits the module host.
- **The docs.** The [databases page](https://spacetimedb.com/docs/databases) (labelled 2.0.0) says only "Deleting a database is permanent and cannot be undone. All data will be lost."
  - The [CLI reference](https://spacetimedb.com/docs/cli-reference) has no garbage-collection or prune command.
  - The [standalone config](https://spacetimedb.com/docs/cli-reference/standalone-config) has no cleanup option.
  - The only bulk command, `spacetime server clear`, deletes all local databases.
- **No GitHub issue** about it was found (searched 2026-11-12, without login).
- **Republishing adds more.** Every `publish --delete-data` to an existing name also leaves the old replica (`living/tools/reclaim_disk.sh`'s header). Our runs publish once per instance, but verify scenes republish.

**Why the list looked empty.** A deleted database leaves the list at once: each trial run pauses and deletes its own database when it ends. The fs1c, fs1f and fs1h samplers saw their databases after the 12:53 restart. Only fs1e's sampler (17:55–18:16) saw none, although publishing and SQL worked. Its 68-character name, the longest of these batches, is the one difference found; to test with a scratch database after the window.

## The 1,766 deleted directories, by kind

Each directory's `db.lock` time is its database's publish time. It was matched to a trial instance's `actions.log` "published …" line (within 40 s), or to a verify run's evidence folder (within 120 s). The "verify" and "unknown" rows are time matches, so they are approximate.

| Kind | Directories | Size |
|---|---:|---:|
| **paid** (a trial run with real model tokens in its journals) | 130 | 20.4 GB |
| **no-model** (real runs without model calls: the `instinct` pack and battle batches pkb*, pkc*, pkr*, pk*) | 208 | 39.9 GB |
| fake runs | 82 | 10.3 GB |
| verify scratch (matched to verify runs' times) | 1,254 | 159.7 GB |
| unknown | 92 | 9.9 GB |

### The paid batches: what else holds their record

The run record is the batch folder in its checkout: journals (every model exchange), summaries, samples, the subject's rows and graphs, and in all-minds batches `thoughts_all`/`experiences_all`.

| Batch | Dirs | Size | Archived beyond its checkout |
|---|---:|---:|---|
| r2d | 15 | 3.00 GB | no |
| r2b | 10 | 2.70 GB | no |
| ar2 | 27 | 2.19 GB | no |
| r2e | 9 | 1.87 GB | no |
| gl1 | 6 | 1.81 GB | no |
| ar1 | 30 | 1.80 GB | no |
| st1 | 8 | 1.68 GB | no |
| gr2 | 8 | 1.29 GB | **store** (`batches/spark/gr2`) |
| st2b | 5 | 1.26 GB | **`~/archive/trials/st2b-20261112.tar.gz`** |
| st2 | 3 | 0.89 GB | no |
| bi1 (other than the 4 kept hamlets) | 2 | 0.77 GB | no |
| fs1e, fs1c, fs1h | 2, 1, 1 | 0.41, 0.30, 0.28 GB | **`~/archive/trials/fs1e-…`, `fs1-…`, `fs1h-…`** |
| es1 | 2 | 0.09 GB | no |
| r2c | 1 | 0.04 GB | no |

More directories than instances (r2d 15 for 10 runs, ar1 30) mostly means a republish or a retried start, each leaving a replica.

**What exists only in the commitlog.** A replica's commitlog (`clog/`, about 93% of each directory) holds every committed transaction: each reducer call with its arguments, caller and time, and every row inserted or deleted. The run records keep the model side completely (journals) but the authority side only in part. Only in the commitlog:
- **every resident's installed graphs and routines over time**, with the authority's acceptance or refusal of each `mind_install`, `mind_patch` and `mind_act` (`graphs.jsonl` and `mind_rows.jsonl` hold the subject's only);
- **every body's motion, vitals and inventory** between the samples, for everyone, not just the subject;
- **experiences consumed and deleted** once integrated, in batches without `experiences_all` (the r2 arenas, ar1);
- **the exact order and time of admin, mind and scripted-player calls.** The commitlog reader can export a player's exact reducer calls from it.

The r2 arenas (one minded subject and a scripted fixture) lose the least. The all-minds batches (ar1, ar2, st1, st2, st2b, bi1, fs1, es1, gr2, gl1) lose the most: 62 of 63 residents' authority-side histories are nowhere else.

Decoding a commitlog later needs the module that wrote it. It is in `program-bytes/` by hash, and as the trial `.wasm` in each checkout's `.local/living/trials/wasm/`. Keep one copy per batch beside the commitlog.

## The proposed shape, priced

**Compression (sampled 2026-11-12: 4 MB slices, in memory, under a second; measure fully after the window):**
- a 20-minute run's single commitlog segment: **gzip 0.19–0.27, xz 0.06–0.21**;
- a long run's first segment (bi1): 0.93, so that segment is already compressed;
- **estimate:** about 0.2–0.3 of the commitlog for paid trial runs.

| Group | Now | Shape | After |
|---|---:|---|---:|
| paid (130) | 20.4 GB (commitlog ≈ 19.0 GB) | keep each commitlog compressed, plus its module, in `~/slop-evidence/commitlogs/<batch>/`; remove the rest of the replica (snapshots, module logs) | **≈ 3.8–5.7 GB** in `~/slop-evidence` |
| fake (82) and verify scratch (1,254) | 170.0 GB | remove whole | 0 |
| no-model (208): not covered by the shape | 39.9 GB | **to decide:** keep compressed like paid (≈ 7.4–11 GB), or remove whole (their reports and measures stay in their checkouts; regenerable only by hours of re-running) | 0 or ≈ 7.4–11 GB |
| unknown (92) | 9.9 GB | **to decide:** hold until identified, or treat as scratch | 9.9 GB or 0 |
| live (6) | ≈ 3.5 GB | untouched | ≈ 3.5 GB |

**Before and after.**
- **Now:** the data directory is 262 GB, and the host has 67 GB free.
- **After the shape as given** (no-model removed, unknown held): the data directory is about 32 GB, plus 4–6 GB of archived commitlogs. That **frees about 225 GB** (host about 290 GB free).
- **With the no-model commitlogs kept too:** another 7–11 GB is kept.

## How it would be done (once the owner approves; not before)

1. **In a quiet window.** Announce it, because the two ticking verify worlds belong to other sessions. Stop the trial server (`trials.py down`; SIGINT, then stop).
   - The server keeps a file open for every database it has hosted, deleted ones too. Files removed while it runs would not free space until a restart.
2. **Archive the paid commitlogs.**
   - **How:** a one-off container reads the volume read-only: `docker run --rm -v slop-trials-stdb:/data:ro …`, then `tar` with `zstd` (or `xz`) per batch, plus the module, into `~/slop-evidence/commitlogs/<batch>/`.
   - **What it writes:** each archive's sha256, and a manifest of replica, batch, instance and database.
   - **Checks:** test-decompress each archive and compare file sizes.
3. **Remove the listed directories only.** That is the reviewed `reclaim --json` list, minus live and held directories, removed from the stopped volume. Then start the server.
4. **Check after:**
   - the four bi1 hamlets answer SQL and read `paused` true;
   - `spacetime list` shows the same six;
   - the data directory and host free space are as estimated.

The commitlog archives can go to the store later as their own unit, once the owner allows.

## Changes on this branch (written, not yet run)

- **`trials.py`:**
  - **At publish:** each instance records `database_identity` (by name, `GET /v1/database/<name>`) and `replica` (by its module log, among replicas newer than the publish) in `state.json` and `summary.json`, and logs them.
  - **`clean`** deletes the batch's databases from its own records (`batch_databases`), each paused first by `delete_db`; `spacetime list` is only a backstop.
  - **`dbs --batch B [--json]`:** a batch's databases, identities and replicas, for samplers.
  - **`reclaim` is now a classifier that removes nothing.** It covers every replica directory (live, paid, no-model, fake, verify, unknown), with sizes, commitlog sizes and lock times, and `--json`. It replaces the earlier `reclaim`, which deleted every idle replica with the server running, paid commitlogs included.
- **`trial_scale.py`:** the batch's databases from its records.
- **`battle_diag.py`:** the identity by name, not from the list.
- **Not changed here, but worth knowing:**
  - the verify harness (`verify.py cleanup`, `verify-core/scripts/speech.py`) also reads `spacetime list`;
  - `living/tools/reclaim_disk.sh` removes idle replicas in the `sao-living` reference container and must not be run there while the reference worlds are kept.

**To check after the window:**
- a fake batch records an identity and a replica for each instance;
- `dbs` and `clean` work from the records;
- `reclaim` runs as a dry run, with its totals matching the table above.
- Plus the fs1e name-length test and a full compression measurement.
