# Cheaper animal minds (`LIVING_ANIMAL_MINDS`)

Three switches, any combination (`salient`, `choose`, `pack`; empty is the two-call impulse then compile). Design and measurement: docs/MIND_HARNESS.md, item 3; the tool `living/tools/animal_minds.py` measures calls and tokens per animal-hour for each variant.

## Sub-features

- **choose:** one call (purpose `deliberate`, prompt `prompts::animal_choose_system`) picks a numbered option built from the scene and the species' skills (`animal::menu`: carry on; flee from, hunt or attack the nearest other creatures; keep close to its kind; rest; roam; its signals) and a strength. The graph comes from a template, is weighed by the animal's temperament (`animal::weight`) and goes through `plan_into_desires`, `from_value_for` and `mind_install` like any compiled impulse. An invalid pick carries on.
- **pack:** the deciding animal's choice is shared, for `LIVING_ANIMAL_PACK_S` (60 s), with the animals of its kind it sees that this service thinks for; their requests reuse it without a call (thought detail `mode: pack`, `by`), each weighed by its own temperament.
- **salient:** before any call, the request is compared with the animal's last thought (`animal::Signature`: other kinds seen or smelled, wound band, deaths of its kind it witnessed, hunger band; an attack, a threat or a fight report always counts). Nothing new: `mind_skip` with a thought of kind `instinct` and no call.

Sources: `living/mind/src/mind/animal.rs`, `living/mind/src/prompts.rs` (`animal_choose_*`), `living/mind/src/mind.rs` (`deliberate` dispatch).

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-$(date +%Y%m%d-%H%M%S) --case animals
```

Three adult deer are gathered where the first grazes and a person is placed beside them (animals think only near people) with all switches on. The lead's request is answered by one `choose` call with a valid pick and the built graph installed; the other two deer's requests are answered from the lead's decision without a call; the lead asked again, once its `think_min_s` (240 s) after its chosen option has passed, is answered by instinct. A mind's install counts as having just thought, and within `think_min_s` the authority asks an animal only for urgent reasons, which are all news to the salience check; a fresh deer has not thought, so the first requests go through. (Until 2026-11-11 every request carried a dawn reason, which was urgent; the dawn broadcast is gone.) The fake log must hold exactly one `choose` request and no compile request.

## Gotchas

- See above for why the lead's second request waits out its throttle (the case takes about four minutes longer).
- Pack members are who the deciding animal sees now; there is no stored pack.
- **Known gap since 2026-11-11:** the last step (asked again with nothing new, it lives by instinct) cannot be reached: only urgent reasons pass the deer's 240 s `think_min_s`, every urgent reason is news to the salience check, and waiting the throttle out makes the deer hungrier (also news). The case removes wolves near the herd and waits the throttle out, and fails there. Proving it needs a fixture with a shorter deer `think_min_s` or a needs scene reducer.
