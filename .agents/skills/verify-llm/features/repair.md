# JSON repair and deliberation retry

## Sub-features

- A fenced reply with a trailing comma survives repair.
- Content arrays ignore non-text parts.
- Non-JSON compilation output switches to default and includes rejection feedback.
- Three unusable deliberation replies create an error thought instead of an accepted plan.

## How to get to it (user POV)

A provider emits a JSON slip or unusable output. The client repairs the slip, or the mind asks again with the error.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case repair --case deliberation-retry --case retry-exhausted
```

Check the raw fake content, copied journal requests and authority thoughts. The retry case must preserve the original not-JSON reply and include "That reply was rejected:" in the default request. The exhausted case must record at least three unusable attempts and a "could not decide" error thought.

## Gotchas

`parse_json` and `repair` repairs JSON slips. `Minds::deliberate` bounds compilation attempts to three. JSON parse failures have error null in the HTTP journal because transport succeeded. Authority thoughts and later request feedback establish semantic rejection. The repair cargo test also covers stray closers.

Compilation retries keep their original lane.


## Act repair

`act_repair` inherits `think` routing, effort and output cap unless configured explicitly. It stays in the triggering turn's lane. It makes one model exchange for the refused batch. The original and repaired authority submissions are journaled under `outcomes/act_attempts.jsonl`, apart from the model-call counts. The [verify-minds cases](../../verify-minds/features/deliberation.md#act-repair) drive the authority rejection, a repair reply with a recoverable JSON slip, and the final result, including a second refusal that stops the turn's repair.
