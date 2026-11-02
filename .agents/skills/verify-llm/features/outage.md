# Outage gate and recovery

## Sub-features

- Stop an owned provider process and observe a real connect failure.
- Later calls wait while one probe retries.
- After provider restoration, an addressed player question supplies fresh demand even if the failed compilation left thinking behind an authority cooldown. The gate reopens on a reachable response, so new calls can still enter it after restoration.
- Restart the same port and observe recovery with a positive held-call count.

## How to get to it (user POV)

A model endpoint becomes unreachable while the mind remains connected to the authority. Restore that endpoint to resume its calls.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case outage
```

`mind.log` must contain unreachable holding and reachable-again lines, with at least one held caller. The driver requires requests in the restarted fake log, a successful journal exchange after restart and a mind-installed authority graph. The question may be handled by a pending deliberation instead of a talk turn. `processes.json` records owned processes, and `cleanup.json` records their stops.

## Gotchas

`Queue::candidate` and `Llm::gate_leave` gate by base_url, not profile name. The driver stops only its primary fake pid. A fresh think graph waits for the authority settling period before it can trigger. Gate and pacing waits appear in `queue_wait_ms`; `latency_ms` measures the HTTP exchange. Admission selects the one outage probe before taking a network slot. This case proves recovery after a short local outage, not the 60-second cap under a long outage.
