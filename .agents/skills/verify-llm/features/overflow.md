# Overflow, retries and fallback

## Sub-features

- 429 sends an overflow-enabled primary directly to alternate.
- A 500 also sends that primary to alternate.
- A failed nondefault profile falls back once to default, without blind retries.
- A default profile without an alternate permits one same-profile 429 recovery through its learned pacing and cooldown.
- Background calls (`consolidate`, `reorganize`, `internalize`, `identity`) never go to an overflow or default profile (2026-11-10): they fail back to their caller, which retries later with a backoff on the model it chose. A 429 still gets its one paced retry on the same profile.
- Exception (2026-11-11): a 429 that says the provider is out of capacity for the model (Mistral's `backend_out_of_capacity`, code 3505) sends the background purposes the profile lists in `capacity_overflow` straight to its keyed overflow, at the overflow's own effort, with no paced retry on the short model. The project file lists only `consolidate` on `glm-flash` (DeepSeek Flash, thinking off, judged 8/8 for person consolidation); `reorganize` stays on GLM. A rate-limit 429 and an unlisted purpose keep the paced same-profile retry. `ModelsFile::check` refuses a `capacity_overflow` with an unknown purpose or without an overflow profile.

## How to get to it (user POV)

Configure a profile overflow or assign a secondary model. A provider rate limit or failure then selects another keyed profile.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case overflow --case retry-fallback --case error-overflow
```

Capacity: `--case capacity-overflow` (the primary's fake answers every consolidation with the capacity 429; the case waits for an accepted consolidation and checks each primary capacity failure is followed by one successful alternate consolidation at the alternate's effort, think and deliberate stay on the primary, and no consolidation failure is logged). `cargo test ... a_model_out_of_capacity_sends_listed_memory_work_to_the_overflow` covers the unlisted purpose, the rate-limit 429 and the config refusals against the real fake server.

Background lanes: `cargo test --manifest-path living/Cargo.toml -p living-mind background_calls_do_not_overflow` (two unreachable base URLs: consolidate and reorganize journal only the first profile, think both).

Compare `primary-requests.jsonl`, `alternate-requests.jsonl` and copied journals. The fallback case must have exactly one failed alternate think attempt followed by successful default think. The overflow cases must show primary HTTP 429 or 500, successful alternate think and an accepted plan.

## Gotchas

`Llm::chat_in_lane` owns alternate selection and bounded recovery. Every dispatched attempt uses the same lane scheduler and its target profile pacer. HTTP errors are client failures with reply and tokens null. Explicit-clock tests and a direct fake HTTP exchange in [pacing.md](pacing.md) cover pacing and saturation. These scenes do not measure provider limits.
