# Deliberate acts

## Sub-features

- A gift completes while a rest graph waits and reports success.
- Two conception acts create a pregnancy.
- Missing know-how produces failure feedback with a reason.
- Real-time behavior is rejected as a one-off act.
- Rework creates a routine and refuses premature revision.
- A mind's act decided while one of its acts runs waits for it in `act_queue` (as shipped), or, under the value-only law `mind_act_replaces`, replaces it exactly as a player's `human_act` does ([below](#mind-acts-replace)).
- A target `{"id": n}` is what the scene lists under that id: a creature first, else a structure or a resource in sight (`brain.rs` `visible_thing`, since `feedback-1`). A depleted bush still resolves, so the gather rule answers ("the berry_bush is depleted"); only a thing out of sight is "no #n in sight". Proved through a real mind in `verify-minds` `acts`.

## How to get to it (user POV)

Controllers submit one-off interactions above the behavior graph. Queueing and outcomes live in `living/authority/src/acts.rs` (`submit_player` for `human_act`, `submit_mind` and `submit_checked` for `mind_act` and `mind_act_checked`, all through `submit_inner`; `next_reporting` starts the next; `outcome` tells how one went). `living/rules/src/acts.rs:16,35` defines real-time exclusions and single-node parsing.

## Driving it with mechanics and Cargo

Run mechanics and Cargo from [SKILL.md](../SKILL.md). The five `act:` results check gifts, mutual conception, failed teaching, rejected fleeing and rework. Keep reducer arguments and experience SQL in `stdb-actions.jsonl`. Cargo checks single-node validation and serialization round trips.

## Mind acts replace

`scenes.py act_replace --run "$R"` (default seed, about 1 min): a spawned person walks 29 m on a mind's act, and 1 s later decides a walk back. With `mind_act_replaces` off the second waits in `act_queue` until the first ends, whose outcome is told. On, a batch of two walks and then a third replace the walk under way at once (the activity's `started_ms` changes in the same call), drop what waited and tell nothing of the broken-off walks; a gaze change and an act that cannot be read replace nothing. The law is set back off. The `place_at` that starts each walk breaks off a walk still under way, told (`act::relocated`), so the scene counts told lines after it.

The diagnostic law `latency_acts` logs each act's course (`input_latency act_submit`, `act_dropped`, `act_queued`, `act_started`, `act_replaced`, `act_done`, `act_refused`, `act_expired`, `act_set_aside`) for every character; `living/tools/act_trace.py capture|report|firstwrite` reads them from the replica's module log.

## Act replacement gaps

`scenes.py act_gaps --run "$R"` (default seed, about 1 min; verify-player `act_gaps.py` drives the same through `human_act`) holds `mind_act_replaces` on and drives a spawned person through `mind_act`, each law beside its control:

- `act_replace_checks` (on as shipped): a walk under way, then "eat cooked_meat" the person does not carry. On, the walk keeps its `started_ms` and the refusal is told ("What you had decided did not work out: eat cooked_meat: no cooked_meat in your pack …"). Off, the walk is gone (broken off before the check) and the same refusal is told. The replacement goes through `act::begin` with the act under way as its current activity, so every check before the start (combat timing, the skill's check for an act that starts here, sight, reach, the intent checks) runs before the break. An act that walks to its target first is checked when it arrives, as a graph's is.
- `act_input_cost` (on): 40 `mind_act` calls sent at once over HTTP are cut at the input bucket (`input_burst` 15 plus `input_hz` 30/s refilled during the burst; on the Spark 15 accepted, 25 refused "too many inputs" in about 22 ms), and an act goes through a second later. Off, all 40 go through. A refused call writes nothing (`mind_act_checked` returns the same error).
- `act_turned_back` (on): seven walks, each given up within 0.4 s for one the other way. On, the sixth is told once as a `self` line, "You keep turning back and forth (…, then …, over and over) without getting anywhere." Off, nothing is told (and nothing is counted, so the law-off part runs first).
- `act_same_continues` (off as shipped): the same walk again 1 s into it. On, its `started_ms` is unchanged; off, it starts over.

Every law is set back to its shipped value at the end, `mind_act_replaces` off.

## Gotchas

- Reducer acceptance queues intentions. Read inventory, pregnancy, routines and actor feedback to prove outcomes.
- Admin walkers stand in for minds. This does not prove model interpretation or non-admin `human_act`.
- Reflex interruption, queue overflow and approach timeout are not driven. Expiry (120 s in the queue) is seen in `act_town.py`'s law-off runs, not asserted.
