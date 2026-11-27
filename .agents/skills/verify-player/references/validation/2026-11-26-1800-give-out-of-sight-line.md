# A gift whose receiver leaves sight is told (branch `give-out-of-sight-line`)

Branch `give-out-of-sight-line` from origin/main `b78c59653`; built from the WIP commit `93ac719da`, whose `living/` is identical to the final commit (that adds the records and the scene's last edits, below). Spark (aarch64), private server `slop-tgm-20261126` (SpacetimeDB 2.14.1, `127.0.0.1:3591`). Builds through `build-slot` with a private `CARGO_TARGET_DIR`; launches under `trial-activity.lock`; worlds deleted by `verify.py cleanup`. No mind service, no model calls.

**The change.** A graph `do` leaf whose own activity is being performed and whose target no longer resolves now breaks the activity off and tells it (`act::lost`, from `Node::Do` in `brain.rs`): "You failed to give meat → person: lost sight of them", once per `repeat_failure_s`, for a player's command as for an AI's graph. Before, `Ev::after` cancelled it with no reason, so only `stuck: give: no #N in sight` reached the record.

**The scene.** `told.py` part 3 (new): the receiver is moved 20 m away (beyond sight in any light) while the gift is handed over. This is done for the player's command (`{"seq":[give]}`), the AI's graph, the player's deliberate act (`human_act {do:give}`) and the AI's deliberate act (`mind_act`, called as the admin). Each gift must give exactly one line, and each graph form must at least once give the leaf's "lost sight of them". Part 2 now moves its receiver 4.5 m instead of 6 m. At 6 m it was out of sight unlit at night (6 m), where the leaf's path now speaks instead of the timer.

| Run | Authority | Result |
|---|---|---|
| `player-tgma-185437` | branch | 28/28. Part 3's graph forms: "You failed to give berries → person: lost sight of them", one line each for the player and the AI. Deliberate acts: one "…: they moved away." each |
| `player-tgma2-185557` | branch, items reordered (meat first) | 28/28, the same with meat |
| `player-tgma3-185936` | branch, the final scene (a try that never reached its handing over is retried) | **28/28** |
| `player-tgmmain-185557` (control, in a throwaway origin/main worktree with this scene copied in) | origin/main `b78c59653` | 21/28. **Graph forms: no line at all in 10 of 10 performing gifts** (5 for the player's command, 5 for the AI's graph; a sixth try never reached its handing over). Deliberate acts: one "they moved away." each, as on the branch |

The first run used berries in part 3. Part 2 had told "give berries → person: they moved away" less than 120 s earlier, so a gift whose timer fired first would have been held back as a repeat. The run passed only because the leaf spoke first. Part 3 now uses other items.

Evidence: `.local/living/verify/player-tgma-185437/`, `player-tgma2-185557/`, `player-tgma3-185936/` (`told.json`, `told.txt`, `actions.log`). The control's evidence is in `~/slop-evidence/give-out-of-sight-line-control-20261126.tar.zst` (sha256 beside it).

**Not covered:** the race between the leaf's look and the activity's 1 s timer was not forced; every branch run had the leaf first. Both paths give exactly one line, and the scene accepts either per try. Not driven: other skills performed on a creature that leaves sight (teach, offer), and the game client's display of the line.
