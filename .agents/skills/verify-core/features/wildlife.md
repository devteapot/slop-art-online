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

## Remains

Since 2026-11-11 every death leaves a `remains` structure at the body (`act::die`): what the dead carried, the `carcass(kind)` law's items (a map, `Scripts::items_of`; deer 5 meat and a hide, a wolf 2 meat and a hide) and its artifacts. A kill puts nothing in the killer's pack; the killer, its pack or anyone beside the remains `take`s from them (wolves have `take` among their skills; the wolf instincts, the wolves' `hunt` routine and both hunter routines take meat from remains in sight first). A private `rot` row (`structure`, `due_ms` with a btree index) is written with the remains, due after the `remains_s(kind)` law (1800 s for animals, 3600 s for people); housekeeping (`tick::expire_remains`, span `housekeeping.remains`) reads only the due rows and deletes the remains with their inventory, unless they hold an artifact, which keeps them as before. `wander` keeps within `wander_turn` radians of the body's heading while it moves or after it has stood less than `wander_keep_s` seconds (laws; 1.2 rad and 60 s).

`scenes.py remains` on a fresh `stage1-acts` world installs the shipped script with `remains_s` 90 s for every kind, holds everyone on `wait`, then checks: an admin `kill` of a deer leaves remains with exactly the shipped `carcass("deer")` items and a `rot` row due `remains_s` after `built_ms`; a wolf's real kill leaves the same and leaves the killer's pack unchanged; the killer and a second wolf each take a meat from that kill (the remains hold two fewer); a wolf on `wander`/`wait 3` turns by at most 1.6 rad between legs at least 80% of the time (uniform headings would about half the time); after its due time plus a housekeeping minute the first remains, their inventory and their `rot` row are gone. It reinstalls the shipped script at the end. It does not cover a person's remains expiring (3600 s) or remains kept by an artifact.

