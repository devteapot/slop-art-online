# Play session report

Status: **in use** since 2026-11-11. After every owner play session, `living/tools/play_report.py` writes one page, `<out>/index.html`, holding what was on screen and a timeline of the session. Nobody has to ask for it: the play launcher (`play-1`) records each session and runs the report when the client exits.

It was built because play-test 2 left no recording. Finding out why residents seemed silent then took a manual investigation (`.local/living/playtest-2/diagnosis/REPORT.md`), and the owner's feedback came from memory minutes later.

## Run it

```bash
python3 living/tools/play_report.py --db <database> --run <run> \
    --journal <journal dir> --logs <dir with client.log and mind.log> \
    --out <dir> [--capture <dir>] [--player <character id>]
```

- It writes `<out>/index.html`, plus `report.json` (the page's facts, for checks) and the stills and video the page shows. It prints the page's path.
- It reads the world as its owner over SQL, using the in-container CLI identity as the verify harness does. It works on a paused world. It only runs `SELECT`s and never calls a reducer.
- Without `--capture` the page has no pictures. The timeline still comes from the authority's rows, the journal and the logs.
- The played character comes from the client log's `playing character #N`; pass `--player` to override.
- The module's log is read with `spacetime logs` inside the container, read-only. A `module.log.jsonl` in `--logs` is used instead when present.

Example, play-test 2 from its saved evidence:

```bash
S=.local/living/playtest-2/session
python3 living/tools/play_report.py --db verify-play2-20261111-135347 --run play2-20261111-135347 \
    --journal $S/journal --logs $S/run --out .local/living/play-report/play2-20261111-135347
```

## Recording

Three steps around the client, which the launcher runs for every owner session:

```bash
python3 living/tools/play_report.py record-start --db <database> --capture <dir> [--no-screen] [--game-pid <pid>]
LIVING_GAME_RECORD=<dir>/client living-game ...
python3 living/tools/play_report.py record-stop --capture <dir>
```

Then the report, with `--capture <dir>`.

### The client's own record (`LIVING_GAME_RECORD`)

`living/game/src/record.rs` is off unless `LIVING_GAME_RECORD=<dir>` is set. It writes:

- `stills/<unix ms>.jpg`: the frame as drawn, HUD included. It takes one every `LIVING_GAME_RECORD_EVERY` seconds (default 3), and at each line sent, reducer answer, new speech bubble and act note, at most one a second.
- `state.jsonl`: four samples a second. Each holds where I am and face, the camera, the people the HUD knows (label, distance, hovered, targeted, talking), the bubbles and chat lines shown, the target, whether the text box is open, hp, energy and the frame time.
- `events.jsonl`: presses as the game reads them (a tap or a held press and who was under the cursor; keys outside the text box), each line sent, and every reducer call with the authority's answer and its arguments. This settles questions like "did a tap on a person strike them?" that play-test 2 could not answer.
- `captures.csv`: per still, when it was asked for and when the image arrived (unix µs), the worker's time and the file size.

How a still is taken: Bevy's screenshot reads the frame back asynchronously. An observer moves the image, without copying it, to one worker thread. That thread scales it to `LIVING_GAME_RECORD_WIDTH` pixels (default 960) and writes a JPEG. If the worker is behind, the still is dropped rather than waited for; `state.jsonl` counts the drops. The state and event lines go to a second writer thread, so a slow disk never holds a frame.

Times are unix ms, the authority's `at_ms` base. The module reads only the client's own state and changes nothing the player sees or sends. It hooks the client in one place: `Net::on_reply` (net.rs), where every reducer's answer arrives.

**Frame cost** (2026-11-11, headless at 3200×1800, the readback size of the owner's 1600×900 window at Retina scale, capped at 60 fps, on `verify-report-e2e`). The laptop was at load average 15–27 from other workers' builds, Blender bakes and captures throughout, so these numbers are indicative, not acceptance-grade:

- **The recorder's own main-thread time** (its systems plus the still observer, self-timed into `state.jsonl` as `rec_main_us`) was p50 64–84 µs per quarter second in the A/B runs, and **0.20 ms per second** in the final run. That is about 0.005 ms per frame at 60 fps. Isolated samples of 54–330 ms coincided with whole-process stalls that the recorder-off runs show too (frame maxima of 3.7 s there).
- **Each still:** the readback reached the observer after p50 33–48 ms, and the worker thread took p50 19–33 ms to scale it and write a JPEG of about 24 KB.
- **Frames over 25 ms** (three interleaved pairs): recorder off 106, 305 (a run under heavy load) and 110; recorder on (a still every 2 s) 179, 66 and 46. There is no consistent difference beyond the load.
- **The five frames right after a still** in the two quieter "on" runs had frame-time p95 27 and 35 ms, against 21–23 ms over all frames of those runs. Main-thread work p95 was 11–13 ms against 4–10 ms. The likely cause is Bevy's full-size readback copy on a task-pool thread competing for a loaded CPU. That is why periodic stills are 3 s apart and event stills at least 1 s apart. A windowed run on a quiet machine is the measurement still owed.

### The authority's rows (`record-start`)

`record-start` starts one detached process. It writes its PID to `<dir>/recorder.pid` and its notes to `<dir>/recorder.json`, and records into `<dir>/authority.jsonl`:

- **New `skill_use` rows** and **everyone's position** (the `body` row, advanced to the sample time), every second. The authority keeps only the last 24 skill presses per character.
- **New `experience` rows**, every 2 s. Residents' rows are deleted when their mind consolidates them, and all of a character's rows when it dies. In play-test 2 that took most hearers' rows; they were recovered only from model prompts.
- **New `chronicle` rows**, every 10 s.

This load is about 2.6 owner SQL requests a second, each one `SELECT … WHERE id > N` on a primary key. SpacetimeDB 2.14.1 accepts one statement per request. Each request opens and closes an HTTP connection, so the authority runs its connect and disconnect hooks: each request commits two short transactions that insert and delete the admin's `connection` row (presence.rs; `adopt` returns early for the admin, so presence is untouched). That is about 5 small transactions a second beside the tick, while recording. The final run made 249 requests in 96 s, with round trips p50 4.7 ms, p95 7.9 ms and max 13.6 ms (an earlier run under heavy build load had p95 80 ms). One report run makes about 10 such requests, so reading a paused world writes only those connection rows; it stays paused.

The SpacetimeDB documentation ([HTTP database API](https://spacetimedb.com/docs/http/database)) says the HTTP SQL API is "intended primarily for management, debugging and interactive developer use" and is less optimized than the WebSocket API; [subscriptions](https://spacetimedb.com/docs/clients/subscriptions) are the pattern for following rows. This recorder is a developer-audit diagnostic of one owner session, not a game path. That is why polling by owner SQL is acceptable here. A subscription-based recorder (a small Rust SDK client) would replace it if the load ever matters, for example with several sessions at once or a long soak.

### The screen (`screencapture`)

When the launching app may record the screen, `record-start` records the game's window. It finds the window by its owner process (`living-game`, or `--game-pid`), polling for up to 10 minutes, and runs `screencapture -x -v -o -l <window>` into `<dir>/screen.mov`. `record-stop` sends it SIGINT, which finishes the file. The recorder stops the video early if the disk falls under 15 GB free.

- **Permission:** macOS asks the "responsible" app, the one at the top of the process tree that launched the recorder. T3 Code (Nightly) already holds Screen Recording on the laptop, so a launcher run from a T3 thread needs nothing. A launcher run from Ghostty, Terminal, iTerm or Warp needs that app added once: **System Settings > Privacy & Security > Screen & System Audio Recording > +**. Granting `living-game` itself does not help: it is ad-hoc signed, and every rebuild loses the grant. `record-start` checks with `CGPreflightScreenCaptureAccess`, which never prompts. Without the permission it records no video, and the page says why.
- **Cost:** about 12% of one core, all in macOS's own daemons (`replayd`, the VideoToolbox encoder), from 2 s tests on a still desktop (M4 Pro). Size is about 25 MB a minute for a still screen. Expect 75–225 MB a minute of moving game footage at full Retina size. The game's frame time while recording was not measured, because the windowed game was not run during these checks. `--no-screen` turns it off.

## What the page shows

- **What stands out:** one line per thing the owner would ask about. That covers each line said and whether it got a conversation turn, the first reply and its latency, fights and killings with the time since the victim last spoke to the player, the longest silences, unprompted approaches, refused commands, errors and the cost.
- **On screen:** the video, if any, with the timeline's times seeking it; a strip of the client's stills; the client's state as a table.
- **What you said:** for each line, the hearers (with experience ids, salience and distance), who was in earshot by the world's own hearing law, the conversation turns, parked lines and the answers with their latency and source (a conversation turn or a deliberation, and that deliberation's trigger). Each hearer without a turn gets the reason the mind log gives: parked, settled, or an unaddressed line the gate passed over, which it does not log.
- **Timeline:** everything above in order, plus lines heard, gestures, blows and the client's presses, each with the nearest still.
- **Fights and deaths**, with the player's skill presses and their outcomes (`skill_use`).
- **Refused commands**, with the authority's reasons: `act` rows ("What you had decided did not work out: …"), `skill_use` refusals ("refused: too tired"), reducer errors from the module log, and the client's `refused` log lines. Repeats within 10 s are counted on one row.
- **Errors** from the client, the mind service, the module and model calls, from a minute before the arrival to a minute after the quit.
- **Cost** at the prices in `living/tools/trials.py`, by purpose and model, for the session (arrival to quit) and for the whole journal, split into people, animals and the player's own character.
- **Sources and limits.**

### Where the facts come from

- **The session** runs from the client's `playing character #N` to the `presence` row's `changed_ms` when `present` is false (the quit). Rows written after the takeover, whose `controller` is the mind service's identity, are left out.
- **Hearers** of a line are the `speech` rows written in the same instant (`at_ms`) with the player as subject. When those rows were deleted, they are recovered from the residents' model requests. Consolidation prompts show `[id]` experience ids, and those rows are the actor's own. Think, deliberate and talk prompts show `[day D HH:MM]` lines, matched by text and game minute. The line's rows have consecutive ids (said, repeat, then hearers nearest first), so a single unexplained gap is filled by a hearer seen only in an id-less prompt.
- **Turns** are the journal's `talk` calls whose `# You and … (#player)` header names the player and whose `# What you are answering` or `# The conversation so far` carries the line. **Parked** and **settled** come from mind-log lines.
- **Replies** are the player's own `speech` rows addressed to them. Each is matched to the model call that produced its words, and through that call to the player's lines it answered.
- **Distances:** the recorder's positions when there are any, else the distance to the player in the hearer's nearest model prompt (`# What you perceive right now`), within 20 s. The player's own track also comes from the client log's 2-second `island perf … at (x, y)` line.
- **Silences** are stretches of at least 60 s with no line, no act and no skill on anyone. Dodges and jumps do not break one.
- **Blows** on others are the victims' own `attacked you (N damage)` rows, from the recorder or from their prompts (to ±0.5 s).

## Evidence

Archived in `/Users/carlid/dev/slop-art-online/.local/living/play-report/` (the main checkout's `.local`):

- **Play-test 2**, from its saved evidence, with no recording: `.local/living/playtest-2/report/index.html`. Point by point against the hand-made diagnosis (`playtest-2/diagnosis/REPORT.md`):

  | REPORT.md | The page |
  |---|---|
  | First "hi", 13:54:22.0, `to = 0`, heard by Maud, Mercy, Cuth and Aldith (a crowd), no talk turn | Same time and hearers, with ids 1060–1063. Maud, Mercy and Aldith come from consolidation prompts; Cuth from an id-less think prompt, put in the one unexplained gap (1062). "No conversation turn" |
  | Cuth's reply 28.3 s later, from a deliberation triggered by a failed plan | "Cuth Marrow spoke to you 28.3 s later, from a deliberation (its think step) whose trigger was: What you had decided did not work out: teach medicine → person: they moved away" |
  | Second "hi", 13:54:43.5, heard by Bram, no turn; "6.8 s after the second" | Same, with the repeat note. Cuth's reply is not credited to it, because Cuth is not among its hearers |
  | First strike 13:55:06.6, 16 s after her greeting | "You struck Cuth Marrow at 13:55:06.6, 16.3 s after Cuth Marrow spoke to you" |
  | The blows: 8, then 26 (fire-bolt size), 8, 9, 9 | The same five blows from Cuth's prompts, ±0.5 s |
  | The killing at 13:55:36.2, after the yield | "Diego killed Cuth Marrow, who had yielded", the yield at 13:55:23.1 and the strike after it at 13:55:31.8 |
  | Silent for 3 min 49 s, 13:55:50 → 13:59:39; only Sissly spoke near him; residents saw him at 11–35 m | "Silent for 3 min 49 s (13:55:50.3 → 13:59:39.7) … you heard 1 line(s): Sissly Fenner at 13:59:19. Residents' prompts saw you at 11–35 m" |
  | "ssssssssshi": Mercy after 12.7 s, parked while deliberating | "Mercy Abbot after 12.7 s (parked: the listener was deliberating)", heard by Mercy (1706) and Osric (1707) |
  | "wassup": Linnet after 2.6 s, Mercy after 3.5 s | Same, both conversation turns, heard by Mercy, Osric and Linnet (1732–1734) |
  | The three refused "take wound tending" | "3× What you had decided did not work out: take wound_tending x1 → nearest remains: no wound_tending there." |
  | 0 model errors; `mind_say: character is dead` | 0 model-call errors; that WARN and its module-log ERROR |
  | Not in REPORT.md | 17 refused skill presses from `skill_use` at 14:00:04–10: strikes at Mercy and Osric ("too tired", 12× "out of reach") and bowshots ("too tired"); a dodge and two jumps at 13:56:15–18 during the silence; the session cost, $0.174 for 130 calls |

  REPORT.md listed "1180–1181" as unidentified hearers of the second "hi". Bram's journal shows 1180 is his own next row ("You failed to face → speaker"), so the page does not count it as a hearer; it flags the rows after the hearers it knows as not held.
- **Play-test 3** (`verify-play2-20261111-161445`, 16:15–16:19, no recording): `.local/living/play-report/play2-20261111-161445/index.html`. Diego's "Hi", addressed to Bram by the new tap-to-talk, was heard by four people and answered by Bram after 3.2 s through a conversation turn. Then came 3 min 16 s of silence with ten dodges and jumps. The session cost $0.091 for 67 calls. The player-memory internalization of the session is shown.
- **The recording, end to end** on the scratch world `verify-report-e2e` (island seed, a throwaway identity, headless client, no minds, deleted afterwards): `evidence-report-1/`, with the capture, the page, the A/B runs (`ab2/`, `ab3/`: frames, captures, state) and the driver (`ab.sh`, `frames.py`). It shows stills with the HUD and chat, client events with each reducer call's arguments, a `wave` refused with the authority's reason ("graph.do: skill `wave` needs a target", from the client and the module log as one row), strikes refused from `skill_use`, and hearers from rows the recorder kept.

## Not covered

- **The screen video was not recorded with the game.** The windowed game was not run during these checks: client runs here are headless. `screencapture -v -o -l <window>` was tested on other windows, and SIGINT was tested to finish a valid file. Recording the game's own window, and the game's frame time while it records, are untested.
- **Frame cost on a quiet machine, windowed.** The A/B above ran headless on a heavily loaded laptop.
- **Minds and replies through the recorder.** The scratch world ran without minds, so its page has no conversation turns. Turns, parking and reply latencies were checked only on play-test 2's and play-test 3's real journals.
- **Hearers of a line whose rows were deleted and who never showed it in a later prompt** cannot be recovered without the recorder. Play-test 2's pages say so where rows after a line's block are missing.
- **Several players in one world:** the page follows one played character (`--player` picks another).
- **Turn arcs:** recorded positions follow a body's straight segment to its end, not the arcs the authority's `common::pos` follows, so distances during turns are approximate.
- **Why an unaddressed line got no turn** is inferred: the mind service's gate does not log it (DEBUG lines are never recorded).
