# People drawn from their look (look-1)

A person is drawn from the look the authority projects for them (docs/LOOK.md): their row in `seen_characters` carries a line key (`look`, `lk_` and 16 hex digits) at every distance at which they are seen, and the client draws the line it finds under that key in the look book shipped with it (`assets/characters/looks.json`, git-ignored, from char-4's bundle). The line is composed from shared type and style files ([crowd.md](crowd.md) `compose`). Code: `living/game/src/characters/book.rs` (the book), `characters/seen.rs` (the row's column and `world.look_book`, in one place), `live.rs` (`recipe_for`, `swap_look`, `Live::swaps`), `looks.rs` (`clothes`, `place`), `loading.rs` (the prewarm), `island.rs` (`person_recipe`), `view.rs` (`look:<lk_…>`).

## Sub-features

- `composed`: a key the book holds is that line on its type, at the line's own height (`stage_scale` scales only the VRoid fallback). My own character is drawn from my own row, as anyone's; `LIVING_GAME_PLAYER` is look-dev only.
- `fallback`: no key, a key the book lacks, a line naming a file not on disk, no book, or composing off (`LIVING_GAME_COMPOSE=0`): today's VRoid recipe from the land seed and the id. In a world with looks each case is one warning line a session; a world made before looks (`world.look_book` empty) falls back quietly, with one line at connect ("this world was made before looks"). A world generation the book does not hold (`generation`, `generations`) is one warning at connect.
- `redraw`: a new key (a band change, a `relook`) redraws the person where and as they are. The new body takes the old one's transform and motion; the old stays drawn and moving with it until the new is fitted (`Live::swaps`, `drawn()` gives the old meanwhile), then the two cross-fade (`fade.rs`). The person is never off the screen.
- `chips`: a line's chips are its outermost upper and lower pieces' own colours (`colors.outfit` by piece). Which piece is which comes from each outfit style file's scene extras, `outfit: {piece, slot, layer, trim}`: `upper` and `lower` give a chip, the higher layer worn over the lower (jersey 0, smock or coat 1, apron 3; trousers 0); `feet`, `head` and a `trim` (a smock's bands) give none. A file without them falls back on its name with the same values. The book's `files` lists the same and is only a cross-check.
- `prewarm`: under the loading cover, the fewest book lines that wear every type and style file (`LookBook::covering`), so no composed material or mesh layout is first drawn when someone comes into sight. `LIVING_GAME_PERF=nolooks` leaves them out, to measure that hitch.
- `decor`: an island's background people (offline and look-dev only: a live island plans none) take a grown line from the book's `decor` by their own seed, never a line a character wears; their preload and their spawn take the one recipe (`person_recipe`).

## How to get to it (user POV)

Connect to a world whose people have looks, with the book on disk: the people in sight are drawn from their keys. There is no control.

## Driving it with drive.py

Preconditions: a scratch island world (`--seed island`, Brackenford) or a Cullet world, the book from char-4's bundle at `living/game/assets/characters/looks.json` and the bundle's types and styles under `lookdev/`. Until the authority projects looks (dev-box's look-1-auth), the key comes from the client's test shim: `LIVING_GAME_LOOK_SHIM=on[;none=ID,…][;missing=ID,…][;generation=G][;grow=ID@S]`, or `old` (`characters/seen.rs`): each person a wearable line of their life stage's band by id; no key for `none`; a key the book lacks for `missing`; the world's generation `G`; person `ID` the next band's line `S` seconds after the first look is read. The shim goes with the rebase onto the authority's bindings, and the scenario then takes keys from the world.

- Scenario: `check.py --run $R looks` (16 checks). Three residents are placed beside me (`sync:scene`, `--place-free`): A with a key, B with none, C with a key the book lacks. A grows a band at 19 s, inside a burst of 48 dumps 0.15 s apart. Then a drive with a world generation the book lacks, a drive on an old world, and a look-dev island tour (`LIVING_GAME_LOOKDEV=1 LIVING_GAME_TOUR_ONLY=island`) whose background people are logged (`RUST_LOG=…,living_game::island=debug`: `looks: background person … drawn from decor lk_…`).
- The dump's `looks`: each person drawn, its key (empty for none), whether composed, whether a redraw is under way, and its chips.
- Run talk, windows, names, houses and death with `LIVING_GAME_LOOK_SHIM=on` too: labels and plates read the drawn colours.
- `LIVING_GAME_VIEW=look:<lk_…>` shows one line in the asset view, as the game draws it (stills of a type band's faces).

Checks:
- the three residents in view; A composed from its line (the shim's key); every composed key in the book, and every key the book holds composed;
- B and C drawn as VRoid bases, one warning line each;
- every composed person's chips are its line's outermost upper and lower pieces' colours, by the style files' extras; every worn outfit style carries them, as the book's `files` lists them;
- my own look from my own row;
- A redrawn from the next band's line ("redrawn for a new look"), composed, no longer swapping; in view in every dump of the burst, never more than 60 px from one dump to the next, a redraw seen under way;
- no generation warning for the book's own generation; one for another; an old world: VRoid bases, one connect line, no warning per person;
- background people drawn from decor lines only.

## Known

- A redraw whose files are already loaded is fitted within a dump or two (under 0.3 s): the cross-fade is short. Judge it in the burst's shots (`s00`…`s42`) whether it reads as a change in place or as pop-in.
- `names` failed one of four runs on a Cullet world with the shim (no plate among the names on screen; residents wander under town life) and passed on the next, on main and without the shim.
