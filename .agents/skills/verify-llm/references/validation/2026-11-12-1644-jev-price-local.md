# verify-llm: jev-price-local (Jev's price from a local file)

- **Branch:** `jev-price-local`, based on main `1cffc5b6`; the tree that this record is committed with.
- **Server:** the Spark's trials container `slop-trials-stdb` (`http://127.0.0.1:3320`).
- **Mind:** release `living-mind` from this tree, `CARGO_TARGET_DIR=~/slop-jevprice-target`.

## Runs

- `llm-jevprice-20261112-172024`, the full local tier. It ran at the same time as the verify-minds suite above.
  - Pass: the fake contract, the cargo tests, `basic`, the five routing cases, `missing-default-key`, `overflow`, `capacity-overflow`, `capacity-retry`, `retry-fallback`, `error-overflow`, `outage`, `repair`, `deliberation-retry`, `retry-exhausted`, `timeout`, `mix` and `fast-route`.
  - **Fail: `fast-cap`.** At most 4 calls started in one second, where the case allows 3. Its other caps held: 4 issued at once and 4 in flight at the provider. There were 29 calls and 17 of 20 fighters got one.
- `llm-jevprice2-20261112-173920`, `fast-cap` and `fast-route` alone.
  - `fast-route` passed.
  - `fast-cap` failed the same way: 4 starts in one second, 26 calls.
- **Control on main:** `llm-mainctl-*`, `fast-cap` alone from a clean detached checkout of `origin/main` 9fa0d254, with its own target dir. It failed the same way: 4 starts in one second, 31 calls.
  - So the failure is on main and not from this change.
  - The last record that passed is 2026-11-12-1054-fast-lane.md (at most 3 in a second). Something merged since then, or this host, has changed the burst. Not diagnosed here.

## What this change touches

The Jev price leaves `rethink.json` and `judgments.json` for an untracked local file (`living/mind/src/prices.rs`). The models file format (`models.json`) is unchanged, and so are `llm.rs`'s requests, routing and journals. The judges' cost path is proven in verify-minds (`jev`, `rethink`, `rethink-llm`).
