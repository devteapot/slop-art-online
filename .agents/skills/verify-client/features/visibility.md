# Table visibility

## Sub-features

- Refuse anonymous WebSocket subscriptions and HTTP SQL reads of every private table: the authority's bookkeeping, the private combat tables and, since 2026-11-09, developer audit truth (minds' state, thoughts, beliefs, personas, relations, judgments, routines, genomes, backgrounds, the chronicle, `stats`, offers, communities, `activity`, `practice`, `artifact`) and `perceived` (docs/PERCEPTION.md). `PRIVATE` in `drive.py` lists them.
- In a `scoped` build (`LIVING_PERCEPTION=scoped`), refuse the same to the nine tables behind the perception views (`SCOPED` in `drive.py`: `body`, `character`, `fighter`, `doing`, `vitals`, `experience`, `place`, `inventory`, `know_how`), for anonymous and for a player identity.
- Refuse a player's subscription and HTTP SQL to the scoped tables and to `thought`, `belief`, `persona`, `mind_state` and `perceived`: a player is not the owner.
- `thought` (raw model replies included) is refused anonymously in every build; the owner still reads the scripted raw markers (`owner-thought.json`).
- `experience` is refused anonymously in a scoped build. In an open build it stays public for today's game client, and the driver records the known issue as `XFAIL` (`privacy-experience.json`); `open-build-tables.json` proves the nine tables are public there.
- Record the exact transport-specific refusal for each table.

## How to get to it (user POV)

A client submits `SELECT * FROM <table>` on its connection. Table visibility is enforced by the authority: a private table is "Visible only to reducers and the database owner" (2.14.1 resolves table names through the caller's read access, `crates/engine/src/sql/ast.rs`), independently of any client-side filter.

`living/authority/src/tables.rs` declares the private tables without `public`. The scoped ones are declared twice under `cfg_attr(open_tables, …)` (public) and `cfg_attr(not(open_tables), …)` (private); `living/authority/build.rs` sets `open_tables` unless `LIVING_PERCEPTION=scoped`.

## Driving it with drive.py

```bash
LIVING_PERCEPTION=scoped .agents/skills/verify-client/scripts/run.py --run "$R"
```

Read `visibility.json` and `private-<table>.json` (and `private-player-<table>.json`). Every subscription must be `rejected` with an error containing `private`. Every HTTP query must return a non-200 status and a private-table error. Each check uses a separate connection.

The driver stops before driving if the private, scoped or view inventory in the source differs from its lists. Update the lists, this file and the views' feature map together.

## Gotchas

- `XPASS` on the open build's experience check means it is no longer public there: update the expected-fail policy and the compatibility notes (docs/PERCEPTION.md) together.
- Inspector filters are not permission checks. Another client can omit them.
- The owner's evidence holds perceptions and scripted reply detail from a scratch world. It remains under `.local/`.
- `resource_node`, `structure`, `gate` and `terrain_chunk` stay public world data; their live state (amounts, owners, a gate's last opener) is readable beyond sight (docs/PERCEPTION.md).
