# Cover geometry in Shade

Run `check.py --run $R cover` on a fresh scoped Cullet scratch world with the generated Cullet kit linked under `living/game/assets/envs/cullet/`. The scenario places a stationary resident behind a trunk, just outside that shadow, in brush and across the authored mid-row 1.8 m hedge. It uses live wheel input at the current top-down Far, Middle and Near stops and holds the cursor at the resident's world position.

The paired captures in `ui/cover-{trunk,edge,brush,hedge}/` include the law, body coordinates and authority perception snapshots, client draw and pick dumps, the talk and strike attempts, and the Shade texture. The selected target's texel is compared with its authority membership. `ui/cover-canopy/` captures the player under an authored Hanger tree at Middle and Near under both law settings. The client log records the canopy cutaway.

The camera, camera-lod, pick, far and look-walk regression scenes use a separate island scratch world with the cover law off. [Shared cover proof and scratch recipe](../../../../docs/COVER_SIGHT.md#client-edits-and-scratch-recipe).
