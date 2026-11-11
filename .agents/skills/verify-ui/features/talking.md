# Talking

Enter talks to the person under the cursor (the owner's rule, 2026-11-11), and with nobody under the cursor to the room (`to = 0`). The box lives in their window ("To a stranger in orange"), or in Log and people ("To the room"). Tab goes to the next person within earshot, then back to the room. About 10 s after a line to the room that nobody took up, a note says so ("Heard by 2 — no one took it up. …"). Each person has a window keyed by character id: how I name them and how they look, how we met, acts (Give ›, Trade…, Wave, Look over, Introduce yourself) and our conversation from experience rows. Strangers are named by looks only; a name shows only when the projection gives one.

## Sub-features

- `room`: Enter with nobody under the cursor: to the room, in Log and people; the line goes out with `to = 0`; the room note after 10 s.
- `address`: Enter while hovering someone: to them, in their window; the line goes out with `to`.
- `tab`: Tab cycles people in earshot, then the room.
- `modes`: the box's modes from `talk::MODES` (a person, the room; whisper greyed, not built).
- `person-window`: opened by talking, by a tap on them, by F, from the list of acts (Their window) or from Log › People.
- `conversation`: my `said` lines to them and their `speech` lines; "did not hear you" from a `silence` row.
- `introduce`: "Introduce yourself" puts "I'm <name>." in the box, editable, to them.
- `labels`: looks ("a child in red"; a second colour when two read alike), never a name the rules have not given.
- `pending`: `heard_by` (under my line) and `introduced` ("They told you their name") show nothing until the authority writes them (`living/game/src/heard.rs`).
- `prompt-tip`: the F prompt beside the person ("F Talk · hold F · more") and the first-time tip ("New here").

## How to get to it (user POV)

- Point at someone and press F (a tap talks; held, the list of acts); or Enter; or tap them with the weapon sheathed.
- L, then People, then a name.

## Driving it with drive.py

Preconditions: baseline; two residents placed 2 m from the player with `--place ID:-2.5:2.0 --place ID:-1.0:3.2 (the arrival point is in a market stall; the other side is blocked from sight)` (held still).

- **The room.** `cursor:0.5,0.12;key:Enter:tap` → dump `typing.to` null, `typing.window == Log`, `typing.label == "To the room"`. `type:Good morning, all.;enter` → log `say: "…" to no one in particular`; after 11 s the log has `talk: room note "Heard by N — no one took it up…"`.
- **A person.** `point:<ID>;key:Enter:tap` (the cursor on them) → `typing.window == Person<ID>`, `typing.label` "To a …" (looks, no name). `type:Hello there.;enter` → log `say: "Hello there." to #<ID>`; owner SQL `SELECT kind, object, text FROM experience WHERE kind = 'said'` has the line with `object` = the addressee (and the room's with 0).
- **Tab.** `key:Enter:tap;tab;tab;tab` → among the dumps, another person in earshot (the window followed) and the room (window `Log`).
- **Esc.** Closes the box and its window.
- **Log › People.** `key:KeyL:tap;click:@log:tab:1;click:@log:person:0` → a `Person<ID>` window.
- **Introduce yourself.** `click:@person:intro` → `typing.words` "I'm Verifier.", `typing.to` = ID.
- Scenario: `check.py --run $R talk`.

## Gotchas

- Someone behind a stall or a house is not perceived (sight is a rule), so Enter skips them; place people in the open.
- A run's character keeps its old experience rows: "First seen 12 min ago" can predate the run.
- No mind runs: nobody answers. Their lines appear only with `verify-minds` or a play-test.
