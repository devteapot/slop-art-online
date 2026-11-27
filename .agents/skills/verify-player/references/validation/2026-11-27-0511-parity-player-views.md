# Player parity views: `my_kin`, `my_bond_offers`, `my_community` (branch `parity-player-views`)

Follows 2026-11-27-0248-heed-player-3.md. Branch `parity-player-views` from `origin/main` (`e220bea8e`), code commit `75ffbf270`, bindings regenerated with pinned `clockworklabs/spacetime:v2.14.1`; private `parity-views-stdb` (SpacetimeDB 2.14.1 on `:3381`), no model calls.

**Targeted maintenance pass** (`maintain-verification-skill`, scoped to the shape change): added `features/kin.md`, `scripts/kin.py`, and entries in `features/README.md` and `SKILL.md` for `my_kin`, `my_bond_offers`, and `my_community`.

Run `player-kin-20261127-055123` (default `world` seed, `scoped`, fresh): `kin.py` **22/22** PASS:
- Courting offer (`conceive` from Wren to Moss): outgoing in Wren's `my_bond_offers`, incoming in Moss's, ids only (no name column), empty for third player Fern and anonymous; `bond_offer` refused to player and anonymous.
- Real birth (via short-gestation `life_years` script overlay, tree script reinstalled in `finally`): accepted offer leaves `my_bond_offers`; newborn appears with `parent_a`/`parent_b`; both Wren's and Moss's `my_kin` list the other as `"partner"` and the newborn as `"child"` with only `id` and `relation` columns; Fern and anonymous see `[]`.
- Community (`found` by Wren): Wren's `my_community` returns `HearthKin` (`founder`, `since_ms`); Moss, Fern, and anonymous see `[]`; `community` and `membership` refused to player and anonymous.
- Admin scene setup calls used: `set_behavior`, `place_near`, `install_script` (restored). Cleanup deleted `verify-player-kin-20261127-055123` (SQL 404).

**Not covered:** `"parent"` role in `my_kin` (newcomers join without parents; exercised by the same `me.parent_a`/`parent_b` code path as `my_known_names`). Evidence archived to `~/slop-evidence/parity-player-views-20261127.tar.zst`.
