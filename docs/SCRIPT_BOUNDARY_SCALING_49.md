# Script invocation boundary (49)

This investigation follows [compressed audit digests (48)](AUDIT_DIGEST_SCALING_48.md).
That change lowers archive CPU cost, but normal combat misses 48.3% of clock
slots and all sustained world/client requirements remain open.

## Paused checkpoint — 2026-09-08

Work is paused at the user’s request for a commit to `main`. The candidate is
implemented and its 360 focused tests pass, but candidate actual-authority paired,
profile and normal-release measurements have **not run**. Iteration 48 remains
the latest measured normal release; no performance gate is accepted.

## Constraint and measurement

The retained iteration-48 profile contains a 78.85 ms physical execution burst,
including 67.96 ms in actor processing and 10.72 ms in lifecycle observations.
Two other actor bursts take roughly 40 ms with only 600–687 emitted events, so
large death-observation batches are not the only latency source. Every scripted
skill performs JSON budget checks, conversion, cached-definition lookup, Rhai
execution and output validation. The unlayered scoped call also repeats its
input byte check when forwarding to the ordinary call.

The new opt-in profile separates those six phases. It samples the first and
every 17th invocation of each phase within each kernel call and retains complete
eligible counts. Nested law execution overlaps its enclosing skill invocation;
phases cannot be added as disjoint work, and systematic sample means cannot be
extrapolated to complete population cost. Normal builds erase diagnostic clocks.
No timer value enters gameplay or persisted state.

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/) and
[views](https://spacetimedb.com/docs/functions/views/) before investigation.
The authority still pins Rust SDK 2.1.0, control CLI 2.7.1 and service 2.10.0
(image `b22dfaac6d46`). Rhai remains pinned to 1.26.0 and the lockfile selects
serde_json 1.0.149. The retained candidate changes no database schema, index, subscription or
permission boundary.

The current [Serde writer](https://docs.rs/serde_json/latest/serde_json/fn.to_writer.html)
and [vector](https://docs.rs/serde_json/latest/serde_json/fn.to_vec.html) APIs are
also checked. The versioned 1.0.149 pages could not be opened through the browser;
local registry source confirms that version's `to_vec` allocates a vector and
calls the same compact writer. The existing budget checks remain unchanged; the before-candidate profile
selected cached-definition comparison as the next cost to investigate.

## Storage reserve

Before any measured run, duplicate-extent sharing verifies 267 completed runtime
and release artifact files. The active development executable is excluded using
both process mappings and executable identity. Complete SHA-256 and selected
metadata remain unchanged; free disk rises from 8,867,741,696 to 9,070,387,200 bytes.
A second 718-file pass registers 193 earlier files without repeated deduplication,
again preserving bytes/metadata, with free disk rising from 9,036,025,856 to
9,065,512,960 bytes. An attempted compiler-cache cleanup finds no eligible
unmapped single-link files and removes nothing.

A bounded pass over 12 already-stopped iteration-47/48 benchmark volumes then
shares equal extents in 73 files of at least 1 MiB. Current container state is
checked before and after; every original successful stop time remains unchanged.
The pass acquires each replica's exclusive database file lock, excludes mapped
or writable files, and verifies every complete SHA-256 plus size, modification
time, mode and ownership afterward. It neither starts services nor deletes,
rewrites or truncates their data. Free disk rises from 9,036,443,648 to
10,458,664,960 bytes. Retained logical WAL sizes and original failed outcomes
remain intact. No allocation maintenance overlaps measured authority work.
The existing 8 GiB disk and 3 GiB available-memory guards remain unchanged.


## Retained candidate and completed validation

The before-candidate actual-authority profile runs 200 colocated characters with
100 HP, 200 reference controllers, one component SDK observer, no open inspector,
no human input and no external inference for ten simulated seconds at the 60 Hz
requested clock. Both services stop successfully. In 305 deadline kernel calls,
sampled compiled lookup averages 24.79 microseconds (p95 51.40), versus 1.46
microseconds for input budget checks. These samples exclude the general bound-law
compiled lookup and do not represent all script lookups. This is a profile of
the previous implementation with new instrumentation, not candidate performance.

`Definition` now wraps shared immutable data with transparent serialization.
Clones share an `Arc`; edits detach through `Arc::make_mut`. Equality first checks
shared identity, then exact field content. Cache hits adopt current definition,
law and dependency handles only after the existing complete content checks pass.
A freshly parsed equivalent registry therefore pays the content comparison before
subsequent identity reuse. Changed source, including unchanged IDs/revisions,
continues to invalidate compiled entries. Cache bounds, JSON shape, budget checks,
privacy and authoritative behavior remain unchanged. No whole-world loader or
additional persisted state is introduced. Official Rust [Arc documentation](https://doc.rust-lang.org/std/sync/struct.Arc.html)
was consulted for identity and copy-on-write semantics.

Completed checks: 258 simulation tests pass (one ignored), 63 authority tests pass
and 39 storage tests pass. New tests cover exact serialized shape, unknown-field
rejection, independent clone editing, equal restored registry reuse in all three
cache paths and dependency changes producing new behavior. Normal and diagnostic
WASM builds succeed. An initial authority build failed because the system temporary
directory hit its quota; its log remains preserved. Retrying with a dedicated
temporary build directory in shared memory succeeds. After tests finish, only that
completed temporary compiler directory is removed; test logs and binary digests
remain in the local validation evidence.

The local evidence root is `output/realtime/scale-49/`: `validation/` holds the
build/test logs and storage-maintenance records; `combat-script-profile-before/`
holds the before-candidate run. Frozen `implementation/`,
`profile-implementation/` and `profile-before-implementation/` retain the builds.
Normal candidate WASM SHA-256 is
`b08b54fefda14b72df92136634229ecd77b1087517fa024bc415f41847b64b11`.
Evidence, retained database volumes and temporary drivers remain local under the
repository’s existing ignore rules; they are not part of the source commit.

A final completed reserve pass shares extents in 53 files across nine previously
stopped benchmark containers. Every file’s full digest and selected metadata stay
unchanged, and post-pass inspection verifies identical container IDs and successful
stop timestamps. Free disk rises from 9,284,718,592 to 10,206,519,296 bytes. No
benchmark overlaps this maintenance, and no retained database is deleted.

## Resume point

Resume only when requested. First validate the prepared, unexecuted comparison
in `.local/tmp/scale49/compare_scripts.py` (prepared by `prepare_comparison.py`
in the same directory). It compares iteration-48 normal authority with the
iteration-49 candidate using identical complete worlds and ordered audits, then
checks staged script/law changes, privacy and upgrade behavior. Its new assertions
have only been syntax checked. Complete that comparison, candidate profiling and
a normal release run before making a performance claim. Verify disk reserve and
selected service/database/output paths before launching. Preserve original failed
outcomes and all prior frozen artifacts. The 216-character/30-minute and
2,000-character/eight-hour gates, sustainable populations, full model workload,
client pacing and autonomous outcomes remain open.
