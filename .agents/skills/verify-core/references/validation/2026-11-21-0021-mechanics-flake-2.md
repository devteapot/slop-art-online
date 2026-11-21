# Mechanics driver: walkers kept together, waits for their own result (mechanics-flake-2)

- **Branch and module.** Branch `mechanics-flake-2` from main `7499c2707`. Test-only: `living/tools/verify_mechanics.py`, and [features/mechanics.md](../../features/mechanics.md), "Walkers that walk apart, and a fish spoiled in the grant".
- **Server and module.** `mf-stdb` (v2.14.1, a scratch container in its own scope, 127.0.0.1:3346), main's module built once by `verify.py launch --target-dir`.
- **Runs.** Each world was launched by `verify.py launch --run gate-mf2-<round>-<k>-mechanics`, driven by `verify_mechanics.py --gate-world` as the gate drives it, and cleaned up. 64 worlds ran, 4 at a time, while the coordinator's gate ran beside them (load 3–21). Evidence: `.local/living/verify/gate-mf2-*-mechanics/` (`mechanics.txt`, `mechanics.json`, `launch.log`) and the round logs in `.local/mf/`, on the dev-box.

**The causes, from the evidence:**
- **Tending wounds** (`d3-3`, `d3-4`). A and B were 13.96 and 16.70 m apart when A was told to attack, so B was out of A's sight. No blow and no care was ever started (no feedback, no activity). The planting check (any new node) and the conception check (any `expecting` row) had let the scene go on while A still walked to its bush.
- **The tablet chain** (`p6-4`). B was 26 m from A at the give: "Walker1 wrote a tablet (×6)". B was placed before the setup calls and set idle only after them.
- **Act: conception chosen by both** (`f3-4`). The same order, for C and D.
- **`reset_pack`** (`p7-1`). A fish spoiled between the grant and the read-back, and the driver stopped.

**The fixed driver** (sha256 `f8f57498…`) passed 12 of 12 worlds at 23/23 (rounds `g1`–`g3`). Tending passed in every world from `p1` on: 52 of 52.

| Round | 23/23 | Failing keys |
|---|---|---|
| d1 | 2/4 | wolf; the tablet chain (16/23) |
| d2 | 3/4 | wolf |
| d3 | 2/4 | tending ×2 |
| p1, p2, p5 | 4/4 each | |
| p3 | 3/4 | road, wall and gate built (21/22) |
| p4 | 2/4 | wolf; planting |
| p6 | 3/4 | the tablet chain (18/23) |
| p7 | 3/4 | driver stopped in `reset_pack` (0/0) |
| f1, f2 | 4/4 each | |
| f3 | 3/4 | act: conception chosen by both |
| g1, g2, g3 | 4/4 each | |

**Not covered, or open:**
- **The wolf check: 3 of 64.** In `p4-3` the wolf saw I and J 2 to 3 tiles away after it was placed, and was 14.3 m off at the end of its 20 s, without a balk. It is not fixed here; the driver now prints its distances, activity and feedback.
- **Planting: 1, a real miss.** Walker1 never planted in 90 s; the old check had hidden it.
- **Road, wall and gate: 1.** Both now print diagnostics on a failure.
- **The threat check** was left alone: the authority's stuck-activity fix is the Spark's.
- **No authority code changed.**
