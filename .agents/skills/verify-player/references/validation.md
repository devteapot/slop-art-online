# Validation record (player)

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

## Not verified

- A real player client; none exists in `living/` yet.
- Rate-limited movement input from a player identity. `verify-core` proves it on its steering scene, through the admin identity.
- Conception and teaching as player acts. They share the `acts::submit` path proven by the gift, but their effects were not driven from a player identity.
- Whether Claude Code, Codex, Cursor and Mistral Vibe pick up this skill at runtime.
