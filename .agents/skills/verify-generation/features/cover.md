# Authored cover syntax and genesis geometry

Use the shipped `living/seeds/cullet.json` to exercise the authored cover inputs. Optional tree trunk metadata, brush, cliffs and the reserved overlooks survive public recipe normalization. Geometry uses the generated terrain; the existing digests cover the same inputs as before.

Since `cover-genesis` (2026-11-20), the private `cover_ground` bands exist only where the world's cover law is on: kept at creation, in the staged genesis's band steps ("cover: ground bands a..b of n"), or derived after a switch-on (`cover_step`, `cover_derivation`). A seed with cover off (island, plan-test, the megacity) keeps none. That is why `floor-megacity-4k`'s hosting fits in its step (14.9 × 10⁹; main ran out of energy there). The proof that the rows are the same in every path (sha256 over the rows, main against the branch, staged against switched on) is in [cover geometry](../../../../docs/COVER_SIGHT.md#cover-geometry-only-where-cover-is-on-2026-11-20); this skill's seeds check the count only through the scene gate's fuel. `living/rules` Cargo `ground_in_bands_is_ground` checks band sampling against the whole land.

[Shared cover proof and scratch recipe](../../../../docs/COVER_SIGHT.md#client-edits-and-scratch-recipe).
