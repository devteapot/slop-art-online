# Outage gate and recovery

## Sub-features

- Stop an owned provider process and observe a real connect failure.
- Later calls wait while one probe retries.
- Restart the same port and observe recovery with a positive held-call count.

## How to get to it (user POV)

A model endpoint becomes unreachable while the mind remains connected to the authority. Restore that endpoint to resume its calls.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case outage
```

`mind.log` must contain unreachable holding and reachable-again lines, with at least one held caller. The fake restarted log and copied journal must show resumed requests. `processes.json` records owned processes, and `cleanup.json` records their stops.

## Gotchas

`llm.rs:394-434` gates by base_url, not profile name. The driver stops only its primary fake pid. A fresh think graph waits for the authority settling period before it can trigger. Gate waiting happens before latency measurement, so journal latency alone cannot prove held-call time. This case proves recovery after a short local outage, not the 60-second cap under a long outage.
