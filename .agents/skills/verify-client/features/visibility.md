# Table visibility

## Sub-features

- Refuse anonymous WebSocket subscriptions and HTTP SQL reads of every private table: the authority's bookkeeping, the private combat tables and, since 2026-11-09, developer audit truth (minds' state, thoughts, beliefs, personas, relations, judgments, routines, genomes, backgrounds, the chronicle, `stats`, offers, communities, `activity`, `practice`, `artifact`) and `perceived` (docs/PERCEPTION.md), and since town life layer 2 households' guests (`guest`) and, since 2026-11-11, people's daily rhythms (`rhythm`), which the player is refused too. `PRIVATE` in `drive.py` lists them; its inventory check fails when `tables.rs` adds a private table the list lacks.
- In a `scoped` build (the default), refuse the same to the nine tables behind the perception views (`SCOPED` in `drive.py`: `body`, `character`, `fighter`, `doing`, `vitals`, `experience`, `place`, `inventory`, `know_how`), for anonymous and for a player identity.
- Refuse a player's subscription and HTTP SQL to the scoped tables and to `thought`, `belief`, `persona`, `mind_state`, `perceived`, `projected`, `presence`, `woken`, `prior`, `prior_head`, `guest` and `player`: a player is not the owner.
- `thought` (raw model replies included) is refused anonymously in every build; the owner still reads the scripted raw markers (`owner-thought.json`).
- `experience` is refused anonymously in a scoped build. In an open build (`LIVING_PERCEPTION=open`, diagnostics) it is public, and the driver records the known issue as `XFAIL` (`privacy-experience.json`); `open-build-tables.json` proves the nine tables are public there.
- A world's own law values (`world_law`: its seed's `rules`, kept when the world is made; since `laws-2`, docs/WORLD_RULES.md) are private in every build; minds and players are told the laws in words, not the table.
- Speech (docs/COMMUNICATION.md, since `speech-1`): `heard` (who heard each line: `line`, `speaker`, `way`, `hearers`, `at_ms`) is private in every build, and a speaker's person reads its own rows through the per-sender `my_heard` view (a point lookup on `heard.speaker`). The driver checks each player identity's `my_heard` holds only its own lines (`speaker` among its characters) and is not empty after it spoke, and that an anonymous client gets none. `speech_card`, the ways of speaking from the script, is public like `skill_card` (`speech-card-public.json`).
- The world's records (`record`, `record_party`, `record_clock`, since `rules-2`, docs/WORLD_RULES.md) are private in every build: a player reads its own characters' records through the `my_records` view, and verify-player `deal.py` proves the view's rows; this driver proves the tables are refused.
- Record the exact transport-specific refusal for each table.

## How to get to it (user POV)

A client submits `SELECT * FROM <table>` on its connection. Table visibility is enforced by the authority: a private table is "Visible only to reducers and the database owner" (2.14.1 resolves table names through the caller's read access, `crates/engine/src/sql/ast.rs`), independently of any client-side filter.

`living/authority/src/tables.rs` declares the private tables without `public`. The scoped ones are declared twice under `cfg_attr(open_tables, …)` (public) and `cfg_attr(not(open_tables), …)` (private); `living/authority/build.rs` sets `open_tables` only for `LIVING_PERCEPTION=open`; unset or `scoped` is the scoped build.

## Driving it with drive.py

```bash
LIVING_PERCEPTION=scoped .agents/skills/verify-client/scripts/run.py --run "$R"
```

Read `visibility.json` and `private-<table>.json` (and `private-player-<table>.json`). Every subscription must be `rejected` with an error containing `private`. Every anonymous HTTP query must return a non-200 status and a private-table error; a player's HTTP query must return a non-200 status. Each check uses a separate connection.

The driver stops before driving if the private, scoped or view inventory in the source differs from its lists. Update the lists, this file and the views' feature map together.

## Gotchas

- `XPASS` on the open build's experience check means it is no longer public there: update the expected-fail policy and the compatibility notes (docs/PERCEPTION.md) together.
- Inspector filters are not permission checks. Another client can omit them.
- The owner's evidence holds perceptions and scripted reply detail from a scratch world. It remains under `.local/`.
- `resource_node`, `structure`, `gate` and `terrain_chunk` stay public world data; their live state (amounts, owners, a gate's last opener) is readable beyond sight (docs/PERCEPTION.md).
- Since 2026-11-11 (`goods-1`) that live state includes whether a fire burns, `structure.lit_until_ms` (lit while it is ahead of the clock), and a fishing ground's shared stock, `resource_node.pool` (the node holding it). A fire's fuel is not kept as items, because `inventory` is private in a scoped build. `drive.py` checks both columns reach anonymous SQL (`fire-signal.json`, "fire and shared-stock signals public to anonymous SQL").
