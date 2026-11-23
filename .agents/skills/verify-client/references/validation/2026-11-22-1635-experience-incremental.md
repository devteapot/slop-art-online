# A player's lines as rows (`experience-incremental`)

Validated on the dev-box on branch `experience-incremental` from `origin/main` `9ed12f51d`; module and client from the branch's commit (amended in place: the authority last changed at `48e401906`, the verify scripts after). Server: a private `clockworklabs/spacetime:v2.14.1` container `so-stdb` on `127.0.0.1:3378` with its own volume and `/wasm` mount; `performance` governor. No paid model calls. Scoped `maintain-verification-skill` pass: the change adds a public table (`experience_copy`, row-level security `viewer = :sender`), a private one (`lines_state`), two value-only laws (`lines_table_on`, shipped on; `lines_table_check`, a diagnostic) and the game client's switch (`Feed::lines_table`, `net::my_lines`). Outcome: **changed**.

## What changed in the skill

- `scripts/lines_table.py` (new; run by `run.py` after `combat_feed.py`): 18 checks, isolation and the same rows as `my_experience` through a death, a rejoin, a takeover and return, and the law off and on.
- `scripts/drive.py`: `lines_state` in `PRIVATE`; `experience_copy` in `RLS_TABLES`, in the names an owner program may not use, and `lines_table.py` among the scripts that subscribe to everything on purpose. The first run stopped on `private table inventory changed; update PRIVATE: {'lines_state'}`: the inventory check works.
- `scripts/probe/src/main.rs`: `experience_copy` among the tables streamed.
- Map and features: a row for lines as rows ([features/README.md](../../features/README.md)); [features/perception.md](../../features/perception.md) "Lines as rows"; [features/game-client.md](../../features/game-client.md) (`my_experience` left the base set for the perception set: 33 base queries, 23 of `PERCEIVED`); [features/triage.md](../../features/triage.md); SKILL.md's paragraph.
- Outside the skill, in the same branch: `living/tools/scene_gate.py` case `lines_table` (group `client`; `scene_gate_selftest.py` passes) and docs/TICK_RATE.md's pin list.

## Runs

- `client-ei4-11221720` (`run.py`, scoped build, default seed): drive 45 PASS, cues 23, near tier 7, motion tables 34, combat feed 17, no FAIL; `lines_table.py` 16 of 18: two checks of the script itself were wrong (A had just joined again and held no line; the `takeover_s` change reinstalls the script, so the revisions are taken around the lines law's switches alone). Fixed.
- `client-ei5-11221728` (launch, doctor, probe, `lines_table.py`): **18 PASS, no FAIL**; at each moment a fresh read of A's copies equals its view (dead: 5 = 5; joined again: 0 = 0; handed back: 3 = 3; law on again: 3 = 3); law off: no copy and no record left, the view showing 3.
- Known answer, `client-eika-11221732`: the module built without `experience_copy`'s rule (working tree only, restored after the build): `lines_table.py` **8 of 18 fail**: the five isolation checks and the three same-rows checks (others' copies arrive).

Evidence: `.local/living/verify/client-ei4-11221720/`, `client-ei5-11221728/`, `client-eika-11221732/` (`lines_table.json`, `lines-table-*.jsonl`).

## Not covered

The open-perception build; `experience_copy` at battle density (`battle_viewers.py --privacy` checks only the battle-views copies).
