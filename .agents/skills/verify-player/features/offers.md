# Trade offers a player receives

Since 2026-11-11 (branch `rules-offers`; docs/PERCEPTION.md "Offers"). A trade offer (`offer` act: give `item` × `qty` for `want` × `want_qty`) is a private `trade_offer` row. A player reads the offers addressed to its living character, and its own standing one, through the `my_offers` view; nothing else of the table.

## Sub-features

- An incoming offer: `incoming` true, `from` the maker's character id (named through `seen_characters`; no name in the row), `to` the player's, the goods both ways, `at_ms`, and `until_ms` = `at_ms` + the `trade_window_s` law (180 s by default), fixed when the offer is made. The player is also told it in `my_experience` ("A stranger offers you 2 wood for 1 berries.").
- An outgoing offer: the player's own, `incoming` false. A new offer replaces the maker's earlier one.
- Accepting: the `accept` act toward the maker (`{"do": "accept", "target": {"id": FROM}}` through `human_act`). Refused with the rules' words when either side lacks the goods, or "they have no standing offer for you" after `until_ms`; the offer then stands. Accepted, the goods move both ways in one transaction and the row goes. `accept_done` takes a proposal record of terms from the same person first (`proposal_from`, the dealings), and the standing trade only when there is none.
- Declining: there is no act. An offer ends at `until_ms` (housekeeping deletes it within a second) or when its maker offers again.

## How to get to it (user POV)

A resident offers something to the player's character. The client subscribes `SELECT * FROM my_offers` and shows the row; the player accepts with the `accept` act toward that person.

## Driving it with offers.py

```bash
V=.agents/skills/verify/scripts/verify.py; R=player-offers-$(date +%m%d-%H%M%S)
$V launch --run $R && $V doctor --run $R
.agents/skills/verify-player/scripts/offers.py --run $R    # 17 checks; RUN/offers.json
$V cleanup --run $R
```

Admin calls set the scene: `spawn_crowd` (the resident), `set_behavior`, `place_near`, `grant_items`, and `mind_act` for the resident's offer, as a mind would act. The second player is a fresh identity joined over HTTP (its token in memory only). Every player read is the player's own SQL on its views; the owner's read of `trade_offer` only confirms what the authority holds.

## Gotchas

- Expiry past the 180 s window is not waited for by the script. On `player-offers-1111-183948` the second player's offer (until 18:44:15) was gone from `trade_offer` at 18:46 (`expiry-after-window.json`).
- A refused `accept` is told as "What you had decided did not work out: accept → person: you don't have 1 berries."; the HTTP call itself returns 200 (the act was accepted for execution).
