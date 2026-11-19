# Value-only law changes (`law_override`)

Since `law-override` (2026-11-19, [docs/LAW_OVERRIDE.md](../../../../docs/LAW_OVERRIDE.md)). A world's own law values live in the public `law_override` table. Its law revision is in the private one-row `law_revision` table. The authority and every client lay the values over the compiled script in one place (`living_rules::script::Scripts::with_overrides`, `apply_overrides`).

## What it does

`set_world_law` takes one of two paths, depending on the law.

**A value-only law** (`VALUE_ONLY`, unless the world's script reads it outside its constants):

- **Which laws:** the delivery laws `cue_transport_on` and `near_tier_on`, the five `cover_*` laws, and `gaze_on`.
- **What the edit writes:** its row and the next law revision.
- **What it keeps:** the script revision and the script row. There is no compile and no validation.
- **What is refreshed, per class:**
  - delivery: nothing derived; the next tick reads the new value;
  - cover: the `cover_law` row at once, and the cover mask at the next map read (only when the policy changed);
  - gaze: the gaze ceilings and the senses; `applied_gaze` is deleted when gaze goes off.
- **What is recorded:** `law_change` (its `revision` is the script revision in force) and a chronicle line "… (law revision N, value only, script revision M)".

**Any other law, and a source edit (`install_script`):** a full install with a new script revision, as before. The values in `law_override` are written at the script's end and kept.

**Refusals leave nothing written:**

- a value of another kind;
- a name that is not a law;
- a player's call ("admin only");
- a value a derived check refuses after the rows were written, which rolls back: `gaze_on` true under an overlay whose `gaze_ceiling` is out of bounds.

The next edit then takes the same law revision.

**Migration.** A world from before the table has its `world_law` rows copied into `law_override` once, by the first transaction that reads the laws: the tick.

## Driving it

```bash
R=client-law-$(date +%H%M%S)   # a client-* name: the first-result checks drive verify-client's drive.py
python3 "$V" launch --run "$R" --seed island     # gaze off: the rollback scene runs; cover geometry: the cover laws too
python3 "$V" doctor --run "$R"
python3 .agents/skills/verify-core/scripts/law_override.py checks --run "$R" > ".local/living/verify/$R/law-checks.txt" 2>&1
python3 .agents/skills/verify-core/scripts/law_override.py time --run "$R" > ".local/living/verify/$R/law-time.txt" 2>&1
python3 "$V" cleanup --run "$R"
```

The two parts:

- **`checks`** needs the verify-client probe built: its last two checks read a client's first subscription result through `drive.py --query`.
- **`time`** reads each call's reducer time from the module's own spans in the database log: `set_world_law`, `set_world_law.value_only`, `install.compile` and `install.validate`. It also records the HTTP round trip and the first tick after the commit (with `set_profile` on).
  - Each value-only law goes to its other value and back `--repeat` times; `fire_warmth` is the full-install reference.
  - It runs on main's module too: there the install spans and the round trip are the measure.
  - Run it on a world launched from main's worktree for the before.

Evidence: `law-checks.json`, `law-time.json`, `law-first-before.jsonl`, `law-first-after.jsonl` and the run's `actions.log`.

**Cargo.** `living_rules::law_override_check` covers:

- precedence: the override over the written-in values over `laws()`, through Rust and through Rhai's `law(name)`;
- a value-only edit reading exactly as a fresh compile with the value, for each law on the island and Cullet (the laws, the value through Rust and Rhai, the gaze ceilings, every senses sample through the memo, the constants' words);
- `gaze_on` changing the field;
- a refused value changing nothing;
- the source guard.

The mind test `the_laws_minds_read_change_by_an_install` covers the minds' laws.

The scenes for the laws themselves:

- the delivery laws: verify-client `cues.py` and `near_tier.py`;
- gaze and cover on Cullet: verify-player `gaze.py` and `sight_on.py`.

## Gotchas

- `law_override.py checks` needs a seed whose `gaze_on` is off for its rollback scene: the island, or the default world. On Cullet, gaze is on in its laws, and an overlay with a bad ceiling would be refused at its install. The scene says when it skips.
- The cover laws are driven only on a world with quantized cover geometry (`cover_ground` row 0): the island and Cullet. `cover_sight_on` true without geometry is refused before anything is written.
- The timing spans are logged by the module. On a module from before `law-override` there is no `set_world_law` span, so the round trip and `install.*` spans are the measure.
- The verify lease is 10 minutes. `time` with `--repeat 3` on Cullet takes about 3 minutes on main's module (each change about 2.4 s plus the waits), and less than a minute on the branch.
