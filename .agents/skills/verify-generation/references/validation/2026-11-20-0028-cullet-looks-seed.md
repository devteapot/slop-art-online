# cullet-looks-seed: Cullet's compiled seed wears its look data's generation

- **Branch** `cullet-looks-seed` (`ddd4be0bb`) from main `7fff6a61d`; server: a scratch 2.14.1 container `cls-stdb` (local). Run `generation-cls-20261120-012541` (`--feature worlds --seeds cullet`), evidence `.local/living/verify/generation-cls-20261120-012541-0-cullet/` (archived to `~/archive/worktree-evidence-20261120/cullet-looks-seed-local.tar.gz`).
- **Cause of the two red Cullet look-band checks on main:** `living/seeds/cullet.json` still carried look generation `c4-e61b01c0` after char-port-1 and coat-chains-2 rewrote `worlds/cullet/looks.json` and `look-cases.json` to `c4-cbcc40bf` without recompiling the seed.
- **Change:** `author_world.py cullet --compile-only` (no model calls). A structural diff of the seed shows only the `looks` block and each resident's `look` key changed.
- **Result:** the Cullet child passes all 350 checks, including "the cases are of the world's generation" and "each band case's resident wears its entry, in its band, with its line, at its stage (11 cases)".
- **Not covered:** the client's book (`LIVING_LOOK_BOOK` unset, as on this host); the `cullet-laws` seeds ("the seed's laws are composed over the shipped script" is red on main, owned by the Spark); other seeds.
