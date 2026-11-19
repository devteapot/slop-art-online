# Combat tables and views

What a client receives of fights (docs/COMBAT.md). The fixed suite (`drive.py`) checks it with three identities and anonymous.

## Sub-features

- `combat_seen`, `fight_seen` (the blows onlookers saw, waiting to be folded into their lines; docs/BATTLE_SCALE.md fix 4), `missile`, `skill_use`, `readiness` and `skill_code` (the stable presentation codes, docs/COMBAT.md) are private: subscriptions and HTTP SQL are refused (part of the private-table inventory, `visibility.json`). Clients read codes from `skill_card` and `act_card`.
- `my_combat` (per-sender view): each player's refused strike (`use_skill("strike", 0, 0, 0)` in the reducer matrix) arrives as a `REFUSED` row in that player's view only; every row's `viewer` is the caller; anonymous receives none (`combat-*.json`).
- `my_skill_uses` and `my_readiness` (per-sender views): only the uses and readiness of the character the caller plays now, while it lives (nothing after its death), with the refused strike recorded (`accepted_ms` 0, outcome `refused: …`); anonymous receives none.
- `skill_card` is public, and `fighter` too in an open build (`combat-public.json`); in a scoped build `fighter` is private and a player receives its own fighter row through `my_fighter` and the fighters it perceives through `seen_fighters` (frame copies of others only; [perception.md](perception.md)). `skill_card` holds one row per combat skill the installed script declares (`<skill>_combat()`: 13 with `living/scripts/skills.rhai`, at least the six on the bar), each with its bar `slot` (255 off the bar), presentation `code`, `aim`, `reach`, missile `radius`, guard `arc`, the bar's `needs`/`knows` hints, and since `stamina-1` the `pool` its `cost` comes from (`stamina` for the body's moves, `focus` for fire bolt and heal; checked with the dodge's cost of 20, `combat-public.json`). Clients name `fighter.act` and `combat_seen.skill` by `skill_card.code`; codes are stable across script installs (private `skill_code`), but they are the world's, not fixed numbers: read them from `skill_card`.
- `use_skill` and `release_skill` succeed for any identity with a living character (refusals are data, not reducer errors) and are refused "you have no living character" without one (`reducers.json`).

## Gotchas

- `my_combat` rows of the two involved and a refusal stay 4 s, an onlooker's 300 ms from its frame (since 2026-11-10); probe right after the reducer matrix. A join clears the player's earlier rows, its death screen included.
- Event tables were not used for the feed: RLS is unimplemented in 2.14.1, so a public event table would broadcast to anyone (docs/COMBAT.md).
- The game client subscribes `my_combat`, `my_readiness` and `skill_card` with its connection its own fighter through `my_fighter` and the fighters it perceives through `seen_fighters`; [game-client.md](game-client.md) measures those bytes.
- `my_combat` tells an onlooker only within its own sight and with a clear sight line to where it happened (`combat::show`, `perception::in_sight`, the rule minds' percepts use), at its next frame (rows kept 300 ms); the two involved get theirs at once.
