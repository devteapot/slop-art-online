# verify-ui: outline-attr-1

**2026-11-18, branch `outline-attr-1`.** Baseline `29735dbe9` and the same tree with the attribute registration. Headless release clients on laptop Metal, built through `build-slot` with one slot and a private `.local/target`. Both used the installed char-4 composed bundle through local asset links. The look book and world both named `c4-e61b01c0`, the bundle had 118 KTX2 images, and the client reported BC support. No mind service ran.

Ran `check.py --run ui-outline-attr-1 looks` twice on the same Cullet scratch world on SpacetimeDB 2.14.1. The harness doctor passed. Both versions passed **14/14** checks, including the composed resident and player, fallback for the removed look, and the island decor tour. The scenario placed two residents nearby through its standard admin scene setup. The harness deleted the database after the second pass and verified HTTP 404.

| Launch | Before | After |
| --- | ---: | ---: |
| Cullet, one look removed from the test book | 163 | 0 |
| Cullet, mismatched look-book generation | 178 | 0 |
| Look-dev island decor tour | 438 | 0 |

Counts are for `Unknown vertex attribute _OUTLINE_WIDTH` in each launch's `client.log`. All 538 width accessors in the installed type/style GLBs are Float32 scalars. Bevy's loader looks up custom names without the leading underscore, so the registration key is `OUTLINE_WIDTH`. [bevy_gltf 0.20.1 vertex attribute conversion](https://docs.rs/crate/bevy_gltf/0.20.1/source/src/vertex_attributes.rs).

The field is an authored multiplier. The pinned outline renderer uses an authored vertex direction and a mesh-wide `OutlineVolume.width` in logical pixels. The registration preserves the multiplier on the mesh and leaves the width calculation as it was. The live and decor-tour stills show no visible outline-width difference. These are visual spot checks of the headless scenes. [bevy_mod_outline 0.14.0 pipeline](https://docs.rs/crate/bevy_mod_outline/0.14.0/source/src/pipeline.rs), [outline shader](https://docs.rs/crate/bevy_mod_outline/0.14.0/source/src/outline.wesl).

`just living-check` passed under `build-slot`, including the release client tests with **128 passed, 0 failed, 1 ignored**.

Evidence is under `.local/living/verify/ui-outline-attr-1/`. The baseline logs, dumps and stills are in `before/` and the updated ones are in `ui/`. The paired stills are `comparison.png` and `decor-comparison.png`, baseline on the left. `actions.log` records publication and cleanup. Build and client test output is in `.local/outline-check.log`.
