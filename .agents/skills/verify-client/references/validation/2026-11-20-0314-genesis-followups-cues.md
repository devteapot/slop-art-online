# genesis-followups: `cues.py` checks ticks and order; wall-clock delivery is a measurement (verify-client)

Branch `genesis-followups` (from `origin/main` `b6aa74890`), dev-box, the worker's own server `sg-stdb` (v2.14.1, 127.0.0.1:3344). The GC asked to split `cues`: the gate asserts tick-based correctness, and the 100 ms wall-clock bound becomes a measurement.

What changed in `scripts/cues.py`:
- "within 100 ms of act_ms" is now two checks. (1) Each of B's windups reaches A first by `seen_fighter_cue`, before any tier row of it. (2) The cue was written within `MAX_TICKS` (2) ticks of the windup's `act_ms`, from the cue's own `at_ms` (authority time) in the tick spacing the private `clock` row shows across the scene (owner SQL, read before and after B's acts).
- The law-off check "by its near tier within 150 ms" is now "by its near tier".
- The wall-clock receipt (A's client against `act_ms`, by cue and by the near tier with the law off), the tick spacing, the tick count and the 1-minute load go to `cues.json` `measure` and are printed. They are not checked.

Run `client-gf1` (default world, staged genesis, launched fresh): 22 of 22 PASS at load 3.9.
- Cue lateness: 0.18–0.9 ticks (p50 0.66; tick spacing 16.667 ms over 1,079 ticks).
- Receipt by cue: 20–34 ms. Receipt by the near tier, law off: 20–52 ms.

Not done: a mutation run of the new tick check (a module that writes the cue a few ticks late). The old wall-clock check had none either.

`maintain-verification-skill`, scoped to this case:
- `features/perception.md` (the `cues.py` paragraph) now states the tick and order checks and the measurement.
- No other page states the old bounds for this case. `SKILL.md`, `triage.md` and `perception.md`'s general "within 100 ms" lines describe frame delivery, not this case.
- Not covered: the scene gate's run of case `cues` (the coordinator's gate runs it), and the game client.

Evidence: `.local/living/verify/client-gf1/` (`cues*.jsonl`, `cues.json`; worktree, not in git).
