# Skills, laws and exchanges

## Sub-features

- Write and give a tablet, read its technique and craft with learned know-how.
- Trade atomically, teach, plant and tend wounds. Every know-how in the world's `know_how` table can be taught, not only what experimenting reveals: `scenes.py teach` has a knower teach fire_bolt and wound_tending and checks a thing (leather) is refused with what makes it (since 2026-11-11, branch `rules-offers`; before, `teach_check` refused both as "no technique"). Cargo: `every_know_how_can_be_taught`, and `cullet_s_glassmaking_can_be_taught` for a seed's own know-how.
- Build roads, walls and gates; close and reopen a gate.
- Craft and use a net, smoke fish, make bows, arrows and leather, and clear forest.
- Install runtime laws and enforce their movement-input rate limit.
- Refuse a script at install, naming the function, when a law or skill function fails on the install samples, returns the wrong shape, reads a context field the engine does not provide, or exceeds the engine's limits; a refused install changes nothing.

## How to get to it (user POV)

Characters work through graph leaves and acts. `living/scripts/skills.rhai` provides checks, durations, effects and laws. The typed boundary is `living/rules/src/script.rs:721,735,749,816` (`check`, `duration_ms`, `done`, `laws`). The authority checks again at completion before applying effects.

Since 2026-11-09 (`rhai-1`, docs/SCRIPT_ENGINES.md "What changed"):

- Each law is called with only the context fields it reads, found in its AST when the script compiles (`living/rules/src/script/fields.rs`, `context.rs`).
- Numbers looked up by a name (`combat_cooldown`, `lunge`, `max_hp`, …) are read when the script compiles and served from a table (`script.rs:872`, `num_of`).
- `install_script` (`living/authority/src/lib.rs:100`) and `init` run `Scripts::validate` (`script.rs:573`, `living/rules/src/script/check.rs:86`) before writing anything. It calls every law and skill function on sample states, the way the engine calls it, and logs the operations each took.
- The engine limits are `LIMITS` (`script.rs:488`): 2,000 operations, call depth 8, expression depth 40, strings 2,048, arrays and maps 64. The source cap is 256 KiB.

## Driving it with verify_mechanics.py, codes.py and Cargo

Run the existing mechanics driver through the recorder using [SKILL.md](../SKILL.md). Keep its 23-check report, transcript and `stdb-actions.jsonl`. Cargo checks skill preconditions, missing techniques, costs, rates and typed effects. Steering changes `input_hz` and `input_burst` through `install_script` and observes movement refusals.

Cargo also covers the install checks and the lean contexts:

- `script::check::tests::the_rules_pass_their_install_checks` and `an_install_names_the_function_it_refuses`;
- `lean_contexts_answer_as_the_whole_context_does`, which compares each law's answer with only its fields against the whole map over all samples;
- `numbers_by_name_are_tables_read_once`.

`cargo test -p living-rules --release measure_limits -- --ignored --nocapture` prints each function's operations, the least limits that pass, and each law's fields.

Live, `scripts/codes.py RUN` checks the refusals on a launched run. After its code checks, it installs three broken scripts with `--expect-refusal`: a law reading `a.actor.hungr`, a skill whose effects divide by zero, and a law past the operation limit. Each refusal must name its function, and the script revision and the cards must stay as they were.

## Gotchas

- Both existing drivers publish their own database. Pass `--db verify-core-...`; never use their defaults.
- Run the shared baseline launch first to build the default WASM. Non-default seed builds have separate artifact names.
- `docs/LIVING_CORE.md:425` retains the historical 14-check count. The driver has 23.
- Admin setup does not prove player authority, personal learning or model reasoning.
- Seize is absent from the existing driver. Use [combat.md](combat.md).
- A script that a world installed before 2026-11-09 is not re-validated when the module is updated: the cached `Scripts` only compiles it. Its laws then run under the lower limits. A law that needs more than 2,000 operations fails each time it is asked, and the engine falls back to its default or refuses the action. Reinstall the script to see its refusal.
- A skill is any one-parameter function named `<skill>_check`, `_duration`, `_done`, `_hit` or `_missile`. Helpers with those suffixes and more parameters (`gesture_check(a, reach)`) are not validated as skills.

### A fished-out spot

The net check gives Walker4 a net, then a fishing spot. Residents fish too, and a spot with nothing left fails the gather ("the fishing_spot is depleted"), which also fails the chained smoking and crafting check. With the combat change of 2026-11-09 (docs/COMBAT.md) that spot was fished out in four of four fresh worlds, and in none of two worlds on the base commit; why residents fished it out more often is not established. The driver then picked the nearest spot holding at least two fish, and the net still failed once with no reason in the walker's experiences. Cause (2026-11-09): the drop, craft, walk and gather were one `seq`, and a sequence restarts from its first step when a step fails; with the berries already dropped, `drop` failed on every later pass, so one failed gather (the spot emptied during the walk) left the walker never gathering again, and identical repeated failures are not recorded as experiences. The driver now crafts the net in its own sequence, places the walker at a spot holding at least two fish, and gathers in a loop until it works. With that: 23 of 23 in two of two fresh worlds (`core-traits-mech-1`, `-2`).

### Recognize and investigate intermittent failures

The preserved `core-1004-proof-mechanics` run passed 16/23 on unchanged product code. It failed tablet transfer, reading, spear crafting, trade, teaching, deliberate conception and expecting-parent retention. Its tablet stayed with Walker1. Walker2 later reported "You failed to accept → Walker1: they moved away". The fresh fix-round runs also retain blocked-path refusals between walkers. Read [the validation record](../references/validation/history.md) for the exact failed keys, outputs and fresh-run counts.

Keep `mechanics.json`, `mechanics.txt` and `stdb-actions.jsonl` for every attempt. A mixed pass count on fresh databases is evidence of intermittent behavior, not permission to waive a failure. Check whether the first failed operation explains later missing rows. Compare actor feedback, positions, inventory, installed graphs and pregnancies before blaming each dependent skill.

`living/authority/src/lib.rs:142,143` and `living/authority/src/seed.rs:869-870` randomize walker placement and genes. `living/authority/src/lib.rs:151` installs their forager repertoire. `living/tools/verify_mechanics.py:77,79` waits before scene setup, and C through J keep their instincts until their later scenes. `place_near` (`living/authority/src/lib.rs`) puts a character 1 m east of its target only when that tile is walkable and free, else on the nearest free walkable tile of the target's ground within 6 m (since `fix-place-free`, 2026-11-11; before, it placed one tile east without checking terrain). `living/authority/src/act.rs:974` rejects a target that moved during an action. `living/authority/src/brain.rs:374,384` resets a failed sequence to its first step, so a failed give can cause repeated writes. Timing, terrain and live neighbours are plausible contributors. A passing rerun does not identify which one caused a preserved failure.

The gift predicate at `living/tools/verify_mechanics.py:197` accepts any berries in D's inventory, including the three spawn berries and instinct gathering. Its success-feedback check at `living/tools/verify_mechanics.py:199` can match the preceding eat act. A reported gift PASS can coexist with "give berries: the way is blocked". Read the complete inventory and feedback before counting a gift effect.

The conception predicate at `living/tools/verify_mechanics.py:141` accepts any expecting row. Unrelated animal pregnancies can satisfy it before the walkers finish eating and conceiving. The next scene replaces their graphs at `living/tools/verify_mechanics.py:147,148`. The death check at `living/tools/verify_mechanics.py:331,337` requires an actual walker pregnancy, so it can fail downstream. Record this false-positive risk separately from a broken conception or death rule.

To check reproducibility, repeat the mechanics recipe in [SKILL.md](../SKILL.md) at least four times. Give each attempt a fresh `$R-mechanics-1` through `$R-mechanics-4` name and a fresh `verify-core-*` database. Keep all counts and failing keys. If a failure repeats with the same installed graph, valid placement, inventory and actor-specific preconditions, isolate that operation on a fresh scene and treat it as a possible regression. Consistent Cargo failures or the same refusal under controlled preconditions also need investigation. Intermittent mechanics failures stay `FAIL`; only documented product defects such as yielded-healthy seize use `XFAIL KNOWN ISSUE`.
