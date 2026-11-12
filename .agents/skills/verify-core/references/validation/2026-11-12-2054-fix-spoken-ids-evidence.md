# verify-core: fix-spoken-ids, the prompt and the evidence

Follows `2026-11-12-2019-fix-spoken-ids.md`. The same branch, after the coordinator's two conditions: the prompts' sentence on ids, and the original line kept as evidence. Trial service `slop-trials-stdb`, `scoped`, private `CARGO_TARGET_DIR`.

- **The change here.** When the rewrite changes a line, `speech::speak` also gives the speaker a `spoken_as` experience (salience 0.2): "Your line was said as “…”: you wrote “…”, and #ids are not words anyone hears.". Hearers and the chronicle get only the words said.
- **`say`** 37/37 (`core-ids2-214131`), with a new check: "the speaker keeps what it wrote beside what was said (spoken_as)". The speaker has exactly one `spoken_as` row, holding "Watch out, #<b> is here, and the archer #<far> too." and "…and the archer too.". The two earlier id checks still pass.

  Evidence: `.local/living/verify/core-ids2-214131/` (`say.txt`, `say-id-line-kept.json`).
- **Rules test** `spoken_lines_carry_no_ids` passes (rules unchanged since the first record).
- **`just living-check`** through `~/slop-mq/build-slot`, with pipefail: exit 0. Authority, mind and viewer, and seed laws ran; game, game tests, viewer wasm, rules tests and script gate were skipped on inputs identical to the first record's passing run.
