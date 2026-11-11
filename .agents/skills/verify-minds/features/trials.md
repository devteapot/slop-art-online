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

- `--fake` starts the shared [fake model server](../../verify-llm/scripts/fake_llm.py), keeps the variant's models file with its routing but points every profile at that server, named `fake-<model>` (so the journal shows where each call was routed), and blanks the provider keys in the mind's environment. `fake-requests.jsonl` in the batch directory holds every request.
- Each instance's `actions.log` shows every reducer call with its HTTP status; `events.jsonl` shows every timeline step and trigger as it fired, and any refused call.
- `samples.jsonl` advances every 2 s from the start; `summary.json` exists for every instance, including failed ones (`stopped_by` says why).
- `journal/` in the instance directory is a copy of the mind's journal (`.local/living/journal/<db>/`), with the actual requests and replies.
- After `clean`, the batch's databases answer SQL with 404 and the Neo4j nodes of their runs are gone; the evidence directory remains.
- Every `summary.json` has `prompt_frame` (per purpose, the subject's journaled requests that opened with the player frame) and `out_of_character` (`ooc_lines`, `ooc_private`: [`ooc.py`](../../../../living/tools/ooc.py) over spoken and written lines and over private reply fields). Under `default` every purpose reads `character 0/n`; under `player-frame` every think, deliberate, talk and consolidation request is framed and starting identities are not ([frame.md](frame.md)).
- From a git worktree, `build` copies each module into the container's `/wasm` mount (the starting checkout's `.local/living/trials/wasm/`) as `<module>-wt<tag>.wasm` and `run` publishes that copy; `actions.log` names it. The worktree needs its own `.local/living/trials/neo4j.env` and does not run `up` against a running stack.

## Life runs, resume and disk

- A `"kind": "life"` trial spawns its subject with the admin-only `spawn_newcomer` (a player's `join`, thought for by the minds), keeps no timeline, restarts a mind that exits, writes `snapshots/hNN.json` hourly and pauses its database at the end. `trials.py life --batch B` writes `timeline.md` from rows.
- `trials.py resume --batch B` continues instances whose `state.json` says they were running: it adopts a mind whose pid and `/proc` start time still match, or starts one. Proven by killing the runner (`kill -KILL <runner pid>`; never `pkill -f` a pattern in your own command line) and resuming.
- `trials.py reclaim` removes replica directories that deleted databases leave in the trial volume, keeping live ones (written in the last 5 minutes) and paused ones (matched by their last module-log timestamp). It refuses when the counts do not match.

## Paid tier

Real batches spend money. Run them only when the user has authorized them. There is no cap by default: `budget.tokens` in a trial or `TRIALS_TOTAL_TOKENS` sets one, and the ledger (`trials.py ledger`) records each batch's tokens. A runaway watchdog stops a run on 30 failed calls in 5 minutes, the same failure 15 times, more than 60 calls in a minute, or five mind restarts in 30 minutes, and records why in `events.jsonl` and `summary.json`. Summaries break calls, tokens, latency p50/p95, failures, empty replies, repaired and unparseable replies and estimated cost down per purpose × model (`by_purpose_model`); `trials.py resummarize` recomputes them from evidence.

## Not proven here

- Determinism: a seed does not make inference repeatable; read spread across replicates.
- Fake-model runs prove the plumbing (setup, timeline, sampling, journal, stop, cleanup), not what minds decide.
- Population, latency or memory claims; see `AGENTS.md` and `docs/PERFORMANCE_CONTRACT.md`.
