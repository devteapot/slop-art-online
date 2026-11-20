# Seen ranges merged onto main, 2026-11-19

`battle-seen-ranges` (authority 71e925ea, built on 1cd32ab2) merged with main at `974ef3d8`, which brings cover sight, gaze, tick-rate, bystanders-2, verify-guard, guard-audit, sight-on and reply-timing. The runs used the merged tree at `1b49fefd`, plus the scene and doc edits committed with this record. They ran on a private SpacetimeDB 2.14.1 container (`slop-seenrebase-stdb`, port 3395). Each launch passed doctor with a ticking world and used `--driver-pid` guards. Each world was paused before deletion.

- **Default seed, `core-seenrb-155637`.** `seen_remains` passed 15/15, `notice_delta` 8/8, `notice_inplace` 6/6, `familiar_dense` 4/4 and `first_sight` 22/22. An earlier run on the first merge (`core-seenrb-153724`, main at `c39a33ee`) gave the same counts.
- **Cullet, `core-seencul-155657`.** The new `seen_remains_gaze` scene passed 7/7, with cover, facing sight and gaze on as Cullet ships them. A Near observer got one counted line for the 6 strangers' bodies within 28.8 m. Middle then gave one line for only the 5 bodies it brought within 48 m. Near, Middle and Far again told nothing more, and the observer's ranges held all 11 body ids. The first attempt failed in setup: a ring placement fell inside a house (`no free walkable tile`). The scene now picks walkable tiles from the map.
- **Offline.** `just living-check` passed on both merges. The authority's library tests passed 41/41, including `seen_structures::tests`. `living/tools/generate_in_container.sh slop-trials-stdb` regenerated the bindings with no diff.

Composition with cover and gaze is set out in [Seen remains](../../../../../docs/SEEN_REMAINS.md#composition-with-cover-sight-and-gaze). On main, cover is traced for people only, so a body behind cover is still noticed and recorded. That is main's rule for every structure; this branch does not change it.

Not covered: night or torch radii in the gaze scene (it waits for daylight), animal remains under gaze, a body holding a tablet under gaze, and any battle-scale replay on the merged tree.
