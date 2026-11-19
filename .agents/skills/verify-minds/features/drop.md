# A mind is told of drops and low things, and sees across them

Since 2026-11-11 (drop-1 and eye-2; docs/PERCEPTION.md "Drops: sight across ground levels"). A drop between ground levels (`Terrain::Drop`, 8) and something low or open in the way (`Terrain::Low`, 9: a cart, an open stall, a well under its roof, a building's overhang) block the foot and not the eye. The scene a mind is sent says so in words.

## Sub-features

- The scene's `terrain_near` (the authority's `perceive::scene_json`) lists the nearest drop and the nearest low thing within sight range (by distance; the line to it is not tested), as it lists water, forest, rock, roads and walls. A class whose name does not say what it does (`living_rules::map::Terrain::words`) is told in words, followed by how it meets the foot and the eye (`Terrain::passage`, from the class's own `walkable` and `opaque`):
  - `"drop": "west 1, a drop to ground at another level (stairs, ramps and roads join the levels): you can see past it but not walk through it"`;
  - `"low": "south 1, something low or open in the way, such as a cart, a low wall or an open stall: you can see past it but not walk through it"`.
  Before eye-2 the drop was `"drop": "west 1"` and a low thing was not listed. The authority keeps no heights, so the scene cannot say which way the ground drops.
- A creature on the other side of the drop, or of the low tiles, is in the scene's `creatures` (the sight line passes over them).

## Driving it

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case drop
```

On an island world (built in `.local/living/target-resident-island`, shared with `resident`). The driver reads `terrain_chunk` for two walkable tiles 2–5 apart on one axis with only drop tiles between, and two with only low tiles between (`across_spots`). It freezes three of the admin's residents (`set_behavior` wait) and places the eye and the one across with admin `place_at`. Then it asks the eye's mind to think with a `think` marker, for the drop and then for the low tiles. The checks read the scene from the prompt the fake model was sent (`sent-prompt-drop.txt`, `sent-prompt-low.txt`; `scene-*.json`, `spots.json`).

## Gotchas

- The scene is parsed from the prompt (the JSON line under "# What you perceive right now", or an animal's "# Around you now"), not from the `deliberation` row: the running mind can answer and delete the row before a poll sees it.
- The nearest drop may lie in another direction than the one across: `terrain_near` names the nearest tile of each class.
- A map with no walkable ground on both sides of a drop or a low run fails with "no walkable ground on both sides", a fixture failure.
