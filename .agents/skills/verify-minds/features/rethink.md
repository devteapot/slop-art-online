# The rethink gate (`LIVING_RETHINK=jev|llm`; off by default)

A fast judge sits in front of non-urgent deliberation requests and decides whether the slow mind thinks now or the request waits. Jev (TypeSafe, `POST /v1/systemone`, three nouls combined in code) or a chat model (`llm.route`, purpose `rethink`, a yes/no with a probability) answers over a compact state built in code: the plan and its outline, the pending reasons, needs as words (since 2026-11-11 the world's `status_of` law's `felt` word for each meter, `{"health", "hunger", "energy"}`: energy 20 reads "tired", was "very tired"; docs/WORLD_RULES.md "The body: meters and statuses"), what was perceived, succeeded and failed since the last thought, people spoken to without an answer, and the plans of the last few thoughts. Configuration: `living/configs/rethink.json` (`LIVING_RETHINK_CONFIG`; `LIVING_RETHINK_URL` overrides Jev's endpoint). Design and results: docs/MIND_HARNESS.md, "Rethink gate".

## Sub-features

- **Urgent bypass:** reasons the level of detail grades `Prompt` or `Now` (attacks, threats, fight reports, bodily alarms, offers, family and join requests, calls of one's kind), a deliberation lane other than `routine` (a player's act, combat words), and the config's `urgent` substrings are never judged. Neither is the first thought after the service starts.
- **Hold:** below the arm's `proceed_above` the request stays pending in the authority, which merges later reasons into it; each merge (or a new percept) asks again; the character is `deferring`, so it still takes conversation turns.
- **Unchanged re-triggers** (the same reasons and no new percept, e.g. "I finished my plan." every 8 s) are held without asking; counted as `unchanged`.
- **Never held (`waits`, since gate-hold-fix):** a line someone said or whispered to the character in the last 10 minutes and not answered since, or the same deliberate act failing twice since the last deliberation (or the authority's "turning back and forth" line). The gate does not ask the judge and journals the fact as `waits_on` (`rethink.rs` `waits_on`, unit test `someone_waiting_or_a_failing_act_is_never_held`; the scripted case does not drive it yet; docs/GATE_LIVE.md, gl1).
- **Release:** a yes, an urgent merge, `max_hold_s` (the tick lets it through) or a failing/slow judge (`fallback`, past `timeout_ms`).
- **Records:** every decision is a journal entry with purpose `rethink-gate` (verdict, p, answers, threshold, reason, state, error); Jev's exchange is purpose `rethink` with `cost_usd` (input tokens × the local price, `living/mind/src/prices.rs`; null, never 0, without a prices file); the chat arm's call is journaled by `llm.rs` as purpose `rethink`. A `rethink gate (<arm>): Stats {…}` log line every minute: `cost_usd` is the known part (`None` while none is known), and `cost_unknown` counts judged calls without a known cost. The chat arm's cost is in `llm.rs`'s journal entry, not here.
- **Replay:** `living-mind rethink-replay --arm jev|llm --out FILE DIR...` asks the same gate at every deliberation of trial evidence directories; `living/tools/rethink_report.py` scores it and live trial batches.

Sources: `living/mind/src/mind/rethink.rs`, `living/mind/src/prices.rs`, `living/mind/src/mind.rs` (`schedule`, `Event::Percept`, the tick), `living/mind/src/mind/talk.rs` (`thinking`), `living/mind/src/main.rs` (percept events, the `rethink-replay` subcommand), `living/configs/rethink.json`.

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-$(date +%Y%m%d-%H%M%S) --case rethink --case rethink-llm
```

The case writes a copy of the config with `max_hold_s` 90 and short timeouts, points Jev at the fake, and drives one adult through `set_behavior` think nodes whose markers pick the fake's answer (`contains` rules): `verify first` (verdict `first`, no judge call); `verify gated one` (held, state shape checked, a talk turn while held, no think exchange, the row still pending); `verify gated two` (merged, held again); `Wolf is attacking you!` (verdict `urgent`, no judge call, the deliberation's reason holds both gated markers); `verify yes` (`rethink`); `verify broken` (503) and `verify slow` (6 s against a 2 s timeout) (`fallback`); `verify gated three` (held, then `max_hold`). `rethink-llm` runs the same script through the chat arm. About six minutes each.

Both arms start with `LIVING_PRICES` naming a file that does not exist. They check that the copied `rethink.json` carries no price, and that the stats line reads `cost_usd: None`. The Jev arm also checks that every Jev exchange has `cost_usd` null, that the log says its cost is unknown, and that `cost_unknown` is above 0.

## Gotchas

- The unchanged rule (held without asking) is proven by the unit test `a_held_request_is_asked_again_only_when_something_changed`, not live: whether a re-raised trigger finds a new percept depends on the world's timing.
- `max_hold_s` must outlast the steps between the first hold and the urgent merge (a talk turn takes up to 30 s); with 25 s the request was released mid-case.
- Wait on the `rethink-gate` journal, not on the pending row: the fake mind answers in under a second, so a released request is gone before a poll sees it.
- A think node fires at most once per 90 s and not within 45 s of a decision; the case sleeps 46 s between steps.
- The trials runner blanks provider keys in `--fake` runs, so a Jev arm there needs `LIVING_RETHINK_URL` pointing at the fake; with an empty `TYPESAFE_API_KEY` the mind refuses to start.
