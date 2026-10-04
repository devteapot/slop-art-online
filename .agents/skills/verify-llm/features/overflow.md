# Overflow, retries and fallback

## Sub-features

- 429 sends an overflow-enabled primary directly to alternate.
- A 500 also sends that primary to alternate.
- Without overflow, one initial 429 plus three retries uses increasing backoff, then falls back once to default.

## How to get to it (user POV)

Configure a profile overflow or assign a secondary model. A provider rate limit or failure then selects another keyed profile.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case overflow --case retry-fallback --case error-overflow
```

Compare `primary-requests.jsonl`, `alternate-requests.jsonl` and copied journals. The fallback case must have exactly four failed alternate think attempts, at least 1.5, 3 and 6 seconds apart, followed by successful default think. The overflow cases must show primary HTTP 429 or 500, successful alternate think and an accepted plan.

## Gotchas

`llm.rs:247-308` owns overflow and its window. `llm.rs:311-333` owns retries and default fallback. HTTP errors are client failures with reply and tokens null. The bounded local run does not fill the eight-slot window or measure its adaptive limit.
