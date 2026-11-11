# Offers to me

Each standing swap offered to me (`my_offers`, `incoming`) and each proposal of terms (an open `agreement` record in `my_records`, `offered`, where I am `to`) is a card in its maker's person window, oldest first, at most three. A new one opens their window when the left anchor is free (or holds Log and people) and is noted ("A stranger in green offers you 2 berries for 1 wood."); terms are noted by the rules' own record note. The card's buttons are the skills whose `_ui()` puts them on `offer` (Accept, Decline), sent as `living_rules::ui::act_node` toward `ActTarget::Offer { from, offer }` (`"offer": <trade_offer id>`) or, for terms, `ActTarget::Record { from, record }` (`"record": <record id>`), so each card's act takes exactly that card's offer. A refusal is noted in the rules' words and the card stays. Decline tells the maker ("A stranger declined your offer of 2 berries for 5 hide.") and the rules drop the offer. A card goes when its row does: taken, declined, withdrawn, offered again or out of time (`trade_window_s`). `answer_offer` in `ui/people.rs` builds every answer.

## Sub-features

- `swap-card`: a swap's card, its note, Accept (the goods change hands at once).
- `refused`: Accept the rules refuse ("You don't have 5 hide", "Out of reach"): a note, and the card stays.
- `decline`: the rules' decline, naming the offer; the maker is told; the card closes.
- `re-offer`: offered again, a new card.
- `terms-card`: proposed terms in the proposer's window; Accept agrees (the record becomes `agreed`).

## How to get to it (user POV)

- Someone offers a trade or proposes terms: their window opens with the card; else Log › People or hold F › Their window.

## Driving it with drive.py

Preconditions: baseline; two residents placed within reach (3 m: farther, the rules refuse an accept, "Out of reach"); goods granted (admin `grant_items`); the residents' offers made by admin `mind_act`, as a mind decides (`check.py`'s `act()`: `mind_act|<ID>|["{\"do\":\"offer\",\"target\":{\"id\":{me}},…}"]|"verify-ui"`). Scene setup only: the player's answers go through its own `human_act`.

- **A card.** After `sync:swap;wait:4`: dump `windows` has `Person<A>` Left; `tags` has `person:offer:<A>:0:0` (Accept, the first skill on `offer`) and `person:offer:<A>:0:1` (Decline); `notes` has "offers you 2 berries for 1 wood".
- **Accept.** `click:@person:offer:<A>:0:0` → log `verbs: Accept → {"do":"accept","offer":<id>,"target":{"id":<A>}}`; the card's tag gone; owner SQL: their `wood` up by one.
- **Refused.** An offer asking what the player lacks; Accept → a note in the rules' words; the tag stays.
- **Decline.** `click:@person:offer:<A>:0:1` → log `verbs: Decline → {"do":"decline","offer":<id>,…}`; the tag gone; owner SQL `experience` for the maker: "… declined your offer …".
- **Terms.** `offer_terms` by B; `menu:f@id:<B>;click:@acts:0:window` → `person:offer:<B>:0:0`; Accept → log `{"do":"accept","record":<id>,…}`; owner SQL `SELECT status FROM record WHERE kind = 'agreement'` has `agreed`.
- Scenario: `check.py --run $R offers` (20 checks). It leaves nothing standing toward the player.

## Gotchas

- An offer or proposal left standing (a failed run) opens its maker's window on every arrival until it lapses: the windows scenario's "nothing open on arrival" fails meanwhile. Check `SELECT * FROM trade_offer` before a full run.
- The buttons come from the declarations: a skill added `on: ["offer"]` appears as another button, up to two (`OFFER_ACTS`).
