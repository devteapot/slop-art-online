# Batch 018: interrupted capacity diagnostic and the 36-participant repair

Neither batch 018 attempt completed its planned twelve-minute society sample. The first failed before world creation because the compact 36-person scenario exceeded the existing input bound. The second created the world but participant reads and authority updates became too slow to sustain reasoning. Its failed status is retained. Later isolated diagnostics exercised the same 36-person seed without model calls; the final diagnostic returned all 108 concurrent reads successfully and maintained 0.988 simulation seconds per wall second over a short sample. A fresh paid run is still needed to establish sustained social behavior.

## The two preserved attempts

`output/society-lab/batches/018-faction-world` used frozen `faction-world-m5-2`. Its compact scenario was 116,911 bytes, above the legacy 100,000-byte scenario cap. The host reported `scenario too large` from `sim_create_participant`. No world became ready, no actors enrolled, and no model journals or external calls were recorded. The subsequent bound is two MiB and remains explicit; this was a setup defect, not an agent decision.

`output/society-lab/batches/018-faction-world-retry` used frozen `faction-world-m5-3` with that bound corrected. Run `sim-bevy-1788655101928` enrolled all 36 actors. Its host snapshot stalled at 16.882 simulation seconds and two updates while calls repeatedly timed out. Read subscriptions were deserializing the complete world to produce each participant view, including retained observation leases. One early compact world was approximately 2.90 MB, with 2.36 MB of participant state, including 1.96 MB of leases. This exposed a growing cost in authority serialization and observation publication.

The supervisor was interrupted rather than allowed to spend the remainder of the model budget on failed reads. Its first final pause timed out after 30 seconds, so `pilot.json` correctly remained `failed`. A later scoped cleanup confirmed that the owned host was absent, paused only this world, and captured the same authority state before and after the audit read. No other world or shared server was restarted. The [cleanup confirmation](../output/society-lab/batches/018-faction-world-retry/faction-world/cleanup-confirmation.json) records that recovery separately from the failed pilot.

The authoritative final state is **28.068 simulation seconds, five updates, 2,894 audit events, and all 36 actors at health 100**. It is later than the stale host export. Event 2869, `clock_recovery_required`, records an elapsed interval of 68,644 ms at update five; the run cannot be interpreted as a normal twelve-minute survival experiment.

There were 83 external process attempts: 72 failed and eleven were interrupted. None produced an `external.json` model result, so those attempts are not counted as successful inference calls. Nineteen built-in completed journals contain HTTP 200 replies and 289,472 reported tokens; twelve subsequently report `receipt timeout; outcome unknown, retry same request ID`, and seven have no processing error. HTTP success does not establish that a proposed command was accepted. These counts describe recorded evidence, not unobserved remote work.

The ordinary completed-run reporter rejects this failed pilot. A separate [cleanup infrastructure audit](../output/society-lab/batches/018-faction-world-retry/faction-world/CLEANUP_INFRASTRUCTURE_AUDIT.json) applies the material-accounting analyzer to the stable final authority snapshot and explicitly labels its scope as a failed diagnostic. Its accounts balance without violations:

| Account | Final identity |
| --- | --- |
| Electricity | 1,710 initial + 297 produced = 1,809 retained + 198 body use + 0 compute use |
| Water | 396 initial = 396 retained + 0 cooling use |
| Parts | 229 initial = 229 retained + 0 repair use |

The parts account includes 121 embodied in endowed modules and 108 carried. No compute job, report retrieval, construction, infrastructure grant or support charge occurred. The absent Hugging Face terminal therefore remained a possibility in the seed, not an observed construction outcome. No conclusions about council action, alliances, religion, provisioning or forecast usefulness follow from this truncated attempt.

## Changes measured after the failed sample

The server now publishes a private participant cache keyed by run and actor, with the grant-authenticated view selecting only that participant's cached status. The cache includes request-bound observation results, identity, epoch, revisions, cursors and receipts. Reading a participant status no longer reconstructs the entire world for each subscription. A new read also avoids cloning the previous read output before discarding it.

Retained evidence observations and experience lists were then changed to immutable shared storage. Finally, observations retain their JSON in immutable `RawValue` storage, and participant status is serialized directly from borrowed fields instead of building another generic JSON tree. These changes preserve the authority state and observation contract while reducing repeated parsing, cloning and publication work. They were made between diagnostic worlds; neither failed batch was repaired in place.

The first cache diagnostic, v2, still returned only 89 of 108 reads: 36, 31 and 22 over three rounds. Its original probe incorrectly required the intentionally omitted `status.time_ms` field, causing additional false validation flags. The separate [corrected read summary](../output/society-lab/scale-cache-diagnostic-v2/participant-scale-read-summary.json) preserves the original results and distinguishes nineteen genuine receipt timeouts from that probe bug. The corrected probe checks actor identity, health, control epoch and `status.tick >= observation.tick`.

The reusable [diagnostic runner](../scripts/run_scale_diagnostic.py) starts a fresh 36-person world with an explicit release WASM, manual built-in harnesses and no external model workers. The [participant probe](../server/bridge/examples/participant_scale_probe.rs) opens all 36 personal sessions, performs three concurrent observation rounds separated by fifteen seconds, and disconnects every session. It submits no physical actions or model calls. Starting behavior trees and the physical clock still run. The wrapper captures stable paused evidence, stops its host, and revokes only its own 36 grants.

| Diagnostic | Round reads returned | Round median latency (ms) | Round maximum latency (ms) | Measured updates / wall second | Simulation / wall ratio |
| --- | --- | --- | --- | ---: | ---: |
| v2: private status cache | 36 / 31 / 22 | 4,070 / 7,584 / 8,392 | 7,428 / 10,022 / 10,016 | Not sampled by wrapper | Not sampled by wrapper |
| v3: shared immutable evidence | 36 / 36 / 32 | 2,470 / 6,627 / 5,251 | 3,932 / 6,823 / 10,030 | 1.830 | 0.778 |
| v4: retained raw JSON and direct status serialization | 36 / 36 / 36 | 1,288 / 1,033 / 1,762 | 1,871 / 2,132 / 3,614 | 5.065 | 0.988 |

V3 and v4 have zero identity/epoch/freshness validation failures among returned reads. V3 has four real receipt timeouts; v4 has none. V2 began after about eleven simulation seconds, whereas the wrapper started v3 and v4 immediately after enabling the clock. V2 comparisons therefore include different initial lease and event loads. V3 and v4 use the same scenario and controller hashes and the same wrapper/probe procedure.

V3 sampled 95 updates and 40.397 simulation seconds over 51.904 wall seconds. V4 sampled 193 updates and 37.664 simulation seconds over 38.106 wall seconds. These intervals include the final pause acknowledgement. V4's configured clock interval is 50 ms, but its measured update rate is approximately five Hz, not twenty Hz. Near-real-time elapsed simulation does not imply that every individual action opportunity has a 50 ms cadence. The result supports usable reads during this short burst test; it does not establish long-run capacity with 36 model controllers, growing records, construction and ongoing reasoning.

Both wrapper runs ended with a paused clock, stopped host, all 36 owned grants revoked, no model journals and no cleanup errors. Their complete artifact hashes and timing boundaries are in [v3 diagnostic.json](../output/society-lab/scale-cache-diagnostic-v3/diagnostic.json) and [v4 diagnostic.json](../output/society-lab/scale-cache-diagnostic-v4/diagnostic.json). The native profiling and functional tests are supporting implementation checks; the table above reports the actual server measurements.

## Evidence hashes

| Evidence | SHA-256 |
| --- | --- |
| Failed retry, stable final authority | `6fe7428d9aabcf3154ddf0f956b7ca7868d65e258c789705ffceafe11332f91d` |
| v3, paused before grant revocation | `9e32478ad2b84b1758ddddf9dd2fbafe3f8d3b098df3c435e224be98e05a2924` |
| v3, final after grant revocation | `69a50a45d6cc4ed57517017ff6cee25f2fc892dca4a3658c49dbebf2aa6ebfd6` |
| v4, paused before grant revocation | `65a81773596ec094f1ca411140c5e7aced47d6fb593d9e0b25cd496a151b3027` |
| v4, final after grant revocation | `3f84fa28c418565f8cb5b195579849d9ddc4eb36d81a7f663232c2a11df44ec2` |

The failed attempt, its cleanup and each subsequent diagnostic remain in distinct directories. A new frozen implementation and a fresh output directory are required for the paid full-duration integration sample; none of these results should be relabeled as its completion.
