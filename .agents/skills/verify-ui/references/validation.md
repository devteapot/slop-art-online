# verify-ui: last real run

**2026-11-11, branch `ui-1` (interface D steps 1–3) on base `90f6fac1`, laptop.**

- **World:** `verify-ui-b`, from `$V launch --run ui-b --seed island --target-dir …` (scoped perception; Brackenford's residents; no mind service, no model calls). `$V doctor --run ui-b`: all ok (v2.14.1, ticking, module newer than the sources).
- **Client:** `living-game` release from the `ui-1` working tree, private `CARGO_TARGET_DIR`, built through `build-slot`.
- **Scenarios:** `check.py --run ui-b` (windows, talk, items): **37 passed, 0 failed** (`.local/living/verify/ui-b/ui/checks.json`).
  - windows 14/14: arrival empty; Menu; Settings centre; pack right and log left inside 1600×900 and apart; the log dragged right snaps there and the pack takes the left; ✕; I replaces the log on the right; Esc closes the top window, then opens Menu (log line), closes it, opens it again.
  - talk 14/14: Enter with nobody under the cursor goes to the room (`to = 0`; owner SQL `said` row with object 0); after 11 s the note "Heard by N — no one took it up…"; `point:2` then Enter goes to #2 in their window ("To a stranger in green and dark grey", no name); `say: … to #2` and the `said` row with object 2; Tab reaches another person in earshot (window follows) and the room; Esc; Log › People › a window; Introduce yourself ("I'm Verifier." to them).
  - items 9/9: hold-F list › Their window; the pack beside it; berries' acts; berries slid onto the window sent `give berries`; hold F › Give › Berries sent a second; the authority moved 2 berries (owner SQL `inventory`). Admin scene calls: `place_at`, `set_behavior` (two residents held still), `grant_items` (4 berries).
- **Evidence:** `.local/living/verify/ui-b/ui/{windows,talk,items}/` (photographs, dumps, client.log, plan.txt, scene.json); a contact sheet beside the design's pictures in `.local/living/ui-1/sheet/index.html`.
- **Cleanup:** `$V cleanup --run ui-b` once the frame-time runs on the same world are done; the evidence stays.

**Found while making the skill** (fixed before this run): residents placed on the stall side of the arrival point are not perceived (sight is a rule), so scenes place them on the open side; the dump spelt windows `Person(3)` while tags said `Person3`; a one-shot `point:` lost the person as the camera eased (it now follows them); the items scene needs its own berries.

**Not covered:** a real window, trackpad or system cursor (capture, Esc giving the cursor back); residents' answers (no minds); frame time.
