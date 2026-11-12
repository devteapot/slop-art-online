# Speech: ways of speaking over one primitive

Design: [docs/COMMUNICATION.md](../../../../docs/COMMUNICATION.md). Source: `living/authority/src/speech.rs` (the primitive `speak`, `speech_card`, `my_heard`), `living/rules/src/script/speech.rs` (`WaySpec`, read from `<way>_speech()`), the ways in `living/scripts/skills.rhai` ("ways of speaking").

## What it does

- **Ways are script.** Each `<way>_speech()` map is read once per script revision (`Scripts::ways`). An unknown key, a `needs` that is no technique, a way named like a skill, or words `only_to` the addressee without `to: "required"` is refused at install, naming the key. A script with no ways speaks by the built-in `say` (`WaySpec::say()`, field for field the shipped `say_speech()`). `say` is required once any way is declared.
- **One primitive.** `speech::speak(ctx, speaker, text, to, way, now)`:
  1. Empty text is accepted and writes nothing. An unknown way is refused: "no way of speaking called `X`". Lines are cut to the way's `max_chars`.
  2. Refusals, which write nothing and come back as the reducer's `Err`:
     - the engine's own: "no way of speaking called `X`" and "speaking too fast" (2 s across all ways, `SPEAK_GAP_MS`, for a speaker with a `mind_state` row);
     - the way's (since the coordinator's requirement on `speech-2`): exactly the words its `<way>_check(a)` returns, through `living_rules::script::speech::check_way(scripts, way, actor, addressee, text, since_ms)`, the function a client calls to run the same check before sending (it also gives "no way of speaking called `X`"). A check may read only `a.actor`, `a.target`, `a.text`, `a.qty` and `a.skill`; the install refuses one that reads another field.

     The check gets the addressee as `a.target` (class `none` for the room; absent or dead reads as alive false and very far), the line as `a.text`, and the milliseconds since the speaker's last line in this way as `a.qty` (from its `line_heard` rows; 4,000,000,000 if never). The install refuses a way that requires an addressee, a reach, a technique or a gap without a check that refuses a sample line breaking it (`check.rs` `ways`). Shipped words:
     - `whisper_check`: "a whisper needs someone to whisper to", and "too far to whisper: step closer";
     - `call_check`: "too soon to call out again: wait a few seconds".
  3. The chronicle line. A `say` line reads as before; another way names itself: "Ilsa (whisper) to Bram: …".
  4. The speaker's `said` row (0.5) and a `repeat` row (0.3) for nearly the same line within 90 s.
  5. One gather of creatures within the way's widest carry (`WaySpec::widest`). Animals hear the way's `animals` text: "You hear a person's voice, north." (0.25). People receive the words when within `carry_for(their hearing)`, and, for `only_to`, only the addressee.
  6. `silence` for an addressee who did not receive the words (`speech::unheard_text`; since `speech-truth`, the law `speech_truth`, on by default; docs/COMMUNICATION.md §15). When the speaker sees them: "<Who> is too far away: they could not have heard you. Call out or go closer." (the farthest-carrying public way's label; "Go closer." when the way used carries farthest). When it does not: "<Who> is out of earshot: they could not have heard you." A played speaker also gets an `act_outcome` row keyed by that line (kind `act`, code `reach`, not ok, `why` the same words). With the law off, `speech-2`'s words: "<Who> is too far to hear you; call out or go closer." and "No answer from <who>; they don't seem to be within earshot."
  7. Each receiver gets a row of the way's `kind` (`speech` for `say`) with the way's templates. Salience is `addressed` (0.9: the addressee; or, for a room line, the only person within `address_m` 6 m, or someone named in the line) or `overheard` (0.45).
  8. Introductions: a line that holds the speaker's own name gives every receiver an `acquaintance`. When the name is news, the receiver also gets an `introduced` row (subject = the speaker, 0.55): "Walker1 told you their name." The salience is below the 0.6 wake threshold, so a name never re-runs the listener's graph.
  9. Overheard names (since `speech-2`, the way's `names`, off for words for one ear): a line to someone that mentions their name tells it to each receiver who sees them. That receiver gets an `introduced` row with the named person as subject and the caller as object: "You heard a stranger call Walker3 by name."
  10. `noticed` (a whisper's onlookers): people within `within_m` who see the speaker, and who did not receive the words, get a row of the way's own kind with its `text` and no words.
  11. A `line_heard` row in the same transaction: `line` = the `said` row's id, `speaker`, `way`, `hearers` = the receivers the speaker saw by the sight rule (`perception::in_sight` with the hearer's glow, as `seen_characters`), nearest first, and `at_ms`.
- **Entry points:**
  - `human_say(text, to)` is the `say` way;
  - `human_speak(text, to, way)` takes any way ("" is `say`);
  - `mind_say(actor, say, say_to, way, seen_ms, thought)`;
  - `mind_install`'s say is `say`;
  - a graph's `say` node takes an optional `way` (normalizer: `{"say": "...", "way": "whisper"}`, the `do` forms too). The node waits out the way's limits (`too_soon_to_speak`) and is refused as a failed leaf for an unknown way.
- **`speech_card`** (public, one row per way, rewritten at install): `name`, `label`, `order`, `about`, `needs_to`, `reach_m`, `carry_m` (for the world's ordinary hearing), `requires`, `needs_sight`, `private` (only_to), `max_chars` and `gap_ms`. The shipped rows on the island (9 m hearing) are:

| name | label | order | needs_to | reach | carry | requires | needs_sight | private | max_chars | gap_ms |
| --- | --- | ---: | --- | ---: | ---: | --- | --- | --- | ---: | ---: |
| say | Say | 0 | false | 0 | 9 | "" | false | false | 400 | 2000 |
| whisper | Whisper | 1 | true | 1.5 | 1.5 | "" | false | true | 400 | 2000 |
| call | Call out | 2 | false | 0 | 22.5 | "" | false | false | 80 | 6000 |
- **Retention of `line_heard`.** A row goes when its `said` row leaves the speaker's window: the trim in `perceive::percept`, `mind_consolidated` (a mind's integrated rows) and `forget_dead`. A played character keeps its rows (consolidation does not delete them).
- **Mentions** (since `speech-2`): a name is mentioned by its given name (the first word) or in full. "I'm Vessa" introduces Vessa Pontil. Before, a name of two words never matched.
- **The shipped ways** (since `speech-2`, docs/COMMUNICATION.md §14):
  - `say`.
  - `whisper`: 1.5 m, words for the addressee only (kind `whisper`); onlookers within 6 m who see the speaker get `whispered`, "<a> whispers something to <b>." with no words; no animals, no names.
  - `call`: 2.5 times each listener's hearing (22.5 m on the island, 30 in Cullet); listeners read "… calls out from about {d} m" (the `{d}` placeholder, distance from the reader); animals hear "a person shouting"; 80 characters, 6 s apart.
- **World text.** The `speech` topic (heading SPEAKING) lists each way as "<name> (<reach>) = <about>", the reach in metres from the spec and the world's hearing (`WaySpec::reach_words`: "carries 9 m", "to someone within 1.5 m"; since `speech-truth`).
- **Queued lines** (graph `say` nodes, `brain.rs`; since `speech-truth`, with `speech_truth` on): a say to someone beyond what the way carries as it comes due (`speech::within_reach`; not for a way with a reach, which its check refuses) is not said; the speaker's `silence` row reads the words above and "You did not say your planned line: “…”." (`speech::unsaid`), and the node counts as done. A mind plan's say (`brain.source = "mind"`) the conversation has overtaken (`line_overtaken`: since the install or the node's last line, the addressee spoke to the speaker, or the speaker answered them by a line not this plan's) is dropped with no row. The second is driven in `verify-minds` `queued`.

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
  - the `line_heard` row of a self-introduction (hearers by day or night sight);
  - `introduced` for b, c and the player but not d, and not news a second time;
  - `introduced` in `my_experience`;
  - `human_speak` (say, "" and an unknown way, refused), `human_say`, and an empty line;
  - `my_heard` for the player: its lines, joinable to `my_experience` by `line`, empty for a second player identity; `line_heard` is not readable by a player;
  - a graph say with `way: "say"`, and with an unknown way (not spoken, the speaker told);
  - `mind_say` in an unknown way (refused);
  - a hearer behind a wall within earshot (`scenes.wall_geometry`): hears the words, not listed in `line_heard`;
  - `mind_consolidated` removing a mind's `line_heard` rows while the player's stay.
- **`channels`** places five minded people, a deer and a player named "Mara Quill" on one quiet line. From the speaker: b at 1 m, the deer at about 4 m, c at 4 m, the player at 7 m, e at 10 m (in sight by day, beyond the 9 m voice) and d at 20 m (within a call). It checks:
  - a whisper to b: b gets the words; c notices them without the words; the player, e, d and the deer get nothing; the speaker's row, the `line_heard` row and the audit line are right; only b's hearing mark moves;
  - whispers to c at 4 m and to no one are refused and write nothing;
  - a whispered self-introduction teaches only b;
  - a call: d and the deer hear it (as a shout), it is cut to 80 characters, and a second call within 6 s is refused;
  - the truthful silence (`speech_truth`): to e, seen by day, "too far away: they could not have heard you. Call out or go closer."; to d, unseen, "out of earshot: they could not have heard you.";
  - the player's line to d (13 m): its `silence` row and an `act_outcome` (act, reach, not ok, the same words);
  - a graph's say to e, out of earshot as it comes due: not said (no chronicle line, nobody receives it), and the speaker is told "… You did not say your planned line: “Queued words for e.”.";
  - with `set_world_law speech_truth false`: d's silence is speech-2's "No answer from …", and the queued line to e is said into the air with speech-2's "too far to hear you" (the law is set back on after);
  - overheard names: b to c by name teaches c's name to those in earshot who see c; a name in a whisper teaches no one;
  - the two-word name "Mara Quill" is learned from "I'm Mara.".
- **`crowd`** places N minded people in a square, says room lines in turn at a declared rate through `mind_say`, and reads the server's `/v1/metrics` for this database. It reports:
  - `reducer_wasm_time_usec` and `reducer_wasmtime_fuel_used` per `mind_say`;
  - reducer plus query time;
  - `spacetime_num_rows_inserted_total` by table per line;
  - speech rows per line;
  - the mean `line_heard` hearers.

  Run it on the pre-change module with `--baseline` for the comparison.

Privacy across experience rows, prompts, clients and memory is `verify-minds/scripts/privacy.py` (verify-minds, "Privacy of words").
