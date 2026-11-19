# Seat contact: handoff notes

Status: **proposal, not implemented.** Handed to the laptop coordinator on 2026-11-19 (general coordinator's decision). Order of work: **2a, ground sitting first** (a ground collider plus coat and skirt spring chains), **then chairs** (with authority and seed seat markers). It is client-system work, built by Opus.

- [PROPOSAL.md](PROPOSAL.md): the dev-box design note, verified against the client at `29735dbe9`: where the sitting signal comes from, the proposed seat, back and ground spheres, the timing ramp, the coat chains in `person.py`, and the cost and proof plan.

## Measured garment depths today (generator `cloth_check.py`, 8 sampled frames per clip)

Measured by char-4-detail on 2026-11-19, on main `49adf9a36` plus body-joins `b670baba2` (generator-side, no client contact). How far the outer garment ends up inside the support. The authored panels change none of these: panelled runs match the unpanelled control. The panelled logs are kept beside the control logs.

| Piece | Ground sit: below ground | Chair sit: below seat top | Chair sit: behind seat back |
|---|---:|---:|---:|
| coat-m (Aldric) | 0.0 mm | 79.0 mm | 127.3 mm |
| coat-f (violet coat) | 32.6 mm (78 vertices beyond 5 mm) | 98.8 mm | 115.7 mm (618 vertices beyond 5 mm in one pose) |

Layer crossings during ground sitting on the female coat: trousers through the coat by up to 37.8 mm (8 of 8 poses), the jersey through the coat by 20.6 mm (7 of 8), the jersey through the trousers by 13.3 mm (8 of 8). On the male coat, the jersey goes through the trousers by 7.6 mm in 2 of 8 poses. Full logs: `control-*-seat.log` and `panels-*-seat.log`.

Earlier baselines from the proposal: 85–119 mm into the seat and 113–124 mm behind the back on the chair clips. Target from the proposal: ≤5 mm residual inside the seat and back footprints after settling, no new body intersections, no visible pop.

## What is already on main

- Sitting stage 1 (`0457ec509`): matched hip-zone weights in the 28 outfit files (chair-seated crossings 8 → 2), and the chair in `cloth_check` (`--chair`).
- body-joins (`b670baba2`, not yet on main; folding into the next character bundle): the heavy-build upper-only fit added 0 new crossings in 242 sitting comparisons over 14 wearers.
- Skirt spring chains exist (char-4-skirts, `04b9ccc21`). Coat chains do not yet. The proposal gives the bone layout.
