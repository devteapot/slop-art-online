# Pacing, priority and caching

## Sub-features

- Every profile has a smooth request pacer, even with the global call cap disabled.
- HTTP 429 halves its current request rate, with a floor of 0.01 requests/minute. A success reporting total usage can grow it by one request/minute when at least 60 seconds have elapsed since the previous increase or 429, up to the configured or advertised ceiling.
- Optional token admission uses a rolling minute of reservations. Estimates count message bytes divided by three, message overhead and the output cap. Reported total usage replaces the reservation. An estimate larger than the token limit fails before dispatch.
- Mistral request/token limit headers lower ceilings with ten percent headroom. Zero remaining requests or tokens pauses dispatch for a minute. Numeric and standard HTTP-date Retry-After values extend the cooldown.
- Interactive, Urgent, Routine and Background are typed lanes. The highest queued lane runs first, with FIFO order among eligible requests in that lane. Lower lanes leave a quarter of network slots, at least one, for Interactive when concurrency exceeds one. Waiting and cancelled calls occupy no network slot.
- Player conversation participants select Interactive. Deliberation selects it when a recent experience involving a player matches its reason text, explicit player ID or combat-report participant. Combat, fight, alarm, attack, hit, danger and wound reasons select Urgent; ordinary thinking selects Routine. Consolidation, reorganization and identity use Background.
- Enabled cache keys are stable for a profile and purpose, independent of actor. Disabled profiles omit the request field.

## Profile configuration

| Key | Default | Meaning |
| --- | --- | --- |
| `requests_per_minute` | `60` | Positive request ceiling, accepted range 0.01 through 60000. Convert the account's requests/second limit to a minute rate. |
| `tokens_per_minute` | omitted | Optional positive token ceiling; provider headers can also establish one. |
| `prompt_cache_key` | `false` | Send a stable cache key when the endpoint supports it. |

`LIVING_LLM_PER_MIN=0` disables only the optional global ceiling. A positive value applies shared pacing across profiles and uses the same lane queue. The old purpose-specific reserve is removed. `LIVING_CONCURRENCY`, default 64, bounds actual HTTP requests.

## Driving it

```bash
cargo test --manifest-path living/Cargo.toml -p living-mind llm::tests -- --nocapture
.agents/skills/verify-llm/scripts/fake_contract.py --run llm-transport-contract-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-transport-$(date +%Y%m%d-%H%M%S) --case basic --case overflow --case retry-fallback
```

Explicit-clock tests prove request spacing, rolling token limits, 429 adaptation, header ceilings, lane ordering under saturation and reserved capacity. Async checks prove cancellation releases tickets and outage probes. A direct Rust/fake-server exchange verifies paced 429 recovery, usage fields, stable keys, omission and missing-usage handling. It prints its evidence directory. The basic authority case also checks player-talk and consolidation lanes, cache keys and usage breakdowns.

## Limits and documentation

Source entry points are `llm.rs` symbols `Rate`, `Queue`, `Scheduler`, `Admission`, `Lane`, `retry_after` and `chat_once`; `Minds::deliberation_lane` and `reply_turn` supply context. This is process-local scheduling. Profiles or processes sharing provider quota require separately configured shares. Strict priority can defer Background indefinitely under sustained higher-priority demand. In-flight requests are not preempted, and Interactive still respects provider pacing.

Character primary-key lookups reuse the existing subscription. Deliberation classification scans the subscribed experience window for that actor without allocating or sorting it. There is no new authority query, subscription, table or write. Reason strings lack a durable source-experience ID. Classification uses text containment, explicit `(#[player ID])` text, or combat reports naming a recent player participant. This can miss unmatched or expired player causality; name matching is heuristic. The existing player predicate also treats externally controlled instinct characters as players.

Mistral's [usage limits](https://docs.mistral.ai/admin/billing-usage/usage-limits) document model-specific requests/second and tokens/minute. Its [SDK issue with captured response headers](https://github.com/mistralai/client-ts/issues/169) shows `x-ratelimit-limit-req-minute`, `x-ratelimit-remaining-req-minute`, `x-ratelimit-limit-tokens-minute` and `x-ratelimit-remaining-tokens-minute`. Those observed names are not a formal, guaranteed header contract. Missing headers use configured pacing; no reset header is assumed.

Mistral's [prompt caching documentation](https://docs.mistral.ai/studio-api/conversations/advanced/prompt-caching) documents the chat-completion cache key and `usage.prompt_tokens_details.cached_tokens`. Keys do not guarantee cache hits. This change preserves message order and prompt text.

The SpacetimeDB [tables](https://spacetimedb.com/docs/tables/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [views](https://spacetimedb.com/docs/functions/views/) guidance was checked against the pinned 2.10.1 SDK and generated bindings. Classification uses existing subscribed `Character.ai/controller` and `Experience` fields; it adds no new SpacetimeDB API dependency. Cached observations classify priority, not permissions.

Free-tier checks establish neither tokenizer accuracy nor provider quota, billing, cache hit rate, player latency at population scale or performance acceptance. A separately authorized measurement must establish those against the selected Mistral account and active configuration.
