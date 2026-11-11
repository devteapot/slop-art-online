# The prompt frame (`LIVING_FRAME`)

Source: [`living/mind/src/prompts.rs`](../../../../living/mind/src/prompts.rs) (`Frame`, `PLAYER_FRAME`, `opening`), the start-up check in [`living/mind/src/main.rs`](../../../../living/mind/src/main.rs); design in [`docs/TRIALS.md`](../../../../docs/TRIALS.md#the-player-frame-experiment-2026-11-11).

## What it is

`LIVING_FRAME` chooses how a person's prompts frame the model. `character` (the default, also when unset or empty) is the person ("You are the mind of the person …"). `player` replaces the opening sentence of four system prompts (think, deliberate, consolidate, talk) with `PLAYER_FRAME` and a role line: the model is an AI playing the person in a world shared with other players, the body, needs, death and rules are real, what to pursue is its own choice, and what the person says or writes stays in their own words. Any other value stops the service before it connects. Animals, starting identities, sleep and player memory are never framed.

## Assertions

Offline (`cargo test -p living-mind --bin living-mind prompts::`, run by the suite's test step):

- `frame_parses`: unset, empty and `character` are the character frame; `player` the player frame; anything else (`Player`, `npc`) an error.
- `character_frame_is_the_default_and_unchanged`: without `LIVING_FRAME` the production prompts equal the character frame's; each of the four opens with its old first sentence and carries nothing of the player frame.
- `player_frame_changes_only_the_opening`: under `player` each of the four opens with `PLAYER_FRAME`; replacing the opening with the old sentence gives the character frame's prompt byte for byte; user messages are identical.
- `player_frame_and_projects_compose`: with `LIVING_PROJECTS` on too, the frame replaces only the opening (both-on minus the frame opening is projects alone) and the projects text, `serves` and `# Your projects` stay (both-on minus the projects text is the frame alone); prefixes still shared.
- `player_frame_is_short_and_prescribes_nothing`: at most 80 words, no goals, activities, advice or survival ranking; it states who plays, what is real, the free choice and in-character speech.
- `*_shares_prefix` run the four framed prompts under both frames: the system prompt and shared user head stay identical across characters (provider caching).
- `export_prompt_fixtures` writes `<purpose>-person-<name>-player.json` beside the character fixtures. Byte identity of the character frame with the prompts before the switch was shown by exporting all 26 fixtures before and after the change (2026-11-11).

Live (`verify_minds.py --case frame`, fake model, `LIVING_NEO4J=off`):

- `LIVING_FRAME=npc` makes the binary exit non-zero with "expected character or player" (`bad-frame.log`) before any connection.
- With `LIVING_FRAME=player` the mind logs `prompt frame: player (LIVING_FRAME)`. After a deliberation and four addressed lines from a player, every think, deliberate (compile), talk and consolidation request in `fake-requests.jsonl` opens with the frame, and no starting-identity request does (`frame.json`). The journal's stored system prompts (`content_ref`) carry it too.
- `roundtrip` (no `LIVING_FRAME`) asserts that no request is player-framed.

Trials: variant `player-frame` sets `LIVING_FRAME=player`; each summary's `prompt_frame` counts the subject's framed requests per purpose, and `out_of_character` ([`living/tools/ooc.py`](../../../../living/tools/ooc.py)) counts spoken or written lines and private reply fields that break character ([trials.md](trials.md)).

## Not proven here

- Whether the frame changes what minds do (initiative, exploration, long-range aims) or how often they break character: that needs real-model trial batches, which are paid.
- The word list's precision: it over-counts and misses paraphrase; read its examples.
