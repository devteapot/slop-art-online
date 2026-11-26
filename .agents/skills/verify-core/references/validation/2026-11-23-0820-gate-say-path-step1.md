# The scene gate, step 1: acting and fight groups, speak and told, the group cap (`gate-say-path`): the core surface

Follows [2026-11-23-0445-gate-say-path.md](2026-11-23-0445-gate-say-path.md). Validated on the Spark on branch `gate-say-path`: the series ran on `84f63b90d` and, from run `new02` on, its working tree with the shake-out fixes, committed as `198a3a245`; the post-fix runs ran on `198a3a245`. Server `slop-gatesay2-20261123` (private, `127.0.0.1:3622`, `clockworklabs/spacetime:v2.14.1`, CPUs 0-4,10-14). The gate ran under `taskset -c 0-4,10-14` with `LIVING_GATE_REDS_GIT=0` and `--no-main-check`. No paid model calls.

## What step 1 adds

- **speech:** verify-player `speak` and `told`, after `say`, `heard_first` and `audience` on the speech group's world.
- **acting** (`ACTS_PATHS`: the authority's `acts.rs` and `outcomes.rs`, the rules' `acts.rs` and `outcome.rs`): `act_gaps`, `act_replace`, `truthful_refusals`.
- **fight** (`COMBAT_PATHS`: the authority's `combat.rs` and `codes.rs`, the rules' `combat.rs`): `committed`, `dodge_told`, `health_seen`, `seize`; and `outcomes` after `skirmish` on the island world.
- **The cap.** `LIVING_GATE_GROUPS` caps how many world groups run at once. The default is 10; 0 runs all at once.

## Wall time and load (Spark; the 1-minute load sampled every 5 s)

| Run | Cases | First pass | Whole run | Load mean | p90 | max | Over 8 |
|---|---|---|---|---|---|---|---|
| baseline01 | main's 22 (10 groups) | 719 s | 920 s (combat retried) | 12.2 | 27.9 | 31.0 | 53% |
| full01-03 | all 37 (14 groups, uncapped) | 683, 725, 775 s | same | 14.3-16.0 | 41.5-41.9 | 65.0-70.1 | 37-47% |
| cap10-01, 02 | all 37, at most 10 groups | 802, 857 s | 955 (flee_wall retried), 857 s | 9.8 | 20.8-23.4 | 42.1-44.9 | 31-34% |

- **Load profile.** The load stays at 3-6 for the gate's first 4-5 minutes (genesis fuel and builds). When every group launches its world it peaks for about 2 minutes (baseline 27-31, all 14 groups 44-70), and it is under 8 again by about minute 10.
- **Wall time.** The new groups finish within the minds and generation groups' time, so uncapped the gate is no longer. The cap at 10 costs about 80-170 s and halves the spike above the baseline.
- **Host.** The host's own load before each run was 2-6.

## Shake-out (13 first runs per new scene)

Every new scene ran on fresh gate worlds of its group, in gate order: new01-08, full01-03 and cap10-01/02.

| Scene | First runs | Failed | Cause | Fix |
|---|---|---|---|---|
| say, heard_first, audience, speak, told | 13 each | 0 | | |
| pursue_last_seen, act_gaps, act_replace, committed, dodge_told, health_seen | 13 each | 0 | | |
| outcomes | 13 | 1 (new01) | The archer spawned beside rock, so `place_at` moved the targets laid out from it up to 6 m and the far one was never struck. | `open_ground` stands each part's archer on open walkable ground with no body on it; 12 of 12 since. |
| flee_wall | 13 | 1 (cap10-01) | "No flight closes on the threat by more than a stride" compared consecutive gaps, which counts the chaser's own walk. One sparse-sampled step read 1.03 m (17 samples against 23-26). | It now reads the fleer's own move against where the threat stood. |
| seize | 13 | 1 (new06) | A yield holds 20 s. Under load the last attack took 21.7 s to kill, so "Walker1 killed Walker2" carried no "who had yielded". | The victim yields again every 5 s while it runs. |
| truthful_refusals | 13 | 1 (new06) | The say leaf to "speaker" was stuck with the truthful status, "nobody has spoken to you in the last minute", but no "You failed to say" line was written. The world's commit log (replica 419) holds the status and no line; the retry world (427) holds both. Cause not established (`act::refused` → `news`/`tell`). | Recorded as `CASES['truthful_refusals']['flaky']`, parts: the say-leaf check alone. The scene's wait for the line no longer raises, so only that named check fails. |

Not from this branch: in baseline01, verify-player `combat`'s breath check ("a held run keeps draining while it lasts") failed once under full gate load and passed on its retry.

## Post-fix runs

Five gates at `198a3a245`, the acting, fight and steering groups only (`post01`-`post05`): every case passed in all five, 868-908 s each. Since its fix, `flee_wall` passed 12 of 12 first runs (new02-08 and post01-05), `seize` 6 of 6 (new08, post01-05; 7 of 7 counting new07, whose run straddled the edit) and `truthful_refusals` 7 of 7 (new07, new08, post01-05). Load in those runs: mean 4.2-9.0, max 7.7-33.1.

## Not covered

- The dev-box's numbers: the dev-box coordinator runs the same three arms there.
- A gate with every group on dev-box's server.
- The `truthful_refusals` missing line's cause.
