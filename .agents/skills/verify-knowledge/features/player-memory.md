# Player memory (a human-played character internalizes what it lived)

Design: [docs/PLAYER_MEMORY.md](../../../../docs/PLAYER_MEMORY.md). Off by default (`LIVING_PLAYER_MEMORY=1`).

## Sub-features

- **Switch off:** the mind subscribes as before (only its own controller's experiences), makes no `internalize` request, writes no graph for the player and leaves the player's `experience` rows alone; a minded resident still answers the player.
- **Own speech:** a human-controlled speaker perceives its words as a `said` experience ("You said to Walker1: “…”"); AI speakers do not.
- **Switch on:** the mind also subscribes to `experience WHERE controller != <mind identity>` and `settlement`, buffers each played character's experiences and integrates them at a cadence (buffer, game day, session end after `LIVING_PLAYER_MEMORY_IDLE_S`, death). The request carries only that character's experience lines with `@[x, y]` and the settlement, and no input, commands, `deliberation` or transient views. Its system prompt is identical across requests.
- **Provenance:** memories, concepts the patch names and beliefs carry `lived_under = ["human"]`; `self.lived_upto` is the last integrated experience id; the `thought` is kind `internalize` with `lived_under`, reason and mode in its detail.
- **Projections:** `relation`, `judgment`, `place` (and `belief`) rows for the player come from its graph through `mind_update`, accepted from the mind service for a human-controlled character; no `persona` row is written (the authority refuses one).
- **Rows kept:** the player's experience rows remain after integration (no `mind_consolidated`).
- **Restart:** a restarted mind reads `lived_upto` ("internalized up to N" in its log) and the next integration takes only later ids.
- **No leak, and recall:** the resident's own memory of the player is in its talk prompt and recall; the player's private memory (the wolf fight) is in neither; the player's recall (`recall_replay`) returns it. Recall sizes in tokens are recorded.
- **Death:** admin `kill` right after the player speaks: the authority deletes the player's experience rows, and the mind still integrates the last words from its buffer (log "lived experiences (death").
- **Batch mode** (`--mode batch`): every request goes through the fake's `/v1/batch/jobs` (`batch_job` in `requests.jsonl`) and the thought detail says `mode: batch`.

Sources: `living/mind/src/mind/lived.rs`, `living/mind/src/llm.rs` (`Llm::batch`, `request_body`), `living/mind/src/prompts.rs` (`internalize_system`), `living/mind/src/memory.rs` (`Patch::lived_under`, `lived_upto`), `living/mind/src/main.rs` (subscriptions, `Event::Lived`), `living/authority/src/perceive.rs` (`speak`), `living/authority/src/mind.rs` (`authorize_projection`).

## How to get to it (user POV)

A person plays a character on an island world; with the switch on, what the character lived is in its Neo4j mind once the session ends, marked as lived under a human, and a mind that later takes the character over recalls it.

## Driving it

```bash
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) [--mode batch]
```

It launches `--seed island` through the shared harness, starts its scratch Neo4j on 7691, builds the mind in `.local/living/verify/build-knowledge`, joins the player (`Wren`), adds one minded resident with admin `spawn_crowd 1 true`, `place_at` and `set_behavior` (scene setup, not player abilities), and runs the [scripted session](../scripts/player_session.py). The fake script (`fake-script.json`) uses `cite` replies that name the experience ids of the request. Evidence: `results.json`, `session.json`, `requests.jsonl`, `mind-off.log`, `mind-on.log`, `mind-restart.log`, `off-player-*`, `on-player-*` (nodes, edges, relation, judgment, place, persona, experience), `resident-*`, `resident-talk-prompt.txt`, `recall-cases.json`, `recall_replay.log`, `death-player-experience.json`, `journal/`, `cleanup.json`.

Paid tier (after the user authorizes the run): `scripts/player_memory_real.py --allow-live --run knowledge-pmem-real-<name>` runs the session once with a real resident mind, then one mind per (model, mode) with its own `LIVING_RUN`, and writes `fidelity.json`, `cost.json` and `report.md`.

## Gotchas

- The island's residents live on instinct (`ai = false`), so the driver adds a minded Walker. `LIVING_ONLY` must name the player too: the switch respects it.
- The world differs between runs: the gather may fail ("no nearest tree in sight"), which is still a lived experience; checks key on "gather".
- The first integration with the switch on may be the off phase's backlog alone; the checks look across every `internalize` request.
- The fight stops at half health: a dead player's rows are deleted by the authority (the buffer keeps them, but the next scene needs a living player).
- The resident consolidates only once its salience threshold is met; the driver waits up to 240 s.
- `kind:` concepts created only as an edge's endpoint carry no `lived_under`; the edge does.
