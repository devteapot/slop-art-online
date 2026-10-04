# Overflow, retries and fallback

## Sub-features

- 429 sends an overflow-enabled primary directly to alternate.
- A 500 also sends that primary to alternate.
- A failed nondefault profile falls back once to default, without blind retries.
- A default profile without an alternate permits one same-profile 429 recovery through its learned pacing and cooldown.

## How to get to it (user POV)

Configure a profile overflow or assign a secondary model. A provider rate limit or failure then selects another keyed profile.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case overflow --case retry-fallback --case error-overflow
```

Compare `primary-requests.jsonl`, `alternate-requests.jsonl` and copied journals. The fallback case must have exactly one failed alternate think attempt followed by successful default think. The overflow cases must show primary HTTP 429 or 500, successful alternate think and an accepted plan.

## Gotchas

`Llm::chat_in_lane` owns alternate selection and bounded recovery. Every dispatched attempt uses the same lane scheduler and its target profile pacer. HTTP errors are client failures with reply and tokens null. Explicit-clock tests and a direct fake HTTP exchange in [pacing.md](pacing.md) cover pacing and saturation. These scenes do not measure provider limits.
