# The wheel

Hold F on a target whose place the world's `menus()` gives a wheel (docs/INTERFACE.md §8): up to eight sections round a hub, the acts on that one target. Move toward a section and let go of F to choose it; let go in the hub to choose nothing. What goes where is the rules' (`living_rules::ui::wheel_of` over the F list's own choices): a pinned act keeps its direction and greys in place when the rules refuse it, with their `_check` text in the hub; a filled one shows only while allowed; the rest is behind More (the full list). A greyed section is still sent when chosen: the authority decides and its note says why. While it is open the cursor is held (`pointer.rs` `hold`): motion moves the selection, the view does not turn, and when it closes the cursor is where it was.

## Sub-features

- `person`: the shipped person wheel: Talk n, Give ne, Offer e, Teach se, More s, Their window sw, Look over w, Wave nw (`skills.rhai` `menus()`).
- `held`: hold F (0.28 s), move, let go; the hub cancels; Esc closes it without sending.
- `sticky`: a tap of F with nothing likely to do on the target opens the wheel sticky (the log's `(sticky)`): it stays open after F is up, and a click, Enter or F chooses the selected section.
- `gone`: when its target leaves sight (or dies) it closes with a note "<them> is out of sight" (log `ui: wheel closed (its target left sight)`).
- `flick`: F and a quick move (30 px, after 80 ms) before it would draw: it opens with that direction chosen.
- `keys`: digits 1–8 choose at once (clockwise from north); the arrows point it; another bar key closes it.
- `sub`: a section with a further choice (Give ›, Offer ›, Teach ›) opens its sub-list; More opens every act.
- `grey`: a pinned act the rules refuse greys with their reason in the hub, and is sent all the same (with a real item when it takes one).
- `workplace`: Cullet's fuel fires (furnace, oven, hearth, smokehouse): Make n, Feed e (Cullet's laws, over `base_menus()`). F held where only pinned acts exist and none is allowed now (a cold hearth) still opens the wheel, all greyed, to say what belongs there and why not now.
- `cursor`: the drawn cursor hides while held, and is back to the pixel after.

## How to get to it (user POV)

- Point at a person, or at a thing, and hold F. Not for yourself (C keeps its list), the pack, the bar or an offer.

## Driving it with drive.py

Preconditions: baseline; a resident beside the player (`--place`); for `workplace`, a Cullet world (`--seed cullet`) and the kit linked into the checkout (`living/game/assets/envs/cullet`).

- **Open.** `point:<ID>:1.0;wait:0.6;key:KeyF:down;wait:0.5;dump:NN` → `wheel` in the dump: `held`, `sections` (dir, what, label, allowed, pinned, sub, reason), `sel`, `more`; the log line `ui: wheel toward … (held): n talk, ne give, …; behind More: …`.
- **Choose.** `nudge:-42,-42` (toward nw) → `wheel.sel` `nw`; `key:KeyF:up` → log `ui: wheel chose nw wave` then `verbs: … → {"do":"wave","target":{"id":<ID>}}`, and a note.
- **Cancel.** `key:Escape:tap` → `ui: wheel closed (Esc): nothing sent`; F up with no motion → `ui: wheel chose the hub: nothing sent`.
- **Flick.** `key:KeyF:down;wait:0.12;nudge:45,0` → opened with `sel` `e`.
- **Digit.** `key:Digit1:tap` while open → `ui: wheel chose n talk`.
- **The cursor.** `extra.cursor` in the dump before opening and after closing: within 1 px.
- **A thing.** `pointat:X,Y[:H]` keeps the cursor on a world point (a fuel fire with no one by it: a creature under the cursor is aimed before a thing).
- **Scripts:** `wheel:DIR` points an open wheel as the arrows do.
- Scenarios: `check.py --run $R wheel` (island, 16 checks); `check.py --run $R wheel-workplace` (Cullet, 8 checks: a fuel fire with no one by it, the client joined, `notes_clear`, Make north and Feed east, Make greyed with the rules' reason, choosing it opens Make's recipe grid with its cells greyed, a greyed cell is still sent, and the authority's words noted).

## Gotchas

- `click:@tip:ok` before the tip is shown clicks the world: a strike, which draws the weapon. The wheel scenarios do not click it.
- After choosing a `›` section its list is open; Esc first closes its sub-list, a second Esc the list.
- Digits 1–3 are also the bar's skill keys' twins: while a wheel is open they choose on it.
- A resident working a fire stands on it: F aims the person. `wheel-workplace` picks the fuel fire with no body nearest.
