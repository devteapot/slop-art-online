# Items on people

The pack (I, or the Pack button) sits on the right anchor: one cell per item with its count, and how much of what I can carry I carry. A click on an item lists the rules' acts with it, beside the cell. Holding the click on an item and sliding it onto a person in the world or onto their window gives it: the rules' choice toward them with that item and nothing asked back (today `give`). Hold F on someone lists every act toward them; Give › opens the items from the pack beside the list.

## Sub-features

- `pack`: cells, counts, carried / limit.
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
- **Hold F › Give ›.** `menu:f@id:<ID>;click:@acts:0:give;click:@acts:1:berries` → a second `{"do":"give","item":"berries",…,"target":{"id":<ID>}}` in the log.
- **The authority.** Owner SQL `SELECT item, qty FROM inventory WHERE owner = <ID>`: two more berries.
- Scenario: `check.py --run $R items`.

## Gotchas

- `menu:f@id:N` refuses quietly when N is not perceived (behind a stall): place them in the open.
- The carried ghost shows only while the button is held and the cursor has moved more than 5 px.
- What a store or remains hold is not perceived, so `take ›` may offer an item that is not there; the authority refuses it.
