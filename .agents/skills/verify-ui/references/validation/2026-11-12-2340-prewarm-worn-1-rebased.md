# verify-ui: prewarm-worn-1 rebased onto main db4c1e35

**2026-11-12. Follows `2026-11-12-2315-prewarm-worn-1.md`, which was measured on main `6c198bd5`.** `prewarm-worn-1` was rebased onto main `db4c1e35`, which brings look-1-island (the island seed now carries looks) and meters-always. The only conflict was the end of LOOK.md §8 against main's new §9; both were kept. Client tests: 122 passed, 1 ignored. Worlds were launched fresh from the rebased module.

- **Cullet `verify-ui-pw1r-cullet`: `looks` 14/14.**
- **Island `verify-ui-pw1r-island`:** the cover prewarms 10 composed and 0 on VRoid bases ("none, every person in sight is composed"). `looks-old` fails 0/2: "the world has no looks" (`look_book 'c4-aa393793'`), then 11 people drawn composed.
  - This is not this branch: since look-1-island a fresh island has looks, and `looks-old`'s premise ("the island seed: no `looks`") is out of date on main. features/looks.md says the same.
  - The fix belongs to the verify-ui skill: `looks-old` needs a world made without looks, such as the one below.
- **A world without looks `verify-ui-pw1r-old`**, from the island seed with its `looks` removed (`.local/prewarm-worn-1/island-nolooks.json`): the cover prewarms 6 on VRoid bases ("a world without looks"), and **`looks-old` passes 2/2**. The VRoid fallback still prewarms its bases on main.

Not run again after the rebase: the cost runs (the prewarm code is unchanged), `names`, `windows` and `looks-band` (33/33 and 6/6 on `6c198bd5`).
