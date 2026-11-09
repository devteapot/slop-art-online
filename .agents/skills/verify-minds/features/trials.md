# Trials: one mind in a scripted world

Source: [`living/tools/trials.py`](../../../../living/tools/trials.py), trial files in [`living/trials/`](../../../../living/trials/), design and results in [`docs/TRIALS.md`](../../../../docs/TRIALS.md).

## What it is

A trial publishes one `verify-trial-<batch>-<trial>-<variant>-r<k>` database per instance from a module built with a derived seed (the trial's seed plus its `rules`/`overrides`, written to `.local/living/trials/seeds/`). It picks the subject and the cast from the census, runs the `prepare` and `start` steps through admin reducers (`place_at`, `set_behavior`, `grant_items`, `grant_know_how`, `set_background`, `place_structure`, `kill`) and through the mind reducers as the world admin, which controls every seeded character in a `minds: true` world (`mind_say` with thought kind `trial`, `mind_act` with source `trial`, `mind_routines`). It then starts the real `living-mind` with `LIVING_ONLY=<subject>` and the variant's models file and environment. Timed steps (`"at": <minutes>`) and triggers (`said`, `near`, `hour`) run while a sampler reads the subject's rows every 2 s. The run stops at the trial's minutes, its token cap, the batch's total cap, 20 s after the subject dies, or when the mind exits.

## Assertions (free tier: `--fake`)

Run on a trial service, never on a paused reference world:

```bash
python3 living/tools/trials.py up
python3 living/tools/trials.py build wolves
python3 living/tools/trials.py run --batch dry1 wolves --replicates 1 --minutes 6 --fake --keep-db
python3 living/tools/trials.py clean --batch dry1
```

- `--fake` starts the shared [fake model server](../../verify-llm/scripts/fake_llm.py), writes a models file whose only profile points at it, and blanks the provider keys in the mind's environment. `fake-requests.jsonl` in the batch directory holds every request.
- Each instance's `actions.log` shows every reducer call with its HTTP status; `events.jsonl` shows every timeline step and trigger as it fired, and any refused call.
- `samples.jsonl` advances every 2 s from the start; `summary.json` exists for every instance, including failed ones (`stopped_by` says why).
- `journal/` in the instance directory is a copy of the mind's journal (`.local/living/journal/<db>/`), with the actual requests and replies.
- After `clean`, the batch's databases answer SQL with 404 and the Neo4j nodes of their runs are gone; the evidence directory remains.

## Paid tier

Real batches spend tokens. Run only within an authorized budget: each trial's `budget.tokens` stops its mind, and the ledger (`.local/living/trials/ledger.json`, `trials.py ledger`) refuses a batch whose worst case exceeds what is left of `TRIALS_TOTAL_TOKENS` (default 6,000,000) unless `--allow-partial`, in which case the total cap still stops every mind.

## Not proven here

- Determinism: a seed does not make inference repeatable; read spread across replicates.
- Fake-model runs prove the plumbing (setup, timeline, sampling, journal, stop, cleanup), not what minds decide.
- Population, latency or memory claims; see `AGENTS.md` and `docs/PERFORMANCE_CONTRACT.md`.
