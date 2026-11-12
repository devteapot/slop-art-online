# The recipe grid

A way of making whose `_ui()` says `choose: "grid"` from `products` (make, craft, cook, smoke; recipes-1) opens a grid in place of its sub-list: from the wheel's section (a fuel fire's Make) or the list's group. One cell per product, in the recipes' order (`Scripts::products_of`), each with its look (`recipe_look`) and, greyed, the rules' own refusal for that cell's item (`<skill>_check` with `making_item`). The hovered cell (else the first) shows its detail (`made_how`) and its recipe as rows from `recipe_parts`: Takes (an item, or a trait with the items that satisfy it), Holds (tools, goods-3), Where (a structure kind, any fire, burning, fuel from it), Knowing, Time. A click on a cell, or its number, sends the way's act with `making_item` toward the target; a greyed cell is sent all the same (the authority decides; its note says why). Esc closes it without sending.

## Sub-features

- `open`: from the wheel (a pinned Make, greyed or live) or a list group.
- `cells`: one per product; greyed exactly when the rules refuse it, with their words.
- `rows`: takes, holds, where, knowing, time; the detail.
- `send`: a cell sends `{"do": skill, "item": making_item, "target": …}`.

## How to get to it (user POV)

- Hold F on a fuel fire (Cullet) and choose Make; or open a thing's list and choose a way of making.

## Driving it with drive.py

Preconditions: a Cullet world (`--seed cullet`), the kit linked; a hearth with no one by it (`check.py` picks the one whose nearest body is farthest).

- **Open.** `pointat:X,Y:0.8;key:KeyF:down;wait:0.5;nudge:0,-50;key:KeyF:up` → the dump's `grid`: `skill`, `title`, `cells` (product, item, label, allowed, reason, detail, rows).
- **Choose.** `key:Digit1:tap` or `click:@grid:cell:0` → log `ui: grid make chose ash` and `verbs: … → {"do":"make","item":"ash",…}`; owner SQL `inventory` for the made item.
- Scenario: `check.py --run $R grid` (Cullet, 9 checks).

## Gotchas

- A household's hearth is usually burning already: Feed is refused as full ("holds at most 12 units"), in the rules' words.
- Digits on an open grid, wheel or list are theirs: the bar's twins (1–3) do not also press.
- The client has drawings for few item icon ids: an item without its own draws as its group (tool, glass, …).
