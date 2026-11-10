# Model integration verification map

Run `scripts/verify_llm.py` from the repository root as shown in [SKILL.md](../SKILL.md). Each case builds on a scratch world launched and checked through shared `verify.py`.

| Feature | Cases | File |
| --- | --- | --- |
| Basic exchange, accepted replies and journals | `basic` | [exchange.md](exchange.md) |
| Routing and key configuration | `routing-group`, `routing-assign`, `routing-rotate`, `routing-child`, `routing-default`, `missing-default-key` | [routing.md](routing.md) |
| Per-purpose model mixes, stage of attention, effort per purpose, output caps per purpose, effort gaps | `mix`; Cargo `mixes_route_each_purpose_and_stage_with_its_effort`, `a_models_file_naming_what_does_not_exist_is_refused`, `purposes_sent_without_an_effort_entry_are_reported`, `every_profile_caps_each_purpose_near_its_need` | [mixes.md](mixes.md) |
| Pacing, priority lanes, token admission and caching | Cargo and fake contract, `basic` | [pacing.md](pacing.md) |
| Rate limits, overflow and fallback; background calls do not overflow | `overflow`, `retry-fallback`, `error-overflow`; Cargo `background_calls_do_not_overflow` | [overflow.md](overflow.md) |
| Outage gate and recovery; a deliberation keeps its request | `outage` | [outage.md](outage.md) |
| JSON repair and bounded deliberation retry | `repair`, `deliberation-retry`, `retry-exhausted` | [repair.md](repair.md) |
| Real HTTP timeout | `timeout` | [timeout.md](timeout.md) |
| Provider batch jobs, inline or as an uploaded file; failed polls, cancelling, collection after a restart | Cargo `a_large_batch_is_uploaded_as_a_file`, `a_failed_poll_keeps_the_batch_and_a_left_job_is_collected_after_a_restart`; `verify-knowledge` `player_memory.py --mode batch` and the knowledge suite's night batch | [batch.md](batch.md) |
| Existing model-client cargo tests | Every invocation | [cargo-tests.md](cargo-tests.md) |
| Authorized provider access check | Opt-in only | [live.md](live.md) |

Local evidence includes the action, fake requests, mind attempts and authority effect. The opt-in live tier remains unrun unless the user authorizes that paid run.
