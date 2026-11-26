# give-out-of-sight-line: a leaf's activity that loses its target is told

Branch `give-out-of-sight-line` from origin/main `b78c59653`, built from the WIP commit `93ac719da`, whose `living/` is identical to the final commit. Spark (aarch64), private server `slop-tgm-20261126` (SpacetimeDB 2.14.1, `127.0.0.1:3591`). Builds through `build-slot` with a private `CARGO_TARGET_DIR`; launches under `trial-activity.lock`; worlds deleted by `verify.py cleanup`. No mind service, no model calls.

**Rule changed.** In `Node::Do` (`brain.rs`), when the leaf's target no longer resolves while the leaf's own activity is being performed and not committed, `act::lost` breaks it off. The break counts against its routine and is told through `report`, with the once-per-`repeat_failure_s` rule. It uses steering's words, "lost sight of them" ("lost sight of it"), with code `unseen`, or otherwise the resolver's words and code. The leaf's result is not left to be read a second time. Other `why = None` cancels were checked and left untold, because each is a choice the character or its person made or an event told another way:

- `Ev::after`: a branch losing priority or a new plan;
- `acts::submit_inner` and `act::begin_with`: a replacement;
- `presence` handback: the person takes the character back;
- `act::let_go`: a guard released;
- `perceive::wake_body`: told "You woke up: …".

| Check | Result |
|---|---|
| `just living-check` (`~/slop-tgm-logs/a-check.log`) | ok in 3138 s; authority-tests 58 passed, including `brain::tests::a_lost_target_is_told_what_happened` |
| `scenes.py truthful_refusals` (`core-tgma-185502`) | **26/26** |
| `scenes.py refusal` (`core-tgma-185502`) | **4/4** |
| verify-player `told.py` (see that skill's record of the same name) | 28/28 on the branch; on origin/main its new part fails, with no line for 10 of 10 graph gifts lost from sight |

Evidence: `.local/living/verify/core-tgma-185502/`.

**Not covered:** the scene gate's full groups; det_compare (the change alters outcomes only when a performed activity's target is lost, which no seeded scene drives deterministically).
