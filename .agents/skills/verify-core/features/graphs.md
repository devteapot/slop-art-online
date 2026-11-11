# Behavior graphs

## Sub-features

- Parse compact and canonical graphs, priorities, sequences, guards and labels.
- Normalize slipped forms and report invalid paths or pruned branches.
- Restrict skills to a body's species.
- Parse and expand routines and desires; rework a routine.
- Evaluate installed work sequences, threatened and hurt guards, and locomotion.
- An action refused as it would start (`act::begin` returns why) is a failure like one after starting (`act::refused`): it counts in its routine's `routine_stat` with the reason and in `mind_state.fails`, and the character is told ("You failed to …"), once per `repeat_failure_s` for the same action and reason: an AI character, or a person playing it (since 2026-11-11, `act::tell`, the same words; `verify-player` `told.py`). A guard's first choice refused on every look while its fallback runs counts once a window.
- `judged`: read a cached typed judgment from the private `judged` table (written by the mind service's `mind_judged`), comparing its value (`above`, `below`) or choice (`is`); with none, or an expired one, the condition is its `else` (default false). It never waits on the mind (docs/MIND_HARNESS.md, item 4).

## How to get to it (user POV)

Installed graphs run beneath slow deliberation. Parsing lives in `living/rules/src/graph.rs:380`, normalization in `normalize.rs:49`, and evaluation in `living/authority/src/brain.rs:80`. Admin scenes install graphs through `set_behavior`.

## Driving it with Cargo and existing drivers

Run Cargo, mechanics and steering from [SKILL.md](../SKILL.md). Cargo names each parser and normalization test. Mechanics drives write, give, read and craft in sequences; threatened and hurt guards yield; rework installs a new routine and refuses premature revision. Steering drives consecutive walks to their endpoint.

`scenes.py refusal` gives a person the routine `snack` (eat cooked meat it does not carry) in a `seq` that retries it, and checks after 10 s that `routine_stat` counts the refusal with its reason, that the person was told once, and that `fails` counts it. Before 2026-11-10 a refusal at start left no trace while the graph retried every second.

## Gotchas

- Keep pure-rule transcripts and actual-authority outcomes. Neither replaces the other.
- `set_behavior` calls `graph::parse` through `living/authority/src/mind.rs:265`. `living/rules/src/graph.rs:385` calls `from_value_lenient` and discards warnings. Normalization can rewrite or prune the request before validation. Read back `brain.graph` after installation and `routine.graph` after rework whenever that can change a scene. The scene helper and recorder retain these rows. Do not infer the installed graph from reducer acceptance.
- A replacement graph adopts the activity in progress only when skill, target, item and amount match (since 2026-11-10; before, a three-second wait replacing a 120-second one kept the old timer). The tick fixture changes to rest first.
- Not every condition, target selector or reflex interruption has an authority scene. `judged` has a rules test (`judged_reads_a_cached_value_or_its_fallback`) and an authority scene in verify-minds (`jev`: the cached 0.9 takes the flee branch).
- Evaluator timer marks for root completion, failure and reflection use `0xFFFE`, `0xFFFD` and `0xFFFC`. `brain.rs` preserves those evaluator-owned marks while merging speech and signal marks written during evaluation. A graph replacement clears both graph-node marks and evaluator timers. Dropping these marks previously refreshed pending reflection requests about every two seconds after the reflection period elapsed. The infant verification work retains before/after authority evidence for this defect in its validation record.
