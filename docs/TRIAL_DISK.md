# The trial server's disk: deleted databases, their commitlogs, and a plan

Status: **plan for the owner, nothing removed** (2026-11-12, branch `trials-records`). Everything below was read, not changed. The code changes on this branch were tested after the battle quiet window ("Tested", below).

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

**Why the list looked empty: a database name of 64 characters or more breaks it.** Tested on a scratch fake run, 2026-11-12.
- **The reproduction.** SpacetimeDB 2.14.1 publishes a database named `verify-trial-trtestlong…-wolves-default-r1` (68 characters), and lookup by that name answers 200. But `GET /v1/database/<identity>/names` then answers 500: "Domain name parts must be shorter than 64 characters".
- **Its effect.** `spacetime list` fails as a whole ("Error: … 500 Internal Server Error") and lists nothing for any database, while such a database exists.
- **fs1e is exactly this.** Its database was named `verify-trial-fs1e-strangers-2b-c-strangers-first-sight-hf-earshot-r1`, 68 characters. While it lived (17:55–18:16), every consumer of the list saw no databases: `trials.py clean` and `down`, the tick samplers, `verify.py cleanup` and `speech.py`'s metrics.
- **Otherwise the list was sound.** A deleted database leaves the list at once: each trial run pauses and deletes its own database at its end. The fs1c, fs1f and fs1h samplers saw theirs after the 12:53 restart.

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

## The reviewed removal list (2026-11-12, owner-approved shape)

The list is [`docs/trial-disk/removal-list-20261112.tsv`](trial-disk/removal-list-20261112.tsv), one row per replica directory: replica, class, action, size, commitlog size, lock time, and what it was. It was made by `trials.py reclaim --json` and `trial_disk.py list` after gl2 ended, with only the four bi1 hamlets and the merge gate's world hosted.

| Class | Dirs | Size | Commitlogs | Action |
|---|---:|---:|---:|---|
| live (hosted, or written in the 15 minutes before the list) | 11 | 4.0 GB | 3.7 GB | keep |
| paid | 224 | 32.5 GB | 27.1 GB | archive the commitlog (with its module), then remove |
| no-model | 273 | 51.2 GB | 41.6 GB | archive the commitlog (with its module), then remove |
| fake | 77 | 9.6 GB | 7.7 GB | remove |
| verify scratch (`verify-gate-*` of finished merges included) | 1,157 | 157.9 GB | 120.7 GB | remove |
| unknown | 181 | 15.7 GB | 10.9 GB | hold, untouched |

**Totals:**
- **Remove:** 1,731 directories, 251.2 GB.
- **Archive first:** 497 commitlogs, 68.7 GB before compression. Expect about 4–21 GB, since zstd -6 gave 0.063 on a gl1 commitlog, and the plan's sample range was 0.06–0.3.

**Where it differs from the plan's read-only tally:**
- **The matching is now conservative.** A directory whose lock time is within 40 s of any real trial run's publish is archived, even when a verify publish is as near. This moves directories from verify into paid and no-model.
- **More runs are counted.** gl2, pkp1 and ew1 have run since, and every checkout on the machine was scanned.
- **unknown is 181 directories (15.7 GB), not 92 (9.9 GB):** verify runs are now matched only by their own publish lines, not by folder times. All 181 are held.
- **The two ticking verify worlds of the plan have since ended.** The live rows are the four bi1 hamlets, the merge gate's world, and six directories written in the last 15 minutes. All are kept.

## Done (2026-11-12 22:58 to 2026-11-13 00:2x)

The owner approved the plan with the general coordinator's two recommendations (keep the no-model commitlogs too; hold the unknown directories). It was run as written.

1. **Waited.** At the stop, the server hosted only the four paused bi1 hamlets. No directory on the list had been written since the list was made; the one new directory (6001679) was not on the list. The merge queue was held (the Spark coordinator's lock, 22:55:40).
2. **Stopped `slop-trials-stdb` only** (SIGINT, then `docker stop`; exit 0 at 22:58:56). The trial Neo4j and the `sao-living` containers were untouched.
3. **Archived through read-only `alpine` mounts:** 497 of 497 commitlogs (the paid and no-model classes), each with its `module_logs` and `db.lock`.
   - **Where:** `~/slop-evidence/commitlogs-20261112/<batch>/<instance>-<replica>.tar.zst`, **6.8 GB** from 68.7 GB.
   - **Checks:** each was tested with `zstd -t`, and its tar listing was compared with the source's files and byte sizes before the next one started. All 497 passed.
   - **Modules:** the module that wrote each batch's commitlogs (34 modules for 32 batches), copied from the trial server's served copies (exact names) by `trial_disk_modules.py`, recorded in `MODULES.jsonl`. The first pass looked only in each checkout's `wasm/` under the served name and found 8; nothing was missing after the second.
   - **Records:** `MANIFEST.jsonl` (one row per commitlog: replica, class, batch, instance, sha256, sizes, lock time) and `SHA256SUMS` (539 entries). `sha256sum -c SHA256SUMS` passed in full before the first removal.
   - The archive log is [`trial-disk/archive-20261112.log`](trial-disk/archive-20261112.log).
4. **Removed exactly the list** (`trial_disk.py remove`, server stopped): 1,731 directories.
   - **Left:** 194 directories, the 192 kept as listed (11 live, 181 unknown held) plus the 2 created after the list.
   - **The data directory** is now 39.3 GB, from 262 GB.
5. **Restarted.**
   - **File limit:** the soft open-file limit had reset to 1024, so the stack record's `prlimit --pid 1 --nofile=65536:524288` was applied (65,536 since).
   - **The four bi1 hamlets** answer SQL, read `paused` true, and keep their worlds: about 1.3 million ticks, with 15, 10, 7 and 11 people alive.
   - `spacetime list` works.

**Free space** on the host went from 207 GB before the removal (58 GB at the stop; other work freed the rest meanwhile) to **483 GB** after.

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

- **Names of 64 characters or more are refused** before anything is published: `trials.py run` (`MAX_DB_NAME` 63) and `verify.py launch`.
  - `databases()` raises when `spacetime list` fails, instead of returning an empty list. `clean` and `down` then fall back to the records.
  - `verify.py cleanup` treats a failed listing as "other databases may be live" and leaves the server up.
  - `verify-core/scripts/speech.py` looks the identity up by name.
- **`living/tools/reclaim_disk.sh` refuses.**
  - It refuses unless run with `--owner-approved`.
  - It refuses whenever the server it targets holds a kept reference world (`aske-coast*`, `stage*`), or its listing fails, so the reference worlds cannot be ruled out.

## Tested (2026-11-12, after the battle quiet window)

- **Records.** A fake batch (`trtest1`, wolves, 2 minutes, `--keep-db`) recorded `database_identity` and `replica` 6001417 in `state.json` and `summary.json`, and logged them. `trials.py dbs --batch trtest1` printed them.
- **`clean` from the records.** It deleted the kept database: the world was paused first, then deleted (SQL 404), and the Neo4j minds were removed.
- **The 68-character name.** A fake run under that name was published and kept. `spacetime list` failed as above while it existed. `clean` deleted it from the records (SQL 404), and the listing worked again.
  - Now `trials.py run` refuses the same name before publishing: "database names over 63 characters break the server's listing: … (68)".
- **`reclaim` (dry run).**
  - **Classified:** 1,820 directories. It found 12 live databases by their module logs: the four bi1 hamlets, fs1n's running database, and seven verify worlds of other sessions.
  - **Totals:**

    | Class | Directories | Size |
    |---|---:|---:|
    | live | 12 | 4.3 GB |
    | paid | 180 | 25.6 GB |
    | no-model | 272 | 51.2 GB |
    | fake | 159 | 28.5 GB |
    | verify | 1,195 | 148.5 GB |

    These are larger than the read-only tally above: more of the machine's checkouts were scanned, and more runs have happened since.
  - **Nothing removed.**
- **`reclaim_disk.sh`** without the flag printed its refusal and exited 1, before any docker call. The reference-world check was not run: it would read the `sao-living` server, which this work must not touch.
- **Archived run records** (the checkout-only paid batches): r2b, r2c, r2d, r2e, ar1, ar2, st1, st2, es1, bi1 and gl1, as `tar` + `zstd` in `~/slop-evidence/trial-records-20261112/`.
  - Each archive has a per-file sha256 manifest (`<batch>.files.sha256`) and its own sha256.
  - A test decompress listed the same file count as the source for all 11.
  - They total 93 MB, from 1.5 GB of records.
- **Not run:** `speech.py`'s metrics path (the change is a lookup by name; the verify-core speech scene was not driven). The full compression measurement of the paid commitlogs also waits for the owner's decision on the plan.
