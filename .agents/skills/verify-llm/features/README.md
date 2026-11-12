# Model integration verification map

The sources are `living/mind/src/llm.rs` and the model configuration `living/configs/models.json`. Run `scripts/verify_llm.py` from the repository root as shown in [SKILL.md](../SKILL.md). Each case builds on a scratch world launched and checked through shared `verify.py`.

| Feature | Cases | File |
| --- | --- | --- |
| Authorized provider access check | Opt-in only | [live.md](live.md) |
| Basic exchange, accepted replies and journals | `basic` | [exchange.md](exchange.md) |
| Existing model-client cargo tests | Every invocation | [cargo-tests.md](cargo-tests.md) |
| JSON repair and bounded deliberation retry | `repair`, `deliberation-retry`, `retry-exhausted` | [repair.md](repair.md) |
| Outage gate and recovery; a deliberation keeps its request | `outage` | [outage.md](outage.md) |
| Pacing, priority lanes, token admission and caching | Cargo and fake contract, `basic` | [pacing.md](pacing.md) |
| Per-purpose model mixes, stage of attention, effort per purpose, output caps per purpose, effort gaps | `mix`; Cargo `mixes_route_each_purpose_and_stage_with_its_effort`, `a_models_file_naming_what_does_not_exist_is_refused`, `purposes_sent_without_an_effort_entry_are_reported`, `every_profile_caps_each_purpose_near_its_need` | [mixes.md](mixes.md) |
| Provider batch jobs, inline or as an uploaded file; failed polls, cancelling, collection after a restart | Cargo `a_large_batch_is_uploaded_as_a_file`, `a_failed_poll_keeps_the_batch_and_a_left_job_is_collected_after_a_restart`; `verify-knowledge` `player_memory.py --mode batch` and the knowledge suite's night batch | [batch.md](batch.md) |
| Rate limits, overflow and fallback; background calls do not overflow, except listed ones on a capacity 429 | `overflow`, `capacity-overflow`, `capacity-retry`, `retry-fallback`, `error-overflow`; Cargo `background_calls_do_not_overflow`, `a_model_out_of_capacity_sends_listed_memory_work_to_the_overflow` | [overflow.md](overflow.md) |
| Real HTTP timeout | `timeout` | [timeout.md](timeout.md) |
| Routing and key configuration | `routing-group`, `routing-assign`, `routing-rotate`, `routing-child`, `routing-default`, `missing-default-key` | [routing.md](routing.md) |
| The fast lane's route (purpose `fast` on the urgent lane to `fast.route`, a timeout dropped and journaled) and its world caps (`fast_lane_rate`, `fast_lane_inflight`) in a 20-fighter fake battle | `fast-route`, `fast-cap` | [fast.md](fast.md) |

Local evidence includes the action, fake requests, mind attempts and authority effect. The opt-in live tier remains unrun unless the user authorizes that paid run.
