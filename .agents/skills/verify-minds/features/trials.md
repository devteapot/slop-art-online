# Trials: one mind in a scripted world

Source: [`living/tools/trials.py`](../../../../living/tools/trials.py), trial files in [`living/trials/`](../../../../living/trials/), design and results in [`docs/TRIALS.md`](../../../../docs/TRIALS.md).

## What it is

A trial publishes one `verify-trial-<batch>-<trial>-<variant>-r<k>` database per instance from a module built with a derived seed (the trial's seed plus its `rules`/`overrides`, written to `.local/living/trials/seeds/`). It picks the subject and the cast from the census, runs the `prepare` and `start` steps through admin reducers (`place_at`, `set_behavior`, `grant_items`, `grant_know_how`, `set_background`, `place_structure`, `kill`) and through the mind reducers as the world admin, which controls every seeded character in a `minds: true` world (`mind_say` with thought kind `trial`, `mind_act` with source `trial`, `mind_routines`). It then starts the real `living-mind` with `LIVING_ONLY=<subject>` and the variant's models file and environment. Timed steps (`"at": <minutes>`) and triggers (`said`, `near`, `hour`) run while a sampler reads the subject's rows every 2 s. The run stops at the trial's minutes, its token cap, the batch's total cap, 20 s after the subject dies, or when the mind exits.

## Assertions (free tier: `--fake`)

Run on a trial service, never on a paused reference world:

```bash
python3 living/tools/trials.py up
python3 living/tools/trials.py build wolves
python3 living/tools/trials.py run --batch dry1 wolves --replicates 1 --minutes 6 --fake
python3 living/tools/trials.py clean --batch dry1
```

- `--fake` starts the shared [fake model server](../../verify-llm/scripts/fake_llm.py), keeps the variant's models file with its routing but points every profile at that server, named `fake-<model>` (so the journal shows where each call was routed), and blanks the provider keys in the mind's environment. `fake-requests.jsonl` in the batch directory holds every request. A variant with `LIVING_RETHINK=jev` also has its gate's Jev judge pointed at the fake server's `/v1/systemone` (`LIVING_RETHINK_URL`, with a placeholder `TYPESAFE_API_KEY`), so a gated arm runs free too. The fake answers every gate question 0.1, so every non-urgent request is held (`glf2`, docs/GATE_LIVE.md).
- Each instance's `actions.log` shows every reducer call with its HTTP status; `events.jsonl` shows every timeline step and trigger as it fired, and any refused call.
- `samples.jsonl` advances every 2 s from the start; `summary.json` exists for every instance, including failed ones (`stopped_by` says why).
- `journal/` in the instance directory is a copy of the mind's journal (`.local/living/journal/<db>/`), with the actual requests and replies.
- `summary.json` has `consolidations` (per character: attempted, primary, fallback, retried, lost, trimmed, capacity 429s, from the copied `journal/outcomes/consolidations.jsonl`), `call_failures` by kind and `outages`; `report.md` has the consolidation tables. The runaway watchdog ignores provider failures (capacity or rate 429s, 5xx, connection errors) and stops only when no route has answered for 10 minutes: `python3 living/tools/trials_runaway_selftest.py`.
- After `clean`, the batch's databases answer SQL with 404 and the Neo4j nodes of their runs are gone; the evidence directory remains.
- Every `summary.json` has `prompt_frame` (per purpose, the subject's journaled requests that opened with the player frame) and `out_of_character` (`ooc_lines`, `ooc_private`: [`ooc.py`](../../../../living/tools/ooc.py) over spoken and written lines and over private reply fields). Under `default` every purpose reads `character 0/n`; under `player-frame` every think, deliberate, talk and consolidation request is framed and starting identities are not ([frame.md](frame.md)).
- From a git worktree, `build` copies each module into the container's `/wasm` mount (the starting checkout's `.local/living/trials/wasm/`) as `<module>-wt<tag>.wasm` and `run` publishes that copy; `actions.log` names it. The worktree needs its own `.local/living/trials/neo4j.env` and does not run `up` against a running stack.

## The arrival trial (2026-11-11; kept as tooling, 2026-11-12)

- `human.script: arrive` (`Player.arrive_session`; living/trials/arrive.json, docs/TRIALS.md, "Arrivals") joins after the world has lived `subject.join.after_s` seconds, walks (`goto` to the densest group's centre, re-aimed every 15 s) until two residents are within `within_m`, then stands silent `stand_s`, `stands` times, each next group sharing the fewest members with the last; it never speaks or gestures. Each stand is a `human_stand` / `human_stand_end` event pair with from/to ms, the group and who was within 12 m. It counts and approaches only residents the minds think for (`Player.is_mind`: past infancy, in `LIVING_ONLY` or the `minds.max` thinkers); the greeting script counts every resident.
- `human.answer` (the `arrive-answer` trial): the player says that one line back to the first resident who addresses it (its own `speech` experience with the player as `object`), a `human_answer` event, then is silent.
- `record` adds, beside `speech`, `talk` and `audience`: `experiences` (every experience row as it arrives, before minds integrate and delete it, to `experiences_all.jsonl`), `gestures` (`skill_use` rows of `wave`, `nod`, `face`, `appraise` to `gestures.jsonl`), `positions` (every person's position, heading and activity with the creature it is aimed at, to `positions.jsonl`) and `thoughts` (every thought row, with `detail.reasons`, to `thoughts_all.jsonl`). `living/tools/arrive_report.py BATCH` reads them.
- A trial's `variants` lists the only variants it runs with (`arrive-answer`: `arrive-control` only); `minds.concurrency` sets `LIVING_CONCURRENCY` (default 64 under `minds.only: "all"` or `minds.max`, 4 for one thinker), recorded in `mind-env.json` and `summary.json`.
- `living/trials/fake/arrive-answer.json` is a proof-only fake script: every thought whose scene has #13 in sight (the joined player of a hamlet world) says "Hello there. Are you new here?" to #13, so the answer and the exchange after it can be measured without a provider.
- The newcomer laws and their `arrive-notice`/`-known`/`-wonder`/`-all` variants were rejected (2026-11-12) and are not in the code; they stay on `exp-arrive`.

## Life runs, resume and disk

- A `"kind": "life"` trial spawns its subject with the admin-only `spawn_newcomer` (a player's `join`, thought for by the minds), keeps no timeline, restarts a mind that exits, writes `snapshots/hNN.json` hourly and pauses its database at the end. `trials.py life --batch B` writes `timeline.md` from rows.
- `trials.py resume --batch B` continues instances whose `state.json` says they were running: it adopts a mind whose pid and `/proc` start time still match, or starts one. Proven by killing the runner (`kill -KILL <runner pid>`; never `pkill -f` a pattern in your own command line) and resuming.
- `trials.py reclaim` removes replica directories that deleted databases leave in the trial volume, keeping live ones (written in the last 5 minutes) and paused ones (matched by their last module-log timestamp). It refuses when the counts do not match.

## The greeting trial and runner switches (2026-11-11)

- `greet` (living/trials/greet.json; docs/TRIALS.md, "The greeting trial") has a scripted human player (`Player.greet_session`) that joins with its own identity and plays through `join`, `human_act` (`goto` with `{"at": [x, y]}`), `human_move` (a step into the group, and a stand-still call every 10 s that keeps its presence) and `human_say`, in cycles. Every reducer call is in `human.jsonl`, and each line is a `human_line` event with the residents within 12 m. `record.speech`, `record.talk` and `record.audience` write `speech.jsonl` (every line), `talk.jsonl` (every talk turn) and `audience.jsonl`. `living/tools/greet_report.py BATCH` reads them.
- `run --fake --fake-script FILE` passes a rules file to the fake server (only with `--fake`): `living/trials/fake/latency.json` gives think 5 s, compile 4 s, talk 1.5 s and consolidate 2 s, so that `LIVING_PARK` timing shows in a fake run.
- A seed with its own laws (`laws`/`laws_file`, e.g. Cullet's) keeps them: the runner composes the overlay over the skills file (`compose_laws`), logs whether that equals the world's own composition ("seed laws composed as the world composed them: True"), applies `skills_patch` and installs the result.
- When the container's `/wasm` mount is another checkout's (this one is a git worktree), `trials.py build` copies each module into that mount under a tagged name (`served_name`: `<module>-wt<hash of the checkout path>`), and `run` publishes that name. It never overwrites another checkout's module. Remove the tagged `.wasm` files from the mount when done.

## Paid tier

Real batches spend money. Run them only when the user has authorized them. There is no cap by default: `budget.tokens` in a trial or `TRIALS_TOTAL_TOKENS` sets one, and the ledger (`trials.py ledger`) records each batch's tokens. A runaway watchdog stops a run on 30 failed calls in 5 minutes, the same failure 15 times, more than 60 calls in a minute, or five mind restarts in 30 minutes, and records why in `events.jsonl` and `summary.json`. Summaries break calls, tokens, latency p50/p95, failures, empty replies, repaired and unparseable replies and estimated cost down per purpose × model (`by_purpose_model`); `trials.py resummarize` recomputes them from evidence.

## Not proven here

- Determinism: a seed does not make inference repeatable; read spread across replicates.
- Fake-model runs prove the plumbing (setup, timeline, sampling, journal, stop, cleanup), not what minds decide.
- Population, latency or memory claims; see `AGENTS.md` and `docs/PERFORMANCE_CONTRACT.md`.
- The trial service's open files: each live database holds file descriptors, and the trial container's soft limit is 1,024. With about 120 kept databases (2026-11-11) publishes fail with "cannot create a memfd: Too many open files" or `identity: timed out`. Clean kept batches before running wide.
