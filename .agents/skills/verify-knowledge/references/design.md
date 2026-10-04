# Knowledge proof design

The run owns one `verify-knowledge-*` database, a labeled throwaway Neo4j container, recorded process IDs and private credentials. The shared harness owns authority lifecycle and player identity. This run object follows the Model the Domain principle by keeping ownership and cleanup state together.

One runner with automatic cleanup was chosen over separate launch and drive processes. It preserves process handles during a normal run and leaves a private state file for interrupted cleanup. Feature assertions remain grouped by the real mechanisms they drive.

The proof reads actor-filtered `know_how`, `practice`, `experience`, projection tables and artifact holders. The existing authority uses `(actor, technique)` and `(actor, skill)` indexes for knowledge and practice, and a holder index for artifacts. Each action writes only its affected rows. Seed and actor listings are explicit diagnostic snapshots. No product storage path changes.

The real mind uses its existing subscriptions, restricted by controller for experiences, and `LIVING_ONLY` limits work to Oren. Cypher targets `(run, actor)`. Scratch data persists only until evidence capture and cleanup. This small workload does not measure subscription bandwidth, retained-data growth or scale.

## Official documentation check

Consulted on 2026-10-04 before implementation:

- [Official documentation](https://spacetimedb.com/docs/) and [tables](https://spacetimedb.com/docs/tables/) describe typed tables, local row operations and durable state.
- [Indexes](https://spacetimedb.com/docs/tables/indexes/) guide lookup paths for actor/technique and artifact holders.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) describe the real SDK subscription boundary. SQL snapshots prove authority state; they do not prove client permission filtering.

The docs display version 2.0.0. The repository pins `spacetimedb` and `spacetimedb-sdk` to `=2.10.1` in `living/Cargo.toml:9`. Shared doctor checks the running server image is v2.10.1. The proof reuses the pinned generated bindings and existing reducers; it introduces no assumed new API.

## Compatibility

The shared skill uses standard frontmatter and runtime-independent shell commands. Codex and Mistral can discover `.agents/skills/verify-knowledge`. The parent provided Claude and Cursor links to this directory. The implementation only writes within this directory. Check frontmatter and those links during validation. Actual skill invocation by all four runtimes remains a separate compatibility check.
