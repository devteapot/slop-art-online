# The learned-body pilot's plumbing

docs/NEURAL_BODY.md, "Built (pilot plumbing)". Behind the value-only law `body_delegate_on` (off as shipped). Case `body` (`scripts/verify_minds.py`), on the default seed, no model for the body: the scripted `HoldDistance` placeholder in the real `living-mind body` worker, and the real mind with the fake model for the read-back.

## What a user (here: a mind and its body controller) sees

- With the law off, a graph holding a `delegate` leaf is refused at install with the law's words, a brief is refused with them, and nothing is written.
- With the law on, a mind-driven character's graph may hold a `delegate` leaf: while it runs, the leaf stands in the private `body_slot` (goal, target, skill scope) and the character's movement and combat inputs come from a body controller session.
- The mind's brief (`mind_body_brief`) is refused truthfully: a stale revision, an unknown goal, a value out of range, a lifetime past `body_brief_max_s`, a target not perceived now (the same words for a hidden creature and an id that does not exist), a caller that does not control the character. An accepted brief holds the next revision.
- A body session is an identity of its own bound by the controller (`body_open`, epoch 1, 2, …). It sends `human_move`, `human_face`, `use_skill`, `release_skill` as a player would; a skill outside the leaf's scope is refused; it reads its own character's `my_body` and none of the private body rows. A newer epoch fences the older identity ("you hold no body session"); a session left without beats lapses ("lapsed") and its character stands.
- The worker drives a duel against an R2-heavy-like spear foe: every skill use of the subject in the window has `source = body`, some are accepted, the subject moves, and its plan stays the installed one. A SIGSTOP past the lease lapses the session and the subject stands with no new inputs; on SIGCONT the worker opens a new epoch with a new identity and inputs resume. Its capture holds `decision`, `reply`, `outcome` and `session` records, each decision's encoded vector of the fixed length; no reply to the old epoch after the resume is an acceptance.
- The owning mind's think prompt has "# Your body" with the accepted brief ("What you asked of your body (revision 1): engage …"); whether the delegated step is shown depends on when the scene was taken (recorded, not asserted).

## Run

```bash
flock -s ~/slop-mq/trial-activity.lock .agents/skills/verify-minds/scripts/verify_minds.py --run minds-body-$(date +%H%M%S) --case body --no-unit-tests
```

Evidence: `body-checks.json` (each check and the brief refusals), `body.log` (the worker), `capture/` (the worker's records), `body-prompt.txt` (the read-back prompt), the SQL snapshots.

## Source

`living/authority/src/delegation.rs` (law, tables' writers, reducers, lease pass, read-back note), `brain.rs` (`Ev::delegate`, the after-step), `lib.rs` and `combat.rs` (the player reducers' `input_for`), `perception.rs` (`current`, `sweep_viewer_now`), `combat.rs` (`viewer`, `viewers`), `living/rules/src/graph.rs` (`Node::Delegate`), `living/rules/src/body.rs` (the brief's checks), `living/mind/src/body/` (worker, encoder, policy, capture), `living/mind/src/prompts.rs` (`body_section`).

Unit tests: `living_rules::body::tests`, `living_rules::graph::tests::a_delegated_leaf_parses_validates_and_describes_its_scope`, `living-mind` `body::encode::tests` (the leakage tests), `body::policy::tests`, `body::capture::tests`, `prompts::tests::the_body_section_shows_the_brief_the_leaf_and_a_body_not_answering`.
