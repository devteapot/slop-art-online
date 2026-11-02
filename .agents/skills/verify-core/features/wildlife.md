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
- This bounded scene does not prove ecological equilibrium. Wolf arrivals at 30 minutes, update recovery of cooldowns and seasonal pasture remain unverified.
