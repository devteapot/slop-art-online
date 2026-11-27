# relation-fight-prune: mind service keys relation_fight lookups in Index

Branch `relation-fight-prune` from `origin/main` (`18564737a`), Spark (`aarch64`), private SpacetimeDB 2.14.1 container `slop-retfix-20261126` (`127.0.0.1:3621`), fake model only (no paid calls).

**SpacetimeDB 2.14.1 SDK check:** Consulted [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and [Rust client SDK](https://spacetimedb.com/docs/clients/rust/), verified against `spacetimedb-sdk-2.14.1/src/client_cache.rs:445-448` (`TableHandle::iter()` locks the cache mutex and clones every cached row into a `Vec`) and `living/bindings/src/generated/relation_fight_table.rs:179-195` (generated bindings expose only `.id().find(&u64)`, no secondary B-tree accessors).

**Change:** Added `relation_fight: Mx<HashMap<u32, BTreeSet<u64>>>` to `mind::Index` (`living/mind/src/mind.rs`), maintained via `conn.db.relation_fight()` `on_insert`/`on_delete`/`on_update` callbacks (`living/mind/src/main.rs`). `Minds::relations` reads per-actor row IDs from `Index::relation_fight_ids(actor)` and fetches each row with `conn.db.relation_fight().id().find(&id)` instead of `iter()`.

| Check | Result |
|---|---|
| `cargo test -p living-mind -- --test-threads=1` | 149 passed, 0 failed, 14 ignored, incl. `mind::tests::the_index_finds_an_actors_relation_fights_by_actor` (note: parallel run hit pre-existing `LIVING_PLAYER_FRAME` env race in `prompts::tests`) |
| `verify-minds` (`minds-rf-20261126-230823`): `roundtrip`, `conversation` | pass (2/2, fake model) |

**Evidence archive:** `~/slop-evidence/relation-fight-prune-20261126.tar.zst` (+ `.sha256`).

**Not covered:** Paid real-model runs, Neo4j personal memory (`verify-knowledge`), other mind `iter()` sites (`character`, `experience`, `acquaintance`, etc.).
