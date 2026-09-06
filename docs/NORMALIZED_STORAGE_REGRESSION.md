# Normalized storage authority regression

The real-authority regression passed its API, privacy, retained-evidence and WAL-growth checks. It measured **52,537,635 bytes (50.10 MiB) of WAL file growth** over 92.027 wall seconds, while four participant connections and an observer connection remained subscribed. It did **not** demonstrate a 20 Hz update cadence: the 50 ms configured clock delivered 119 authoritative updates, or **1.293 updates/second**. Simulation time nevertheless advanced 91.406 seconds, 99.33% of elapsed wall time.

This was one four-person, explicit no-inference fixture, not a research trial or a four-world endurance test. Longer-trial reliability remains to be measured.

## Authority and retained evidence

The fresh normalized database was `sim-bevy-db-1788662158539-1930878`, served at `http://127.0.0.1:3101`. The probe created its own run, `sim-storage-regression-1788662277692033689`; it did not advance the diagnostic's original run. The exclusive replica mapping identifies replica `8000003`.

Evidence directory:

`output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/`

| Evidence | Content |
| --- | --- |
| [storage-regression.json](../output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/storage-regression.json) | Owner SQL samples, actual WAL file samples, cadence, completion and cleanup |
| [participant-storage-result.json](../output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/participant-storage-result.json) | Every read's checks, last four captured reads per person, final views and subscription timing |
| [snapshot.json](../output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/snapshot.json) | Paused, self-contained World and contiguous audit events |
| [mutable-row-footprint.json](../output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/mutable-row-footprint.json) | Read-only post-cleanup compact-row measurements and separate 20 Hz payload calculation |
| [analysis.json](../output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/analysis.json) | Derived latency and extrapolation figures |
| [implementation-hashes.json](../output/society-lab/research-m6-4-authority-check-retry/storage-regression/retry-count-alias/implementation-hashes.json) | Local implementation artifact hashes captured after the run |
| [replica.json](../output/society-lab/research-m6-4-authority-check-retry/replica.json) | Exclusive database-to-replica mapping |

The snapshot contains events **1–4,906**, with `next_event = 4907`. The paused owner state was unchanged across capture. Its SHA-256 is `fff6853753aab38d93c6d375a5f986259404891ca57e2213d006af0a95ff1ed7`.

The implementation hash file was captured after subsequent native rebuilding; its native executable hash is a post-run build identifier, not a retained hash of the executable used during measurement. The probe source is retained, and the authority's exact published module is separately archived with the diagnostic run.

The first attempt stopped before creating a run because its table-existence query omitted the alias required for `COUNT(*)`. That failure remains in the parent `storage-regression/storage-regression.json`. The probe was corrected to `COUNT(*) AS count` and retried in a fresh directory. This was a probe SQL error; it produced no participant sessions or timed measurement.

## Workload and exactness checks

The four people used fixed observe/eat/rest/gather policies. They started with ordinary nutrient support and separate private notes used to detect disclosure. There were **zero model calls**. Each person retained the same `ParticipantService` and underlying connection throughout; reads did not reconnect. The workload kept four participant-status subscriptions, four personal client-view subscriptions and one observer client-view subscription active, while the owner repeatedly selected the full `sim_run.state` compatibility view.

| Check | Measured result |
| --- | --- |
| Atomic reads | 320 across 80 rounds; zero read errors or validation failures |
| Retained traces | All four filled 256 entries and rotated; final oldest cursor 353 |
| Retained read leases | Four per person; all 16 final bodies, cursors and expiry times matched the captured reads |
| Read identity | Correct run, actor, context player, control epoch, ordered/bounded cursor page and matching accepted receipt for every read |
| Atomic evidence | Exact retained JSON value, `atomic = true`, matching observed cursor and 330,000 ms lease duration |
| Kernel compatibility | Self-contained World deserialized and round-tripped to the same JSON value; each reconstructed `participant_status_json` matched its subscribed status value |
| Personal privacy | Other people's private-note markers, knowledge, memories, beliefs, health and private research were absent from personal views |
| Observer projection | Full four-person rendering view remained available; final simulation time matched the paused World |
| Raw owner view | `SELECT state FROM sim_run` returned no rows for every participant and the observer |
| Private tables | Owner first established table existence; direct nonowner SELECTs on `sim_run_store`, `sim_world_blob` and `sim_participant_cache` were denied with HTTP 400 |
| Runtime/capture | No model, script-error, failed-script-tick or clock-recovery events; all four people finished at health 100 |

“Exact” above means equality of the complete parsed JSON values, including embedded source/text strings, rather than JSON key-order or insignificant-whitespace identity. Observer privilege allowed the rendering projection; it did not expose the raw owner World or private storage tables.

## Observed cadence and latency

| Measure | Result |
| --- | --- |
| Requested interval and measurement | Scheduled 50 ms; requested 90 seconds |
| Actual elapsed time | 91,406 simulation ms / 92,027 wall ms |
| Authoritative updates | 119; 1.293 per wall second |
| Atomic read latency | Median 731 ms; p95 1,216 ms; maximum 1,245 ms |
| Concurrent owner SQL | 81 samples; median 1,167.32 ms; p95 1,244.34 ms; maximum 1,249.82 ms |
| Subscription inserts received | 204 for each personal client view; 442 for the observer, including setup/finalization |
| Atomic observation size | 35,071–123,041 bytes |
| Final self-contained owner state | 1,815,462 UTF-8 bytes |

Percentiles use the nearest-rank definition. The lower update frequency is a material limit of this measured subscription workload. Fewer full client subscriptions may permit faster updates, which can increase repeated mutable-row writes even if wall-time progression already appears correct. The test's `all_pass` field covers correctness and its configured storage bounds; it does not assert a 20 Hz service rate.

## Actual WAL growth, allocation and sparse files

Measurements came from the actual replica directory:

`/home/carlid/.local/share/containers/storage/volumes/sao-bevy_spacetimedb-home/_data/.local/share/spacetime/data/replicas/8000003/clog`

The directory was sampled throughout the subscribed workload. Other existing clocks were verified paused. Neither compact-row sizes nor reconstructed World sizes were substituted for WAL measurement.

| Quantity | Measured value |
| --- | --- |
| Total logical WAL-file sizes before → after | 14,383,427 → 66,921,062 bytes |
| Net logical growth | **52,537,635 bytes**, 50.10 MiB |
| Net allocated-block growth | **52,572,160 bytes**, 50.14 MiB |
| Logical growth per wall second | 570,893.71 bytes/s |
| Configured growth limit | 256 MiB; not reached |

The same `.stdb.log` inode grew from 10,189,123 to 62,726,758 logical bytes. The `.stdb.ofs` file stayed at 4,194,304 logical bytes while its allocated blocks grew from 4,096 to 12,288 bytes. There was no segment rotation during the measurement, so sampled positive growth equalled net growth.

Logical size, allocated disk blocks and bytes overwritten inside an already allocated segment are different quantities. The unchanged sparse offset-file length is not newly appended log data. These measurements establish file growth and allocation under active materialized views; they do not count every device write or infer how future segment preallocation will behave.

## Separate faster-clock payload calculation

After capture and grant cleanup, read-only owner SQL measured `sim_run_store.state` at **19,392 bytes** and each of the four `sim_participant_cache.body` strings at **864 bytes**. Their combined mutable JSON payload was **22,848 bytes**.

Grant revocation calls `change_control`, which clears retained read leases. These are explicitly **post-cleanup sizes**; live lease references are absent. They are not a complete upper bound for the active workload.

If every 50 ms pulse deletes and reinserts all five payloads at those measured sizes, counting both before and after images:

`22,848 × 2 × 20 = 913,920 bytes/second/world`

Across four worlds for twelve minutes each, that is **2,632,089,600 bytes, or 2.451 GiB**, for those mutable JSON payloads alone. Row keys/metadata, new immutable blobs, audit inserts, command-triggered saves and any growth in active payload size are additional. This deliberately separate calculation prevents the observed 1.293 Hz workload from being treated as proof of 20 Hz storage cost.

## Four-world, twelve-minute extrapolation

Four twelve-minute worlds comprise 2,880 world-seconds. Scaling the measured growth by `2,880 / 91.406 = 31.5078` gives:

| Inferred scenario | Result |
| --- | --- |
| Observed logical growth at the measured workload/cadence | 1.542 GiB |
| Observed allocation growth at the measured workload/cadence | 1.543 GiB |
| Twice the observed allocation extrapolation | 3.085 GiB |
| Separate 20 Hz mutable-payload calculation above | 2.451 GiB, before additional writes and active-size differences |

These are extrapolations, not a completed four-world test or a guaranteed ceiling. They assume four people per world and comparable read, trace and subscription activity. Research jobs, growing archives, different context sizes, faster updates and future segment allocation can change the result. The reported free space at the launch decision was approximately 17 GiB with a 3 GiB reserve, leaving about 14 GiB of usable budget. The longer-trial decision must account for the faster-clock calculation and these unmeasured costs, rather than relying only on observed WAL bytes/second.

The probe's own run was paused, its five grants were revoked after the contiguous capture, and its connections closed. Cleanup reported no errors. Other runs were left unchanged. The later mutable-row queries were read-only; the timed probe was not restarted.
