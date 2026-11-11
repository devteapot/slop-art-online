# What you stand on

The camera's fade (`living/game/src/envs.rs` `cutaway`) turns what stands between the camera and you see-through. What holds you up or what you are stepping onto never fades (`envs::supports`: probes at, under and half a metre round your feet inside a thing's box), whatever the eye does; landmarks (`envs::Landmark`) and anything more than 30 m from the eye are not faded for being in the way either. The owner's Cullet walk (2026-11-11) found a flight of stairs dithering away while it was climbed: the line from the eye to the feet ended inside the flight's box.

## Sub-features

- `stairs`: a flight (a kit fixture, an occluder at 3 m or more) under your feet stays solid, and it is the only flight there: the plan's stairs take no other kit flight at random (`island::prop_file`; before `stairs-place` a Store Wynd flight stood on the Ladder Wynd's foot).
- `terrace`, `quay`: a terrace or the quay's edge under you stays solid (both are under 3 m, so the fade never considers them; the check proves nothing fades).
- `wall`: at a retaining wall's top edge the drop's tiles keep you 1–1.5 m from it, so it is beside you, not under you; it still fades when it stands between the camera and you, as anything that hides you does.

## How to get to it (user POV)

Walk up or down a flight, onto a terrace, along the quay's edge, with the camera behind.

## Driving it with drive.py

Preconditions: a Cullet world (`$V launch --run ui-<…> --seed cullet`), not the island's. The client's `RUST_LOG` must include `living_game::envs=debug`; `check.py` sets it.

- The player is moved by an admin `place_at` at each `sync:` step (scene setup), first to the arrival point (`sync:away`: the character keeps its place between drives, and the log names a support only as you come onto it), then to each spot, and the camera settles behind for 6 s: `ready;sync:away;wait:3;sync:stairs;wait:6;shot:stairs;dump:stairs;…`.
- The client log says `cutaway: <file> holds me up; not faded` once each time you come onto something, and `cutaway: <file> fades to 0.8 (it is in the way …)` or `(the eye is inside it …)` when something fades.
- The check splits the log at each `live script: sync:<spot>` line: at the stairs it wants the flight held and no other `stairs/` file held; at every spot no file it held fades, nor what you walk on there (the flight, the terrace, the quay). The wall beside you at the wall spot may fade when it is in the way.
- A pre-fix client for comparison: `drive.py --client <binary> --name support-before …`.
- Scenario: `check.py --run $R support` (not part of the default set, which needs the island).

## Gotchas

- `place_at` snaps to the nearest walkable tile centre: spots are written as land metres and land on x.5.
- Ordinary things in the way still fade (net lofts in front of the camera at the wall spot; a wall on the next level): that is the rule working, not a failure.
- The Cullet kit must be in the checkout's assets: `living/game/assets/envs/cullet` (git-ignored; link it from the main checkout). Without it the flights and buildings are drawn as plain boxes, no kit file is named, and the stairs check fails for that reason alone.
- The cutaway names what holds you up among things it never fades too (a structure a settlement's kit models, drawn by `world.rs` with no `Occluder`; low fixtures: "… holds me up; not an occluder"), only while `living_game::envs=debug` is on.
- The first drive after linking a kit may stall while its models load and compile; a second run goes through.
