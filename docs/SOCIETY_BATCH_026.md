# Batch 026: final evidence retained, external continuity and completion failed

The [026 campaign](../configs/experiments/campaign/026-faction-reality-cached.json) ran 36 Luna-medium controllers for a requested twelve minutes: eighteen built-in and eighteen external, with serial behavior, communication, and learning responsibilities. The original pilot reached 720.055 active wall seconds, then exceeded the batch supervisor's additional sixty-second cleanup/export allowance and received SIGTERM. Both batch and pilot remain **failed**. A later successful cleanup is separate evidence, not a completed model trial.

Unlike batch 025, this run retained an original final export: `sim-bevy-1788685221259`, 717.486 simulation seconds, tick 286, 180 updates, and 58,889 contiguous run-scoped events. Its SHA-256 is `d1df0b080f0b7aa72e15399799460fd7e21a50b5e87cc8a8b6e3076d605e393c`. The [full failed-original report](../output/society-lab/reality-m7-build-verification/026-gated-trial-preparation/analysis/026-failed-original/REPORT.md) links frozen inputs, copied audit wrappers, exact request/event reconstruction, and separate termination evidence. No original status or evidence was rewritten to claim completion.

## Service and model outcomes

The external supervisor recorded 476 attempts: 92 completed, 377 failed, and seven interrupted. Of these, 365 failed before a model journal existed with `no participant grant or subscription not ready`; seven interrupted attempts also lack journals. The first setup failure began 145.968 wall seconds after pilot start. The error describes an empty local participant-state cache and does not itself prove an authority grant was revoked.

| Retained evidence | Built-in | External |
| --- | ---: | ---: |
| Model journals / HTTP 200 | 368 / 368 | 104 / 104 |
| Native error-free journals | 318 | 92 |
| Native invalid proposals | 43 | 12 |
| Valid no-operation proposals | 31 | 32 |
| Authority-accepted modeled commands | 277 | 56 |
| Authority-rejected modeled commands | 11 | 4 |
| Reported tokens | 22,251,061 | 6,523,246 |

All retained journals requested and reported serving `gpt-5.6-luna`; all reported cached-prompt counts are zero. Four canceled built-in streams lack usage, so 28,774,307 reported tokens is not a complete billing reconstruction. HTTP success, schema validity, command acceptance, and subsequent execution are distinct measurements.

The [call reconstruction](../output/society-lab/reality-m7-build-verification/026-gated-trial-preparation/analysis/026-failed-original/CALL_RECONSTRUCTION.json) resolves four generic-helper “unknown” external receipts to expired-speech rejections using exact request IDs. A built-in receipt timeout resolves to accepted command 54859. Two built-in no-access proposals have no matching authority event. Missing journals are unavailable opportunities, not deliberate no-operations.

After four simulation minutes, built-in access remained substantially active: 216 journals contain fresh contexts from 240.000 seconds through before the final paused time. External actors retained only six journals after that point, five native error-free. There are also 28 built-in journals using the final paused context, including all four cancellations and both journaled identity-no-access errors; provider response timestamps place these errors during cleanup. The host log has sixteen additional no-grant/subscription lines but no actor or timestamps, preventing reliable active/cleanup attribution or an exact total built-in attempt denominator. Persistent built-in access versus repeated external startup failure points toward subscription readiness as the next diagnostic target without isolating the cause.

## Editor choices and physical outcomes

The four initial territorial editors all used the external route. Their retained contexts expose their local grant and law interfaces, with no universal grant. None submitted a law candidate or experiment, acquired a personal law program, or installed a law. The final law registry has no overlays or pending edits. The lack of later law activity remains confounded by failed external access.

The [editor reconstruction](../output/society-lab/reality-m7-build-verification/026-gated-trial-preparation/analysis/026-failed-original/EDITOR_CAUSAL_RECONSTRUCTION.json) records every retained proposal and exact authority link:

- **Aster-Prime (2):** Five journals across eighteen attempts. Command 30769 at 148.569 simulation seconds replaces its policy with eating, rest, and a once-only observation/wait sequence, removing all gathering. Policy event 30772 links this choice to execution. It subsequently completes four eats, no gathers, and exhausts food at 300.872 seconds. Starvation kills it at 446.105 seconds. This is a concrete harmful mechanism under observed conditions; later unavailable calls cannot establish what it would have chosen with continued access.
- **Orin-Prime (6):** Five journals across thirty attempts. It deliberately retains its initial reserve policy; a later replacement response fails JSON parsing and never commits. Two speeches and one reflection are accepted. It gathers and eats sixteen units each and survives at health 100.
- **Xeno-Prime (10):** Six journals across thirty-one attempts. It deliberately retains its reserve policy twice. Its first speech expires; a later speech and two reflections are accepted. It survives at health 100 after fourteen gathers and sixteen eats.
- **River-Prime (14):** Six journals across thirty attempts. Command 38365 produces patch event 38366 at 227.493 seconds, adding observation before gathering at `root/3`. Descendant execution includes fifteen observations, nine gathers, eleven eats, and one failed skill result. It survives at health 100; the evidence does not establish that the patch eliminated stale observations or independently caused survival.

Final population is 36, with 29 alive and seven starvation deaths: Soren at 257.812 seconds, Mei at 327.618, Veda at 358.934, Aster-Prime at 446.105, Tern at 618.178, Mara at 688.236, and Dai at 713.307. Leto and Tavi survive at health four, Kiri at 84, and all other survivors at 100. Survival is 17/18 built-in and 12/18 external, confounded by bodies, seeded habits, physical facilities, and access. It is not a controlled model-quality comparison.

Eight paid built-in conditional forecasts complete and are retrieved; actors 13, 3, 7, and 5 personally interpret their retrieved results. No authored numeric or law program is submitted. All seven failed-original snapshot audits execute successfully, with no material, knowledge-copy, research, scope, or law invariant violations:

| Account | Balance |
| --- | --- |
| Food | 90 initial + 268 produced = 132 final + 226 eaten |
| Electricity | 1,710 initial + 5,368 generated = 1,882 final + 5,148 body use + 48 compute |
| Water | 396 initial = 372 final + 24 cooling |
| Parts | 229 initial = 229 final |

These balances establish consistency of the retained final export, not completed-run acceptance, continuous access, or sustained survival.

## Resources, termination, and separate cleanup

The original memory window has 833 samples: observed peak RSS 10,806,943,744 bytes, HWM 10,918,158,336, swap zero, and minimum host available memory 5,990,703,104 bytes. Cgroup OOM counters do not increase. The monitor's later failure is a missing-process capture error after forced service shutdown, not evidence that an OOM triggered the trial failure.

For exact replica `16000001`, the approximately 818.178-second setup/runtime/cleanup WAL window records 896,320,968 bytes logical growth, 987,844,608 bytes net allocated growth, and 996,233,216 bytes sampled positive allocated growth. Minimum observed free space is 74,287,341,568 bytes. These are whole-window figures, not only the active twelve minutes.

The [termination timeline](../output/society-lab/reality-m7-build-verification/026-gated-trial-preparation/analysis/026-failed-original/TERMINATION_TIMELINE.json) ties the batch supervision deadline to SIGTERM: batch failure precedes the pilot's recorded signal by 0.000079 seconds, while source cleanup calls `job.terminate()`. Final writing finishes 81.797 seconds after the active boundary. The later service stop requires SIGKILL after SIGTERM's ten-second allowance; it was not a graceful shutdown. Empty batch cleanup errors and a null pilot pause error do not establish that every database observer grant was removed.

A first same-volume recovery verifies the model clock paused and all 36 participant grants gone but finds one remaining actor-0 observer grant, so that recovery remains failed. The separately authorized [observer cleanup](../output/society-lab/reality-m7-build-verification/026-observer-grant-cleanup-preparation/RECOVERY_RESULT.json) validates and revokes only that observer identity, then [checks all 39 databases](../output/society-lab/reality-m7-build-verification/026-observer-grant-cleanup-preparation/ALL39_VERIFICATION.json): every clock is paused or absent and every grant table empty. No model retry or full-world export occurs. Fresh PID 1282286 passes its separate 27-sample memory window, with peak RSS 3,710,738,432 bytes and unchanged zero OOM counters.

The all-database cleanup pass establishes the later quiescent state. It does not change the original failed status or fill gaps in model access. Retained logs do not identify the leftover observer grant's creation or a browser visit; its origin remains unassigned by this evidence.
