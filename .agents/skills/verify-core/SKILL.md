---
name: verify-core
description: Verify the living core authority's rules and scheduled loop. Use when changing ticks, behavior graphs, Rhai skills or laws (including skill specs, the world's data tables of goods, structures, resources and recipes, fires that eat fuel, and the world's records, hooks and stances), needs, the body's meters and statuses (the meters and status_of laws, bodily alarms), life stages, wildlife, combat (including the starter skills, missiles and skill timing), town life (residents' daily rhythm and working hours, starting ways by trade, places, weather, gestures), life tables (the `life_years` law), regrowth by season (`regrow_by_season`) and store capacity by kind (`holds`, `like`), sight that depends on facing (the fov_on law, set_world_law), first sights in a crowd, what a graph's "stranger" means (the stranger_by_name law), steering, deliberate acts, or viewer display sync. Covers living/viewer/src/sync.rs display-sync tests only on the viewer. Runs offline Cargo checks and real scripted scenes on verify-core-* scratch databases.
---

# Verify the core rules and loop

Read the [`verify` entry point](../verify/SKILL.md) first. It owns launch, doctor, identities, the observer, cleanup and evidence. This skill adds core checks. It never starts a mind service or calls a model.

Run commands from the repository root. Use a new run name for every attempt. Scripts reject names outside `core-*`; their databases must be `verify-core-*`. Preserve failed evidence and clean up failed attempts too.

Preconditions: `python3 .agents/skills/verify/scripts/verify.py launch --run "$R"` starts the local SpacetimeDB container if it is down. Use only the local service.

## Launch and doctor

```bash
V=.agents/skills/verify/scripts/verify.py
C=.agents/skills/verify-core/scripts
R=core-$(date +%Y%m%d-%H%M%S)
E=.local/living/verify/$R
mkdir -p "$E"
python3 "$V" launch --run "$R" > "$E/launch.txt" 2>&1
python3 "$V" doctor --run "$R" > "$E/doctor.txt" 2>&1
```

Stop driving if launch or doctor fails. Run cleanup and retain the error. The scenes use the in-container admin CLI. Do not mix a remote `LIVING_STDB_URL` with `stdb -s local`.

## Drive the baseline

```bash
python3 "$C/cargo_checks.py" --run "$R"
python3 "$C/scenes.py" tick --run "$R" > "$E/tick.txt" 2>&1
python3 "$C/scenes.py" needs --run "$R" > "$E/needs.txt" 2>&1
python3 "$C/scenes.py" alarms --run "$R" > "$E/alarms.txt" 2>&1
python3 "$C/scenes.py" food --run "$R" > "$E/food.txt" 2>&1
python3 "$C/scenes.py" refusal --run "$R" > "$E/refusal.txt" 2>&1
python3 "$C/scenes.py" teach --run "$R" > "$E/teach.txt" 2>&1
python3 "$C/scenes.py" seize --run "$R" > "$E/seize.txt" 2>&1
python3 "$C/scenes.py" sight --run "$R" > "$E/sight.txt" 2>&1
python3 "$C/scenes.py" senses --run "$R" > "$E/senses.txt" 2>&1
python3 "$C/scenes.py" doing --run "$R" > "$E/doing.txt" 2>&1
# First sights in a crowd: everyone in sight is told, several in one line (features/sight.md, about 30 s).
python3 "$C/scenes.py" crowd_sight --run "$R" > "$E/crowd_sight.txt" 2>&1
# A graph's "stranger" under the stranger_by_name law, off and on (features/graphs.md, about 30 s).
python3 "$C/scenes.py" stranger_filter --run "$R" > "$E/stranger_filter.txt" 2>&1
python3 "$C/scenes.py" moves --run "$R" > "$E/moves.txt" 2>&1
python3 "$C/scenes.py" death-names --run "$R" > "$E/death-names.txt" 2>&1
# Another's health in fight reports and health_of: the band, exact only while appraised (features/combat.md).
python3 "$C/scenes.py" health_seen --run "$R" > "$E/health_seen.txt" 2>&1
# Sight that depends on facing, switched by set_world_law (features/fov.md, about 3 min).
python3 "$C/scenes.py" fov --run "$R" > "$E/fov.txt" 2>&1
python3 "$C/scenes.py" say --run "$R" > "$E/say.txt" 2>&1
# Admin placement on free walkable tiles (features/steering.md#admin-placement); last: its bodies stay.
python3 "$C/scenes.py" placement --run "$R" > "$E/placement.txt" 2>&1
python3 "$V" cleanup --run "$R" > "$E/cleanup.txt" 2>&1

# Speech (features/speech.md): each scene on its own launched run (they spawn people named
# Walker1..4, and a second spawn would repeat the names).
for S in regress ways channels crowd; do
  P=$R-$S; mkdir -p ".local/living/verify/$P"
  python3 "$V" launch --run "$P" > ".local/living/verify/$P/launch.txt" 2>&1
  python3 "$C/speech.py" $S --run "$P" > ".local/living/verify/$P/speech-$S.txt" 2>&1
  python3 "$V" cleanup --run "$P" > ".local/living/verify/$P/cleanup.txt" 2>&1
done
# The regression proof: `regress --baseline` (and `crowd --baseline`) from a worktree at the
# base commit, then `speech.py diff <base-run> $R-regress`.

# The starter combat skills under graphs use the island seed (its newcomer kit, pack and
# skill cards); see features/combat.md.
K=$R-skirmish
mkdir -p ".local/living/verify/$K"
python3 "$V" launch --run "$K" --seed island > ".local/living/verify/$K/launch.txt" 2>&1
python3 "$C/scenes.py" skirmish --run "$K" > ".local/living/verify/$K/skirmish.txt" 2>&1
# The drop scene over low tiles (9: a cart, an open stall, a well, a building's overhang: open at eye height) on the same island world.
python3 "$C/scenes.py" low --run "$K" > ".local/living/verify/$K/low.txt" 2>&1
python3 "$V" cleanup --run "$K" > ".local/living/verify/$K/cleanup.txt" 2>&1

# Drops between ground levels hide nothing and block the foot (features/sight.md, about 1 min)
# on a planned settlement's land.
P=$R-drop
mkdir -p ".local/living/verify/$P"
python3 "$V" launch --run "$P" --seed plan-test > ".local/living/verify/$P/launch.txt" 2>&1
python3 "$C/scenes.py" drop --run "$P" > ".local/living/verify/$P/drop.txt" 2>&1
python3 "$V" cleanup --run "$P" > ".local/living/verify/$P/cleanup.txt" 2>&1

# Dealings on the world's records on an island world (about 3 min): agreements, demands, regard
# (features/dealings.md, docs/WORLD_RULES.md).
D=$R-dealings
mkdir -p ".local/living/verify/$D"
python3 "$V" launch --run "$D" --seed island > ".local/living/verify/$D/launch.txt" 2>&1
python3 "$C/scenes.py" dealings --run "$D" > ".local/living/verify/$D/dealings.txt" 2>&1
python3 "$V" cleanup --run "$D" > ".local/living/verify/$D/cleanup.txt" 2>&1

# Answers by id (about 1 min, any seed): accept/decline naming a trade offer or a proposal,
# refusals, decline told and witnessed, the unnamed order (features/dealings.md).
A=$R-answers
mkdir -p ".local/living/verify/$A"
python3 "$V" launch --run "$A" > ".local/living/verify/$A/launch.txt" 2>&1
python3 "$C/scenes.py" answers --run "$A" > ".local/living/verify/$A/answers.txt" 2>&1
python3 "$V" cleanup --run "$A" > ".local/living/verify/$A/cleanup.txt" 2>&1

# Town life on an island world: the daily rhythm by the world's own hours (about 14 min),
# rain, a wolf in town, gestures and making way (features/town.md, docs/TOWN_LIFE.md).
T=$R-town
mkdir -p ".local/living/verify/$T"
python3 "$V" launch --run "$T" --seed island > ".local/living/verify/$T/launch.txt" 2>&1
python3 "$C/town.py" --run "$T" > ".local/living/verify/$T/town.txt" 2>&1
python3 "$V" cleanup --run "$T" > ".local/living/verify/$T/cleanup.txt" 2>&1

# Rhythms at any hour and Cullet's trades (about 17 min): a night stoker rising at 14:00 and
# working the night, the day watch feeding the furnace and making glass, a baker's second sleep,
# Cullet's life stages, five trades at the places of the plan's open lots in their hours, and
# two households cooking at their own hearth and using their own store inside the house (hearth-1)
# (features/town.md, features/laws.md, docs/SEEDED_LIVES.md, docs/CULLET_LAYOUT.md pass 2).
Y=$R-rhythm
mkdir -p ".local/living/verify/$Y"
python3 "$C/rhythm.py" seed --run "$Y" > ".local/living/verify/$Y/seed.txt" 2>&1
python3 "$V" launch --run "$Y" --seed "$PWD/.local/living/verify/$Y/cullet-rhythm" > ".local/living/verify/$Y/launch.txt" 2>&1
python3 "$C/rhythm.py" drive --run "$Y" > ".local/living/verify/$Y/rhythm.txt" 2>&1
python3 "$V" cleanup --run "$Y" > ".local/living/verify/$Y/cleanup.txt" 2>&1

# Seeded lives on an island world (about 25 min): placement, routes, the road, ties
# (features/lives.md, docs/SEEDED_LIVES.md).
L=$R-lives
mkdir -p ".local/living/verify/$L"
python3 "$V" launch --run "$L" --seed island > ".local/living/verify/$L/launch.txt" 2>&1
python3 "$C/lives.py" --run "$L" --minutes 24 > ".local/living/verify/$L/lives.txt" 2>&1
python3 "$V" cleanup --run "$L" > ".local/living/verify/$L/cleanup.txt" 2>&1

# Goods, fires that eat fuel and recipes over Cullet's goods (about 9 min), and a seeded
# fishing ground's shared stock (features/goods.md, docs/WORLD_RULES.md).
G=$R-goods
mkdir -p ".local/living/verify/$G"
python3 "$V" launch --run "$G" --seed "$PWD/$C/goods" > ".local/living/verify/$G/launch.txt" 2>&1
python3 "$C/scenes.py" goods --run "$G" > ".local/living/verify/$G/goods.txt" 2>&1
python3 "$C/scenes.py" stock --run "$G" > ".local/living/verify/$G/stock.txt" 2>&1
# Crafting, cooking and smoking as recipes, by acts and by an old graph (features/goods.md).
python3 "$C/scenes.py" making --run "$G" > ".local/living/verify/$G/making.txt" 2>&1
python3 "$V" cleanup --run "$G" > ".local/living/verify/$G/cleanup.txt" 2>&1

# A world's own day and laws (about 30 min; it waits for the world's own night):
# day_minutes, the laws overlay, rates per game hour, sight, names, lamplight
# (features/laws.md, docs/CULLET_RULES.md).
W=$R-laws
mkdir -p ".local/living/verify/$W"
python3 "$V" launch --run "$W" --seed cullet-laws > ".local/living/verify/$W/launch.txt" 2>&1
python3 "$C/scenes.py" laws --run "$W" > ".local/living/verify/$W/laws.txt" 2>&1
python3 "$V" cleanup --run "$W" > ".local/living/verify/$W/cleanup.txt" 2>&1

# Spoiling and regrowth in game time on a world's own day (features/laws.md#decay; a whole
# Cullet game day is 48 real minutes, `--game-hours 2` about 5 minutes): raw fish carried and
# stored, an emptied greens bed regrowing, both at the laws' per-hour numbers in real time.
Y=$R-decay
mkdir -p ".local/living/verify/$Y"
python3 "$V" launch --run "$Y" --seed cullet-laws > ".local/living/verify/$Y/launch.txt" 2>&1
python3 "$C/scenes.py" decay --run "$Y" > ".local/living/verify/$Y/decay.txt" 2>&1
python3 "$V" cleanup --run "$Y" > ".local/living/verify/$Y/cleanup.txt" 2>&1

# Regrowth by season (features/laws.md#winter; about 14 min, it waits for the world's own
# winter): Cullet's laws on a 4-minute day and 4-day year; a fishing spot regrows at its winter
# share, a root plot rests.
Y=$R-winter
mkdir -p ".local/living/verify/$Y"
python3 "$V" launch --run "$Y" --seed "$PWD/$C/winter" > ".local/living/verify/$Y/launch.txt" 2>&1
python3 "$C/scenes.py" winter --run "$Y" > ".local/living/verify/$Y/winter.txt" 2>&1
python3 "$V" cleanup --run "$Y" > ".local/living/verify/$Y/cleanup.txt" 2>&1

# Infant assertions use their own small, long-lived family fixture.
I=$R-infant
IE=.local/living/verify/$I
mkdir -p "$IE"
python3 "$V" launch --run "$I" --seed "$PWD/$C/infant" \
  --target-dir "$PWD/living/target/verify-infant" > "$IE/launch.txt" 2>&1
python3 "$V" doctor --run "$I" > "$IE/doctor.txt" 2>&1
python3 "$C/scenes.py" infant --run "$I" > "$IE/infant.txt" 2>&1
python3 "$V" cleanup --run "$I" > "$IE/cleanup.txt" 2>&1
```

Record each exit status. Unexpected failures exit 1. Run the remaining independent checks, then report the failure. `seize` checks refusal from an unyielded healthy person, seizure from a yielded healthy person, exact transfer, witnesses, and that blows on someone who yielded land and kill. If the yielded seizure fails, it still drives the badly-hurt path and exits 1. A check marked known (`XFAIL`/`XPASS`) exits 1 when it starts passing, so the stale expectation gets reviewed.

`infant` is part of this baseline. Its fixture keeps ordinary lifespans, a 12-minute day and production species/rules. Its hunger waits divide by the rules' `person_pace` (0.3 since iter-11), so the night wait can take up to about 2 hours (2100 s / pace) and the scene about 2 hours in all; before iter-11 allow about 30 minutes: the first night arrives before hunger suppresses healing, so the scene waits for the second real night. It compares shelter warmth, the parent's perceived infant `looks`, anchored HP rates and actual health loss. Then a cloak and a bounded berry meal reset the cry episode; the scene waits until hunger returns above 55 and holds it as the sole cause for a 250-second window. One parent answers scripted requests; the other stays pending. At 60 seconds the answered parent receives an unrelated one-shot `think` request through the existing admin graph setup, then returns to rest. `infant-unrelated-pending.json` saves that row before the reminder. The scene checks that the due cry merges into the same request and preserves its unrelated reason. It also checks parent-only prompts, pending cry suppression, 120-second reminders, witness experiences and one nearest caring adult after the parents leave hearing. No mind service runs.

`infant-prompt-rate.json` records created and merged requests per infant per authority minute, including the initial request. `infant-prompt-events.jsonl` retains each cry prompt stamp and its request row. The changed authority supplies `infant_cry.prompted`; the baseline matches cry `experience.at_ms` to an eligible request spanning that timestamp. Raw request snapshots go to `infant-request-observations.jsonl`. Dawn and reflection updates are retained there and excluded from the cry count. Polling runs roughly once per second, with CLI overhead; it measures this bounded scene, not model calls or a general workload rate. `--resume-infant` reruns cry checks from the retained `infant-cast.json` thermal checkpoint after a harness failure. Preserve the failed results, events and observations in a separate attempt directory, run doctor again, then resume on the same owned database. The scene resets the cry episode through food and waits for hunger to return. `--baseline` runs the same scene on the pre-change authority, retaining physical assertions and measurements while omitting the new appearance and routing/cadence assertions.

`cargo_checks.py` saves separate transcripts for these commands:

```bash
cargo test --manifest-path living/Cargo.toml -p living-rules
cargo test --manifest-path living/Cargo.toml -p living-authority --lib
cargo test --manifest-path living/Cargo.toml -p living-mind
cargo test --manifest-path living/Cargo.toml -p living-viewer sync::tests
```

The authority tests run on the host despite its WASM `cdylib` target and include infant cry routing and cadence. Rules includes infant appearance versus cold damage checks and one ignored reference printer. The mind's five ignored Neo4j tests stay skipped. Do not add `--ignored`. `just living-check` builds the authority WASM, the mind, and the native and WASM viewer targets. Only its test step runs rules tests. It skips a step that already passed on this machine on identical inputs (docs/TOOLING.md); `just living-check-full` runs every step, and `LIVING_CHECK_SERIAL=1` shows cargo's output and the test counts on the terminal. The commands above also run authority, mind and viewer sync tests. Viewer coverage is limited to `living/viewer/src/sync.rs`; no other viewer code is verified here.

## Drive the existing mechanics and steering scripts

These drivers publish and delete their own worlds. Run them after the baseline launch builds the default `living_authority.wasm`. The recorder uses their existing `LIVING_STDB` hook to retain calls and SQL. It also records ownership in `state.json` for shared cleanup after a driver crashes.

```bash
M=$R-mechanics
S=$R-steering
mkdir -p ".local/living/verify/$M" ".local/living/verify/$S"
CORE_VERIFY_RUN="$M" LIVING_STDB="$PWD/$C/record_stdb.py" \
  python3 living/tools/verify_mechanics.py --db "verify-$M" \
  --out ".local/living/verify/$M/mechanics.json" \
  > ".local/living/verify/$M/mechanics.txt" 2>&1
python3 "$V" cleanup --run "$M"
CORE_VERIFY_RUN="$S" LIVING_STDB="$PWD/$C/record_stdb.py" \
  python3 living/tools/verify_steering.py --db "verify-$S" \
  > ".local/living/verify/$S/steering.txt" 2>&1
python3 "$V" cleanup --run "$S"
```

Expect 23 mechanics checks and five steering checks. Inspect every result and keep failures even when another fresh world passes. The driver has a recorded mechanics flake. Use the recognition and investigation steps in [mechanics.md](features/mechanics.md), and retain every failing result. Do not convert these intermittent failures into XFAIL or discard them after a passing retry. `docs/LIVING_CORE.md:425` retains the historical 14-check count.

## Drive life and wildlife

Use fresh `stage1-acts` worlds. The seed has eight people including an infant, 16 deer, three wolves, `year_days: 4` and `life_pace: 0.0714`. The day remains 12 real minutes. `lab-lifecycle` also compresses lives but does not explicitly list an infant. Gestation uses species life fractions, not `laws.gestation_days`.

```bash
L=$R-life
mkdir -p ".local/living/verify/$L"
python3 "$V" launch --run "$L" --seed stage1-acts > ".local/living/verify/$L/launch.txt" 2>&1
python3 "$V" doctor --run "$L" > ".local/living/verify/$L/doctor.txt" 2>&1
python3 "$C/scenes.py" lifecycle --run "$L" > ".local/living/verify/$L/lifecycle.txt" 2>&1
python3 "$V" cleanup --run "$L"

# The laws of starting a family and of the longing for a child (about 2 min, longer if it
# must wait for day): conceive_roof, conceive_food, longing_after_min, longing_food.
F=$R-family-laws
mkdir -p ".local/living/verify/$F"
python3 "$V" launch --run "$F" --seed stage1-acts > ".local/living/verify/$F/launch.txt" 2>&1
python3 "$V" doctor --run "$F" > ".local/living/verify/$F/doctor.txt" 2>&1
python3 "$C/scenes.py" family_laws --run "$F" > ".local/living/verify/$F/family_laws.txt" 2>&1
python3 "$V" cleanup --run "$F"

W=$R-wildlife
mkdir -p ".local/living/verify/$W"
python3 "$V" launch --run "$W" --seed stage1-acts > ".local/living/verify/$W/launch.txt" 2>&1
python3 "$V" doctor --run "$W" > ".local/living/verify/$W/doctor.txt" 2>&1
python3 "$C/scenes.py" wildlife --run "$W" > ".local/living/verify/$W/wildlife.txt" 2>&1
python3 "$V" cleanup --run "$W"

# Remains: every death leaves the carcass law's items, a kill feeds nobody by itself, two wolves
# take from one kill, remains expire (remains_h shortened to 3 game hours, 90 s on the 12-minute day), wander keeps its heading.
M=$R-remains
mkdir -p ".local/living/verify/$M"
python3 "$V" launch --run "$M" --seed stage1-acts > ".local/living/verify/$M/launch.txt" 2>&1
python3 "$C/scenes.py" remains --run "$M" > ".local/living/verify/$M/remains.txt" 2>&1
python3 "$V" cleanup --run "$M"

# A deer flees a wolf: the distance only grows (features/steering.md#flight).
F=$R-flee
mkdir -p ".local/living/verify/$F"
python3 "$V" launch --run "$F" --seed stage1-acts > ".local/living/verify/$F/launch.txt" 2>&1
python3 "$C/scenes.py" flee --run "$F" > ".local/living/verify/$F/flee.txt" 2>&1
python3 "$V" cleanup --run "$F"
```

Start lifecycle promptly after doctor while the seeded infant is still an infant. Wildlife holds initial character graphs on wait, drives grazing, kills deer and waits for the actual 20-minute migration cooldown. It then checks one more minute without another arrival. Run independent checks on separate databases during that wait. Do not accelerate the clock, patch species data or restart the service.

## Keep the evidence

[features/README.md](features/README.md) maps the checks. [references/validation.md](references/validation.md) records the real runs and defects. Keep this map current with `maintain-verification-skill` when behavior changes.

`scenes.py` saves named snapshots, `<scene>-actions.jsonl` and `<scene>-results.json`. The recorder saves `stdb-actions.jsonl`, including the original drivers' before and after SQL. Cargo saves transcripts and `cargo-results.json`. `scenes.py` reads back the installed `brain` row after every graph replacement. The recorder captures complete `brain` rows after `set_behavior` and complete `routine` rows whenever the drivers probe an actor's routines. Compare those rows to the requested scene before interpreting results when normalization can change a graph or routine. Outputs belong under `.local/living/verify/`, never in this skill tree.

After cleanup, confirm result files still exist and SQL reports each scratch database absent. The shared harness verifies HTTP 404 after deletion. Existing drivers delete their own database too. The recorder retains cleanup ownership until the shared harness confirms HTTP 404; check their recorded CLI outcomes and actual absence. Stop only observer processes the run started. Preserve the shared container and reference worlds.

For a visible check, use shared `observer start` and T3's collaborative preview when available. Save captures under the run's evidence directory. Core assertions use tables and client transcripts; screenshots do not replace them.

For a focused grazing rerun, launch a fresh `stage1-acts` run and call the same grazing helper directly:

```bash
G=$R-grazing
mkdir -p ".local/living/verify/$G"
python3 "$V" launch --run "$G" --seed stage1-acts
python3 "$V" doctor --run "$G"
python3 "$C/scenes.py" grazing --run "$G" > ".local/living/verify/$G/grazing.txt" 2>&1
python3 "$V" cleanup --run "$G"
```

If arrival assertions fail after real migration, preserve that attempt's files first. While the same owned database is still live, this command reruns the arrival checks from its retained `wildlife-empty.json` checkpoint. It does not republish or reset the cooldown.

```bash
python3 "$C/scenes.py" arrival --run "$W" > ".local/living/verify/$W/arrival.txt" 2>&1
python3 "$V" cleanup --run "$W"
```

## What this skill does not prove

- Sustained performance acceptance, resource bounds, long-term ecology or every graph and skill combination.
- World generation and authored-world compilation. Use `verify-generation`.
- Subscriptions, visibility and permissions across identities. Use `verify-client`.
- The human player's own identity and complete command path. Use `verify-player`.
- Mind-service execution, model decisions and providers. Use `verify-minds` and `verify-llm`.
- Personal memory, recall and knowledge persistence. Use `verify-knowledge`.
- Observer rendering, interaction, frame rate and visual smoothness. Use the future UI skill (not built; see `verify`).
