# Anonymous observer subscriptions

## Sub-features

- Connect without a token through the generated Rust SDK.
- Apply the viewer's exact 27-query base set and receive initial rows.
- Receive later `body` and `stats` updates while the authority ticks.
- Apply the inspected-character experience filter, routine filter, and routine-stat join.
- Assert that returned experiences and routines belong to the selected actor and joined stats belong to those routines.

## How to get to it (user POV)

A program connects to the authority without logging in, then subscribes to the tables it wants. The viewer does this in `living/viewer/src/net.rs:192`. Its base query set is at `net.rs:11`. Inspecting a character adds the three queries at `net.rs:158`.

## Driving it with drive.py

With the shared run already launched, checked, and joined as `ClientPrimary`:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

Read `anonymous-base.json`. `status` must be `applied`, `initial.counts.world` must be 1, and `initial.counts.character` must be positive. After four seconds both update counters must be positive and `final.ticks` must exceed `initial.ticks`.

The driver selects a living adult AI person for `inspected-character.json`. It sends exactly:

```sql
SELECT * FROM experience WHERE observer = <actor>
SELECT * FROM routine WHERE actor = <actor>
SELECT s.* FROM routine_stat s JOIN routine r ON s.id = r.id WHERE r.actor = <actor>
```

The recorded actor replaces `<actor>`. Experiences, routines, and joined stats must all be nonempty. No experience or routine from another actor may appear. Each stat id must match one of the received routines.

## Gotchas

- A successful connection is not an applied subscription. Wait for `on_applied` before reading initial rows.
- A row count is not proof of live changes. The probe registers update callbacks before subscription and records both counters.
- The driver stops if the viewer query set differs from its copy. Update the skill with the viewer.
- Full public subscriptions can reveal more than a player should perceive. The visibility feature tracks that defect separately.
- This checks the client cache and protocol, not browser presentation or scale.
