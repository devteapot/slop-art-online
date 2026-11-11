# Speech: ways of speaking over one primitive

Design: [docs/COMMUNICATION.md](../../../../docs/COMMUNICATION.md). Source: `living/authority/src/speech.rs` (the primitive `speak`, `speech_card`, `my_heard`), `living/rules/src/script/speech.rs` (`WaySpec`, read from `<way>_speech()`), the ways in `living/scripts/skills.rhai` ("ways of speaking").

## What it does

- **Ways are script.** Each `<way>_speech()` map is read once per script revision (`Scripts::ways`). An unknown key, a `needs` that is no technique, a way named like a skill, or words `only_to` the addressee without `to: "required"` is refused at install, naming the key. A script with no ways speaks by the built-in `say` (`WaySpec::say()`, field for field the shipped `say_speech()`). `say` is required once any way is declared.
- **One primitive.** `speech::speak(ctx, speaker, text, to, way, now)`:
  1. Empty text is accepted and writes nothing. An unknown way is refused: "no way of speaking called `X`". Lines are cut to the way's `max_chars`.
  2. Refusals, which write nothing:
     - "speaking too fast": 2 s across all ways (`SPEAK_GAP_MS`, for a speaker with a `mind_state` row);
     - the way's own `gap_s` when it is longer: "too soon to <way> again: wait N s", from the speaker's `heard` rows;
     - `to: "required"` with no addressee: "a <way> needs someone to <way> to";
     - `needs`: "you don't know <technique>";
     - `reach`: "too far to <way>: step closer", with an absent or dead addressee refused in the same words;
     - `needs_sight`: "you can't see whom to <way> to";
     - `<way>_check(a)`: its own words.
  3. The chronicle line. A `say` line reads as before; another way names itself: "Ilsa (whisper) to Bram: …".
  4. The speaker's `said` row (0.5) and a `repeat` row (0.3) for nearly the same line within 90 s.
  5. One gather of creatures within the way's widest carry (`WaySpec::widest`). Animals hear the way's `animals` text: "You hear a person's voice, north." (0.25). People receive the words when within `carry_for(their hearing)`, and, for `only_to`, only the addressee.
  6. `silence` for an addressee who did not receive the words.
  7. Each receiver gets a row of the way's `kind` (`speech` for `say`) with the way's templates. Salience is `addressed` (0.9: the addressee; or, for a room line, the only person within `address_m` 6 m, or someone named in the line) or `overheard` (0.45).
  8. Introductions: a line that holds the speaker's own name gives every receiver an `acquaintance`. When the name is news, the receiver also gets an `introduced` row (subject = the speaker, 0.55): "Walker1 told you their name." The salience is below the 0.6 wake threshold, so a name never re-runs the listener's graph.
  9. `noticed` (a whisper's onlookers): people within `within_m` who see the speaker, and who did not receive the words, get a row of the way's own kind with its `text` and no words.
  10. A `heard` row in the same transaction: `line` = the `said` row's id, `speaker`, `way`, `hearers` = the receivers the speaker saw by the sight rule (`perception::in_sight` with the hearer's glow, as `seen_characters`), nearest first, and `at_ms`.
- **Entry points:**
  - `human_say(text, to)` is the `say` way;
  - `human_speak(text, to, way)` takes any way ("" is `say`);
  - `mind_say(actor, say, say_to, way, seen_ms, thought)`;
  - `mind_install`'s say is `say`;
  - a graph's `say` node takes an optional `way` (normalizer: `{"say": "...", "way": "whisper"}`, the `do` forms too). The node waits out the way's limits (`too_soon_to_speak`) and is refused as a failed leaf for an unknown way.
- **`speech_card`** (public, one row per way, rewritten at install): `name`, `label`, `order`, `about`, `needs_to`, `reach_m`, `carry_m` (for the world's ordinary hearing), `requires`, `needs_sight`, `private` (only_to), `max_chars` and `gap_ms`. The shipped `say` row reads `("say", "Say", 0, needs_to false, reach 0, carry 9, "", false, false, 400, 2000)`.
- **Retention of `heard`.** A row goes when its `said` row leaves the speaker's window: the trim in `perceive::percept`, `mind_consolidated` (a mind's integrated rows) and `forget_dead`. A played character keeps its rows (consolidation does not delete them).
- **World text.** The `speech` topic (heading SPEAKING) lists each way as "<name> = <about>".

## Drive

```bash
R=core-speech-$(date +%m%d%H%M)
$V launch --run "$R" && $V doctor --run "$R"
python3 .agents/skills/verify-core/scripts/speech.py regress --run "$R"
python3 .agents/skills/verify-core/scripts/speech.py ways --run "$R-w"   # its own launched run
python3 .agents/skills/verify-core/scripts/speech.py crowd --run "$R-c" --n 20 --side 10 --lines 60 --every 0.5
python3 .agents/skills/verify-core/scripts/speech.py diff core-speech-base core-speech-branch
```

- **`regress`** places four minded people, a deer and a player (`Listener`, its own identity) on a quiet open line: from the speaker, b at 3 m, the deer at about 4 m, c at 7 m, the player at 8.5 m and d at 14 m. It says ten lines through `mind_say`, `human_say` and a looping graph `say`: a room line, a line to c, a line to d out of earshot, a self-introduction, a repeat, a line naming c, the player's three lines, and b's introduction. It also checks the 2 s limit. It writes `speech-regress.json`, which holds every speech-kind row with ids and names mapped to roles (experience per observer, the player's `line_seen`, new acquaintances, chronicle lines, `mind_state` hearing marks and the calls' results). `--baseline` drives a module from before ways (`mind_say` without a way).
- **`diff A B`** compares two `regress` outputs with the new kinds (`introduced`) left out and writes `<B>/speech-diff.json`. That is the regression proof that the shipped `say` is unchanged: run `regress --baseline` on the pre-change module (a worktree at the base commit, its own `verify.py launch`) and `regress` on the change.
- **`ways`** checks:
  - `speech_card` read anonymously;
  - the `heard` row of a self-introduction (hearers by day or night sight);
  - `introduced` for b, c and the player but not d, and not news a second time;
  - `introduced` in `my_experience`;
  - `human_speak` (say, "" and an unknown way, refused), `human_say`, and an empty line;
  - `my_heard` for the player: its lines, joinable to `my_experience` by `line`, empty for a second player identity; `heard` is not readable by a player;
  - a graph say with `way: "say"`, and with an unknown way (not spoken, the speaker told);
  - `mind_say` in an unknown way (refused);
  - a hearer behind a wall within earshot (`scenes.wall_geometry`): hears the words, not listed in `heard`;
  - `mind_consolidated` removing a mind's `heard` rows while the player's stay.
- **`crowd`** places N minded people in a square, says room lines in turn at a declared rate through `mind_say`, and reads the server's `/v1/metrics` for this database. It reports:
  - `reducer_wasm_time_usec` and `reducer_wasmtime_fuel_used` per `mind_say`;
  - reducer plus query time;
  - `spacetime_num_rows_inserted_total` by table per line;
  - speech rows per line;
  - the mean `heard` hearers.

  Run it on the pre-change module with `--baseline` for the comparison.

Privacy across experience rows, prompts, clients and memory is `verify-minds/scripts/privacy.py` (verify-minds, "Privacy of words").
