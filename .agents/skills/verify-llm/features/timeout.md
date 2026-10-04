# HTTP timeout

## Sub-features

- A fake delays think for 185 seconds.
- The real client cancels it near its 180-second timeout.
- A nondefault timeout falls back to default and still installs a plan.

## How to get to it (user POV)

A provider accepts the HTTP connection but fails to return a reply before the fixed 180-second client timeout.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case timeout
```

The alternate request log must show delay_s 185. Its think journal entry must report timeout with latency_ms at least 179000. A successful primary think and a deliberate authority thought prove fallback and acceptance.

## Gotchas

`Llm::new` sets the 180-second timeout. `Llm::chat_once` classifies connect, timeout and request errors for the gate. This case deliberately takes several minutes. It does not change the product timeout or use a shortened surrogate.
