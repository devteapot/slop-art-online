# Player parity views: `my_kin`, `my_bond_offers`, `my_community` (branch `parity-player-views`)

Follows 2026-11-27-0248-heed-player-3.md. Branch `parity-player-views` from `origin/main` (`e220bea8e`), code commit `75ffbf270`, bindings regenerated via `just living-generate` with pinned `clockworklabs/spacetime:v2.14.1` (probe rebuilt on them); private `parity-views-stdb` (SpacetimeDB 2.14.1 on `:3381`), no model calls.

**Targeted maintenance pass** (`maintain-verification-skill`, scoped to the shape change): added identity-scoped views `my_kin` (`MyKin { id: u32, relation: String }`), `my_bond_offers` (`MyBondOffer { id: u64, incoming: bool, from: u32, to: u32, at_ms: u64 }`), and `my_community` (`MyCommunity { id: u32, name: String, founder: u32, founded_ms: u64, home_x: f32, home_y: f32, since_ms: u64 }`), all using indexed reads (`character.parent_a/b`, `bond_offer.to/from`, `membership.member`, `community.id`) with no whole-table scans. Map updated: `features/perception.md`, `features/README.md`, `scripts/drive.py`, `scripts/probe/src/main.rs`.

| Run | Driven | Result |
|---|---|---|
| `client-parity-scoped-20261127-055153` (`scoped`) | `run.py` | drive **47/47** PASS (incl. 335 reducer permission calls, 118 private tables, `my_bond_offers`, `my_community`, `own-*` with `my_kin`/`my_bond_offers`/`my_community`), cues, near-tier, motion-tables, combat-feed, lines-table, tick-marker 5/5; `cleanup-proof.json` `"pass": true` |

Additional checks:
- `det_compare` (Cullet 200 fighters + 16 players, 3,600 ticks vs `origin/main` `e220bea8e`): **identical** (`ticks_compared: 3600`, `ticks_differ: 0`, `tables_compared: 113`, `rows_compared: 50264`).
- `just living-check`: all 8 steps passed (`authority`, `mind+viewer`, `game`, `game-tests`, `authority-tests`, `viewer-wasm`, `rules-tests`, `script-gate`).

**Not covered:** `LIVING_PERCEPTION=open` diagnostic build; game client UI subscription to the new views (separate client task). Evidence archived to `~/slop-evidence/parity-player-views-20261127.tar.zst`.
