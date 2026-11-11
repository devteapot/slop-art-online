# Validation record (player)

## 2026-11-11 fov-1: perceiving by facing (dev-box)

Branch `fov-1` (from main `f2d803fa`, goods-1 merged), own container `fov1-stdb` (2.14.1, port 3318, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, fake model only. The host ran seven other workers (load average 17–60). Evidence under the worktree's `.local/living/verify/` (git-ignored).

- `player-fov1-m` (after merging `origin/main` `accf27c8`): `fov.py` 18 of 18.
- `player-fov1-d` (the final build before the merge): `fov.py` 18 of 18 (`fov.json`). `player-fov1-a` (the build before): 18 of 18. Two runs in between (`-b`, `-c`) wrote no `fov.json`, because the driver's output was piped into `head`, which closed it. The first attempt failed the field's edge and "R behind not in view" with R 4 m off, because the keep metre widens the 3 m near ring and the 3.7 m daytime side vision past 4 m. R is now 5.5 m off.
- Not run on this change: the other player scripts (`appraise`, `approach`, `combat`, `gesture`, `deal`, `drop`, `new_skill`, `told`, `host`, `command`).



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

## Not verified

- The game client's keyboard and mouse themselves: the runs drive its script steps, which call the same code as F, C, I, K and the list's keys.
- Rate-limited movement input from a player identity. `verify-core` proves it on its steering scene, through the admin identity.
- Conception and teaching as player acts. They share the `acts::submit` path proven by the gift, but their effects were not driven from a player identity.
- Whether Claude Code, Codex, Cursor and Mistral Vibe pick up this skill at runtime.
