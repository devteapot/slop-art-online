# neural-body-pilot: memory, roles and traits (follows 2026-11-26-2320-neural-body-pilot.md)

Branch `neural-body-pilot` at `a8b4763df`, private server `slop-nbpilot-1127` (2.14.1), CPUs 0-4,10-14, fake model only. The design input relayed on 2026-11-26 (`~/slop-mq/notes/neural-body-suarez-input.md`) changed the shape: `body_slot.role`, `body_brief.traits` (and `BodyBriefIn.traits`), a per-character `policy::Memory` (recurrent state 16, intent history 4×8) reset on a new epoch or brief revision, one shared policy per role, and new capture records (`layout`, `memory`; `flat`, `memory`, `memory_after`, `role`, `policy_version`, `intent_encoded` in `decision`).

| Check | Result |
|---|---|
| `living-mind` cargo tests (`body::`) | 12 passed (memory reset and size, seeking a target out of sight, the memory clock at the wall clock's size) |
| `delegate-body` (`minds-dbody-011829-delegate-body`) | **35/35**: the 32 before plus the flat input equal to the encoded vector then the memory read, role and policy version in every decision with the brief's two traits, a memory reset at each epoch (3 and 4); brief refusals now include traits out of range and more than 8 |

Earlier attempt (kept): `minds-dbody-001542` failed 3 of 35: the placeholder kept its clock base in an f32 state slot, which at the wall clock's size (about 1.8e12 ms) lost about 100 s, so after one press it never pressed again in the window (fixed: `Memory::t0_ms`, a u64; test `the_memory_clock_holds_at_the_real_clock_s_size`); and epoch 2's `human_move` south was refused, its reply not recorded (the probe now moves east and records the reply: 200).
