# Verify client privacy for C2

The `battle-notice-delta` authority at `1a27fe3c` ran in scoped mode on the private Spark container `slop-c2-rebase-stdb` (SpacetimeDB 2.14.1, port 3389). The Rust SDK probe used regenerated bindings with the 2.14.1 SDK. Doctor passed before the queries.

| Identity | WebSocket subscription to `last_look` | HTTP SQL |
| --- | --- | --- |
| Anonymous | Refused as private | Refused (400) |
| Joined player | Refused as private | Refused (400) |
| Database owner | Applied | 200, 267 rows |

The client map and permission inventory now include `last_look`. The inventory matches the private tables declared by the authority. This run exercised the new table with the scoped build. The full client suite, open build and migration of an existing database were outside this focused run.

Evidence is in `.local/living/verify/client-c2-rebase/`, including `last-look-privacy.json` and the three probe results. Shared cleanup paused the world before deletion and confirmed SQL returned 404.

The table is declared private without a scoped-build condition. Its character primary key serves the authority's lookup and update, and it has no player subscription recipients. [Table access permissions](https://spacetimedb.com/docs/tables/access-permissions/), [Indexes](https://spacetimedb.com/docs/tables/indexes/), [Rust bindings v2.14.1](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/bindings/src/lib.rs).
