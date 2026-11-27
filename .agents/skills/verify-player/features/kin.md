# Player kin, courting offers and community (`my_kin`, `my_bond_offers`, `my_community`)

Since 2026-11-27 (`parity-player-views`, perception-parity phase 0): players have identity-scoped views of their own family, courting offers and community membership — the same facts AI behaviour graphs (`Target::Partner`, `Target::Parent`, `Target::Suitor`, `Weight::Courted`, `membership`) and minds' scenes (`perceive.rs`) already read about their own character.

## Sub-features

- `my_bond_offers` (`MyBondOffer`: `id`, `incoming`, `from`, `to`, `at_ms`): standing courting offers (`conceive`) addressed to the player's living character (`incoming: true`) or made by it (`incoming: false`), read by `bond_offer`'s `to` and `from` btree indexes. Character ids only, no names. `bond_offer` remains private. Players can decline an incoming offer or withdraw their own outgoing offer via `human_act` `decline` (`{"do": "decline", "target": {"id": other}, "bond": id}` or unnamed); the row leaves `my_bond_offers`, the other side is told (`kind = "record"`), and gone/expired/foreign offers are refused truthfully (`bond_decline.py`).
- `my_kin` (`MyKin`: `id`, `relation`): the player's living character's parents (`"parent"`), children (`"child"`), and partner (`"partner"`, the other parent of its youngest child), read by `character`'s `parent_a` and `parent_b` btree indexes. Carries only `id` and `relation` (no `alive`, health or position of unseen relatives; names come from `my_known_names`).
- `my_community` (`MyCommunity`: `id`, `name`, `founder`, `founded_ms`, `home_x`, `home_y`, `since_ms`): the community the player's living character belongs to (0 or 1 row), read by `membership.member` (unique) and `community.id` (primary key). `community` and `membership` remain private.
- All three views return empty for other players (who are not a party/member/kin) and for anonymous clients.

## Driving it

```bash
.agents/skills/verify-player/scripts/kin.py --run "$R"
.agents/skills/verify-player/scripts/bond_decline.py --run "$R"
```

On any launched run (`$V launch --run $R`). Joins three players (`Wren`, `Moss`, `Fern`), holds them with admin `set_behavior` and places `Moss` near `Wren` with `place_near`, installs a short-gestation `life_years` overlay via `install_script` to observe a real birth, and reinstalls the tree's `skills.rhai` in `finally`. Writes `RUN/kin.json`.
