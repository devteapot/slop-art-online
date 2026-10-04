# Validation record (player)

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

## Not verified

- A real player client; none exists in `living/` yet.
- Rate-limited movement input from a player identity. `verify-core` proves it on its steering scene, through the admin identity.
- Conception and teaching as player acts. They share the `acts::submit` path proven by the gift, but their effects were not driven from a player identity.
- Whether Claude Code, Codex, Cursor and Mistral Vibe pick up this skill at runtime.
