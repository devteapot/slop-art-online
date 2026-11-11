# Windows

Floating walnut-and-parchment windows on two anchors (left: a person, the log, later the character; right: the pack), one per anchor, so at most two narrow windows are open at 1600×900. Skills and Settings are wide, in the centre, and close the others. A window moves by its title bar and snaps to the nearer anchor; if another window holds it, they change places. With nothing open, Esc opens Menu and frees the system cursor.

## Sub-features

- `open-home`: a window opens on its home anchor and replaces what holds it.
- `open-wide`: Skills and Settings open in the centre and close the others; opening a narrow one closes a wide one.
- `drag-snap`: a title-bar drag moves the window; letting go snaps it left or right; a held anchor swaps.
- `close`: ✕, the window's own key (I, L, K), or Esc for the top window.
- `esc-order`: the list of acts (sub-list first), the Menu list, the words being typed with their window, the top window; then Menu opens and the cursor is freed.
- `menu`: the Menu button and its list (Character, Skills and know-how, Log and people, Settings, Leave the world: asked twice).
- `compass`: the needle follows the view; the place's name shows only from `my_places`.

## How to get to it (user POV)

- The Pack (I) and Menu (Esc) buttons under the compass; Menu's rows.
- Keys: I the pack, L the log and people, K skills and know-how, C the list of acts on oneself (until the character window), Esc.
- Hold the click on a title bar and slide (or three-finger drag); ✕ at its right.

## Driving it with drive.py

Preconditions: baseline; nothing open on arrival.

- **Menu.** `click:@menu` → dump `menu: true`. `click:@menu:Settings` → `windows: [Settings, Centre]`, `menu: false`.
- **Two narrow windows.** `key:KeyI:tap;key:KeyL:tap` → `Pack` Right and `Log` Left; Settings gone. Rectangles inside 1600×900 and apart.
- **Drag and swap.** `slide:@win:Log:head>0.62,0.45:0.6` → log line `ui: Log snapped to Right`; dump: `Log` Right, `Pack` Left. Photograph during the slide shows the anchors' outlines.
- **Close.** `click:@win:Pack:close` → Pack gone. `key:KeyI:tap` opens it on the right again, replacing the log there.
- **Esc order.** Esc closes the top window; with none, `menu: true` and the log says `ui: Esc with nothing open: Menu, cursor freed`; Esc closes the list; Esc again opens it.
- **Leave.** `click:@menu:Leave` reads "Leave? Click again"; a second click quits (do it last).
- Scenario: `check.py --run $R windows`.

## Gotchas

- Headless there is no system cursor, so "frees the cursor" shows only as the log line; capture and release need a real window.
- A drag needs the press to land on the title bar: slide from `@win:<Win>:head`, not from the window's body.
- The anchors' outlines show only during a drag of a narrow window.
