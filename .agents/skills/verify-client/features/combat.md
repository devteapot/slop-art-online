# Combat tables and views

What a client receives of fights (docs/COMBAT.md). The fixed suite (`drive.py`) checks it with three identities and anonymous.

## Sub-features

- `combat_seen`, `missile`, `skill_use` and `readiness` are private: subscriptions and HTTP SQL are refused (part of the private-table inventory, `visibility.json`).
- `my_combat` (per-sender view): each player's refused strike (`use_skill("strike", 0, 0, 0)` in the reducer matrix) arrives as a `REFUSED` row in that player's view only; every row's `viewer` is the caller; anonymous receives none (`combat-*.json`).
- `my_skill_uses` (per-sender view): only the caller's characters' uses, with the refused strike recorded (`accepted_ms` 0, outcome `refused: …`); anonymous receives none.
- `fighter` and `skill_card` are public (`combat-public.json`; `skill_card` holds 6 rows).
- `use_skill` and `release_skill` succeed for any identity with a living character (refusals are data, not reducer errors) and are refused "you have no living character" without one (`reducers.json`).

## Gotchas

- `my_combat` rows expire 4 s after they happen; probe right after the reducer matrix.
- Event tables were not used for the feed: RLS is unimplemented in 2.14.1, so a public event table would broadcast to anyone (docs/COMBAT.md).
- The game client subscribes `my_combat`, `my_readiness` and `skill_card` with its connection and `fighter` through its body window join; [game-client.md](game-client.md) measures those bytes.
