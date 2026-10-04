# Behavior graphs

## Sub-features

- Parse compact and canonical graphs, priorities, sequences, guards and labels.
- Normalize slipped forms and report invalid paths or pruned branches.
- Restrict skills to a body's species.
- Parse and expand routines and desires; rework a routine.
- Evaluate installed work sequences, threatened and hurt guards, and locomotion.

## How to get to it (user POV)

Installed graphs run beneath slow deliberation. Parsing lives in `living/rules/src/graph.rs:380`, normalization in `normalize.rs:49`, and evaluation in `living/authority/src/brain.rs:80`. Admin scenes install graphs through `set_behavior`.

## Driving it with Cargo and existing drivers

Run Cargo, mechanics and steering from [SKILL.md](../SKILL.md). Cargo names each parser and normalization test. Mechanics drives write, give, read and craft in sequences; threatened and hurt guards yield; rework installs a new routine and refuses premature revision. Steering drives consecutive walks to their endpoint.

## Gotchas

- Keep pure-rule transcripts and actual-authority outcomes. Neither replaces the other.
- `set_behavior` calls `graph::parse` through `living/authority/src/mind.rs:265`. `living/rules/src/graph.rs:385` calls `from_value_lenient` and discards warnings. Normalization can rewrite or prune the request before validation. Read back `brain.graph` after installation and `routine.graph` after rework whenever that can change a scene. The scene helper and recorder retain these rows. Do not infer the installed graph from reducer acceptance.
- A replacement graph can adopt a compatible activity. Changing a 120-second wait to three seconds may retain its old timer. The tick fixture changes to rest first.
- Not every condition, target selector or reflex interruption has an authority scene.
