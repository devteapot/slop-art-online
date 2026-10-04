# Table visibility

## Sub-features

- Refuse anonymous WebSocket subscriptions to all ten private tables.
- Refuse anonymous HTTP SQL reads of the same tables.
- Record the exact transport-specific refusal for each table.
- KNOWN ISSUE: an anonymous client currently reads every character's `experience` rows.
- KNOWN ISSUE: an anonymous client currently reads `thought.detail`, including raw replies.

## How to get to it (user POV)

A client submits `SELECT * FROM <table>` on its connection. Table visibility is enforced by the authority, independently of the viewer's selected-character filter.

The private tables are `clock`, `steer`, `wake`, `familiar`, `deliberation`, `rearing`, `act_queue`, `pasture`, `tick_timer`, and `slow_timer`. `living/authority/src/tables.rs:417` declares `experience` public. `tables.rs:588` declares `thought` public. The claim at `tables.rs:3` that percepts are private is contradicted by this access.

## Driving it with drive.py

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

Read `visibility.json` and `private-<table>.json`. Every subscription must be `rejected` with an error containing `private`. Every HTTP query must return a non-200 status and a private-table error. Each check uses a separate anonymous connection.

The intended privacy assertion is that anonymous subscriptions to `experience` and `thought` are refused. It currently records `XFAIL`. `privacy-experience.json` must contain perceptions for more than one observer. `privacy-thought.json` must contain scripted raw marker text for at least three actors. These are real authority rows created by ordinary authorized reducer calls, without model inference.

When either table becomes private, its privacy check becomes `XPASS` and the driver exits 1. Update the expected-fail policy and any affected viewer queries as part of that product fix. A missing marker, transport failure, or empty fixture is a separate `FAIL`.

## Gotchas

- The existing public-table leak is a product issue. This skill does not fix it.
- Inspector filters are not permission checks. Another client can omit them.
- The evidence contains perceptions and scripted reply detail from a scratch world. It remains under `.local/`.
- Both privacy XFAILs track the KNOWN ISSUE in [LIVING_HANDOFF.md, Still open](../../../../docs/LIVING_HANDOFF.md). This skill changes no product code.
