# Skills, laws and exchanges

## Sub-features

- Write and give a tablet, read its technique and craft with learned know-how.
- Trade atomically, teach, plant and tend wounds.
- Build roads, walls and gates; close and reopen a gate.
- Craft and use a net, smoke fish, make bows, arrows and leather, and clear forest.
- Install runtime laws and enforce their movement-input rate limit.

## How to get to it (user POV)

Characters work through graph leaves and acts. `living/scripts/skills.rhai` provides checks, durations, effects and laws. The typed boundary is `living/rules/src/script.rs:313,327,338,359`. The authority checks again at completion before applying effects.

## Driving it with verify_mechanics.py and Cargo

Run the existing mechanics driver through the recorder using [SKILL.md](../SKILL.md). Keep its 23-check report, transcript and `stdb-actions.jsonl`. Cargo checks skill preconditions, missing techniques, costs, rates and typed effects. Steering changes `input_hz` and `input_burst` through `install_script` and observes movement refusals.

## Gotchas

- Both existing drivers publish their own database. Pass `--db verify-core-...`; never use their defaults.
- Run the shared baseline launch first to build the default WASM. Non-default seed builds have separate artifact names.
- `docs/LIVING_CORE.md:414` retains the historical 14-check count. The driver has 23.
- Admin setup does not prove player authority, personal learning or model reasoning.
- Seize is absent from the existing driver. Use [combat.md](combat.md).

### Recognize and investigate intermittent failures

The preserved `core-1004-proof-mechanics` run passed 16/23 on unchanged product code. It failed tablet transfer, reading, spear crafting, trade, teaching, deliberate conception and expecting-parent retention. Its tablet stayed with Walker1. Walker2 later reported "You failed to accept → Walker1: they moved away". The fresh fix-round runs also retain blocked-path refusals between walkers. Read [the validation record](../references/validation.md) for the exact failed keys, outputs and fresh-run counts.

Keep `mechanics.json`, `mechanics.txt` and `stdb-actions.jsonl` for every attempt. A mixed pass count on fresh databases is evidence of intermittent behavior, not permission to waive a failure. Check whether the first failed operation explains later missing rows. Compare actor feedback, positions, inventory, installed graphs and pregnancies before blaming each dependent skill.

`living/authority/src/lib.rs:124` and `living/authority/src/seed.rs:679` randomize walker placement and genes. `living/authority/src/lib.rs:132` installs their forager repertoire. `living/tools/verify_mechanics.py:77,79` waits before scene setup, and C through J keep their instincts until their later scenes. `living/authority/src/lib.rs:262` places a target one tile east without checking terrain. `living/authority/src/act.rs:794` rejects a target that moved during an action. `living/authority/src/brain.rs:366` resets a failed sequence to its first step, so a failed give can cause repeated writes. Timing, terrain and live neighbours are plausible contributors. A passing rerun does not identify which one caused a preserved failure.

The gift predicate at `living/tools/verify_mechanics.py:197` accepts any berries in D's inventory, including the three spawn berries and instinct gathering. Its success-feedback check at `living/tools/verify_mechanics.py:199` can match the preceding eat act. A reported gift PASS can coexist with "give berries: the way is blocked". Read the complete inventory and feedback before counting a gift effect.

The conception predicate at `living/tools/verify_mechanics.py:141` accepts any expecting row. Unrelated animal pregnancies can satisfy it before the walkers finish eating and conceiving. The next scene replaces their graphs at `living/tools/verify_mechanics.py:147,148`. The death check at `living/tools/verify_mechanics.py:323` requires an actual walker pregnancy, so it can fail downstream. Record this false-positive risk separately from a broken conception or death rule.

To check reproducibility, repeat the mechanics recipe in [SKILL.md](../SKILL.md) at least four times. Give each attempt a fresh `$R-mechanics-1` through `$R-mechanics-4` name and a fresh `verify-core-*` database. Keep all counts and failing keys. If a failure repeats with the same installed graph, valid placement, inventory and actor-specific preconditions, isolate that operation on a fresh scene and treat it as a possible regression. Consistent Cargo failures or the same refusal under controlled preconditions also need investigation. Intermittent mechanics failures stay `FAIL`; only documented product defects such as yielded-healthy seize use `XFAIL KNOWN ISSUE`.
