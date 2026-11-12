# Items on people

The pack (I, or the Pack button) sits on the right anchor: one cell per item with its count, and how much of what I can carry I carry. A click on an item lists the rules' acts with it, beside the cell. Holding the click on an item and sliding it onto a person in the world or onto their window gives it: the rules' choice toward them with that item and nothing asked back (today `give`). Hold F on someone lists every act toward them; Give › opens the items from the pack beside the list.

## Sub-features

- `pack`: cells, counts, carried / limit. The limit rises by the largest room among the containers carried (a basket: 20; a second adds nothing, it is not a sum); the load counts each item by its carry (an arrow 0.1).
- `item-acts`: a click on an item lists its acts (eat, plant, drop, …) beside the cell.
- `carry-window`: an item slid onto a person's window is given to them.
- `carry-world`: an item slid onto a person in the world is given to them (the person hovered, else the nearest head within 70 px).
- `hold-f-give`: hold F (or `menu:f@id:N`) › Give › item.
- `person-give`: the person window's Give › list.

## How to get to it (user POV)

- I or the Pack button; click an item; hold the click and slide it out.
- Hold F on someone; or their window's Give ›.

## Driving it with drive.py

Preconditions: baseline; a resident placed beside the player; berries in the pack (the scenario grants four with admin `grant_items` at `sync:kit`: earlier drives of the same run may have given the newcomer's away).

- **Their window and the pack.** `menu:f@id:<ID>;click:@acts:0:window` → `Person<ID>` Left; `key:KeyI:tap` → `Pack` Right.
- **Item acts.** `click:@pack:berries` → dump `acts.rows` hold the rules' acts with berries.
- **Carry onto the window.** `slide:@pack:berries>@win:Person<ID>:head:0.8` → log `verbs: berries let go on #<ID>: give berries`; a note "Give berries › person (gave 1 berries …)".
- **Hold F › Give ›.** `menu:f@id:<ID>;click:@acts:0:give;click:@acts:1:berries` → a second `{"do":"give","item":"berries",…,"target":{"id":<ID>}}` in the log. Before Give ›, the dump's `acts.rows` start with `talk` and `their window`, and hold a `give` row.
- **Load and limit.** `sync:load` (admin `grant_items`: a basket and ten arrows) between `dump:07` and `dump:08` → the dumps' `pack.limit` up by 20 (0 when a basket was carried already: the largest room, not a sum) and `pack.carried` up by at least 1.0 (ten arrows at 0.1, and the basket's own carry) and under 10.
- **The authority.** Owner SQL `SELECT at_ms, text FROM experience WHERE observer = <me> AND kind = 'act'`: two outcomes "You did what you had decided: give berries → person (gave 1 berries to a stranger)" since the drive began; `… WHERE observer = <ID> AND kind = 'gift'`: two "A stranger gave you 1 berries". The scenario waits up to 10 s for both (the authority goes on after the client quits).
- Scenario: `check.py --run $R items`.

## Gotchas

- `menu:f@id:N` refuses quietly when N is not perceived (behind a stall): place them in the open.
- The carried ghost shows only while the button is held and the cursor has moved more than 5 px.
- What a store or remains hold is not perceived, so `take ›` may offer an item that is not there; the authority refuses it.
- Don't prove a give by the receiver's berries: a resident is free until `sync:scene` holds it, and eats, gathers and gives berries meanwhile (43 of an island's residents changed their berries within 45 s), so a count taken before the drive is no baseline. Before 2026-11-11 the check did, and read 2 → 3 for two gives that both landed.
