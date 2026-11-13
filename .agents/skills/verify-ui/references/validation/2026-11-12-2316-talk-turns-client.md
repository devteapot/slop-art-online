# verify-ui: talk-turns-client

**2026-11-12, branch `talk-turns-client`: main `db4c1e35b` with `origin/talk-turns` (`723998ff0`, not yet on main) merged locally, so the client compiles against `on_the_move` and the `moved` code. The module and client are built from that tree.** COMMUNICATION.md §19's client needs:

- **Naming detail on lines to someone.** Code: `heard::detail_to` and `people::line_head`. The authority's ", naming …" after the addressee is kept from the first comma before the words, whatever the verb or the way's template. The Log and the speaker's window show "A stranger in green and dark grey (to a stranger in green and black, naming … and you)", with the addressee in the player's own label (`Looks`). Bubbles keep the words only.
- **The `moved` code.** It shows as a quiet note, once, in the rules' words ("The look stopped: you moved off before it was done"). It is not a failure or unknown (`verbs::outcome_of`). A `moved` row counts as mine whichever way the act was sent, the gesture keys included.
- **Gestures on the move.** A gesture whose skill is `on_the_move` (wave, nod) no longer ends when its body moves 0.5 m (`town.rs`), as the authority no longer breaks it off. No other wave or nod prediction is wrong now:
  - the press still turns my body to the target, as the authority's `motion::face` does at the start;
  - both clips are `layer: "upper"`, drawn over the walk.
- **Dump additions:**
  - `note_ok`: each note's kind;
  - `extra.onces`: the one-shot each body plays;
  - `extra.lines[].head` and `head_window`.
- **Bindings:** unchanged, so no `just living-generate`.

## Runs

**Island world `verify-ui-1113-000726`, 63 passed, 0 failed.** Evidence is in `.local/living/verify/ui-1113-000726/ui/`.

| Scenario | Passed | What it shows |
| --- | --- | --- |
| `room-detail` | 11/11 | Extended. A says to B "Ask Listener, she will know.": the row has ", naming … you: “", `how` ", naming … you", both heads end "naming … you)" with no seed name, and the bubble has the words only. Stills: `room-detail/05_to_other.png`, `06_log.png`. |
| `move-off` | 8/8 | New. The look over, walked off 0.4 s later, gives one `moved` act outcome (owner SQL). Its note shows once with `note_ok` null, and the Log has one event. A wave walked on from 0.4 s later is not broken off; it is drawn (`onces` `wave`) while the body has moved over 0.5 m, with no failure note. Stills: `move-off/01_moved.png`, `02_waving.png`. |
| `talk` | 22/22 | |
| `unheard` | 12/12 | |
| `own` | 6/6 | |
| `names` | 4/4 | On the island. |

- **Cullet world `verify-ui-1113-001519c`:** `names` 4/4.
- **Unit tests:**
  - living-game: 122 passed, including `heard::how_tests::a_line_to_someone_that_names_others_keeps_its_detail_whatever_its_verb`;
  - living-rules: `ui::tests::the_game_client_names_no_new_skills` passed.

## Notes

- **The first room-detail run** had the line naming "you" alone. The second, on the same world, named "a stranger and you": the first run's "Listener" was an offline player character still standing there, and the authority named both. The checks accept any names before "you".
- **To do when talk-turns is on main:** rebase onto main, rebuild, and rerun these scenarios.
