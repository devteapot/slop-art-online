# Repaired batch 020: filesystem failure before a usable research sample

The repaired four-world research batch stopped after approximately one simulation minute because the shared filesystem filled. It did not complete the planned twelve-minute duration and does not establish invention, independent practice, transfer, rereading or sustained service. Three actors submitted paid built-in forecasts; two retrieved their report. All sixteen actors were healthy in the subsequently recovered paused-authority snapshots, and all four exact snapshots pass material, food, research, physical-copy, engine and scope audits.

This is a separate failed attempt under immutable `research-m6-3`, retained in [020-research-repaired](../output/batches/020-research-repaired). The [preceding batch report](SOCIETY_BATCH_020.md) remains unchanged. The four seeds, Luna-medium model configuration, fifteen-second post-completion cadence and absence of a call cap were preserved. The new implementation added personal record rereading, a bounded composite-index observer query and upper-bounded host exports. An [isolated authority regression](OBSERVER_TAIL_REGRESSION.md) had passed the 180-event observer tail and participant isolation contract before this launch. That small regression did not establish durable storage capacity under continuous writes.

## Failure and recovered evidence

All four pilots became ready and their initial exports were fresh. At the 91.9-second monitoring read, every last export was approximately sixty simulation seconds and thirty-one wall seconds old. The monitor itself then failed with `ENOSPC` while appending its output. The coordinator likewise could not replace `batch.json`; pilot files still claimed `running` because final status writes failed. Those stale phase fields are not evidence of ongoing operation or completion.

The operator terminated the affected work, freed space by removing expendable build caches, and recovered each paused authority separately. No source, retained experiment evidence or database was deleted as part of that cache cleanup. Each variant retains its original pilot as `pilot-before-disk-recovery.json`, an explicitly failed current pilot, `disk-failure-recovery.json`, and a separately named `recovered-paused-snapshot.json`. The recovery record says the filesystem failure stopped durable authority and prevented supervisor final status writes. No measured completion duration was reconstructed or invented.

| Variant | Recovered simulation seconds | Updates | Events | Retained journals / HTTP 200 | Reported tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Invention | 60.992 | 1,043 | 3,905 | 11 / 9 | 188,708 |
| Transfer-repeat | 60.657 | 1,006 | 4,678 | 11 / 8 | 201,027 |
| Cooling | 60.772 | 1,019 | 4,324 | 10 / 8 | 193,351 |
| Loss-risk | 60.645 | 1,009 | 6,616 | 11 / 10 | 228,756 |

The 43 retained journals contain 35 HTTP 200 responses and 811,842 reported tokens. Five journals have recorded processing errors: three invalid proposals and two cancellations. No retained external process log records a missing-grant/subscription failure or receipt timeout. Eight external process entries remain `started` in the saved pilot records; their status was not guessed after storage failure. Retained counts may omit activity whose writes failed, and an HTTP 200 reply does not imply an accepted participant operation.

The original `MONITOR.jsonl` is exactly 4,096 bytes and ends with a partial eighth line. It remains unchanged. Its seven complete JSON lines and failed append are usable as partial monitoring evidence; the damaged line is not silently repaired into an observation.

## Actual research and resource use

In invention, Ari submitted forecast event 1276 at 32.331 seconds, completed in 1504 at 35.383 seconds, and retrieved in 1518 at 35.444 seconds. The supplied stock 8, inflow 4/min, demand 5/min and ten-second horizon yielded the instrument's integer projected stock 8, with no shortfall.

Loss-risk Ari submitted the same conditional input in event 1289 at 25.502 seconds, completed in 1748 at 28.522 seconds, and retrieved in 3345 at 39.055 seconds. Transfer-repeat Cato submitted stock 3, inflow 15/min, demand 16/min and ten seconds in event 719 at 17.013 seconds, completed in 867 at 20.027 seconds, and did not retrieve the report before the recovered endpoint. Its integer projected stock is 3, with no shortfall.

These computations apply the built-in conditional arithmetic to model-supplied inputs; they are not authored solutions to the nonlinear, finite-buffer, multi-interval questions. Each completed job consumed three paid quanta: six electricity, three water and three condition points. Invention, transfer and loss-risk each reconcile electricity as 220 initial + 66 produced = 232 retained + 48 body consumption + six computation. Cooling reconciles 220 + 60 = 232 + 48 and has no accepted computation. Water remains conserved, including cooling's one station water plus 24 carried water. Parts remain unchanged.

All four food accounts reconcile as 14 initial + six produced = 18 retained + two eaten. Every actor ends at health 100. There is no accepted reread, personally assessed research bootstrap, prototype, practice, ordinary technique run, code transfer or erasure. Consequently there is no authored source to inspect for novelty or evaluate on holdouts. Cooling did not activate a paid cooling-blocked job, and the loss-risk disturbance times were not reached.

## Audit provenance and next-run guard

The standard completed-trial reporter cannot accept these failed pilots. Separately named `INTERRUPTED_RESEARCH_RESULT.json` files record direct audits with explicit filesystem-failure labels and links to their recovered input: [invention](../output/batches/020-research-repaired/invention/INTERRUPTED_RESEARCH_RESULT.json), [transfer-repeat](../output/batches/020-research-repaired/transfer-repeat/INTERRUPTED_RESEARCH_RESULT.json), [cooling](../output/batches/020-research-repaired/cooling/INTERRUPTED_RESEARCH_RESULT.json), and [loss-risk](../output/batches/020-research-repaired/loss-risk/INTERRUPTED_RESEARCH_RESULT.json).

Recovered source SHA-256 values are:

- Invention: `0dff77d7e13925027bf114998d4f988afbf1f4a0f278df3dbfb201bd4164fa41`.
- Transfer-repeat: `80e98e36e1b88d5aef09e436d71872db34d2eb75c691516b39623ab0c8ae26f5`.
- Cooling: `75142d4916edced35d23e4771914234120726f417fb135c146b07ae4455d2bdc`.
- Loss-risk: `86f32878b298de45595fd6834a3677cfca84848d5905bf6e3a7bf235910b4316`.

After this failure, the coordinator gained a [disk reserve guard](EXPERIMENT_SCALING.md). It defaults to 3 GiB on the output filesystem, refuses launch or gate release at that threshold, checks running space every second and stops supervisors through their existing graceful cleanup. The batch report retains timestamped free-byte measurements and a specific failure reason. Five new mocked-space tests cover preflight refusal, initialization and runtime peer cleanup, override and cadence; all 23 coordinator tests pass. This host guard was not present in the failed frozen run and does not alter any world rule, delete evidence or fix storage write amplification. Stage 6 behavioral acceptance still requires a fresh completed sample.
