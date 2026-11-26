# mind-sex-seen-keyed: a remembered body found by its pair, not by a table scan

Branch `mind-sex-seen-keyed` from origin/main `b78c59653`, built from the WIP commit `95afc18e6`, whose `living/` is identical to the final commit. Spark (aarch64), private server `slop-tgm-20261126` (SpacetimeDB 2.14.1, `127.0.0.1:3591`). Builds through `build-slot` with a private `CARGO_TARGET_DIR`; launches under `trial-activity.lock`; the fake model only, no paid calls.

**Change.** `Minds::known_sex` found a pair with `conn.db.sex_seen().iter().find(..)`. In SDK 2.14.1, `TableHandle::iter` clones every cached row under the client cache's one lock (`client_cache.rs`, versioned source in the cargo registry). The generated `sex_seen` handle has only the `id` unique accessor: the client generates none for the `by_pair` or `known` btree indexes. The mind's `Index` now keeps `(observer, known) → id` from the table's `on_insert`/`on_delete`/`on_update` callbacks. A lookup reads that map, then `sex_seen().id().find`, which clones one row. In 2.14.1 the initial subscription's rows reach `on_insert` too (`DbContextImpl::apply_update` runs the row callbacks for `SubscribeApplied`, after releasing the cache lock). The docs page on subscriptions (https://spacetimedb.com/docs/clients/subscriptions/, version 2.0.0) names the row callbacks but says nothing of client-side indexes or initial rows. The Rust SDK page came back empty. So the source is the evidence here. No table, reducer, view or subscription changed.

| Check | Result |
|---|---|
| `just living-check` (`~/slop-tgm-logs/c-check.log`) | ok in 3157 s |
| mind cargo tests (the suite's `cargo-tests.log`) | 148 passed, 14 ignored, including `mind::tests::the_index_finds_a_sex_seen_pair_by_its_key` |
| `roundtrip` (`minds-tgmc-185606-roundtrip`) | pass |
| `conversation` (`minds-tgmc-185606-conversation`) | pass |
| `body-sex` (`minds-tgmc-185606-body-sex`) | **14/14**, including "remembered: the absent wife is listed with her body" (a `sex_seen` row found through the map) |
| `sex-boundary` (`minds-tgmc-185606-sex-boundary`) | fail before any prompt check: "timed out after 20s waiting for Oren faces along the ray" on the third face attempt. This is authority staging the scene already retries (minds-sex2-f, -g), at host load about 20 |
| `sex-boundary` rerun (`minds-tgmc2-190605-sex-boundary`) | **16/16**, including the mutant without the row |

Evidence: `.local/living/verify/minds-tgmc-185606*/`, `.local/living/verify/minds-tgmc2-190605-sex-boundary/`.

**Other whole-table reads in the mind** (not changed; each clones its table on every call). On growing tables:
- `relation` (7: `mind.rs`, `facts.rs`, `lived.rs`, `talk.rs`);
- `character` (7);
- `place` (5);
- `routine` (5);
- `membership` (6);
- `know_how` (3);
- `judgment` (2);
- `record_party` (2);
- `acquaintance` (2: `knows_name` at `mind.rs:659`, beside this lookup on every `known_person`, and `mind.rs:669`);
- `line_heard` (`talk.rs:1400`);
- `experience` (`mind.rs:1601`);
- `seen_stock` (`mind.rs:2254`);
- `cue` (`mind.rs:2069`);
- `audience` (`talk.rs:865`).

On small tables: `script`, `settlement`, `lot`, `community`, `trade_offer`, `bond_offer`, `relation_fight` and `my_deliberations`.

**Not covered:** the cost itself was not measured (no battle with minds); the subscription's reconnect path was not re-driven.
