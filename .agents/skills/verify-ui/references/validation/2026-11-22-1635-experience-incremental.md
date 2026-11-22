# A player's lines as rows (`experience-incremental`): the interface

Validated on the dev-box on branch `experience-incremental` from `origin/main` `9ed12f51d` (authority as at `48e401906`, client as committed). Island world `ui-ei-1122-172009` on the private server `so-stdb`; the release client built in this worktree; `performance` governor. No paid model calls. Scoped `maintain-verification-skill` pass: the client now reads its lines from `experience_copy` while `lines_table_on` is on (shipped on), through `net::my_lines`, wherever it read `my_experience` (talk, bubbles, the people windows, verbs' outcomes, the town and weapon notes, the camera's answer framing, the HUD). No feature file names the source, so the map has no drift. Outcome: **clean**.

## Run

`check.py --run ui-ei-1122-172009 talk bubble-once room-detail ways reversal items combat-switches-death`: **86 PASS, 0 FAIL** (`ui/checks.json`).

## Not covered

The other scenarios; the switch of the lines law while a client runs (proven at the protocol level by verify-client's `lines_table.py`).
