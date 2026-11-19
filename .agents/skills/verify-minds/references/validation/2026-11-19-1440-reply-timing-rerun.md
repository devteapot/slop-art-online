# reply-timing: rerun on the final mind binary

Follows [2026-11-19-1316-reply-timing.md](2026-11-19-1316-reply-timing.md). Branch `reply-timing` at 0669e2e6, on `slop-trials-stdb` (3320) under the battle lock, with the fake model only: `verify_minds.py --run minds-rt2-1533 --case conversation --case reasons --case reply-timing --no-unit-tests`, 15:36–15:40 CET.

- **conversation:** pass.
- **reasons:** pass. Both now ran on the binary with the follow-up wake fix; in the first record they had run before it.
- **reply-timing:** 11/11. F greeted H at 4.19 m. H's reply was said 217 ms later by the authority's clock, while H walked away. The frame said "A stranger is 5 m west of you." K's missed reply got its one follow-up turn, and the exchange ended after the second silence.

Evidence: `.local/living/verify/minds-rt2-1533-*`, archived in `~/slop-evidence/reply-timing-2026-11-19.tar.zst`.
