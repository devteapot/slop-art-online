# Talking

Enter talks to the person under the cursor (the owner's rule, 2026-11-11), and with nobody under the cursor to the room (`to = 0`). The box lives in their window ("To a stranger in orange"), or in Log and people ("To the room"). Tab goes to the next person within earshot, then back to the room. About 10 s after a line to the room that nobody took up, a note says so ("Heard by 2 — no one took it up. …"). Each person has a window keyed by character id: how I name them and how they look, how we met, acts (Give ›, Trade…, Wave, Look over, Introduce yourself) and our conversation from experience rows. Strangers are named by looks only; a name shows only when the projection gives one.

## Sub-features

- `room`: Enter with nobody under the cursor: to the room, in Log and people; the line goes out with `to = 0`; the room note after 10 s.
- `address`: Enter while hovering someone: to them, in their window; the line goes out with `to`.
- `pick`: who is under the cursor is one pick (`living/game/src/pick.rs`) for the nameplate (hover), Enter, a tap and combat's target: the body whose outline on screen holds the cursor, the one drawn in front where two overlap; with no outline under it, the body within 1.2 m of the cursor's ground point. Before 2026-11-11 each asked its own way, and with two people overlapping Enter spoke to the one behind.
- `tab`: Tab cycles people in earshot, then the room.
- `modes`: the box's modes from `talk::MODES` (a person, the room; whisper greyed, not built).
- `person-window`: opened by talking, by a tap on them, by F, from the list of acts (Their window) or from Log › People.
- `repeats`: the same words said again in a row by the same speaker to the same one are one bubble with "×N" after the name (`people.rs` `collapse`, unit test `the_same_words_again_are_one_line_with_a_count`; in the person window and the log). In Glass a person's window stops at 42% of the screen's height (`Theme::person_cap`) and its conversation scrolls to its end.
- `conversation`: my `said` lines to them and their `speech` lines; "did not hear you" from a `silence` row.
- `introduce`: "Introduce yourself" puts "I'm <name>." in the box, editable, to them.
- `labels`: looks ("a child in red"; a second colour when two read alike), never a name the rules have not given.
- `pending`: `heard_by` (under my line) and `introduced` ("They told you their name") show nothing until the authority writes them (`living/game/src/heard.rs`).
- `mouth`: while a line is said, the speaker's `Fcl_MTH_A` moves (`living/game/src/mouth.rs`, read by `lookdev::face`): my own line, and every line I hear or see said, for each rigged person drawn. It moves for the line's length at 14 characters a second (open on vowels, shut on punctuation), never past its bubble, then shuts. How wide comes from the world's way of speaking (`Carry::Hearing` share: a call wider, speech 0.8; a way for a few metres or one ear, a whisper and its onlookers' rows, 0.3), found from the row's kind and heard words. Unit tests `the_mouth_over_a_line`, `loudness_comes_from_the_ways`; the dump's `extra.mouths` (character id → opening now) and the record's `state.jsonl` `mouths`.
- `prompt-tip`: the F prompt beside the person ("F Talk · hold F · more") and the first-time tip ("New here").

## How to get to it (user POV)

- Point at someone and press F (a tap talks; held, the list of acts); or Enter; or tap them with the weapon sheathed.
- L, then People, then a name.

## Driving it with drive.py

Preconditions: baseline; two residents placed beside the player with `--place ID:-2.5:2.0 --place ID:2.0:2.5` (apart across the view; the arrival point is in a market stall; the other side is blocked from sight), held still, and placed again at `sync:hold` just before the cursor goes to the first: in the 11 s of the room's note they may walk (town life), once onto one spot, stacked exactly on screen.

- **The room.** `cursor:0.5,0.12;key:Enter:tap` → dump `typing.to` null, `typing.window == Log`, `typing.label == "To the room"`. `type:Good morning, all.;enter` → log `say: "…" to no one in particular`; after 11 s the log has `talk: room note "Heard by N — no one took it up…"`.
- **A person.** `point:<ID>;key:Enter:tap` (the cursor on them) → `typing.window == Person<ID>`, `typing.label` "To a …" (looks, no name). `type:Hello there.;enter` → log `say: "Hello there." to #<ID>`; owner SQL `SELECT kind, object, text FROM experience WHERE kind = 'said'` has the line with `object` = the addressee (and the room's with 0).
- **Tab.** `key:Enter:tap;tab;tab;tab` → among the dumps, another person in earshot (the window followed) and the room (window `Log`).
- **Esc.** Closes the box and its window.
- **Log › People.** `key:KeyL:tap;click:@log:tab:1;click:@log:person:0` → a `Person<ID>` window.
- **Mouths.** After `type:…;enter`, dumps at 0.3, 0.6 and 0.9 s → `extra.mouths[<me>]` above 0.05 in at least one. `sync:answer` makes resident A answer through admin `mind_say` (A's controller is the admin; scene setup, the speech path minds use, no model) → dumps at 0.3–0.9 s have `extra.mouths[<A>]` above 0.05; 5.5 s later both are 0 or absent.
- **Introduce yourself.** `click:@person:intro` → `typing.words` "I'm Verifier.", `typing.to` = ID.
- Scenario: `check.py --run $R talk`.
- **Two overlapping (`pick`).** The view faces north (`frame:0;yaw:0`); A at `-3.0:-1.0`, B at `-3.0:-2.5` (1.5 m behind A along the view, where the ray through A's chest meets the ground). `point:A:1.3` (A's chest) → the dump's `under` and `hovered` are A only; `key:Enter:tap` → `typing.to == A` in `Person<A>`, `targeted == A`; the line goes to #A (log and `said` row); `tap` on the same spot also opens the box to A. Scenario: `check.py --run $R pick`.

## Gotchas

- Face is in no list of a player's (`face_ui() { on: [], tip }`, play-test 5): a player faces where it looks. The talk scenario checks More… leaves it out.

- Someone behind a stall or a house is not perceived (sight is a rule), so Enter skips them; place people in the open.
- `point:ID` puts the cursor 0.3 m above their feet. Someone standing in front of them on screen can cover that spot, and then the pick is rightly the one in front; the dump's `seen` shows where each body was.
- A run's character keeps its old experience rows: "First seen 12 min ago" can predate the run.
- No mind runs: nobody answers on their own. Their lines appear only with `verify-minds` or a play-test; the talk scenario's one answer is the scene's `mind_say`.
- A mouth sampled in a dump can be near 0 at a pause or a flap's trough: the checks take three samples.
