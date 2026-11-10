# HTTP timeout

## Sub-features

- A fake delays think for 185 seconds.
- The real client cancels it near its 180-second timeout.
- A nondefault timeout falls back to default and still installs a plan.
- A timeout does not mark the host unreachable (2026-11-10): only a connect error gates a base URL, so a slow reply does not hold the other profiles on it.

## How to get to it (user POV)

A provider accepts the HTTP connection but fails to return a reply before the fixed 180-second client timeout.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case timeout
```

The alternate request log must show delay_s 185. Its think journal entry must report timeout with latency_ms at least 179000. A successful primary think and a deliberate authority thought prove fallback and acceptance. `mind.log` must have no `unreachable: holding model calls` line.

## Gotchas

`Llm::new` sets the 180-second timeout. `Llm::chat_once` gates the host on connect errors only. A runaway generation is bounded by the purpose's output cap (`purpose_max_tokens`, see [mixes.md](mixes.md)) before it reaches the timeout. This case deliberately takes several minutes. It does not change the product timeout or use a shortened surrogate.
