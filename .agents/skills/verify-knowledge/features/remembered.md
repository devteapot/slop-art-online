# Resources as last seen (`seen_stock`)

Since `talk-places` (2026-11-13; docs/COMMUNICATION.md §20 (b)). What a character has seen of a kind of resource at a spot, and when, from its own looks only (`living/authority/src/stock.rs`, `stock::look`). A mind looks at its noticing (`brain::noticed`), a player's character at its perception sweep (`perception::sweep_one`): one rule. The rows reach a mind's think, deliberate and talk prompts and player memory's internalize prompt (`Minds::places`, verify-minds `talk-places`, `player_memory.py`).

## Sub-features

- **A look** counts every node within sight (`resources_near`, the scene's rule). It runs on coming into another chunk, and otherwise at most every 30 s (`LOOK_MS`).
- **New:** a kind in view with stock that no row holds becomes a row: its nearest 12 bearing nodes (`NODES`), their middle, how many, the time.
- **Still there:** any of a row's nodes in view bearing: `seen_ms` refreshed (at most every 2 minutes, `REFRESH_MS`), `gone_ms` back to 0.
- **Gone:** every one of a row's nodes in view, none bearing: `gone_ms` set, and the character is told once ("Nothing is left to gather on the berry bush around (x, y): 3 had some when you saw them, day N HH:MM.", kind `saw`). Only some in view, all bare: nothing changes.
- **Never from the truth:** stripped out of sight, the row is unchanged.
- **Bounds:** 24 rows a character (`PER_ACTOR`; the longest unseen goes first); deleted at death (`forget_dead`).

## Proof

```bash
V=.agents/skills/verify/scripts/verify.py
R=knowledge-remembered-$(date +%Y%m%d-%H%M%S)
python3 $V launch --run "$R" && python3 $V doctor --run "$R"
python3 .agents/skills/verify-knowledge/scripts/remembered.py --run "$R"
python3 $V cleanup --run "$R"
```

Any seed. The player joins (`takeover_s` set to an hour, so its character stays its own); on an open line with no berry bush within 18 m of its near end, three bushes holding one berry are placed beside it; it steps 43 m off and back (a look). Checks: one row holds the three (count 3, seen, not gone, the middle of the three); stripped by a stranger (`mind_act` gather) while the player is away, the row is unchanged; back, it is gone at the look's time with the count and seen time kept, told once; a fourth bush placed by it is a row of its own and the gone row stays. Evidence: `remembered.json`.

Not covered: regrowth bringing a gone row back (berries regrow 0.6 an hour); the partial-view rule; eviction past 24 rows; the mind path's look (driven in verify-minds `talk-places`).
