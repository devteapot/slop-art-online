# The game client in a world still being made (`genesis-client`)

## Setup

- **Branch:** `genesis-client`, on `origin/staged-genesis` `decb1b1ac` (the authority half, in dev-box's merge gate; not on main yet). The client changes were uncommitted in the worktree while these drives ran (launch logs `decb1b1ac + uncommitted living/ changes`); the commit holds exactly them.
- **Server:** the laptop's shared `sao-living_spacetimedb_1` (v2.14.1), with `scoped` island builds of `decb1b1ac`'s authority in a private target dir (`$HOME/.cache/genesis-client-target`).
- **Client:** the release client, built from the same private target dir through `build-slot` with `BUILD_SLOTS=1`.
- **Not used:** no mind service, no model calls, no owner play-test session open.
- **Feature:** [features/preparing.md](../../features/preparing.md).

## Unit tests

- `cargo test --release -p living-game`: **185 passed, 0 failed, 1 ignored** (the `#[ignore]`d `ik::spots::uneven_ground_spots` tool).
- The 9 `genesis::tests`, run again after the bar change:
  - `the_prefix_is_matched_and_the_rest_is_for_people`;
  - `progress_lines_and_shares`;
  - `the_row_moves_the_gate_and_done_is_timed` (with the bar never running back);
  - `no_row_or_no_table_is_ready`;
  - `a_refused_join_is_sent_again_when_done_turns_true`;
  - `a_refused_join_is_retried_on_a_capped_backoff`;
  - `a_refusal_against_a_ready_row_waits_for_the_backoff`;
  - `other_refused_calls_are_held_quietly_without_a_join`;
  - `a_long_wait_and_a_stopped_chain_are_said`.
- `cargo test --release -p living-rules ui::`: **38 passed**, including the guards `the_game_client_names_no_new_skills` and `no_skill_is_named_in_the_rules_interface_code`.

## `check.py preparing` (island, its own world)

### First run, `ui-gp-0347`: 9/9

The bar ran back when `steps` grew (16 of 24, then 17 of 40). The time from done to join used `genesis.updated_ms` as the authority's `done`, and so read 5.97 s. The client's own time was 1.94 s.

From the samples, `updated_ms` is the last step's start: populate then ran about 4 s on the island before `done` committed. Both were fixed before the second run: the bar keeps the most done so far, and the scenario takes the first owner read that saw `done`.

### Second run, `ui-gp-0349`: 9/9

- **The probe** was refused while the world was made: `player join["Probe"] -> 530 world_preparing: the world is still being made (step 8 of 23: land: plan: city)`.
- **Dump 01** shows `Preparing`, with the cover "Preparing the world…", `step 3 of 23 · land: dispersed sites (step 1)` and the bar at 0.13 (`01_preparing.png`).
- **Dump 02** shows `step 38 of 41 · build: lots 0..718 of 718` with the bar at 0.93 (`02_preparing.png`).
- **Dump 03** shows `Ready`, with no cover and the arrival on Brackenford's square (`03_joined.png`).
- **No error was shown.** Every dump's `genesis.errors` was empty, no note named `world_preparing`, and the log had no warning and no `join refused`.
- **Done to join:** **0.66 s** from the authority's `done` (first owner read, 02:49:27.108 UTC) to `playing character #…` (02:49:27.768). The client's own count was also 0.66 s. That read came 4.02 s after the done row's `updated_ms`.
- **The client's path:** it connected about 3.8 s after it started. It logged `genesis: preparing step …` for each step, then `the world is ready after … s preparing`. Only then came `world kind: Land`, `world subscribed` and `joining as Verifier`. So the base set and `join` waited for `done`, and no `join` was refused.

**Evidence:** `.local/living/verify/ui-gp-0349/ui/preparing/`, holding the stills, `01.json`–`03.json`, `client.log`, `genesis.json`, `timing.json`, `launch.log` and `ui/checks.json`. The first run's is in `.local/living/verify/ui-gp-0347/ui/preparing/`.

## Regressions on a ready world: `ui-gc-0346`, 98/98

`check.py windows talk camera` all passed. `camera` ran with facing sight off and on: far, middle and near, the bearing, the cutaway, the scoped view and picking. `doctor` reported `world is made (genesis done)` before the drives.

**Evidence:** `.local/living/verify/ui-gc-0346/ui/` (`windows/`, `talk/`, `camera-*/`, `checks.json`).

## Cleanup

`verify-ui-gp-0347`, `verify-ui-gp-0349` and `verify-ui-gc-0346` were deleted through `$V cleanup`, and their module copies removed. The evidence is kept.

## Not covered

- **The client's join-refusal path, live.** The client holds `join` until `done`, so no drive sent a refused `join`. That path is covered by the unit tests, and the authority's text by the probe.
- **The 120 s message and a stopped chain, live.**
- **A reconnect into a world being made** (the link line).
- **Cullet.**
- **A module without the `genesis` table.** The quiet subscription error is reasoned from the code and the SDK docs, not driven.
