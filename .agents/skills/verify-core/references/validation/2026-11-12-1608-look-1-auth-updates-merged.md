# verify-core: look-1-auth update guard, after merging main

## 2026-11-12 look-1-auth `68f585e8` (dev-box)

This follows [2026-11-12-1552-look-1-auth-updates.md](2026-11-12-1552-look-1-auth-updates.md), with main (house-owner label, first-sight crowd, compose-client-2) merged. Bindings were regenerated with no difference. `just living-check` passes (all steps). The scene gate on `look1-stdb` with `--no-main-check` passes 11/11 (tick, sight, senses, refusal, skirmish, roundtrip, acts, dealings, conversation, combat, mind-unit; `.local/living/verify/gate-1112165656`).

- `updates.py --run core-updates-1112-170308 --relook fixture-1`: `main-plan` and `main-guard` from main `7a2633b1` (the latter with the guard patch alone), `look-plan` and `look-col` from `68f585e8`.
  - main → look-plan: 2 PANIC (main's `tick` and `housekeeping`). The world ticked on with its rows and timers; relook 5 looks.
  - main → main-guard → look-plan, three chains: 0 PANIC, one guard line each.
  - main-guard → look-plan → look-col: 0 PANIC.
  - look-plan → look-col: 0 PANIC; looks kept.

Not covered: as in the record it follows.
