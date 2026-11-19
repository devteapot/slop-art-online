# Cheaper animal minds (`LIVING_ANIMAL_MINDS`)

Two switches, any combination (`salient`, `choose`; empty is the two-call impulse then compile). `pack` (one animal's decision copied to the others it saw) was retired on 2026-11-12 as shared hidden state (docs/PACK_MIND.md); the word is ignored with a warning. Design and measurement: docs/MIND_HARNESS.md, item 3; the tool `living/tools/animal_minds.py` measures calls and tokens per animal-hour for each variant.

## Sub-features

- **choose:** one call (purpose `deliberate`, prompt `prompts::animal_choose_system`) picks a numbered option built from the scene and the species' skills (`animal::menu`: carry on; flee from, hunt or attack the nearest other creatures; keep close to its kind; rest; roam; its signals) and a strength. The graph comes from a template, is weighed by the animal's temperament (`animal::weight`) and goes through `plan_into_desires`, `from_value_for` and `mind_install` like any compiled impulse. An invalid pick carries on.
- **each decides on its own:** every animal's request is answered by its own `choose` call; no thought has `mode: pack` or another animal's `by`, and no choose prompt has a `# Your pack` section.
- **salient:** before any call, the request is compared with the animal's last thought (`animal::Signature`: other kinds seen or smelled, wound band, deaths of its kind it witnessed, hunger band; an attack, a threat or a fight report always counts). Nothing new: `mind_skip` with a thought of kind `instinct` and no call.

Sources: `living/mind/src/mind/animal.rs`, `living/mind/src/prompts.rs` (`animal_choose_*`), `living/mind/src/mind.rs` (`deliberate` dispatch).

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-$(date +%Y%m%d-%H%M%S) --case animals
```

Three adult deer are gathered where the first grazes and a person is placed beside them (animals think only near people), with `salient,choose` and the retired `pack` passed on purpose. The lead's request is answered by one `choose` call with a valid pick and the built graph installed; each of the other two deer's requests is answered by its own `choose` call (three calls in all, none copied); the lead asked again, once its `think_min_s` (240 s) after its chosen option has passed, is answered by instinct. A mind's install counts as having just thought, and within `think_min_s` the authority asks an animal only for urgent reasons, which are all news to the salience check; a fresh deer has not thought, so the first requests go through. (Until 2026-11-11 every request carried a dawn reason, which was urgent; the dawn broadcast is gone.) The fake log must hold one `choose` request by each of the three (whose request it is comes from its prompt's scene, `you.id`) and no compile request; and, after the second ask, still one by the lead (another deer may think again on its own by then).

## Gotchas

- See above for why the lead's second request waits out its throttle (the case takes about four minutes longer).
- **Staging** (`fix-animals-race`, 2026-11-13; it was on the red-on-main list as flaky, main 2 of 3). The scene sets up its own herd so that the last step is reachable: the three are adults with no request to think pending; every other deer is held on `wait` and moved 60 m off (killed if there is no ground there); the three graze twice before the mind starts (hunger rises about 22 over the case's four minutes, and crossing 50 is news); and 12 s before the lead's throttle ends the three stand still and the person stands 4 m from the lead again (its flight ended at the edge of its sight of the person, and a person gone from the scene is news). A call is counted as a deer's only when its prompt's scene is that deer's own. The races these close, each seen on main: a fourth deer on instinct courted one of the three ("asked to start a family"); the three had requests pending from their own instincts ("My actions keep failing (a child is already on the way)"); a deer's own later re-think ("Nothing in my current plan works", its one-step flight over) was counted as the lead's; the person out of sight; the hunger band. Five in a row on main (`minds-an6-main-*`) and five on `pursue-last-seen` (`minds-an6-branch-*`).
