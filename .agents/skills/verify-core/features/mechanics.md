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

### A spoiled fish and a missed threat

Two gate flakes on 2026-11-20 (`gate-1120141655-c45a27-a-mechanics`, `gate-1120150447-da978a-a-mechanics`; each passed alone on a fresh world, the runs took about 480 s under load against 274 s alone):

- **Smoking, bow, arrows and leather.** The walker carried one raw fish, and raw fish spoils by chance each minute it is carried (`tick::spoil` in `living/authority/src/tick.rs`: a stack loses `qty × rate` in expectation, the fraction drawn at random; `spoil_per_h("fish")` in `skills.rhai`). The fish was lost on the walk ("Some of your fish spoiled (1 lost)", then "You failed to smoke fish → campfire: no fish in your pack"). The driver now grants three fish and compares the products without the raw fish left over; smoking takes one (`takes_of`).
- **Force: a threat is perceived.** `threatened` holds only while a threaten is under way against the walker (phase 1 of its activity, 2 s; `living/authority/src/brain.rs`), and G must evaluate its graph inside that window. Under load G perceived the threat ("a stranger threatens you, fists raised") but never yielded within the 15 s wait. F now threatens in a loop (`first` of the threaten and a 1 s wait, as the killing scene attacks) until G gives in, the wait is 30 s, and F is set idle after.
- **Force: a wolf does not dare.** Found while proving the two fixes (four parallel fresh worlds, `mechflake-3`): the wolf, just placed beside I, did not see I yet ("stuck: attack: no #I in sight"), so its one-step attack gave up and never balked. The wolf now attempts in the same loop until it balks (20 s), and is set idle after as before.

### Walkers that walk apart, and a fish spoiled in the grant

Gate flakes on 2026-11-20 (`gate-1120231507-0192e9-a-mechanics`: tending; earlier, the tablet chain as in `core-1004`) and their causes (branch `mechanics-flake-2`). All come from 64 fresh worlds of main's module, 4 at a time on a scratch server under the gate's load (`gate-mf2-*-mechanics`; the table below). Each check now waits for its own actors' result, and the driver puts them back together where a scene starts. A failure is still a failure: no check is retried until it passes.

- **Tending wounds.** The blow and the care never started: A and B were 14 to 17 m apart, out of A's sight, when A was told to attack. Two looser checks had let the scene move on while A was still busy:
  - **planting** passed on any new resource node, and other characters plant too, so A was still walking to its bush;
  - **conception** passed on any `expecting` row, an animal's included.

  B was placed beside A on the way, and the shelter went there; A then walked on to its bush.
  - **Fixed:** planting waits for a new berry bush within 3 m of A's chosen spot, and conception for an `expecting` row of A with B.
  - **Before the blow:** if A and B are more than 2 m apart, B is placed beside A again, and the driver prints that it was (`tending: B was … m from A; placed beside A again`).
  - **Diagnosis kept:** the tending line prints A's stamina and the A–B distance. On a failure the driver dumps A's feedback and activity.
- **The tablet chain** (tablet, reading, spear, trade, teaching, and the checks downstream). B was 26 m from A when the give was due. The walkers forage on their spawn graphs, and B was placed beside A before seven setup calls (about a second each under load) and only then set idle. Each give failed, and the sequence went back to its first step: "Walker1 wrote a tablet (×6)".
  - **Fixed:** A and B are set idle before B is placed. Before the write-and-give, the driver checks the gap and places B again, saying so.
  - **Diagnosis kept:** the setup line prints the gap. On a failure the driver prints both positions and A's feedback.
- **Act: conception chosen by both** (C and D; `gate-mf2-d1-3`, `f3-4`). The same setup order: C and D were placed beside A, then the grants ran, and only then were they set to rest. Now they rest first, and D is placed beside C again (said) if they are more than 2 m apart before the two conceive acts. On a failure the driver prints their distance and what each was told.
- **A fish spoiled between the grant and the read-back** in the smoking scene's `reset_pack` (3 granted, 2 read). It raised, and the whole driver stopped with no results. A shortfall is now topped up before the pack is compared.
- **Planting, without the loose check, failed once on its own** (`gate-mf2-p4-1`): Walker1 never planted in 90 s while nine others planted 66 bushes. The old check had hidden this. On a failure the driver now prints A's position against the bush, its feedback and its activity, for the next occurrence.
- **Not fixed here:**
  - **The threat check** waits on the authority's stuck-activity fix (the Spark's).
  - **The wolf check failed 3 of 64** (`gate-mf2-d1-2`, `d2-3`, `p4-3`). In `p4-3` the wolf saw I and J 2 to 3 tiles away right after it was placed, and was 14.3 m from I at the end of its 20 s, with no balk and no activity: it walked off before its attack was refused for not daring. On a failure the driver now prints the wolf's distances, activity and feedback. Found and fixed later ([below](#the-wolf-that-fled-before-it-was-told-to-attack)): it fled from I before its attack was installed.
  - **"Road, wall and gate built" failed once** (`gate-mf2-p3-3`, the gate not built in 60 s). It now prints A's place, the target tiles, the nodes near them and A's feedback on a failure.

The rounds: `d` on main's driver with diagnostics only; `p` while the fixes went in (the tending and planting fixes from `p1`, the C/D order after `f3`); `f` and `g` on the driver as merged, `g` with the C/D fix. Every run that was not 23/23:

| Round | 23/23 | Failing keys |
|---|---|---|
| d1 | 2/4 | wolf; the tablet chain (16/23: tablet, reading, spear, trade, teaching, act conception, death) |
| d2 | 3/4 | wolf |
| d3 | 2/4 | tending ×2 (A–B 13.96 and 16.70 m at the blow) |
| p1, p2, p5 | 4/4 each | |
| p3 | 3/4 | road, wall and gate built (21/22) |
| p4 | 2/4 | wolf; planting (Walker1 never planted) |
| p6 | 3/4 | the tablet chain (18/23; B 26 m away) |
| p7 | 3/4 | the driver stopped in `reset_pack` (a fish spoiled; 0/0) |
| f1, f2 | 4/4 each | |
| f3 | 3/4 | act: conception chosen by both |
| g1, g2, g3 | 4/4 each | |

### The wolf that fled before it was told to attack

The wolf check's remaining flake (3 of 64 in `gate-mf2-*`; above), found and fixed on branch `wolf-drift` (2026-11-21).

- **The cause.** The driver placed the wolf beside I, read I's health, and only then installed the attack loop (`set_behavior`). Between the two calls, half a second or more under load, the wolf's own ways ran beside two people. Its `stay safe` routine (`living/seeds/repertoire.json`, species `wolf`) flees the nearest person within 7 tiles unless it is starving (hunger 90). The wolf fled 10 to 16 m, beyond its sight of about 10 tiles. Its attack loop then never resolved I, so nothing was refused for not daring: no balk, and the check failed. A flee that stopped within sight still balked, which is why most runs passed. The 2026-11-20 diagnosis above ("did not see I yet") was very likely the same flee.
- **The evidence.** `.local/wolf/probe.py` repeats the step on one world with a fresh wolf each trial and samples it, four default-seed worlds at a time on a scratch server:
  - **Round `w1`** (the driver's order, 36 trials): 3 trials with no balk, the wolf 11.7 to 12.1 m from I by the first sample (about 2.5 s after placement), its activity the attack loop's `wait`. In the 33 that balked, the wolf was already 2 to 10 m off when it balked.
  - **Round `w2`** (alternating, 48 trials): place first, 7 of 24 with no balk (the wolf 11.3 to 16.2 m off at the end); attack loop first, 0 of 24, the wolf 1.6 m from I at the balk.
- **The fix, in the fixture only.** The attack loop is installed before the wolf is placed. Placing it ends whatever it was doing (`act::relocated`), and its next evaluation is the attack, beside I.
- **The proof.** The fixed driver, as the gate drives it (`--gate-world`), on 12 fresh worlds of main's module (`e1f380909`), 4 at a time (`gate-wd-a1..a3-*-mechanics`): 12 of 12 at 23/23.
- **Seen in the probe, not in the driver.** A balked trial sometimes failed on I's health (about 1.5 HP lower 8 s later) with no attack on I; the same drop repeated across trials in one world. I had no "attacked" feedback; the probe kept I standing for minutes without food, so most likely I's own needs (not traced further). The driver's wolf scene comes early, and its three failures all had I's health rising.

### Recognize and investigate intermittent failures

The preserved `core-1004-proof-mechanics` run passed 16/23 on unchanged product code. It failed tablet transfer, reading, spear crafting, trade, teaching, deliberate conception and expecting-parent retention. Its tablet stayed with Walker1. Walker2 later reported "You failed to accept → Walker1: they moved away". The fresh fix-round runs also retain blocked-path refusals between walkers. Read [the validation record](../references/validation/history.md) for the exact failed keys, outputs and fresh-run counts.

Keep `mechanics.json`, `mechanics.txt` and `stdb-actions.jsonl` for every attempt. A mixed pass count on fresh databases is evidence of intermittent behavior, not permission to waive a failure. Check whether the first failed operation explains later missing rows. Compare actor feedback, positions, inventory, installed graphs and pregnancies before blaming each dependent skill.

`living/authority/src/lib.rs:142,143` and `living/authority/src/seed.rs:869-870` randomize walker placement and genes. `living/authority/src/lib.rs:151` installs their forager repertoire. The driver sets A and B idle before placing B beside A (since `mechanics-flake-2`); C through J keep their instincts until their later scenes. `place_near` (`living/authority/src/lib.rs`) puts a character 1 m east of its target only when that tile is walkable and free, else on the nearest free walkable tile of the target's ground within 6 m (since `fix-place-free`, 2026-11-11; before, it placed one tile east without checking terrain). `living/authority/src/act.rs:974` rejects a target that moved during an action. `living/authority/src/brain.rs:374,384` resets a failed sequence to its first step, so a failed give can cause repeated writes. Timing, terrain and live neighbours are plausible contributors. A passing rerun does not identify which one caused a preserved failure.

The gift predicate at `living/tools/verify_mechanics.py:197` accepts any berries in D's inventory, including the three spawn berries and instinct gathering. Its success-feedback check at `living/tools/verify_mechanics.py:199` can match the preceding eat act. A reported gift PASS can coexist with "give berries: the way is blocked". Read the complete inventory and feedback before counting a gift effect.

The conception check accepted any expecting row until 2026-11-21. It now waits for an `expecting` row of the two walkers themselves (above), so an animal's pregnancy no longer passes it. The death check needs an actual walker pregnancy too, so a real conception failure shows in both.

To check reproducibility, repeat the mechanics recipe in [SKILL.md](../SKILL.md) at least four times. Give each attempt a fresh `$R-mechanics-1` through `$R-mechanics-4` name and a fresh `verify-core-*` database. Keep all counts and failing keys. If a failure repeats with the same installed graph, valid placement, inventory and actor-specific preconditions, isolate that operation on a fresh scene and treat it as a possible regression. Consistent Cargo failures or the same refusal under controlled preconditions also need investigation. Intermittent mechanics failures stay `FAIL`; only documented product defects such as yielded-healthy seize use `XFAIL KNOWN ISSUE`.
