# Wildlife and ecology

## Sub-features

- Deer and wolves have species-specific capabilities.
- A deer refuses a crafting graph and performs grazing.
- The real deer floor creates five adult founders after extinction.
- Newcomers land on grass near an edge and write an arrival story.
- Another minute below the floor does not bypass the cooldown.

## How to get to it (user POV)

Animals share authoritative body rules. Data comes from `living/seeds/species.json`. Once per minute, `living/authority/src/tick.rs:125` considers a floor for a species that has lived here. `living/authority/src/seed.rs:601` creates ordinary newcomers.

## Driving it with scenes.py and Cargo

Run the fresh wildlife recipe in [SKILL.md](../SKILL.md). Hold initial character graphs on wait, check that grazing lowers hunger, kill the deer and wait through their real 20-minute cooldown. Keep the empty population, newcomer rows, arrival bodies, chronicle and later founders. Cargo covers optional floors, cooldowns, fitting edge ground and scent selection. The skill also gives focused `grazing` and checkpoint `arrival` commands.

## Gotchas

- Start the wildlife recipe promptly after launch and doctor. A delayed world can consume the chosen chunk's pasture before grazing is driven. Preserve a grazing timeout and its snapshots, clean up, then retry the whole recipe on a fresh `$R-wildlife` world. Do not rename another scene's evidence into this run.
- Migration uses real minutes, not life pace. Do not rewrite species data to shorten the wait.
- Spawn terrain comes from `character.home_x` and `home_y`. The body may already have moved.
- The edge search normally uses 12 tiles, with a 40-tile fallback. The group jitters up to three tiles around its center. The valley scene allows 15.5 tiles for founders.
- The chronicle kind is `arrival`, not `migration`.
- Count parentless founders separately from later offspring. Births can increase the herd during a delayed arrival probe without violating migration's cooldown.
- The initial `wait` graphs last 120 s, so the world's wolves hunt again long before the deer arrive. Since wolves smell deer at 150 tiles (2026-11-10) they can kill a newcomer within the cooldown probe's 65 s; the check asserts no founder outside the first group and records dead newcomers and their causes (`wildlife-cooldown-newcomers.json`).
- This bounded scene does not prove ecological equilibrium. Wolf arrivals at 30 minutes, update recovery of cooldowns and seasonal pasture remain unverified.

## Since `laws-2` (2026-11-11)

Who grazes is the kind's `grazes` trait in `kinds()` (refusal "only grazing animals graze", was "only deer graze"); `a.actor.pasture` is worked out for any skill whose rules read it, and the grass is eaten by the `graze` effect `graze_done` returns (it was a special case for the skill named `graze` in `act.rs`). Per-kind numbers (`max_hp`, `lunge`, carcasses, dodges, a bare attack's `blow`) are traits of `kinds()`, read by the same functions; the values are unchanged (`rules_read_traits_not_lists`).

## Remains

Since 2026-11-11 every death leaves a `remains` structure at the body (`act::die`): what the dead carried, the `carcass(kind)` law's items (a map, `Scripts::items_of`, from the kind's `carcass` trait in `kinds()`; deer 5 meat and a hide, a wolf 2 meat and a hide) and its artifacts. A kill puts nothing in the killer's pack; the killer, its pack or anyone beside the remains `take`s from them (wolves have `take` among their skills; the wolf instincts, the wolves' `hunt` routine and both hunter routines take meat from remains in sight first). A private `rot` row (`structure`, `due_ms` with a btree index) is written with the remains, due after the `remains_h(kind)` law (the kind's `remains_h` trait in game hours, turned into real time for the world's day: 60 for animals, 120 for people, 1,800 and 3,600 real seconds on the 12-minute day; `remains_s` before rates-2); housekeeping (`tick::expire_remains`, span `housekeeping.remains`) reads only the due rows and deletes the remains with their inventory, unless they hold an artifact, which keeps them as before. `wander` keeps within `wander_turn` radians of the body's heading while it moves or after it has stood less than `wander_keep_s` seconds (fields of the per-creature `motion(a)` law, read through `common::moves_of`; 1.2 rad and 60 s). `remains_law()` describes the remains for minds and covers `carcass` and `remains_h`; `carcass` is among the laws the engine must see described (`check::ENGINE_LAWS`).

`scenes.py remains` on a fresh `stage1-acts` world installs the shipped script with `remains_h` 3 game hours for every kind (90 s on its 12-minute day), holds everyone on `wait`, then checks: an admin `kill` of a deer leaves remains with exactly the shipped `carcass("deer")` items and a `rot` row due `remains_h` times the world's game hour after `built_ms`; a wolf's real kill leaves the same and leaves the killer's pack unchanged; the killer and a second wolf each take a meat from that kill (the remains hold two fewer); a wolf on `wander`/`wait 3` turns by at most 1.6 rad between legs at least 80% of the time (uniform headings would about half the time); after its due time plus a housekeeping minute the first remains, their inventory and their `rot` row are gone. It reinstalls the shipped script at the end. It does not cover a person's remains expiring (3600 s) or remains kept by an artifact.

## The wolves' spacing reflex (`pack_reflex`, since `pack-reflex-on`, 2026-11-12)

A world law, on by default (`pack_reflex: true` in `skills.rhai`'s `laws()`). While it is on, every hunt in a wolf's starting graph sits beside a weighted desire, "keep apart from mates" (`living_rules::graph::with_pack_reflex`). A hunt is an attack on the nearest person or deer, guarded or bare, in the instinct form or the repertoire's shorthand. The desire weighs 1.2 against the hunt's 1. It acts while another wolf is within 3 m and the prey within 6 m: `keep_distance` 3–5 m from the nearest prey, at a run, with `apart` 4.

Three install paths read the law:
- `seed::as_installed` for a seed pack's named instinct (`wolf_bold`);
- the same for a spawned or born wolf's species instinct (`wolf`) once past infancy;
- `seed::give_ways` for a grown animal's species ways (repertoire.json): the wolf's `hunt` routine.

A newborn's `wolf_young` is never given it (`graph::reflex_applies`). It is read only at those installs, so a world turns it off before its wolves are placed: a seed's `"rules": {"pack_reflex": false}`. Graphs already given are kept. It is an ordinary part of the graph, which a wolf's mind may change.

`scenes.py pack_reflex` reads the world's law value and checks every wolf by path: the bold pack's brain, a grown founder's `hunt` routine, a young founder's brain, a newborn's brain. Run it on `--seed pack-reflex-on`: law on, each path carries 2 reflexes, the people hunt and the deer hunt. Run it on `--seed pack-reflex-off` (`rules` off): none carries any. Both seeds are the wildlife lab with a bold pack of 3. Cargo: `graph::pack_reflex_tests`, `script::tests::the_pack_reflex_is_on_by_default_and_a_world_turns_it_off`. Evidence: `pack_reflex-wolves.json`.

Gotcha: grown founding animals live by their species' ways (`give_ways`, plan "the ways of a wolf"), not by `instincts.json`. A check that reads only the brain misses them: the hunt is in the `hunt` routine.
