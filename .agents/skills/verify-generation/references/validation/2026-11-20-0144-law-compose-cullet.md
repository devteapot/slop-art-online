# law-compose over main with cullet-looks-seed

Follows [2026-11-20-0141-law-compose.md](2026-11-20-0141-law-compose.md). Main moved to `16f50c0c` (cullet-looks-seed: Cullet's compiled seed wears its look data's generation `c4-cbcc40bf`), which merges cleanly with `law-compose` (`23a061a4`). Run on a temporary merge of the two (worktree `~/slop-lawcompose-bisect/merged`, not pushed), on the private server `slop-lawcompose-20261120`.

`generation-lcx-024227` (`--feature worlds --seeds cullet,cullet-laws`): cullet 351 of 351 (the two look-case checks that failed on `aba169b0` pass), cullet-laws 48 of 48 (`the seed's laws are composed over the shipped script` and `the installed script carries the seed's rules as its law values` among them). Both cleanups passed; original seeds unchanged. Evidence is archived in `~/slop-evidence/law-compose-20261120.tar.zst`.
