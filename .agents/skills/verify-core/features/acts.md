# Deliberate acts

## Sub-features

- A gift completes while a rest graph waits and reports success.
- Two conception acts create a pregnancy.
- Missing know-how produces failure feedback with a reason.
- Real-time behavior is rejected as a one-off act.
- Rework creates a routine and refuses premature revision.

## How to get to it (user POV)

Controllers submit one-off interactions above the behavior graph. Queueing and outcomes live in `living/authority/src/acts.rs:27,60,100`. `living/rules/src/acts.rs:16,35` defines real-time exclusions and single-node parsing.

## Driving it with mechanics and Cargo

Run mechanics and Cargo from [SKILL.md](../SKILL.md). The five `act:` results check gifts, mutual conception, failed teaching, rejected fleeing and rework. Keep reducer arguments and experience SQL in `stdb-actions.jsonl`. Cargo checks single-node validation and serialization round trips.

## Gotchas

- Reducer acceptance queues intentions. Read inventory, pregnancy, routines and actor feedback to prove outcomes.
- Admin walkers stand in for minds. This does not prove model interpretation or non-admin `human_act`.
- Reflex interruption, queue overflow, expiry and approach timeout are not driven.
