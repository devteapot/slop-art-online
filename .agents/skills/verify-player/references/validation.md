# Validation record (player)

## 2026-11-12 fix-dodge-told (Spark)

Branch `fix-dodge-told` (merged with origin/main `c67bb6e1`), the trial service `slop-trials-stdb`. Island seed, `player-dodge3-074940`: `combat.py` all scenes 45/45. New scene `early_dodge`: the player's dodge toward a wall at the windup was over before the blow ("hit for 9" before the merge). The player was told "You failed to dodge: it was over before the blow came", as a mind is, with its `my_act_outcomes` row (own, dodge, not ok, code failed), and `my_skill_uses` "made way: it was over before the blow came". Run before `breath`, the scene left the player hurt and short of breath, and `breath`'s recovery check failed once (`player-dodge-071153`), so it runs after `heal`. Admin reducers: `place_at`, `set_behavior`, `grant_items`, `kill`, `join`.

## 2026-11-12 fix-unseen-killer-id (Spark)

Branch `fix-unseen-killer-id` from `7729fc9b`, the trial service `slop-trials-stdb`, island seed, `player-unseen2-061653`: `combat.py` all scenes 44/44; scene `shot` gains three: `my_vitals.hurt_by` 2 after the seen archer's hit and 0 after the same archer's hit from 19 m; shot dead from 19 m, the death row's `other` 0, the feed's death `target` 0, "You were killed by an arrow from someone unseen.", the chronicle's `killing` a = 2; after a rejoin shot dead from 6 m, `other` 2 and `target` 2. (Before the move to main, `player-unseen-061037` on `caa295d1`: the same.) Admin reducers: `place_at`, `grant_items`, `set_behavior`, `kill`, `join`.

## 2026-11-12 move-intents (Spark)

`intents.py` (new; `player-intents-060823`, the trial service, default seed): 8 of 8. The player's keys walk at 2.43 m/s and run at 4.01 (breath −4/s); the same body's `back_off` through `human_act` walks at 2.43 and its `close_in` with `run: true` runs at 4.01, draining breath; a resident's graph `back_off`/`close_in` run 4.54/2.75 = 1.65 of its own walk, the player's keys 4.01/2.43 = 1.65. Two earlier attempts failed on the scene: a `close_in` from 9 m at night refused ("no #152 in sight"), and samples arriving after a short run under machine load. It now starts within 5 m and reads the row's cruising `speed`.

## 2026-11-12 fix-missile-told (Spark)

Branch `fix-missile-told` from `ee8790f4`, the trial service `slop-trials-stdb`, island seed, `player-missile-052234`. `combat.py` all scenes: every check passes, the new scene `shot` 2/2: shot from 6 m, "A stranger shot you with an arrow: hit for 6" and the feed's hit names the shooter; from 19.1 m, "An arrow struck you from somewhere you could not see: hit for 6" and the feed's impact and hit carry actor 0. Admin reducers: `place_at`, `grant_items`, `set_behavior`, `kill`, `join`.

## 2026-11-12 speech-truth (Spark)

`speak.py` (`player-struth-speak`, trial service): 16 of 16. New: a `human_say` to the resident 30 m away is said. The player's `my_experience` then holds one `silence` row ending "they could not have heard you." (not "No answer"), and `my_act_outcomes` holds its row: kind `act`, code `reach`, not ok, `why` the same words, `other` the resident.

- Rerun after the coordinator's changes, `player-struth2-speak`: 18 of 18. The addressed line out of earshot reads the fact alone. New:
  - a room line from a spot with no one within the 9 m voice gives one `silence` row (subject 0) "Nobody was near enough to hear you." and its `my_act_outcomes` row (act, reach, not ok, other 0);
  - with the resident placed beside the player, a room line gives no row, and `my_heard` lists the resident.

## 2026-11-12 stamina-1: breath through the player's reducers (Spark)

Branch `stamina-1` with look-2 merged, trial service `slop-trials-stdb`. `player-st1b` (island):

- **`combat.py --scene all --fresh`: 34 of 35.** Every breath check passed:
  - a run at `run_share` draining 4 a second from the row's anchor;
  - letting go refilling from a second later at 25;
  - standing, no row written;
  - a dodge 20 and a jump 10;
  - dodging on without a pause refused "out of breath" and told in `my_combat`.

  The kill scene failed: at the new blows (5) a kill takes about 20 strikes, paused by breath. It counted the pauses as misses and stopped at 45 s. With the fix (pauses waited out, 120 s), `--scene kill` passed 2 of 2.
- **`player-st1a` (before the fixes): 24 of 35.** The strike scenes were refused "out of reach" (main's `fix-place-free` placement), and the breath scene dodged where there was no room. Both were fixed or noted.


## 2026-11-11 force_outcomes: a player is told its own strike and shot as a mind is (mind-act-outcome-far, Spark)

Branch `mind-act-outcome-far` at 3328c7bb, the trial service (port 3320), island seed. `player-far2-233156`: `combat.py --fresh`, 31 of 31, with the new checks: the strike's line "You finished: strike → person. hit for 9" and its `my_act_outcomes` row (`own`, `strike`, ok, `done`), the arrow's "You finished: bowshot → a stranger. struck a stranger: hit for 12" and its row (`own`, `bowshot`, `done`, `other` the one struck); every such line in `experience` and row in `act_outcome` the player's character's only. `player-far2-233156-outcomes`: `outcomes.py` 14 of 14 (the 64-row bound, scoping), `told.py` 12 of 12.

## 2026-11-11 speech with the `speech_audience` law off (exp-greet, Spark)

Branch `exp-greet`, the trial service `slop-trials-stdb` (port 3320). `player-1111-152137`, the speech part of `player-character.md`, passed. An addressed and an unaddressed `human_say` gave the same chronicle lines and listener experiences as before ("A stranger said to you: …", salience 0.9; the unaddressed line was also 0.9, because the listener was the only one close by). No `audience` row was written. `set_paused` and `install_script` were refused to the player ("admin only"), and the player's SQL on `audience` was refused (a private table). The other recipes were not rerun.

## 2026-11-11 look-2: a held look turns the facing, not the travel (dev-box)

Branch `look-2` (from main `017286a1`, `origin/main` `1b1414a3` merged as `d609819d`) on the dev-box, own container `look2-stdb` (2.14.1, port 3330, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped` unless named, no model calls. Evidence under the worktree's `.local/living/verify/`.

- `face.py` rewritten for the decoupled look: travel from successive position anchors, the facing's turn checked against the turn rate and sampled only after it settles (tolerances 0.5° travel and facing, 1% speed), open ground off the road. The pre-`look-2` walking check was flaky on the laptop (−1.02 and −0.02 rad against −0.52): both are steering's slide plan (±0.5 rad) round something ahead of a walker placed in town, not the clamp or the turn rate.
- Merged build, final script: `player-look2-n` `face.py` 28 of 28 three times in a row (`face-run1..3.json`), the same numbers each run: travel 0.000°, speed 1.0000× cruise, sideways 0.0000; `face_turn` ∓6 rad/s for 0.1309 s (45°) and 0.2182 s (75°); settled facing −45, −75, −75, +75° for looks 45, 90, 135, 180° north (the 180° look from a facing on the travel takes the +π side), −75° for 180° after a look north (no turn: the north shoulder kept), back to 0° on release at +6 rad/s; three of eight looks taken in the narrowed bucket each run.
- Merged build, the script before the source-wave fixes: `player-look2-m` `face.py` 27 of 27 three times; `fov.py` 18 of 18.
- Before the merge: `player-look2-b` `face.py` 27 of 27 three times, the same numbers. Earlier attempts on `player-look2-a`: 13 of 21 (the walk ran into an obstacle and slid: heading −1.0 rad), 21 of 22 (a road sped the walk; the 180° look crossed the front before `BEHIND_BAND`), 21 of 22 (`place_at` put a wall between player and resident), 21 of 22 (Q out of range by the time the look was sent): each fixed in the script or, for the 180° crossing, in `steer::walk_face`.
- `maintain-verification-skill` on the look feature (source wave, one reader): fixed the 180° side, the clamped `input_hz` (0.2 is taken as 1; the script now sets 1 and waits 4 s), the slack rule's conditions, and listed what is not driven live.
- After merging origin/main again (`dfc8bcec`, rules-senses-outcomes and fix-health-leak): `player-look2-f` `face.py` 28 of 28 three times, the same numbers (cruise 2.8126 m/s for that character); `fov.py` 15 of 18: `place_at` put the player 5.0 m from R (435.5 for 436.0), within `heard_near_m`, so R was heard near, not close, and the two heard-row checks that look for the close row failed. `fov.py` now tries residents until the player stands 5.25–5.9 m off. `player-look2-g`: 17, 18, 18, 18 of 18; run 1 (the first drive on the fresh world) failed "kept at 75° once seen" once, with the 65° and 100° checks passing; not reproduced in three more runs. Kept as an intermittent failure, not waived.
- Not run on this change: the other player scripts.

## 2026-11-11 rules-senses-outcomes: my_senses, my_act_outcomes (Spark)

Branch `rules-senses-outcomes` on the Spark, the trial server `slop-trials-stdb` (2.14.1, port 3320), private `CARGO_TARGET_DIR`, `scoped`, fake models only, at `7eae101e` (origin/main `7c6a92b6` merged). Evidence under `.local/living/verify/`. A maintain pass scoped to this change: `senses.py` and `outcomes.py` new, `combat.py`'s death scene extended; the feature map gains `senses.md` and `outcomes.md`, and main's duplicated paragraph in SKILL.md is one again.

- `player-sso-214702` (default seed): `senses.py` 8 of 8 (by day; the torch at night passed on `player-senses-204918`'s second run, 6 m to 9 m); `outcomes.py` 7 of 7; `command.py` 4 of 4; `told.py` 11 of 12 on the first run (the player's gift broken off by the receiver moving away wrote no line within the script's window while the AI's did; host load about 37), 12 of 12 on the second.
- `player-sso-island-215136` (island): `combat.py --scene death` 4 of 4: killed by a wolf, a `death` row with code `killed` and the wolf's id in `other`, its line "You were killed by …".
- Earlier on the branch: `player-senses-204918` (senses 7 of 7, then 9 of 9 after the death case and a wait after a handback), `player-outcomes-210154` (outcomes 6 of 7, then 7 of 7 after waiting for the `own` line, which can come up to one release after its row).

## 2026-11-11 ui-1 step 4: the bar, offer cards, face out of the lists (laptop)

Branch `ui-1-step4` (origin/main merged at `5cd546da`), on the laptop's Docker SpacetimeDB 2.14.1, `scoped`, no model calls; world `verify-player-ui1d` (`$V launch --run player-ui1d --seed island`, joined as `Verifier`). The step changes no authority code; the rules are identical with every `_ui()` stripped (`living_rules` test), and its acts go through `human_act` and `use_skill` as before.

- `offers.py` 17 of 17, `answers.py` 9 of 9 (the decline told to the walker, the player's outcome), `gesture.py` 10 of 10.
- `offers.py` now has the walker ask for hide, not berries: the island's newcomer arrives with berries, so "accept without the goods" was accepted at once on a fresh world (an earlier run here: 13 of 17).
- `combat.py --scene all`: 26 of 26 on `player-ui1c` before origin/main's `fix-place-free` (e3f0527f); 16 of 26 on `player-ui1d` after it. Every failure is a staged fight: the target is put on the nearest free tile, out of a strike's reach ("refused: out of reach"), and the jump finds "no room to jump". Not this branch's: its scenes need placing for the new `place_at`. Evidence `.local/living/verify/player-ui1d/combat.txt`.

## 2026-11-11 speech-2: whisper and call, refusals in the script's words (Spark)

Branch `speech-2` (from `speech-1`) on the Spark, the trial server `slop-trials-stdb` (2.14.1, port 3320), private `CARGO_TARGET_DIR`, `scoped`, fake models only. Evidence under `.local/living/verify/`.

- `speak.py` `player-speak5`: 15 of 15. For each way on the card, the refusal (a whisper to no one, a whisper 4 m away, a second call within 6 s) is the reducer's error, byte for byte the words of the installed script's `<way>_check` on the same facts, run outside the authority as a client runs it (`living-rules` example `way_check`, `speech::check_ctx`).
- Earlier attempts:
  - `player-speak3` 12 of 12 was before refusals moved to the script.
  - `player-speak4` failed only the second call: its facts and SQL took 5.7 s before the second call was sent, past the 6 s gap, so the reducer accepted it. It now sends at once and asks the client's check about the same moment.
- After merging origin/main (`93019a3`): `player-speak6` 15 of 15.
- After merging origin/main (`48cd022`): `player-speak9` 15 of 15.
- `speech::check_way`, origin/main `601d1f6` merged: `player-speak11` 15 of 15 (the `way_check` example now calls `check_way`, as the authority does).

## 2026-11-11 speech-1: human_speak (Spark)

Branch `speech-1` (from `a107fdf`) on the Spark, the trial server `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence under `.local/living/verify/`.

- `speak.py` (new): `player-speak2` 8 of 8: `speech_card` read anonymously; `human_say`, `human_speak(…, "say")` and `human_speak(…, "")` spoken; their `said` rows in `my_experience`; `my_heard` rows joined by `line`, listing the resident; refused "no way of speaking called `shout`" and "speaking too fast", writing nothing. The shipped script has one way, so the card's `needs_to`, `reach` and gap loops had nothing to drive.
- `player-speak1` failed only the too-fast check: the first line's row reached `my_experience` at the next frame, during the check's count. The check now waits 0.8 s before counting.

## 2026-11-11 rules-offers-2: answers by id (Spark)

Branch `rules-offers-2` (origin/main merged at `5f7ba5b`), on the Spark, in the trial container `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no model calls. Every scratch database answered 404 after cleanup. Scoped maintain pass on offers (offers.md, README, SKILL.md): "Declining: there is no act" was drift and is replaced; `answers.py` added.

- `answers.py` (new): 9 of 9 on `player-offers2-a`, `-b` and the final code (`player-offers2-final-answers`). On `-a` the outcome of a decline was said twice (the engine's note and the rules' line); the engine's note is gone.
- `offers.py` 17 of 17 and `deal.py` 13 of 13 on fresh worlds (`player-offers2-b`, `-c`; final code `player-offers2-final-offers`, `-final-deal`). Run after `answers.py` on one world they failed 4 and 2 checks on its leftovers (berries in the pack, a declined record first in `my_records`): an order dependence of the drivers, noted in offers.md.
- Not covered: the game client sending these acts (the laptop's ui-1; `ui::act_node` is covered by Cargo).
- After merging main `f047f04f` (`c63c372d`): `offers.py` 17 of 17, `answers.py` 9 of 9 (`player-offers2-m3-*`).

## 2026-11-11 goods-2: making glass at a furnace that burns fuel (dev-box)

Branch `goods-2` (from main `62d861f0`, merged with main four times, last with `94050f9a` at `6fefe997`), own container `goods2-stdb` (2.14.1, port 3323, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR` and `--target-dir`, `scoped`, no model calls. Every scratch database answered 404 after cleanup.

- `workplace.py` (new) on cullet-laws: `player-goods2-glass` 15 of 15, merged `player-goods2m-glass` 15 of 15, third merge `player-goods2f-glass` 15 of 15, fourth `player-goods2g-glass` 15 of 15. Out: refused "the furnace is out: feed it first", nothing taken. Fed one peat: lit for 40 s (one unit at 3 a game hour on the 48-minute day), the feed seen as `doing` (code `feed`) at the furnace; glass refused "has too little fuel left for it (it takes 1, it has 0.99)". Fed three more: glass made from 1 ash and 2 sand, the furnace's `lit_until_ms` 40,001 ms earlier than before, `doing` (code `make`) at the furnace while it lasts and gone after; "You did what you had decided: make glass → furnace (+1 glass)." in `my_experience`.
- The authority has no offered-acts list; the client's F list is the client's own `_check` on its facts (features/workplace.md).

## 2026-11-11 fov-1: perceiving by facing (dev-box)

Branch `fov-1` (from main `f2d803fa`, goods-1 merged), own container `fov1-stdb` (2.14.1, port 3318, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, fake model only. The host ran seven other workers (load average 17–60). Evidence under the worktree's `.local/living/verify/` (git-ignored).

- `player-face1-a` (`human_face`): `face.py` 11 of 11 (`face.json`). The first two runs failed only the bucket check: 40 looks over HTTP never exhausted the shipped refill (30 a second), then a refill of 1 a second refilled before the `human_move`. The laws are now narrowed to 0.2 a second and a burst of 3 for that check.
- `player-fov1-m` (after merging `origin/main` `accf27c8`): `fov.py` 18 of 18.
- `player-fov1-d` (the final build before the merge): `fov.py` 18 of 18 (`fov.json`). `player-fov1-a` (the build before): 18 of 18. Two runs in between (`-b`, `-c`) wrote no `fov.json`, because the driver's output was piped into `head`, which closed it. The first attempt failed the field's edge and "R behind not in view" with R 4 m off, because the keep metre widens the 3 m near ring and the 3.7 m daytime side vision past 4 m. R is now 5.5 m off.
- Not run on this change: the other player scripts (`appraise`, `approach`, `combat`, `gesture`, `deal`, `drop`, `new_skill`, `told`, `host`, `command`).



## 2026-11-11 rules-offers: trade offers a player receives (Spark)

Branch `rules-offers` (from main `74a6d8a`, then `35c0717` merged), on the Spark, in the trial container `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped` unless named, no model calls. Every scratch database answered 404 after cleanup. `offers.py` (new, [offers.md](../features/offers.md)) on `player-offers-1111-183948`: 17 of 17. Shown: a resident's offer in `my_offers`, a second player's outgoing one, isolation between them, refused and then completed `accept`, `trade_offer` private. After the window the second offer was gone (`expiry-after-window.json`). Not covered: a client drawing the offer (the laptop's ui-1), and a mind deciding to offer (the resident's offer came through admin `mind_act`).

## 2026-11-11 eye-2: across a drop, unchanged (dev-box)

Branch `eye-2` (from main `eead7a29`, uncommitted at the time of the runs), own container `eye2-stdb` (2.14.1, port 3317, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no model calls. Every scratch database answered 404 after cleanup. `drop.py` on plan-test (`player-eye2v-drop`): 6 of 6 (both see each other across one drop tile, the walk stops at the edge, the route never crosses, the arrow over the drop strikes). Plan-test's lots name no measured model, so eye-2 changes none of its tiles. Maintained: drop.md (the script reads plan-test's plan whatever the seed; the search's full conditions), comments in `combat.py` and `gesture.py` (open stalls and wells no longer hide).

## 2026-11-11 drop-1: across a drop (dev-box)

Branch `drop-1` (from `6a905c31`, origin/main `fd2030c3` merged), own container `drop1-stdb` (2.14.1, port 3315, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no minds. Evidence under the worktree's `.local/living/verify/` (git-ignored).

- `player-drop1b-20261111-155119` (plan-test): `drop.py` 6 of 6: the players above (the row, 6.5 m) and below (the quay, 2.5 m), 2 m apart across one drop tile, see each other in `seen_bodies` and `seen_characters`; the one above walking straight at the drop slides 2.65 m along its edge and never stands on it or on the quay; told to go below, it walks 20.3 m by the stair and its route never crosses the drop; its arrow over the drop strikes ("struck Below: hit for 16").
- An earlier run (`player-drop1-20261111-154955`) failed only "stops at its edge": the check wanted the player inside the row's polygon, and steering had slid it past the plan's west end into the skirt (neither level). The check is now "never on a blocked tile and never on the lower level".

## 2026-11-11 goods-1 (dev-box)

Own container `goods1-stdb` (port 3313), merged build (rules-1, plan-1). `player-g3-11111531`: `new_skill.py` 6 of 6 (it installs the script, now over HTTP through the harness) and `told.py` 12 of 12 pass. The player path did not change; `feed` and `make` are skills from the script like `whittle`, and are not offered in the shipped world (no fires that burn fuel, no recipes).

## 2026-11-11 every person a mind (lives-2, dev-box)

On the dev-box worktree `~/dev/slop-lives2`, branch `lives-2` (d87310d unit 1, 6157bf0/055d80e/efcd489 units 2-4, 45d4ac6 the new-day fix), own container `lives2-stdb` (2.14.1, port 3461, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only. Several suites ran at once (load 25-45); one batch failed on a full disk (`No space left on device`, the whole dev-box at 98 %) and was rerun.

- `waking.md` and `wake.py` removed with the woken mechanism. On an island run (`player-l2c-025353`): `command.py`, `told.py`, `gesture.py` pass; `host.py` read the removed `prior` ring for the onlookers' theft line and now reads their experiences: passes (`player-l2c-host2-030713`). Combat, appraise, deal and new_skill were not run.

## 2026-11-11 laws-2 (dev-box)

Branch `laws-2` (from `445db09`), worktree `~/dev/slop-laws2`, own container `laws2-stdb` (2.14.1, port 3447, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence archived on the Mac under `.local/living/laws-2/verify/`. `deal.py`, `new_skill.py`, `told.py` (the refusal now reads "only grazing animals graze"), `appraise.py` pass (`player-l6`, default seed); `combat.py` 25 of 25 on an island run after `join` (`player-x1-combat`; two earlier attempts ran it without a joined player or on the default seed, a harness error); `gesture.py` 10 of 10 (`player-l6c-island`; the first run, under the overloaded batch, failed its `face` check 9 of 10: the driver compares with where the resident stood before it walked on).

## 2026-11-11 player-told (dev-box): a failed command told to the player

Branch `player-told` (from `4b75812`), the worker's own container `player-told-stdb` (2.14.1, port 3447), default seed, `scoped`. `act::tell` tells a played character's failed graph action as an AI's is told.

- `told.py` (new): 12 of 12 (`player-told-c`). Refused at start: one line "You failed to graze: only deer graze", the AI control's text exactly; the same command again inside the window added none. After starting: one line "You failed to give berries → person: they moved away", the AI control's text exactly. `character.ai` false at both reads (no takeover). The first two attempts failed on the driver: a `follow` whose target was moved far, and a receiver moved 40 m, are dropped by the evaluator without a report for the AI too (`player-told-a`, `-b`).
- The same script on the unchanged module (`player-told-base`, `act.rs` stashed): 7 of 12, no line in the player's log for either failure while the AI got both. The case detects the defect.
- `command.py`: 4 of 4 (`player-told-c`). The player-character recipe (`player-told-d`): join once, gift and its `act` feedback, follow, run, walk, stop, say, heard, admin refused; after the move the player's log also holds "You failed to follow → person: you moved" (the follow broken off by taking the controls).
- verify-core `scenes.py refusal`: 4 of 4 (`core-player-told`).
- Not run: `combat.py`, `gesture.py`, `host.py`, `appraise.py`, `wake.py`, `deal.py`, `new_skill.py`, `walk_times.py`, the game client binary.

## 2026-11-10 fix-rules-small (dev-box): the client-feel failures triaged

Branch `fix-rules-small`, the worker's own container `rules-small-stdb` (2.14.1, port 3417), island seed, `scoped`; a clean baseline worktree of `origin/main` (`7dab3cb`, authority equal to `6c8d100`) on the same container.
- **origin/main, unchanged scripts** (`player-rs-base1`): `combat.py --scene all` 20 of 25, the same five as `player-feel-1110-231835`; `gesture.py` **10 of 10**. So the gesture failures of the client-feel run (no player `skill_use` for the wave and nod, waving at oneself accepted) do not reproduce on main's authority built clean; that run's module came from a dirty tree ("commit 5b1e54a4 + uncommitted living/ changes", built in the shared `living/target/verify-island`).
- **Block, dodge, heal (stale scene):** the attacker was resident 17, Tib Tolley, a child (`stage` 1); the rules refuse its strike ("too young to fight", told since this branch's refused-start change). `dummy()` now takes adults only; the block scene raises the guard toward the attacker where it actually stands.
- **Fire bolt (stale scene):** the diagonal from the arrival spot (410.5, 258.5, inside a town) crossed a building's wall; with that fixed, residents at their posts stood in the line. The bow and bolt scenes now choose a clear line and follow the body the impact names.
- **Gestures on this branch (stale scene):** with world creation repeating, the first resident found at a post was always an outlaw (Marta Hale, #253) whose fellow threatened the player; the commotion took her attention. The script now takes the resident at a post nearest the player.
- **After the fixes** (`player-rs-combat3`, fresh world): `combat.py --scene all` 25 of 25, `gesture.py` 10 of 10, and `--scene bow,bolt` twice more, each striking its dummy. `command.py` (new, a command runs once): 4 of 4 (`player-rs-cmd2`, `player-rs-final`: `{"wait":4}` back to "waiting for you" after 4.2 s). The sweep's player recipe (`player-rs-final`): join, move and stop, say, admin refused.

## 2026-11-10 client feel (Mac): failures on `origin/main`'s authority

Branch `fix-client-feel`, whose `living/authority`, `living/rules` and `living/scripts` equal `origin/main` (`6c8d1002`); shared container (2.14.1), island seed, `scoped`, run `player-feel-1110-231835`. `combat.py --scene all`: 20 of 25. Failed: the fire bolt struck a wall; both block scenes recorded no events (`[]`); the dodge moved 1.95 m with no events; heal refused "you are not hurt" (health 98). `gesture.py`: 7 of 10. Failed: no player `skill_use` row for the accepted wave and nod (the residents' answers and the `doing` rows are there), and waving at oneself was not refused. Not triaged in this change (no authority code changed); the last full passes recorded below predate the merges since `rhai-1`.

## 2026-11-10 dealings and a skill only the script declares (Mac)

Branch `rules-2` (`eaee6b0`) in a worktree, own container `sao-rules2-stdb` (2.14.1, port 3342), default seed, `scoped`. `deal.py` (new): 13 of 13 (`player-rules2-deal2/`; the first attempt failed one check on the driver, which looked for "proposed to" in lowercase, `-deal1/`). `new_skill.py` (new): 6 of 6 (the first attempt assumed the player's wood count). Not run: `combat.py`, `gesture.py`, `host.py`, `appraise.py`, `wake.py`, the game client binary.

## 2026-11-10 walking far (Mac)

Branch `path-1` (from `fe6ec66`) in a worktree, the worker's own container `path-stdb` (2.14.1, port 3391), island seed, `scoped`: walks planned leg by leg (docs/PATHS.md).

- `walk_times.py --clicks 40` on `player-path2`: 16 journeys from Brackenford to every other settlement, all at once, 16 of 16 arrived on the clicked point (397–2,054 m straight, 2:20–14:11). 40 short clicks: 38 arrived (8 round an obstacle, up to 198 m walked for 39 m straight), 2 refused "destination unreachable" (sea, 26 and 29 m from shore). Every walker stayed under its person while walking (`presence.ai` false, checked mid-run).
- `player-path1` (before the `acts::overdue` change): 4 of 4 short clicks arrived. The journey to Thornby stopped after 91 s with "you could not get to it in time", which found the approach limit (docs/PATHS.md, cause 3).
- Not covered: a WebSocket player client (the game client) walking far; a mind service issuing a far `goto`.

## 2026-11-10 mind feedback (Mac)

Branch `feedback-1` (ffb4280) on `feedback-verify-stdb` (3343), island seed, `player-fb1-012517`: `combat.py --scene kill` 2 of 2 (the resident's cause "killed by a stranger", no `acquaintance` row; the chronicle "FbPlayer killed Kelhan") and `--scene death` 3 of 3 ("killed by a wolf", where an earlier run read "killed by Storm the wolf").

## 2026-11-10 hospitality and the name rule (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), branch `townlife-2` (main `015707b`, the `harness-1` merge, merged in) in a worktree: town life layer 2, phase 2 (docs/TOWN_LIFE.md): woken minds made from facts and their ring, the `woken` route, the stage cap, `host`, the `habit` engagement class, names only when known (a feeling is no longer an introduction).

- `host.py` (new): 11 of 11 (`player-tl2-host`, `player-tl2b-host`, `player-tl2e-host`).
- `wake.py`: 25 of 25 (`player-tl2-wake`, `-tl2c`, `-tl2d`, `-tl2e`); `player-tl2b-wake` 22 of 25 (no second resident within 8 m of the first: where they stood).
- `gesture.py` 10 of 10; `appraise.py` 10 of 10 (`player-tl2f`; `player-tl2e` 9 of 10, the appraise `skill_use` outcome read before it was written, the reveal itself correct).

## 2026-11-09 town life layer 2, phase 1 (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `14f3a72` plus the uncommitted town life layer 2 phase 1 change (docs/TOWN_LIFE.md, "Layer 2"): the `woken`, `prior` and `prior_head` tables, the `wakes` and `woken_ring` laws. Free tier only; no model calls.

- `wake.py` (new): `player-wake-1` 21 of 25 (no first deliberation: `think_min_s` counted the starting graph's install; a lesson to a walking resident never landed because waking was at the effect), `player-wake-2` 21 of 25 (empty rings on a fresh world; the lesson again), `player-wake-3` 25 of 25 after waking moved to the act's start and the first deliberation was freed, `player-wake-4` 25 of 25 on the final code (with `min_salience`).
- `gesture.py` (`player-l2`): 10 of 10. `combat.py`: `player-l2` 23 of 25 (a bolt struck a resident who stepped into its path, an arrow struck a wall: scene geometry in the town), `player-l2b` 25 of 25 on a fresh world.

## 2026-11-09 the Rhai boundary, rhai-1 (dev-box)

Private container `rhai-stdb` (2.14.1). Island runs on `33e3185` (`rhai-1` with `origin/main` `2a64837` merged; scoped perception). `player-rhai1-combat-192743`: 25 of 25. `player-rhai1-appraise-192825`: 10 of 10. `player-rhai1-gesture-192904`: 10 of 10. The player's skills now run on lean contexts, with cooldowns and costs from the tables read at compile.

## 2026-11-09 the scoped default (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `acbbda7` plus the uncommitted change that lands the perception client and makes `scoped` the default build (docs/PERCEPTION.md, "Third change"). Fake model only; private `CARGO_TARGET_DIR`s; every scratch database answered 404 after cleanup. `player-sd` on an island run of the default build (`perception scoped`): `gesture.py` 10 of 10; `appraise.py` 10 of 10; `combat.py --scene all` 24 of 25 in the full run: the bow scene's arrow struck a resident who walked into its path (`struck Gada`) and the fire bolt struck the appraise scene's bystander, so the dummy's health did not change; `--scene bow` alone then passed (`struck Moly: hit for 13`).

## 2026-11-09 minds' sight, the projection and presence (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `81b9dd8`/`dc5e41b` plus the uncommitted minds'-sight, projection and presence change (docs/PERCEPTION.md, "Second change"; docs/PLAYER_MEMORY.md, "Presence and the offline character"). Fake model only; every scratch database answered 404 after cleanup. Run `player-perc2`, `--seed island`, scoped build. `appraise.py` (new) 10 of 10; `combat.py --fresh` 25 of 25; `gesture.py` 10 of 10 after a driver fix: it placed the player 3 m east of a resident at a stall whose building hid it, so the wave at someone unseen was refused (the new sight rule); the driver now picks a spot from which the player sees the resident (a new check). `gesture.py` was not executable in the checkout; `chmod +x`.

## 2026-11-09 gestures and town life (dev-box)

Own scratch container `slop-townlife-stdb` (image `v2.14.1`, own volume, `/wasm` from the worktree's `.local/target`) through a `docker` name shim (`~/townlife-shim`); worktree `~/dev/slop-townlife` on branch `townlife-1` (from `b12fa45`, uncommitted at the time). Run `player-town-1`, `--seed island`; scenes set by admin `place_at`.

- **`scripts/gesture.py`, 9 of 9** ([features/gestures.md](../features/gestures.md)): `human_act` wave accepted and kept in `skill_use` (source `act`, outcome `greeted Feka`); its `doing` row with the wave's `act_card` code and target; the resident answered with a nod from its own graph (`answered Visitor`) and the player perceived "Feka answers your greeting (nod)."; one answer only; a nod 8 s later greeted anew and was answered; `face` turned the player's body to within 0.00 rad; waving at oneself refused by the rules ("not to yourself", told as an act experience); `use_skill("wave")` refused ("wave is not on the skill bar").
- **`scripts/combat.py`, 23 of 23** on the same world, as a regression check of the act path this change touched (`act::begin`, `perform`, `finish`, `cancel`).

## 2026-11-09 combat skills on the island (dev-box)

Own scratch container `slop-combat-stdb` (image `v2.14.1`, own volume) through a `docker` name shim (`~/combat-shim`); worktree `~/dev/slop-combat` at `e0c9d1f` plus the uncommitted combat change (docs/COMBAT.md). Run `player-combat-20261109-054716`, `--seed island`, recipe `features/combat.md`: `scripts/combat.py` with the player identity, scenes set by admin `place_at`, `set_behavior`, `kill` and a second `join`.

- **Passed, 23 of 23:** unknown skill is a reducer error; refusals recorded and told (no target, out of reach, unhurt heal, a fire bolt inside its windup); strike windup visible, damage, perceived release and hit with the amount; band public; bow shot launch, impact on the first body, arrow spent; fire bolt; guard in front blocks (amount 2.4 got through), from behind it does not; release ends the guard; dodge moved 2.6 m and the blow was dodged; self-heal +22; the bold pack attacked; death "killed by Storm the wolf" (an earlier run) with the killer as witness; rejoin made a new character with only the kit.
- **Found and fixed on the way:** the rules never read the new `bold` fact (wolves balked); the band row appeared only below the top band; scene ordering (a teleport after setting a graph dropped its approach); a bolt correctly struck an earlier dummy on its line, so the scene aims off those lines.
- Earlier attempts on `verify-combat-1` are kept in that run's `actions.log`.


## 2026-11-09 island land world (dev-box)

The dev-box (Fedora, rootless podman) ran its own scratch container `slop-live-stdb` (image `v2.14.1`) through a `docker` name shim. The worktree was `c5a2c00`, with uncommitted `living/game` changes (the connected game client); the authority and rules were unchanged. The recipe in `features/player-character.md` ran on `--seed island`, runs `player-island-live` and `player-island-live2`. Evidence is in the dev-box's `~/live-evidence/`.

- **Passed:**
  - `join` placed the newcomer at the `land` row's arrival point, (512.5, 174.5), not at (40, 60).
  - A second `join` was refused.
  - Run and walk speeds were 4.09 and 2.73; stopping set the plan to "moving yourself".
  - `follow` gave plan "your command", source "human".
  - Speech wrote the chronicle line "Verifier to Iseve: “Good morning.”".
  - `set_paused` and `grant_items` were refused with "admin only", and `mind_skip` with "not your character".
  - After an admin `kill`, the same identity joined again as a new character.
- **Recipe gap on land worlds:** the neighbour query `kind = 'person' AND ai = true` returns nothing. Island residents run with `rules.minds = false`, so they are `ai = false`. The first run found no neighbour, and its act steps sent `"id":` with no value, which was refused as bad JSON. The second run picked an adult resident (`stage = 2 AND id != $ME`).
- **Behaviour on land worlds, as designed:**
  - Mindless residents write no `experience` rows, so the neighbour got no `speech` experience. The chronicle line is the proof of speech.
  - The gift failed with feedback "they moved away": the resident kept to its own routine.
- **The game client** joined, walked, spoke, died and rejoined through the same reducers. `verify-client/features/game-client.md` covers it.

## 2026-11-08 SpacetimeDB 2.14.1 upgrade (macOS)

Run `player-1108-214`: default seed, image `v2.14.1`, bindings regenerated with 2.14.1. The recipe in `features/player-character.md` was run as written.

- **Passed:**
  - `join` works once; the second call is refused with "you already have a living character".
  - Failed-act feedback reached the player as `act` experiences.
  - `follow` became the behavior, with plan "your command" and source "human".
  - Speed was 4.29 at a run and 2.86 at a walk; stopping set the plan to "moving yourself".
  - Speech was heard by the neighbour as "Verifier said to you: “Good morning.”".
  - Three refusals held: `set_paused` and `grant_items` ("admin only"), and `mind_skip` ("not your character").
- **Not proven:** the gift. The AI receiver, still running its instincts, walked away. The player got "they moved away" and "the way is blocked", and its berries stayed at 3. This matches the recipe's warning about instinct-driven receivers, not an upgrade fault.
- **Additional check:** the `living/game` spike's demo, built on SDK 2.14.1, joined as #267 and walked from (40.5, 60.5) to (49.1, 60.5) in 3 s.

## 2026-10-04

Run `player-1004-170040`, with the refusal of `mind_skip` rerun as `player-1004-170040b` after a wrong-arity first attempt. Host: Fedora, rootless podman, SELinux enforcing. Commit `384fb50` with uncommitted user changes in `living/viewer/src/clock.rs`. Default seed (`realm-4`). The player used a fresh identity from `POST /v1/identity`. Admin calls set the scene only: `place_near` and `grant_items`. Evidence: `.local/living/verify/player-1004-170040/` (git-ignored, local to this machine).

| Feature | Result | Evidence |
| --- | --- | --- |
| `player-join` | Pass. Character 262 joined: `ai` false, alive. | `actions.log` |
| `player-join-once` | Pass. The second `join` was refused (HTTP 530, `you already have a living character`). | `actions.log` |
| `player-act-deliberate` | Pass. Gift to Lodel (161): the giver's berries went 3 → 2, and the chronicle reads "Verifier gave 1 berries to Lodel". A gift of an item the player lacked failed, and its feedback reached the player's `experience`: "not enough berries (berries: gather it at a berry_bush, or take it from a storage)". | `inv-after-give.json`, `chronicle-give.json`, `feedback-bad-item.json` |
| `player-act-graph` | Pass. `follow` became the behavior: plan `your command`, source `human`, activity `follow`. | `plan-follow.json`, `activity-follow.json` |
| `player-move` | Pass. Run speed 4.10, then walk 2.74; stop 0. This run's stop and the `moving yourself` plan are recorded in the earlier smoke run (`.local/living/verify/smoke/`). | `body-run.json`, `body-walk.json`, `smoke/body-stopped.json`, `smoke/plan.json` |
| `player-say` | Pass. The neighbour's `experience` reads "Verifier said to you: “Lodel, good morning.”". The `speech` chronicle line was recorded in the smoke run. | `heard-by-neighbour.json`, `smoke/speech.json` |
| `player-authority` | Pass. `set_paused` and `grant_items` as the player: `admin only`. `mind_skip` on AI character 167: `not your character`. | `actions.log`, `actions-mind-refusal.log` |

Cleanup deleted both databases (SQL returned 404) and kept the evidence.

Findings recorded during the run:

- Admin `grant_items` accepts any item name without checking it (here `berry`). That is acceptable for an admin scene tool, and the gotcha is in the feature map.
- Earlier reviewers thought `gather` used the graph branch. It does not: every skill outside `REAL_TIME` goes through `acts::submit`. The map now proves both branches explicitly.


## 2026-11-09 one damage rule (Mac)

Shared container (v2.14.1), Mac checkout at `b7cf7fb` plus the change removing the hurt/kill mode (docs/COMBAT.md "One damage rule"). `combat.py --fresh` on island worlds: `player-fm-combat` 25 of 25, with the new `kill` scene (a resident at 4.5 of 100 health took a 12.3 strike: outcome "killed Nogar (12)", cause "killed by Tester", chronicle "Tester killed Nogar"); after review fixes to the scene (40% of `max_hp`, a margin for settled health, only hits in the trail), `player-fm-kill2` 25 of 25 (1.8 health, an 11.5 strike). The attacker graph in the block and dodge scenes no longer carries `"item": "kill"`. Both worlds cleaned up.

## 2026-11-10 verbs from the game client (Mac)

Shared container (v2.14.1), Mac checkout at `6de2bad` plus the uncommitted verbs change in `living/game` (docs/GAME_BRIEF.md "Verbs"). Island world `verify-client-verbs-1110-003532`; the real game client headless from a private release build, driven by `drive_verbs.py` ([verbs](../features/verbs.md)). Runs `game2` and `game3` (after the list fixes), each a new character (#295, #296):

| Act (game client path) | Authority's `act` row |
| --- | --- |
| goto beside a berry bush | "You did what you had decided: goto → (516,184)." |
| F list → gather (twice in `game2`) | "You did what you had decided: gather → berry_bush (+1 berries)." |
| C → eat berries | "You did what you had decided: eat berries." |
| C → craft spear (after admin `grant_know_how` spear, `grant_items` 4 wood, 1 stone) | "You did what you had decided: craft spear (+1 spear)." |
| C → craft bow (not offered: archery unknown; sent by the script) | "What you had decided did not work out: craft bow x1: you don't know how to make a bow (archery: …)." |
| C → write tablet, words "Berries by the arrival road, east side." (after admin `grant_know_how` writing) | "You did what you had decided: write tablet (wrote a tablet)." |
| F on resident #83 (admin `set_behavior` hold, `place_near`) → give berries | "You did what you had decided: give berries → person (gave 1 berries to a stranger)." |
| C → sleep | behaviour (an ongoing skill), as before |

Pack `game2`: start arrow 30, berries 4, bow 1; end arrow 30, berries 4 (+2 −1 −1), bow 1, spear 1, tablet 1, wood 1 (4 − 2 − 1), know-how + spear, writing. Photographs of the hint, both lists, the refusal note, the text box and both panels in `game2/shots` and `game3/shots`.

Genericity: scratch authority with a throwaway `polish` (catalog line and `polish_check`/`_duration`/`_done` plus a `skill_io` entry, `throwaway-skill.diff`, never committed) on `verify-client-verbs-gen-1110-004303`; the same client binary (SHA-1 `87fefd9a…`) logged `defined only by the script: ["polish"]`, offered it on a boulder, showed it in K with its takes and gives, and the authority answered "You did what you had decided: polish → boulder (+1 stone)."

## 2026-11-11, branch fix-perceived-moving (a walking player is perceived walking)

Spark, the trial stack's own server (`slop-trials-stdb`, v2.14.1, :3320), worktree on `origin/main` 6a905c3 plus the change (docs/PERCEPTION.md "Activity derived from the body"). New script `approach.py`. Before the change, on island worlds built from `origin/main` (`fixperc-pre2` at 4df9a89, `fixperc-pre3` at 6a905c3 with the three authority files reverted), `--expect-wait` passed: the resident R's scene had the walking player as `"doing": "wait"`, its first sight was "For the first time you see a stranger, 11 tiles west, wait.", and the AI walking the same line read `goto → person`. After the change, on fresh island worlds (`fixperc-post4`, and `player-fixperc-1`), all 6 checks passed: the walking player read `walk → person`, R's first sight was "For the first time you see a stranger, 11 tiles west, walk → person.", the player standing read `wait`, and the AI read `goto → person`. A bystander player's `seen_bodies` held both bodies moving and its `seen_doing` no row for either. In the same `player-fixperc-1` world, `appraise.py` passed 10/10 and `gesture.py` 10/10. Earlier attempts (`fixperc-post`, `-post2`, `-post3`) show the fixture problems the script now handles: a resident on a house tile with a campfire east of it, a side with no sight line, a just-published world's late `think`, and a crowd in which strangers are not announced. Evidence: `.local/living/verify/{fixperc-pre2,fixperc-pre3,fixperc-post4,player-fixperc-1}/approach.json`.

## 2026-11-11, branch fix-staging-place (staging for the free-tile `place_at`)

Spark, the trial stack's own server (`slop-trials-stdb`, v2.14.1, :3320), worktree on `origin/main` d2a2d228 plus the change. Each script on its own fresh run (`player-sta-*` island, plan-test and cullet-laws; `player-stb-*` default seed). `combat.py` before the change 19 of 26 (`player-stage-1111-221608`, "out of reach" in strike, kill and block; the laptop saw 16), after 26 of 26 on the same world with `--fresh`, then 25 of 26 on a fresh island world (`player-sta-combat`: the jump saw no blow in its 1 s window) and the jump scene 4 of 4 alone (`player-stc-jump`). Unchanged and passing: gesture 10, appraise 10, host 11, drop 6, workplace 15, speak 15, told 12, command 4, new_skill 6, fov 18, face 11, offers 17, answers 9, deal 13. `approach.py` 3 of 5 after appraise on `player-sta-appraise-approach` (the AI walker had already arrived when R's scene was taken: `goto` read as `wait`), 5 of 5 on `player-stc-jump`. `living/tools/combat_scene.py` put its residents 2.0, 8.0 and 1.0 m from the player, as asked.

## Not verified

- The game client's keyboard and mouse themselves: the runs drive its script steps, which call the same code as F, C, I, K and the list's keys.
- Rate-limited movement input from a player identity. `verify-core` proves it on its steering scene, through the admin identity.
- Conception and teaching as player acts. They share the `acts::submit` path proven by the gift, but their effects were not driven from a player identity.
- Whether Claude Code, Codex, Cursor and Mistral Vibe pick up this skill at runtime.
