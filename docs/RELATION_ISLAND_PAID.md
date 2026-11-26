# relation_fight_on on the island with real minds (handoff, not started)

Status: **design notes only; nothing built, nothing run, no paid call.** Written 2026-11-26 by the Opus worker that was stopped when trial runs and their tooling were routed back to Sol (AGENTS.md "Models and coordination"). The plan and decision rule below are a **draft**: they become frozen only when the worker that runs the arms commits them, unchanged or amended, before the first paid call.

Approved by the general coordinator: one small paid real-mind island run, $2 per arm and $4 in total, to decide whether `relation_fight_on` (an ordinary law, off by default on main since 35b0ea218) is switched on by default.

## Inputs read

- `docs/TRIALS.md`, including "Paid runs: every stop rule in code (2026-11-22)".
- `docs/WORLD_RULES.md`, "Whom one fights".
- `.agents/skills/verify-core/references/validation/2026-11-23-0500-relation-fight.md`, including its law-off section and the free island section.
- `living/tools/island_fight.py`.
- `docs/INPUT_LATENCY.md`, "Real-model trial (act-trial, 2026-11-21)", with `living/trials/act-town.json` and the `act-replace-*` variants.
- `living/tools/act_trial.py` (`watch`).
- `docs/ATTENTION_E5.md` §7 on `origin/heed-e4` ("heed-town" there is E3's real-mind Cullet town: 40 minds, 15 min, $0.90).

## Facts established

- **The same exposure in every world.** The free island run gives every island world 277 living persons and the same exposure: of the residents' relation rows about people their own people hold as an enemy, 52 are hostile, 67 peaceful and 25 neutral. All six worlds in `.local/relation-fight/island/*/start.json` agree; the files are in worktree `t3-d6595451-1ac9c1d4346bcf76` and archived in `~/slop-evidence/relation-fight-20261123.tar.zst`. `start.json` holds only the counts, not the pairs, so the 25 pairs must be listed again from a fresh world. Genesis is deterministic, so the ids are the same in every world built from the same module.
- **Picking subjects by id.** trials.py `pick` (`Instance.pick`, around line 1242) has no option for explicit ids. Add one, `"ids": [...]`: the subjects are the listed ids that pass the existing `mindable` and stage filters, with `count` equal to the length of the list.
- **Ordinary laws reach the minds' prompts.** A variant's `world_laws` are set with `set_world_law` after the laws guard and before the mind starts (trials.py around line 1186), and read back into `world_laws.json`. Since `relation_fight_on` is an ordinary law, setting it there puts the law-on prompts in front of the minds from their first call.
- **Two runaway rules.** trials.py's own runaway rule stops multi-subject runs at 60 calls a minute. Set `budget.runaway_calls_per_min` to 400, as `act-town.json` does.
- **The world must outlive the runner.** `keep_db: true` keeps the world for end-of-run reads. The launcher must then delete it: pause, confirm by SQL, then `world_delete.py`.
- **A private stack.** Use `TRIALS_STDB_CONTAINER`, `TRIALS_STDB_PORT`, `TRIALS_NEO4J_CONTAINER` and `TRIALS_NEO4J_PORT` with `trials.py up`. `up` does not pin CPUs: run `docker update --cpuset-cpus 0-4,10-14` on both containers, and start the runner, mind and guard with that affinity. The wasm mount is then this checkout's own, so `served_name` adds no tag.
- **What the guard already does.** `act_trial.py watch` already has:
  - the spend cap read from live journals (`--group-cap`, `--total-cap`, `--margin`; group = arm name with cap 2 and total cap 4 gives $2 per arm and $4 in all);
  - a stop at more than 10% failures over 2 minutes;
  - the 40 GB memory and 45 GB disk floors;
  - `--ready` / `--pid-file`.

  `--price fake-<model>=…` makes fake calls cost money, for the dry run of the spend cap.
- **Tables to read.** `skill_use` (`source` is `player`, `graph` or `act`), `relation` (`actor`, `other`, `trust`, `label`), `relation_fight` (private, owner-readable: `actor`, `other`, `fight`, `by`), `routine` (`actor`, `graph`, `source`) and `activity` (`victim`). They are defined in `living/authority/src/tables.rs`.
- **Expected spend.** About 40 minds × 20 real minutes at $0.105–0.14 per resident-hour (act trial; E3 Cullet $0.0015 per mind-minute), which comes to **about $1.4–1.9 an arm**. That fits $2 only with a small margin (`--margin 0.2`; in-flight calls at concurrency 64 are about $0.08). Little headroom remains for re-running an arm after a provider blip; say so in the plan.

## What is left

1. **trials.py**: the `ids` pick option, plus a selftest or a fake run showing it works.
2. **The trial file and its variants.**
   - The trial: `living/trials/relation-island.json` (kind `life`, seed `island`, `minutes` 20, `keep_db` true, `minds.concurrency` 64, `budget.runaway_calls_per_min` 400, `life.stop_on_death` false, `subject.pick.ids` from step 3).
   - The variants: `relation-fight-off` and `relation-fight-on`, with `world_laws` `{"relation_fight_on": false|true}` and the people mix as the act trial used it (`models: {}`).
3. **`relation_island.py pick`**: publish the trial's own module once with no mind and list the 25 neutral pairs (`island_fight.py`'s hostile test and its `band` function). The subjects are then:
   - the actors of those pairs;
   - their targets that are mindable and past infancy;
   - the actors' nearest residents by home, to fill 40.

   Write `subjects.json` and delete the world.
4. **Split `island_fight.world`** into the publish step and a reusable observer of an existing database. Then `relation_island.py side` follows a trial instance's database, taking its name from `state.json`. It polls:
   - every 2 s: uses, flights, wounds and deaths, as `island_fight` does;
   - every 10 s: `relation_fight`;
   - every 30 s: the subjects' `relation` rows and `routine` graphs, flagging those that contain `enemy`.
5. **The guard, three new rules in `act_trial.py watch`.** Extend `act_trial_guard_selftest.py` to cover them.
   - `--fail-last 50 --fail-share 0.10`: more than 10% of the last 50 journaled calls failed.
   - `--max-calls-per-min R`: calls over 2 minutes, per minute, above R. Use 240 for 40 minds, about 4× the measured 58 a minute.
   - `--frozen MANIFEST`: re-hash the frozen inputs each interval, re-reading a file when its size or mtime changes. A mismatch or a missing file stops the run. The inputs are:
     - the trial file;
     - `variants.json`;
     - `subjects.json`;
     - `living/configs/models.json`;
     - the `living-mind` binary;
     - the trial module wasm;
     - the skills file.
6. **The launcher, `relation_island.py launch`.**
   - Refuse to start when the frozen manifest does not match.
   - Start the guard (`setsid`) with `--ready --pid-file` and wait for the ready file.
   - Take `~/slop-mq/trial-activity.lock` shared from Python with `fcntl.flock`, so the runner's PID is trials.py's own and not a `flock` wrapper's.
   - Start `trials.py run` with the CPU affinity 0-4,10-14, write its PID, and start `side`.
   - After the runner exits, run the final reads, then the world delete.
   - Never wrap it in `timeout`; wait with short foreground waits.
7. **Dry run every rule on the fake model** (`trials.py run --fake`) until it visibly trips, keeping each trip in the evidence:
   - spend: `--price fake-…` set absurdly high;
   - failures: a `--fake-script` with `status` 500 on think, `times` -1;
   - call rate: a low `--max-calls-per-min`;
   - host floors: `--min-mem-gb 10000`;
   - frozen inputs: the launcher refusing, and the guard stopping when a frozen file changes mid-run;
   - no journal and no ready file: `act_trial_guard_selftest.py`.
8. **Freeze the plan and the decision rule** (draft below) in this file and commit it before the first paid call.
9. **The two paid arms,** off then on, in sequence with the same setup. Copy the keys from an existing trials `.env` (for example `~/dev/slop-trials/.env`) without printing them, and delete the copy afterwards. Scan the evidence for keys at the end. Record the switches each batch ran with.
10. **`relation_island.py report`**: the measures below for each arm, and the verdict under the rule.

## Draft plan and decision rule (not frozen)

**Measures per arm:**

- **Violence:** attacks and threats in all; those aimed at people of a hostile people (rival town, outlaws); wounds; deaths; resident deaths by cause.
- **Fights started on hostile people:** an attack by A on B with no attack or threat by B on A in the 60 s before it. Record by whom, and why, from four sources:
  - `skill_use.source` (`act`: the mind's own act; `graph`: a routine);
  - the routine's `source` and whether its graph holds `relation: enemy`;
  - a `relation_fight` row for the pair (`enemy` or `spare`, `by`);
  - the pair's relation row (hostile, neutral or peaceful).
- **`fight` words written by the minds:** the `relation_fight` rows, and the consolidation replies' `fight` fields in the journals, including the ones refused.
- **Killing sprees:** one character killing 3 or more people in the arm, or 2 within 120 s.

**Rule:** switch the law on by default if the law-on arm shows no violence spike, meaning all of the following:

- no killing spree;
- resident deaths by a person's hand no more than in the off arm;
- attacks started on hostile people no more than off + max(2, ⌈0.25 × off⌉);
- the same margin for threats.

Otherwise report the numbers to the general coordinator.

**Stop rules, all in code:**

- spend: $2 an arm, $4 in total, read from live journals;
- more than 10% of the last 50 calls failed, and more than 10% over 2 minutes;
- a runaway call rate: the guard at 240 a minute, and trials.py at 400 a minute;
- 40 GB MemAvailable and 45 GB of free disk;
- the frozen-input hashes, checked at launch and during the run;
- no journal or no ready file: the guard refuses.

## Rules for the worker

- Take the trial-activity flock for trials and verify launches. battle.lock is not needed for outcome counts.
- Pin to CPUs 0-4,10-14 and keep X925 free. Leave the outside "frostmarsh" jobs alone.
- Stop servers with SIGINT and a long timeout, and read their logs before removing anything. Delete worlds by pause, SQL confirmation, then `world_delete.py`.
- Never use `timeout` around guarded runs, Docker volume prunes or reclaim tools.
- Leave other agents' containers and checkouts alone.
