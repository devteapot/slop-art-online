# Pacing, priority and caching

## Sub-features

- Every profile has a smooth request pacer, even with the global call cap disabled.
- An omitted request ceiling starts pacing at 600 requests/minute. Provider headers establish the ceiling with ten percent headroom and may raise it above the starting rate. An explicit ceiling remains an upper bound.
- HTTP 429 halves its current request rate once per congestion event. Responses to requests sent at or before the last decrease cannot halve it again. The floor is the smaller of the ceiling and `max(1 request/minute, 5% of ceiling)`.
- A success reporting total usage grows the rate by `max(1 request/minute, 5% of ceiling)` once at least 10 seconds have elapsed since the previous increase or any 429, capped at the ceiling. With regular successful responses, a halving recovers in 100 seconds. These steps are named `RATE_*` constants in `llm.rs`.
- Optional token admission uses a rolling minute of reservations. Estimates count message bytes divided by three, message overhead and the output cap. Reported total usage replaces the reservation. An estimate larger than the token limit fails before dispatch.
- Mistral request/token limit headers set ceilings with ten percent headroom. Zero remaining requests or tokens pauses dispatch for a minute. Numeric and standard HTTP-date Retry-After values extend the cooldown.
- Interactive, Urgent, Routine and Background are typed lanes. Interactive is strictly first. `NON_INTERACTIVE_ADMISSIONS` is a ten-slot weighted admission ring: six Urgent, three Routine and one Background. `Queue.next_lane` advances only after a non-Interactive admission; empty lanes are skipped. A queued lane keeps its turn while provider pacing or an outage blocks it, so cheaper Routine calls cannot exhaust the tokens needed by Background. FIFO order holds among eligible requests in the selected lane. Lower lanes leave a quarter of network slots, at least one, for Interactive when concurrency exceeds one. Waiting and cancelled calls occupy no network slot.
- Player conversation participants select Interactive. Deliberation selects it when a recent experience involving a player matches its reason text, explicit player ID or combat-report participant. Combat, fight, alarm, attack, hit, danger and wound reasons select Urgent; ordinary thinking selects Routine. Consolidation, reorganization and identity use Background.
- Enabled cache keys are stable for a profile and purpose, independent of actor. Disabled profiles omit the request field.

## Profile configuration

| Key | Default | Meaning |
| --- | --- | --- |
| `requests_per_minute` | omitted | Optional request ceiling, accepted range 0.01 through 60000. Without an override the adaptive starting rate is 600, with no static cap. Convert the account's requests/second limit to a minute rate. |
| `tokens_per_minute` | omitted | Optional positive token ceiling; provider headers can also establish one. |
| `prompt_cache_key` | `false` | Send a stable cache key when the endpoint supports it. |

`LIVING_LLM_PER_MIN=0` disables only the optional global ceiling. A positive value applies shared pacing across profiles and uses the same lane queue. The old purpose-specific reserve is removed. `LIVING_CONCURRENCY`, default 64, bounds actual HTTP requests.

## Driving it

```bash
cargo test --manifest-path living/Cargo.toml -p living-mind llm::tests -- --nocapture
.agents/skills/verify-llm/scripts/fake_contract.py --run llm-contract-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-pacing-$(date +%Y%m%d-%H%M%S) --case basic --case overflow --case retry-fallback
```

Explicit-clock tests prove request spacing, rolling token limits, one decrease for 20 simultaneous 429s, the relative floor, recovery from 200 to 400 requests/minute in 100 seconds, an unconfigured 600 starting rate, advertised ceilings above that start, reserved capacity and weighted sharing under continuously refilled queues. Background gets one admission in each ten non-Interactive admissions when all three lanes stay queued, or one in four when only Routine and Background stay queued. Tests inject Interactive at every ring position, check the 6/3/1 counts and Urgent before Routine, and force a larger Background reservation to wait for the rolling token window while cheaper Routine calls remain queued. The starvation check fails with the former strict `min()` selection. Async checks prove cancellation releases tickets and outage probes. A direct Rust/fake-server exchange verifies paced 429 recovery, usage fields, stable keys, omission and missing-usage handling. It prints its evidence directory. The basic authority case also checks player-talk and consolidation lanes, cache keys and usage breakdowns.

## Limits and documentation

Source entry points are `llm.rs` symbols `Rate`, `Queue`, `Scheduler`, `Admission`, `Lane`, `retry_after` and `chat_once`; `Minds::deliberation_lane` and `reply_turn` supply context. This is process-local scheduling. Profiles or processes sharing provider quota require separately configured shares. The weights allocate admissions, not equal token shares or a wall-clock deadline. Continuous Interactive demand can defer every other lane. Background progress assumes requests fit the profile token ceiling and its provider eventually accepts dispatch. Keeping a paced lane's turn can leave unrelated profiles idle during its cooldown or outage; this avoids spending a shared token budget on cheaper lanes while the selected lane waits. In-flight requests are not preempted, and Interactive still respects provider pacing.

Character primary-key lookups reuse the existing subscription. Deliberation classification iterates every controller-subscribed experience before filtering by observer. The authority has an observer index, but the pinned generated SDK cache exposes only the experience primary key. Iteration clones cached rows and some player matching allocates formatted strings. There is no new authority query, subscription, table or write. With the authority's approximate 400-row window, the worst-case scan is about `400 × controlled characters` per deliberation. At 400 deliberations/minute, 216 characters with full windows imply about 34.6 million row visits/minute. This is a cost estimate, not a measurement; batches can temporarily exceed the window. An observer-keyed mind cache would need separate lifecycle and reconnect verification, so this change leaves classification intact.

Reason strings lack a durable source-experience ID. Classification uses text containment, explicit `(#[player ID])` text, or combat reports naming a recent player participant. This can miss unmatched or expired player causality; name matching is heuristic. The existing player predicate also treats externally controlled instinct characters as players.

Mistral's [usage limits](https://docs.mistral.ai/admin/billing-usage/usage-limits) document model-specific requests/second and tokens/minute. Its [SDK issue with captured response headers](https://github.com/mistralai/client-ts/issues/169) shows `x-ratelimit-limit-req-minute`, `x-ratelimit-remaining-req-minute`, `x-ratelimit-limit-tokens-minute` and `x-ratelimit-remaining-tokens-minute`. Those observed names are not a formal, guaranteed header contract. Missing headers use the configured ceiling or the adaptive 600 requests/minute starting rate; no reset header is assumed.

Mistral's [prompt caching documentation](https://docs.mistral.ai/studio-api/conversations/advanced/prompt-caching) documents the chat-completion cache key and `usage.prompt_tokens_details.cached_tokens`. Keys do not guarantee cache hits. This change preserves message order and prompt text.

The SpacetimeDB [tables](https://spacetimedb.com/docs/tables/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [views](https://spacetimedb.com/docs/functions/views/) guidance was checked against the pinned 2.10.1 SDK and generated bindings. Classification uses existing subscribed `Character.ai/controller` and `Experience` fields; it adds no new SpacetimeDB API dependency. Cached observations classify priority, not permissions.

Free-tier checks establish neither tokenizer accuracy nor provider quota, billing, cache hit rate, player latency at population scale or performance acceptance. A separately authorized measurement must establish those against the selected Mistral account and active configuration.
