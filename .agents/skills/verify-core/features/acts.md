# Deliberate acts

## Sub-features

- A gift completes while a rest graph waits and reports success.
- Two conception acts create a pregnancy.
- Missing know-how produces failure feedback with a reason.
- Real-time behavior is rejected as a one-off act.
- Rework creates a routine and refuses premature revision.
- A target `{"id": n}` is what the scene lists under that id: a creature first, else a structure or a resource in sight (`brain.rs` `visible_thing`, since `feedback-1`). A depleted bush still resolves, so the gather rule answers ("the berry_bush is depleted"); only a thing out of sight is "no #n in sight". Proved through a real mind in `verify-minds` `acts`.

## How to get to it (user POV)

Controllers submit one-off interactions above the behavior graph. Queueing and outcomes live in `living/authority/src/acts.rs:27,60,100`. `living/rules/src/acts.rs:16,35` defines real-time exclusions and single-node parsing.

## Driving it with mechanics and Cargo

Run mechanics and Cargo from [SKILL.md](../SKILL.md). The five `act:` results check gifts, mutual conception, failed teaching, rejected fleeing and rework. Keep reducer arguments and experience SQL in `stdb-actions.jsonl`. Cargo checks single-node validation and serialization round trips.

## Gotchas

- Reducer acceptance queues intentions. Read inventory, pregnancy, routines and actor feedback to prove outcomes.
- Admin walkers stand in for minds. This does not prove model interpretation or non-admin `human_act`.
- Reflex interruption, queue overflow, expiry and approach timeout are not driven.
