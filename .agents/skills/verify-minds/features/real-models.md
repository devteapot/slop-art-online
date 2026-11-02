# Opt-in real models

## Sub-features

- `--allow-live` is required before reading state, config or keys.
- An independent guardian imposes a 90-second deadline and checks that its driver/mind group is gone after any driver or wrapper exit.
- Two real minds run for 60 seconds with real configured providers.
- Model calls are capped at four per minute through `duel.py --per-min`.
- Thoughts, installed behavior, acts and speech can be compared with exact journal exchanges.

## How to get to it (user POV)

An operator authorizes a short live experiment. Two characters have a quarrel; their models decide what happens. No particular fight or outcome is required.

## Driving it with duel.py

Use the literal command block in [SKILL.md](../SKILL.md). It launches and doctors `verify-minds-duel-*`, then runs the existing duel tool through `real_models.py`. The wrapper supplies the admin token without writing it, fixes the caps, and copies the completed journal and log into the evidence directory. Save authority tables and use shared cleanup.

The free process-safety proof is:

```bash
.agents/skills/verify-minds/scripts/paid_safety.py --run minds-duel-safety-$(date +%Y%m%d-%H%M%S)
```

It runs inert children and makes no database or model calls. Inspect `guard.log`, `results.json` and each scenario's `duel-cleanup.json`. The five scenarios cover successful driver exit with a surviving child, killed driver, deadline, killed wrapper and wrapper SIGTERM. Every group must be checked gone, including children that ignore SIGTERM.

## Gotchas

- This tier costs money and is not part of the free suite. Do not run without specific authorization.
- Keep Neo4j off. Never write to the reference memory service on port 7689.
- `duel.py` selects its own journal run name and republishes the supplied scratch database.
- A call-rate cap is not a token or currency budget. The independent guardian terminates the whole group even if the driver dies before it stops the mind. The 90-second deadline covers setup too.
- Config resolution matches `verify-llm`: explicit `--models`, active `LIVING_MODELS`, then the repository default. Host `.env` chooses `.local/living/models.json` and Luna through the local proxy.
- The guardian requires Linux child-subreaper support. Failure without a completed report leaves partial duel logs for manual preservation and shared database cleanup.
- Model outputs are nondeterministic. Record refusals and failures as outcomes, not evidence to overwrite.
