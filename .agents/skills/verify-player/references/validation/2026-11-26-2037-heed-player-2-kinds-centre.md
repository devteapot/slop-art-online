# Heed for players: counts by kind and the centre (branch `heed-player-2`)

Follows 2026-11-26-1942-heed-player-2.md. Branch `heed-player-2` with `origin/heed-client` (`d1f7d279a`, the laptop's client) merged; module at `b666b4780`, bindings and the game's test rows at `08e860530`. Private `hp-stdb` (SpacetimeDB 2.14.1). Shape change on this surface: `seen_throng` gains `people`, `wolves`, `deer`, `others` and `centre_x`, `centre_y` (appended with defaults). Map: features/heed.md, the README row.

Run `player-heed5-211824` (island, fresh): `heed.py` **26/26**. New check: each cell's counts by kind (all people here: a cell of 4 reads `[4, 0, 0, 0]`) and its members' centre to the metre (`[3, 2]` and `[0, 2]`) equal the owner's reading of the members' bodies. Every check of 1942's record passes again.

**Not covered:** a mixed cell (people with animals) live, which `throng.rs`'s unit test `kinds_counted_and_the_centre_to_the_metre` covers; a merged square's centre; the write rate in a moving crowd. Evidence: `.local/living/verify/player-heed5-211824/heed-proof.jsonl`.
